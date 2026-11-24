"""Build menu actions: Fuse All and Place Best, including Forfeit."""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..vision import Match
from .context import Runtime
from .detection import ScreenDetector
from .navigation import Navigator


class BuildMenu:
    """Owns the Build menu and its two-click actions."""

    def __init__(
        self,
        runtime: Runtime,
        detector: ScreenDetector,
        navigator: Navigator,
    ) -> None:
        self.runtime = runtime
        self.detector = detector
        self.navigator = navigator
        self.last_discarded = False

    # -- discovery ----------------------------------------------------------

    def find_button(
        self, frame: np.ndarray, key: str, threshold: float = 0.70
    ) -> Optional[Match]:
        match = self.runtime.find(frame, key, threshold)
        if match is not None:
            return match
        return self.runtime.find_scaled(
            frame, key, threshold - 0.02
        )

    def menu_open(self, frame: np.ndarray) -> bool:
        # Native scale only: this runs every tick. Build/Fuse/Place keep the
        # multi-scale search because they run once per match.
        return self.runtime.find(frame, "stop", 0.66) is not None

    def close_menu(self) -> bool:
        """Close a leftover Build menu so it cannot block other actions."""
        frame = self.runtime.capture()
        if not self.menu_open(frame):
            return True
        stop = self.find_button(frame, "stop")
        if stop is None:
            return False
        self.runtime.click_match(stop, "Build menu closed")
        self.runtime.sleep(self.runtime.config.action_delay)
        return True

    # -- flows --------------------------------------------------------------

    def run(self, kind: str, frame: np.ndarray, allow_forfeit: bool) -> bool:
        """Run one action (manual Fuse Now / Best Place Now)."""
        return kind in self.run_many([kind], frame, allow_forfeit)

    def run_many(
        self,
        kinds,
        frame: np.ndarray,
        allow_forfeit: bool,
    ) -> set[str]:
        """Open Build once and run Fuse and/or Place Best in that same menu."""
        ordered = [kind for kind in ("fuse", "place") if kind in kinds]
        self.last_discarded = False
        if not ordered:
            return set()
        title = " + ".join(
            "Fuse" if kind == "fuse" else "Best Place" for kind in ordered
        )
        if self._handle_discard(frame):
            return set()
        if not self._open_menu(title, frame, allow_forfeit):
            return set()
        # The caller's frame is the pre-menu one; refresh it before checking
        # that the menu is open for the first action.
        frame = self.runtime.capture()

        completed: set[str] = set()
        for kind in ordered:
            action_title = "Fuse" if kind == "fuse" else "Best Place"
            if self._handle_discard(frame):
                break
            if not self.menu_open(frame):
                self.runtime.log(
                    f"{action_title}: build menu closed before the action.",
                    "warning",
                )
                break
            if self._perform_action(kind):
                completed.add(kind)
            frame = self.runtime.capture()
            if self.runtime.stop_event.is_set():
                break

        self._close_menu_once(title)
        return completed

    # -- helpers ------------------------------------------------------------

    def _open_menu(
        self,
        title: str,
        frame: np.ndarray,
        allow_forfeit: bool,
    ) -> bool:
        build = self.find_button(frame, "build")
        if build is None:
            if not allow_forfeit:
                self.runtime.log(
                    f"{title}: Build button not visible; skipping.", "info"
                )
                return False
            build = self._forfeit_and_wait_build(title)
            if build is None:
                return False

        if self.menu_open(frame):
            self.runtime.log(f"{title}: build menu already open.", "info")
            return True

        self.runtime.click_match(build, "Build clicked")
        opened = self._wait_menu_open()
        if not opened:
            retry = self.find_button(self.runtime.capture(), "build")
            if retry is not None:
                self.runtime.click_match(retry, "Build clicked (retry)")
                opened = self._wait_menu_open()
        if not opened:
            self.runtime.save_debug(
                self.runtime.capture(),
                "build_menu_not_open",
                note=f"{title}: Stop button never appeared",
            )
            self.runtime.log(
                f"{title}: build menu did not open; debug capture saved.",
                "warning",
            )
            return False
        self.runtime.log("Build menu opened (verified).", "success")
        return True

    def _perform_action(self, kind: str) -> bool:
        title = "Fuse" if kind == "fuse" else "Best Place"
        target_key = "fuseall" if kind == "fuse" else "placebest"
        target = self._wait_action_button(target_key)
        if target is None:
            self.runtime.save_debug(
                self.runtime.capture(),
                f"{target_key}_not_found",
                note=f"{title}: action button not found with the menu open",
            )
            self.runtime.log(
                f"{title}: {target_key} button not found. Debug capture saved.",
                "warning",
            )
            return False

        self.runtime.click_match(target, f"{title} clicked")
        self.runtime.sleep(0.18)
        # The second click accepts the action confirmation.
        self.runtime.click(target.cx, target.cy)
        self.runtime.sleep(0.18)

        if kind == "fuse":
            wait = self.runtime.config.fuse_wait_seconds
            self.runtime.log(
                f"Fuse: waiting {wait:.1f}s for the fusion to finish.", "info"
            )
            self.runtime.sleep(wait)
        else:
            self.runtime.sleep(0.8)

        frame = self.runtime.capture()
        if self._handle_discard(frame):
            return False
        return True

    def _close_menu_once(self, title: str) -> None:
        frame = self.runtime.capture()
        if not self.menu_open(frame):
            return
        stop = self.find_button(frame, "stop")
        if stop is not None:
            self.runtime.click_match(stop, "Build menu closed")
            self.runtime.sleep(self.runtime.config.action_delay)
        else:
            self.runtime.log(
                f"{title}: Stop button not found after the action.", "warning"
            )

    # -- helpers ------------------------------------------------------------

    def _handle_discard(self, frame: np.ndarray) -> bool:
        handled = self.navigator.handle_discard(frame)
        if handled:
            self.last_discarded = True
        return handled

    def _wait_menu_open(self) -> bool:
        for _ in range(3):
            self.runtime.sleep(0.45)
            probe = self.runtime.capture()
            if self._handle_discard(probe):
                return False
            if self.menu_open(probe):
                return True
        return False

    def _wait_action_button(self, key: str) -> Optional[Match]:
        for _ in range(5):
            frame = self.runtime.capture()
            if self._handle_discard(frame):
                return None
            target = self.find_button(frame, key)
            if target is not None:
                return target
            if not self.menu_open(frame):
                return None
            self.runtime.sleep(0.35)
        return None

    def _close_if_open(self) -> None:
        frame = self.runtime.capture()
        if not self.menu_open(frame):
            return
        stop = self.find_button(frame, "stop")
        if stop is not None:
            self.runtime.click_match(stop, "Build menu closed")

    def _forfeit_and_wait_build(self, title: str) -> Optional[Match]:
        forfeit = self.detector.forfeit(self.runtime.capture())
        if forfeit is None:
            self.runtime.log(
                f"{title}: Build not found and no Forfeit button; aborting.",
                "warning",
            )
            return None
        self.runtime.click_match(forfeit, "Forfeit battle")

        confirm: Optional[Match] = None
        for _ in range(8):
            self.runtime.sleep(0.5)
            probe = self.runtime.capture()
            if self._handle_discard(probe):
                return None
            confirm = self.find_button(probe, "confirm")
            if confirm is not None:
                break
        if confirm is None:
            self.runtime.log(
                f"{title}: forfeit confirmation not found.", "warning"
            )
            return None
        self.runtime.click_match(confirm, "Forfeit confirmed")

        for _ in range(10):
            self.runtime.sleep(0.7)
            probe = self.runtime.capture()
            if self._handle_discard(probe):
                return None
            build = self.find_button(probe, "build")
            if build is not None:
                return build
        self.runtime.log(
            f"{title}: Build still not visible after forfeit.", "warning"
        )
        return None
