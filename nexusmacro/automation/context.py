"""Shared runtime for the automation engine.

Everything a component needs to touch the game goes through this object:
capture, input, templates, config, logging, statistics and debug captures.
Components stay small and testable; they never reach into Qt or the UI.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import cv2
import numpy as np

from ..backend import X11Backend
from ..config import Config
from ..paths import captures_dir
from ..vision import Match, Matcher, TemplateError


class EngineStopped(Exception):
    """Raised when the user presses Stop between two actions."""


@dataclass
class Stats:
    battles: int = 0
    spawner_opens: int = 0
    buy_clicks: int = 0
    scrolls: int = 0
    cycles: int = 0
    started_at: float = field(default_factory=time.time)


@dataclass
class EngineCallbacks:
    log: Callable[[str, str], None]
    status: Callable[[str], None]
    stats: Callable[[Stats], None]
    preview: Callable[[np.ndarray, list[Match]], None]
    manual_done: Optional[Callable[[], None]] = None
    restart_game: Optional[Callable[[str], None]] = None


class Runtime:
    """Single gateway between automation components and the game."""

    def __init__(
        self,
        backend: X11Backend,
        config: Config,
        matcher: Matcher,
        callbacks: EngineCallbacks,
        stop_event: Any,
    ) -> None:
        self.backend = backend
        self.config = config
        self.matcher = matcher
        self.callbacks = callbacks
        self.stop_event = stop_event
        self.stats = Stats()
        self._last_status = ""

    # -- configuration ------------------------------------------------------

    def update_config(self, config: Config, key: str = "") -> None:
        self.config = config
        self.matcher.config = config
        if key in ("scale", "ignore_buy_price", "ignore_spawner_timer"):
            self.matcher.reload()

    # -- lifecycle ----------------------------------------------------------

    def check_stop(self) -> None:
        if self.stop_event.is_set():
            raise EngineStopped()

    def sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            self.check_stop()
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def capture(self) -> np.ndarray:
        return self.backend.capture()

    # -- input --------------------------------------------------------------

    def click(self, x: int, y: int, button: int = 1, park: Optional[bool] = None) -> None:
        self.backend.click(x, y, button=button, park=park)

    def click_match(self, match: Match, message: str) -> None:
        self.backend.click(match.cx, match.cy)
        self.log(
            f"{message}: ({match.cx}, {match.cy}) score {match.score:.2f}.",
            "action",
        )

    def key(self, name: str) -> None:
        self.backend.key(name)

    # -- logging / stats ----------------------------------------------------

    def log(self, message: str, level: str = "info") -> None:
        self.callbacks.log(message, level)

    def status(self, text: str) -> None:
        if text != self._last_status:
            self._last_status = text
            self.callbacks.status(text)

    def stats_changed(self) -> None:
        self.callbacks.stats(self.stats)

    def emit_preview(self, frame: np.ndarray, matches: list[Match]) -> None:
        # The preview was removed from the UI on purpose: do not copy frames.
        return

    # -- templates ----------------------------------------------------------

    def find(
        self,
        frame: np.ndarray,
        key: str,
        threshold: float = 0.75,
    ) -> Optional[Match]:
        try:
            return self.matcher.best(frame, key, threshold=threshold)
        except TemplateError:
            return None

    def find_scaled(
        self,
        frame: np.ndarray,
        key: str,
        threshold: float = 0.72,
        factors: tuple[float, ...] = (
            0.85,
            0.90,
            0.95,
            1.00,
            1.05,
            1.10,
            1.15,
            1.20,
        ),
        early_score: float = 0.92,
    ) -> Optional[Match]:
        """Multi-scale search for buttons whose size changes with the HUD."""
        base = float(self.config.scale)
        best: Optional[Match] = None
        for factor in factors:
            try:
                match = self.matcher.best(
                    frame,
                    key,
                    threshold=threshold,
                    scale=max(0.30, base * factor),
                )
            except TemplateError:
                continue
            if match is not None and (best is None or match.score > best.score):
                best = match
            if best is not None and best.score >= early_score:
                break
        return best

    # -- debug --------------------------------------------------------------

    def save_debug(
        self,
        frame: Optional[np.ndarray],
        tag: str,
        note: str = "",
    ) -> None:
        if not self.config.save_debug_frames:
            return
        try:
            if frame is None:
                frame = self.capture()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = captures_dir() / f"{tag}_{stamp}.png"
            cv2.imwrite(str(path), frame)
            sidecar = {
                "tag": tag,
                "note": note,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "config": self.config.as_dict(),
            }
            path.with_suffix(".json").write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.log(f"Debug capture: {path}", "info")
        except Exception as exc:
            self.log(f"Could not save debug capture ({tag}): {exc}", "warning")
