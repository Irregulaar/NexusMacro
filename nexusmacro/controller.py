"""Qt bridge for the automation engine.

The UI never touches the Engine's internals: it starts/stops it and pushes
live config updates through ``update_config``.
"""

from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .backend import X11Backend
from .config import Config
from .engine import Engine, EngineCallbacks
from .vision import Matcher


class EngineController(QObject):
    log = Signal(str, str)
    status = Signal(str)
    stats = Signal(object)
    preview = Signal(object, object)
    finished = Signal()
    spawner_once_done = Signal()
    game_restart_requested = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._spawner_thread: Optional[threading.Thread] = None
        self._spawner_once_active = False
        self._manual_pending = False
        self._engine: Optional[Engine] = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _callbacks(self) -> EngineCallbacks:
        return EngineCallbacks(
            log=lambda message, level="info": self.log.emit(message, level),
            status=lambda text: self.status.emit(text),
            stats=lambda stats: self.stats.emit(stats),
            preview=lambda frame, matches: self.preview.emit(frame, matches),
            manual_done=self._on_engine_manual_done,
            restart_game=lambda reason: self.game_restart_requested.emit(reason),
        )

    def _on_engine_manual_done(self) -> None:
        if not self._manual_pending:
            return
        self._manual_pending = False
        self.spawner_once_done.emit()

    def start(self, config: Config, matcher: Matcher) -> None:
        if self.running:
            return
        self._stop.clear()
        backend = X11Backend(
            display_name=config.display or None,
            wm_class=config.window_class,
        )
        engine = Engine(backend, config, matcher, self._callbacks(), self._stop)
        self._engine = engine

        def run() -> None:
            try:
                engine.run()
            except Exception as exc:
                self.log.emit(f"Engine startup error: {exc}", "error")
            finally:
                self.finished.emit()

        self._thread = threading.Thread(
            target=run, daemon=True, name="nexus-macro-engine"
        )
        self._thread.start()

    def request_spawner_purchase(self) -> bool:
        if self.spawner_once_running:
            return False
        if self._engine is not None and self.running:
            self._manual_pending = True
            self._engine.request_spawner_purchase()
            return True
        return False

    def request_optional_action(self, kind: str) -> bool:
        if self.spawner_once_running:
            return False
        if self._engine is not None and self.running:
            self._manual_pending = True
            self._engine.request_optional_action(kind)
            return True
        return False

    @property
    def spawner_once_running(self) -> bool:
        return bool(self._spawner_once_active or self._manual_pending)

    def _start_once(self, kind: str, config: Config, matcher: Matcher) -> None:
        backend = X11Backend(
            display_name=config.display or None,
            wm_class=config.window_class,
        )
        engine = Engine(
            backend, config, matcher, self._callbacks(), threading.Event()
        )

        def run() -> None:
            try:
                if kind == "spawner":
                    engine.run_spawner_once()
                else:
                    engine.run_optional_once(kind)
            except Exception as exc:
                self.log.emit(f"Manual {kind} error: {exc}", "error")
            finally:
                self._spawner_once_active = False
                self.spawner_once_done.emit()

        self._spawner_once_active = True
        self._spawner_thread = threading.Thread(
            target=run, daemon=True, name=f"nexus-macro-{kind}-once"
        )
        self._spawner_thread.start()

    def start_spawner_once(self, config: Config, matcher: Matcher) -> bool:
        if self.spawner_once_running:
            return False
        self._start_once("spawner", config, matcher)
        return True

    def start_optional_once(
        self, kind: str, config: Config, matcher: Matcher
    ) -> bool:
        if self.spawner_once_running:
            return False
        self._start_once(kind, config, matcher)
        return True

    def update_config(self, config: Config, key: str = "") -> None:
        """Push a live config change into the running engine."""
        engine = self._engine
        if engine is None or not self.running:
            return
        try:
            engine.update_config(config, key)
        except Exception as exc:
            self.log.emit(f"Could not apply settings live: {exc}", "warning")

    def stop(self) -> None:
        self._stop.set()
        if self._manual_pending:
            self._manual_pending = False
            self.spawner_once_done.emit()
