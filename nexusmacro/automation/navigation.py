"""Navigation actions: Play, the one-shot Tab and the discard modal."""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .context import Runtime
from .detection import ScreenDetector


class Navigator:
    PLAY_CLICK_COOLDOWN = 10.0

    def __init__(self, runtime: Runtime, detector: ScreenDetector) -> None:
        self.runtime = runtime
        self.detector = detector

        self._last_play_click = 0.0
        self._last_play_scan = 0.0

        self.tab_done = False
        self.tab_after = 0.0
        self._last_tab_scan = 0.0
        self._tab_armed_at = 0.0
        self._tab_missing_logged = False

        self._last_discard_click = 0.0
        self._last_discard_center: Optional[tuple[int, int]] = None
        self._discard_ignore_until = 0.0
        self._discard_ignore_center: Optional[tuple[int, int]] = None

    # -- Play ---------------------------------------------------------------

    def click_play(self, frame: np.ndarray) -> bool:
        """Click Play when it appears. Every Play click re-arms Tab."""
        now = time.monotonic()
        if now - self._last_play_click < self.PLAY_CLICK_COOLDOWN:
            return False
        if now - self._last_play_scan < 1.5:
            return False
        self._last_play_scan = now
        match = self.detector.play(frame)
        if match is None:
            return False
        self._last_play_click = now
        self.runtime.click_match(match, "Play button clicked")
        self.detector.invalidate()
        self.runtime.sleep(0.6)
        # New match loading: allow one Tab for this entry.
        self.arm_tab(delay=2.5)
        return True

    # -- Tab ----------------------------------------------------------------

    def arm_tab(self, delay: float = 2.5) -> None:
        self.tab_done = False
        self.tab_after = time.monotonic() + max(0.0, delay)
        self._last_tab_scan = 0.0
        self._tab_armed_at = time.monotonic()
        self._tab_missing_logged = False

    def maybe_tab(self, frame: np.ndarray) -> None:
        """Press Tab only while the leaderboard header image is visible.

        No game-UI heuristic and no fallback: if the image is not on screen,
        Tab is not sent.
        """
        if self.tab_done:
            return
        now = time.monotonic()
        if now < self.tab_after:
            return
        if now - self._last_tab_scan < 0.5:
            return
        self._last_tab_scan = now
        if self.detector.tab_image(frame) is None:
            if (
                not self._tab_missing_logged
                and now - self._tab_armed_at > 10.0
            ):
                self._tab_missing_logged = True
                self.runtime.log(
                    "Tab image not on screen; Tab not sent.", "info"
                )
            return
        try:
            self.runtime.key("Tab")
            self.runtime.log("Leaderboard hidden (Tab).", "info")
        except Exception as exc:
            self.runtime.log(f"Couldn't press Tab: {exc}", "warning")
        finally:
            self.tab_done = True

    # -- discard ------------------------------------------------------------

    @staticmethod
    def _near(
        a: tuple[int, int], b: Optional[tuple[int, int]], radius: int = 40
    ) -> bool:
        return b is not None and abs(a[0] - b[0]) <= radius and abs(a[1] - b[1]) <= radius

    def handle_discard(self, frame: np.ndarray) -> bool:
        """Click the saved-battle Discard modal if it is really on screen.

        A red badge in the Build menu used to be mistaken for the Discard
        button. The colour fallback is now centred, and a click is verified:
        if a fallback candidate does not disappear, it is blacklisted instead
        of clicked over and over.
        """
        match = self.detector.discard(frame)
        if match is None:
            self._discard_ignore_center = None
            return False

        now = time.monotonic()
        center = (match.cx, match.cy)
        if (
            now < self._discard_ignore_until
            and self._near(center, self._discard_ignore_center)
        ):
            return False
        if (
            self._near(center, self._last_discard_center, radius=25)
            and now - self._last_discard_click < 1.2
        ):
            return False

        self.detector.invalidate()
        self._last_discard_center = center
        self._last_discard_click = now
        self.runtime.click_match(match, "Discard clicked")
        self.runtime.sleep(0.35)

        after_frame = self.runtime.capture()
        after = self.detector.discard(after_frame)
        if after is not None and self._near(
            (after.cx, after.cy), center, radius=35
        ):
            # The template is a real button: allow a later retry. A colour
            # fallback that survives its click is a false positive.
            if match.score <= 0.61:
                self._discard_ignore_until = now + 60.0
                self._discard_ignore_center = center
                self.runtime.log(
                    "Discard candidate did not disappear; ignoring this "
                    "false positive.",
                    "warning",
                )
                self.runtime.save_debug(
                    after_frame,
                    "discard_false_positive",
                    f"center={center} score={match.score:.2f}",
                )
                return False
            self.runtime.log(
                "Discard still visible after the click; will retry.", "info"
            )
            return True

        self._discard_ignore_center = None
        self.runtime.log(
            "Saved battle discarded; restarting the pre-battle process.", "info"
        )
        return True
