"""Nexus Macro automation engine (orchestrator only).

The heavy lifting lives in ``nexusmacro.automation``:
- context: shared runtime (backend/config/templates/log/debug)
- detection: pure screen reading
- navigation: Play, Tab, discard
- shop: the spawner shop session
- build: Build/Fuse/Place/Forfeit
- spawner: discovery, scheduling and the spawner → shop action

This module decides **what to do next**, in priority order, and nothing else.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from .automation.build import BuildMenu
from .automation.context import (
    EngineCallbacks,
    EngineStopped,
    Runtime,
    Stats,
)
from .automation.detection import ScreenDetector
from .automation.navigation import Navigator
from .automation.shop import ShopScan, ShopSession
from .automation.spawner import (
    SpawnerAction,
    SpawnerDecision,
    SpawnerFinder,
    SpawnerScheduler,
)
from .backend import BackendError, X11Backend
from .config import Config
from .schedule import spawner_countdown_text, spawner_refresh_time_text
from .vision import Match, Matcher, TemplateError

__all__ = [
    "Engine",
    "EngineCallbacks",
    "EngineStopped",
    "Stats",
]


class Engine:
    def __init__(
        self,
        backend: X11Backend,
        config: Config,
        matcher: Matcher,
        callbacks: EngineCallbacks,
        stop_event,
    ) -> None:
        self.runtime = Runtime(backend, config, matcher, callbacks, stop_event)
        self.stats = self.runtime.stats
        self.detector = ScreenDetector(self.runtime)
        self.navigator = Navigator(self.runtime, self.detector)
        self.shop = ShopSession(self.runtime)
        self.build = BuildMenu(self.runtime, self.detector, self.navigator)
        self.finder = SpawnerFinder(self.runtime)
        self.scheduler = SpawnerScheduler(self.runtime)
        self.spawner_action = SpawnerAction(
            self.runtime, self.finder, self.shop, self.navigator
        )

        self._force_spawner = threading.Event()
        self._manual_lock = threading.Lock()
        self._manual_optional_kind: Optional[str] = None
        self._pre_battle_done: set[str] = set()
        self._pre_battle_retry_at = 0.0
        # Legacy attribute kept for tests/UI: discard is now checked every
        # tick, so this no longer gates anything.
        self._discard_until = 0.0
        self._last_battle_click = 0.0
        self._last_leftover_shop_scan = 0.0
        self._restart_sent = False
        self._restart_sent_at = 0.0

    # -- compatibility properties ------------------------------------------

    @property
    def backend(self) -> X11Backend:
        return self.runtime.backend

    @backend.setter
    def backend(self, value: X11Backend) -> None:
        self.runtime.backend = value

    @property
    def config(self) -> Config:
        return self.runtime.config

    @config.setter
    def config(self, value: Config) -> None:
        self.runtime.update_config(value)

    @property
    def matcher(self) -> Matcher:
        return self.runtime.matcher

    @property
    def shopvision(self):
        return self.shop.vision

    @property
    def _tab_done(self) -> bool:
        return self.navigator.tab_done

    @_tab_done.setter
    def _tab_done(self, value: bool) -> None:
        self.navigator.tab_done = value

    @property
    def _tab_after(self) -> float:
        return self.navigator.tab_after

    @_tab_after.setter
    def _tab_after(self, value: float) -> None:
        self.navigator.tab_after = value

    @property
    def _last_tab_scan(self) -> float:
        return self.navigator._last_tab_scan

    @_last_tab_scan.setter
    def _last_tab_scan(self, value: float) -> None:
        self.navigator._last_tab_scan = value

    @property
    def _next_interval_at(self) -> float:
        return self.scheduler.next_interval_at

    @_next_interval_at.setter
    def _next_interval_at(self, value: float) -> None:
        self.scheduler.next_interval_at = value

    @property
    def _last_spawner_attempt(self) -> float:
        return self.scheduler.last_attempt

    @_last_spawner_attempt.setter
    def _last_spawner_attempt(self, value: float) -> None:
        self.scheduler.last_attempt = value

    def update_config(self, config: Config, key: str = "") -> None:
        """Live config change from the UI. Replaces touching privates."""
        new = config.copy()
        new.validate()
        self.runtime.update_config(new, key)
        self.scheduler.on_config_changed(key)
        if key in ("threshold", "scale", "spawner_threshold"):
            self.detector.invalidate()

    # -- main loop ----------------------------------------------------------

    def run(self) -> None:
        try:
            self.runtime.backend.connect()
            width, height = self.runtime.backend.size
            self.runtime.log(
                f"Engine connected to {self.runtime.backend.display_name} "
                f"({width}x{height}).",
                "success",
            )
            if (width, height) != (1280, 720):
                self.runtime.log(
                    f"Game window is {width}x{height}; templates are calibrated "
                    "for 1280x720. Keep the default gamescope resolution for "
                    "the most reliable detection.",
                    "warning",
                )
            self.runtime.status("Running")
            self.scheduler.start_time = time.monotonic()
            self.navigator.arm_tab(delay=1.5)
            self._log_schedule()
            failures = 0

            while not self.runtime.stop_event.is_set():
                try:
                    frame = self.runtime.capture()
                    acted = self.tick(frame)
                    failures = 0
                    if not acted:
                        self._idle_status()
                        self.runtime.sleep(self.runtime.config.idle_poll)
                except EngineStopped:
                    break
                except (BackendError, TemplateError) as exc:
                    failures += 1
                    self.runtime.log(str(exc), "error")
                    self.runtime.save_debug(None, "error", str(exc))
                    if failures >= 5:
                        raise
                    self.runtime.sleep(1.0)
                except Exception as exc:
                    failures += 1
                    self.runtime.log(f"Error inesperado: {exc}", "error")
                    self.runtime.save_debug(None, "error", str(exc))
                    if failures >= 5:
                        raise
                    self.runtime.sleep(1.0)
        except EngineStopped:
            pass
        except Exception as exc:
            self.runtime.log(f"El motor se detuvo: {exc}", "error")
            self.runtime.status("Error")
        finally:
            try:
                self.runtime.backend.close()
            except Exception:
                pass
            self.runtime.stats_changed()
            self._notify_manual_done()
            self.runtime.log("Engine stopped.", "info")

    def _log_schedule(self) -> None:
        if not self.runtime.config.auto_spawners:
            return
        timing = self.runtime.config.spawner_timing
        if timing == "clock":
            self.runtime.log(
                "Spawner timing: clock. Next refresh at "
                f"{spawner_refresh_time_text()}.",
                "info",
            )
        elif timing == "interval":
            self.runtime.log(
                "Spawner timing: every "
                f"{self.runtime.config.spawner_interval_minutes} min from Start.",
                "info",
            )
        else:
            self.runtime.log(
                "Spawner timing: continuous, every "
                f"{self.runtime.config.spawner_poll_seconds} s.",
                "info",
            )

    def _idle_status(self) -> None:
        config = self.runtime.config
        if config.auto_spawners:
            timing = config.spawner_timing
            if timing == "clock":
                self.runtime.status(
                    spawner_countdown_text(
                        window_seconds=config.spawner_window_seconds
                    )
                )
            elif timing == "interval":
                self.runtime.status(
                    "Spawners: every "
                    f"{config.spawner_interval_minutes} min from Start"
                )
            else:
                self.runtime.status(
                    "Spawners: checking every "
                    f"{config.spawner_poll_seconds} s"
                )
        else:
            self.runtime.status("Waiting for the game...")

    def request_optional_action(self, kind: str) -> None:
        """Queue a manual Fuse/Best Place on the running engine.

        Routing it through the main engine avoids two engines clicking the
        Build menu at the same time.
        """
        with self._manual_lock:
            self._manual_optional_kind = kind

    def _take_manual_optional(self) -> Optional[str]:
        with self._manual_lock:
            kind = self._manual_optional_kind
            self._manual_optional_kind = None
            return kind

    def _notify_manual_done(self) -> None:
        callback = self.runtime.callbacks.manual_done
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            self.runtime.log(f"Manual action callback failed: {exc}", "warning")

    # -- one decision per tick ---------------------------------------------

    def tick(self, frame: np.ndarray) -> bool:
        self.runtime.check_stop()

        # 0. Reconnect screen: never click its button; ask the UI to close
        # Sober/gamescope and relaunch. Retry after a delay if it persists.
        if self._restart_sent:
            now = time.monotonic()
            if (
                now - self._restart_sent_at >= 30.0
                or self.detector.reconnect(frame) is None
            ):
                self._restart_sent = False
                self.runtime.log(
                    "Reconnect screen cleared; resuming automation.", "info"
                )
            else:
                self.runtime.sleep(0.5)
                return True
        if self._handle_reconnect(frame):
            return True

        # 1. A saved-battle modal blocks everything else.
        if self._click_discard(frame):
            return True

        # 2. Play: the macro enters a new match, and Tab is re-armed.
        if self._maybe_click_play(frame):
            self._reset_pre_battle()
            return True

        # 3. Hide the leaderboard once per match entry.
        self._maybe_hide_leaderboard(frame)

        # 4. A leftover Build menu blocks the map and the spawner buttons.
        if self.build.menu_open(frame):
            if self.build.close_menu():
                self.runtime.log("Leftover Build menu closed.", "info")
                return True

        # 5. A shop left open from a previous cycle is closed, never bought
        # from. Check every 2 s: this scan is comparatively expensive and a
        # leftover shop is not urgent.
        now = time.monotonic()
        if now - self._last_leftover_shop_scan >= 2.0:
            self._last_leftover_shop_scan = now
            if self.shop.is_open(frame):
                self.runtime.log(
                    "Closing a leftover shop before continuing.", "info"
                )
                self.shop.close()
                return True

        # 6. Manual Fuse / Best Place requested while the engine is running.
        manual_kind = self._take_manual_optional()
        if manual_kind is not None:
            self._run_manual_optional(manual_kind, frame)
            return True

        # 7. Manual spawner purchase requested from the UI.
        if self._force_spawner.is_set():
            self._force_spawner.clear()
            self.runtime.log("Manual spawner purchase requested.", "action")
            try:
                success = self._run_spawner_cycle(frame, reason="manual")
                self.scheduler.on_manual_purchase(success)
            finally:
                self._notify_manual_done()
            return True

        # 8. Fuse / Best Place before Battle.
        if self._run_pre_battle(frame):
            return True

        # 9. Scheduled spawner purchase. Do not consume the schedule while
        # the game is still loading or in the lobby: wait for a match HUD.
        if self.config.auto_spawners and self.detector.game_ui(frame):
            decision = self.scheduler.due()
            if decision is not None:
                self._log_spawner_decision(decision)
                success = self._run_spawner_cycle(
                    frame, reason=decision.reason
                )
                self.scheduler.finish(decision, success)
                return True

        # 10. Start a battle when its button is available.
        return self._try_start_battle(frame)

    def _handle_reconnect(self, frame: np.ndarray) -> bool:
        match = self.detector.reconnect(frame)
        if match is None:
            return False
        self._restart_sent = True
        self._restart_sent_at = time.monotonic()
        self.runtime.save_debug(
            frame,
            "reconnect_detected",
            "Restarting Sober instead of clicking Reconnect",
        )
        self.runtime.log(
            "Reconnect button detected; restarting Sober/gamescope instead "
            "of clicking it.",
            "warning",
        )
        callback = self.runtime.callbacks.restart_game
        if callback is None:
            self.runtime.log(
                "No game-restart callback is available; stopping the engine.",
                "error",
            )
            raise EngineStopped()
        try:
            callback("Reconnect button visible")
        except Exception as exc:
            self.runtime.log(f"Could not request a game restart: {exc}", "error")
            raise EngineStopped()
        return True

    def _run_manual_optional(self, kind: str, frame: np.ndarray) -> None:
        title = "Fuse" if kind == "fuse" else "Best Place"
        self.runtime.log(f"Manual {title} requested for the running engine.", "action")
        try:
            if self.shop.is_open(frame):
                self.shop.close()
                frame = self.runtime.capture()
            ok = self.build.run(kind, frame, allow_forfeit=True)
            if ok:
                self._pre_battle_done.add(kind)
                self.runtime.log(f"Manual {title} completed.", "success")
            elif not self.build.last_discarded:
                self.runtime.log(
                    f"Manual {title} did not complete.", "warning"
                )
        finally:
            self._notify_manual_done()

    # -- navigation wrappers ------------------------------------------------

    def _maybe_click_play(self, frame: np.ndarray) -> bool:
        return self.navigator.click_play(frame)

    def _maybe_hide_leaderboard(self, frame: np.ndarray) -> None:
        self.navigator.maybe_tab(frame)

    def _game_ui_visible(self, frame: np.ndarray) -> bool:
        return self.detector.game_ui(frame)

    def _discard_visible(self, frame: np.ndarray) -> Optional[Match]:
        return self.detector.discard(frame)

    def _click_discard(self, frame: np.ndarray) -> bool:
        if not self.navigator.handle_discard(frame):
            return False
        self._discard_until = 0.0
        self._reset_pre_battle()
        return True

    # -- pre-battle ---------------------------------------------------------

    def _reset_pre_battle(self) -> None:
        self._pre_battle_done.clear()
        self._pre_battle_retry_at = 0.0

    def _run_pre_battle(self, frame: np.ndarray) -> bool:
        config = self.runtime.config
        enabled = set()
        if config.auto_fuse:
            enabled.add("fuse")
        if config.auto_best_place:
            enabled.add("place")
        if not enabled:
            return False

        # During a battle there is no Build button: reset so the next match
        # gets a fresh pre-battle pass.
        if not self.detector.idle_match(frame):
            self._reset_pre_battle()
            return False

        self._pre_battle_done &= enabled
        pending = enabled - self._pre_battle_done
        if not pending:
            return False

        now = time.monotonic()
        if now < self._pre_battle_retry_at:
            return False
        # Do not reopen the Build menu while a Battle click is still
        # transitioning to the battle screen.
        if now - self._last_battle_click < 5.0:
            return False

        # One Build menu for every pending action. Fuse first, then Place
        # Best, then a single Stop: opening/closing twice made Place Best
        # miss the Build button while the menu was animating.
        completed = self.build.run_many(
            pending, frame, allow_forfeit=False
        )
        if self.build.last_discarded:
            self._reset_pre_battle()
            return True

        for kind in completed:
            title = "Fuse" if kind == "fuse" else "Best Place"
            self._pre_battle_done.add(kind)
            self.runtime.log(f"{title}: completed.", "success")
        for kind in pending - completed:
            title = "Fuse" if kind == "fuse" else "Best Place"
            self.runtime.log(
                f"{title}: failed; will retry before Battle.", "warning"
            )

        if enabled - self._pre_battle_done:
            self._pre_battle_retry_at = time.monotonic() + 6.0
        return True

    # -- battle -------------------------------------------------------------

    def _try_start_battle(self, frame: np.ndarray) -> bool:
        if not self.runtime.config.auto_battle:
            return False
        now = time.monotonic()
        if now - self._last_battle_click < max(
            3.0, self.runtime.config.battle_cooldown
        ):
            return False
        match = self._battle_button(frame)
        if match is None:
            return False
        if match.key == "battle" and self.detector.battle_active(frame):
            return False

        self._last_battle_click = now
        self.runtime.click_match(match, "Battle started")
        self.detector.invalidate()
        self.stats.battles += 1
        self.runtime.stats_changed()

        # The battle screen can take a moment to load. Watch for Forfeit
        # (battle active) or for the Battle button to disappear; a fixed
        # 0.6 s check produced false "battle_not_started" warnings.
        started = False
        deadline = time.monotonic() + 2.5
        post_click = self.runtime.capture()
        while time.monotonic() < deadline:
            self.runtime.sleep(0.30)
            post_click = self.runtime.capture()
            if self._click_discard(post_click):
                return True
            if (
                self.detector.battle_active(post_click)
                or self.detector.battle_button(post_click) is None
            ):
                started = True
                break

        if not started:
            self.runtime.save_debug(
                post_click,
                "battle_not_started",
                "Battle button still visible after 2.5 s",
            )
            self.runtime.log(
                "Battle click did not change the screen; retrying after cooldown.",
                "warning",
            )
        self.runtime.sleep(max(0.5, self.runtime.config.battle_cooldown))
        return True

    def _battle_button(self, frame: np.ndarray) -> Optional[Match]:
        return self.detector.battle_button(frame)

    def _find_battle(self, frame: np.ndarray) -> Optional[Match]:
        # Compatibility for tests and diagnostics.
        return self.detector._find_battle(frame)

    # -- spawner wrappers ---------------------------------------------------

    def _log_spawner_decision(self, decision: SpawnerDecision) -> None:
        if decision.reason == "start":
            self.runtime.log("Trying a spawner purchase on start.", "info")
        elif decision.reason == "refresh":
            self.runtime.log(
                "Spawner refresh window; trying to buy.", "action"
            )
        elif decision.reason == "interval":
            self.runtime.log("Spawner interval; trying to buy.", "action")
        else:
            self.runtime.log(
                "Spawner poll (every "
                f"{self.runtime.config.spawner_poll_seconds}s).",
                "action",
            )

    def _find_spawner(
        self,
        frame: np.ndarray,
        threshold: Optional[float] = None,
        scan_scales: bool = True,
    ) -> tuple[Optional[str], Optional[Match], float]:
        return self.finder.find(
            frame, threshold=threshold, scan_scales=scan_scales
        )

    def _run_spawner_cycle(self, frame: np.ndarray, reason: str) -> bool:
        # A manual purchase from the UI must ignore the automatic-failure
        # cooldown; the user explicitly asked for it.
        return self.spawner_action.run(
            frame, reason, force=(reason == "manual")
        )

    def request_spawner_purchase(self) -> None:
        self._force_spawner.set()

    def run_spawner_once(self) -> None:
        try:
            self.runtime.backend.connect()
            frame = self.runtime.capture()
            self.runtime.log("Manual spawner purchase requested.", "action")
            success = self._run_spawner_cycle(frame, reason="manual")
            if not success:
                self.runtime.log(
                    "Manual spawner purchase did not complete.", "warning"
                )
        except Exception as exc:
            self.runtime.log(
                f"Manual spawner purchase failed: {exc}", "error"
            )
        finally:
            try:
                self.runtime.backend.close()
            except Exception:
                pass
            self.runtime.stats_changed()
            self.runtime.log("Manual spawner purchase finished.", "info")

    # -- build wrappers -----------------------------------------------------

    def _run_build_action(
        self, kind: str, frame: np.ndarray, allow_forfeit: bool
    ) -> bool:
        return self.build.run(kind, frame, allow_forfeit=allow_forfeit)

    def run_optional_once(self, kind: str) -> None:
        """Manual Fuse / Best Place, including Forfeit if in battle."""
        title = "Fuse" if kind == "fuse" else "Best Place"
        try:
            self.runtime.backend.connect()
            frame = self.runtime.capture()
            if self.shop.is_open(frame):
                self.runtime.log(
                    f"Close the shop before using {title}.", "warning"
                )
                return
            self.runtime.log(f"Manual {title} requested.", "action")
            if not self._run_build_action(kind, frame, allow_forfeit=True):
                if not self.build.last_discarded:
                    self.runtime.log(
                        f"Manual {title} did not complete.", "warning"
                    )
        except Exception as exc:
            self.runtime.log(f"Manual {title} failed: {exc}", "error")
        finally:
            try:
                self.runtime.backend.close()
            except Exception:
                pass
            self.runtime.stats_changed()
            self.runtime.log(f"Manual {title} finished.", "info")

    # -- shop compatibility wrappers ---------------------------------------

    def _shop_scan(
        self, frame: np.ndarray, preferred_scale: float = 1.0
    ) -> tuple[float, list[Match], Optional[Match], Optional[Match]]:
        scan: ShopScan = self.shop.scan(frame)
        scroll = scan.scroll
        if scroll is None and scan.buys:
            scroll = self.shop.vision.scrollbar(frame)
        return float(self.runtime.config.scale), scan.buys, scroll, scan.close

    def _buy_and_scroll(self) -> tuple[int, int]:
        return self.shop.buy_and_scroll()

    def _close_shop(self) -> bool:
        return self.shop.close()

    # -- runtime compatibility ---------------------------------------------

    def _click_match(self, match: Match, message: str) -> None:
        self.runtime.click_match(match, message)

    def _set_status(self, text: str) -> None:
        self.runtime.status(text)

    def _check_stop(self) -> None:
        self.runtime.check_stop()

    def _sleep(self, seconds: float) -> None:
        self.runtime.sleep(seconds)

    def _emit_preview(
        self, frame: np.ndarray, matches: list[Match]
    ) -> None:
        self.runtime.emit_preview(frame, matches)

    def _save_debug(
        self,
        frame: Optional[np.ndarray],
        tag: str,
        note: str = "",
    ) -> None:
        self.runtime.save_debug(frame, tag, note)
