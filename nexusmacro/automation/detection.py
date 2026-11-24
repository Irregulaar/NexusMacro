"""Pure screen detection: reads frames, never clicks or changes state."""

from __future__ import annotations

import time
from typing import Optional

import cv2
import numpy as np

from ..vision import Match
from .context import Runtime


class ScreenDetector:
    """Classify what is on screen with the templates and color signatures."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._battle_cache: Optional[Match] = None
        self._last_battle_scan = 0.0
        self._reconnect_cache: Optional[Match] = None
        self._last_reconnect_scan = 0.0

    # -- simple anchors -----------------------------------------------------

    def play(self, frame: np.ndarray) -> Optional[Match]:
        return self.runtime.find(frame, "play", 0.72)

    def discard(self, frame: np.ndarray) -> Optional[Match]:
        match = self.runtime.find(frame, "discard", 0.66)
        if match is not None:
            return match
        # Shape/color fallback for the wide red "Discard saved battle" button.
        # It must be centred: Build-menu badges and map banners are red too,
        # and matching those caused a click loop. Half resolution keeps this
        # cheap enough to run every tick.
        height, width = frame.shape[:2]
        x0 = int(width * 0.20)
        y0 = int(height * 0.30)
        x1 = int(width * 0.80)
        y1 = int(height * 0.80)
        roi_bgr = frame[y0:y1, x0:x1]
        small = cv2.resize(
            roi_bgr,
            (max(1, (x1 - x0) // 2), max(1, (y1 - y0) // 2)),
            interpolation=cv2.INTER_AREA,
        )
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 55, 40), (18, 255, 255)) | cv2.inRange(
            hsv, (170, 55, 40), (179, 255, 255)
        )
        red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(
            red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if not (90 <= w <= 210 and 11 <= h <= 25):
                continue
            if w / max(1, h) < 7.0:
                continue
            roi = hsv[y : y + h, x : x + w]
            white = int(
                np.count_nonzero((roi[:, :, 2] > 190) & (roi[:, :, 1] < 80))
            )
            if white < 15:
                continue
            return Match(
                "discard",
                x0 + x * 2,
                y0 + y * 2,
                w * 2,
                h * 2,
                0.60,
            )
        return None

    def reconnect(self, frame: np.ndarray) -> Optional[Match]:
        """Roblox reconnect button. Never click it; restart the game."""
        now = time.monotonic()
        if now - self._last_reconnect_scan < 0.7:
            return self._reconnect_cache
        self._last_reconnect_scan = now
        self._reconnect_cache = self.runtime.find(
            frame, "reconnectbutton", 0.72
        )
        return self._reconnect_cache

    def tab_image(self, frame: np.ndarray) -> Optional[Match]:
        """The leaderboard header crop: Tab is needed only while this shows."""
        for scale in (1.0, 0.95, 1.05):
            try:
                match = self.runtime.matcher.best(
                    frame, "tabimage", threshold=0.62, scale=scale
                )
            except Exception:
                continue
            if match is not None:
                return match
        return None

    def forfeit(self, frame: np.ndarray) -> Optional[Match]:
        return self.runtime.find(frame, "forfeit", 0.72)

    def battle_active(self, frame: np.ndarray) -> bool:
        """A battle is running when Forfeit is on screen."""
        return self.forfeit(frame) is not None

    def game_ui(self, frame: np.ndarray) -> bool:
        """True when the match HUD is visible (in battle or not)."""
        if self.forfeit(frame) is not None:
            return True
        if self.battle_button(frame) is not None:
            return True
        for key in ("build", "spawner2"):
            if self.runtime.find(frame, key, 0.72) is not None:
                return True
        return False

    # -- cached battle button ----------------------------------------------

    def battle_button(self, frame: np.ndarray) -> Optional[Match]:
        now = time.monotonic()
        interval = max(0.5, float(self.runtime.config.battle_poll))
        if now - self._last_battle_scan >= interval:
            self._last_battle_scan = now
            self._battle_cache = self._find_battle(frame)
        return self._battle_cache

    def invalidate(self) -> None:
        self._battle_cache = None
        self._last_battle_scan = 0.0

    def idle_match(self, frame: np.ndarray) -> bool:
        """Between battles: Battle/Continue visible and no Forfeit."""
        return (
            self.battle_button(frame) is not None
            and not self.battle_active(frame)
        )

    def _find_battle(self, frame: np.ndarray) -> Optional[Match]:
        """Half-resolution battle scan (~5x faster than full frame)."""
        height, width = frame.shape[:2]
        small = cv2.resize(
            frame,
            (max(1, width // 2), max(1, height // 2)),
            interpolation=cv2.INTER_AREA,
        )
        config = self.runtime.config
        threshold = max(0.60, float(config.threshold) - 0.08)
        best: Optional[Match] = None
        for factor in (0.475, 0.5):
            scale = max(0.35, float(config.scale) * factor)
            for key in ("battle", "battle2", "yescontinue"):
                match = self.runtime.matcher.best(
                    small,
                    key,
                    threshold=threshold,
                    scale=scale,
                )
                if match is not None and (
                    best is None or match.score > best.score
                ):
                    best = match
            if best is not None and best.score >= 0.9:
                break
        if best is None or best.score < threshold:
            return None
        return Match(
            best.key,
            best.x * 2,
            best.y * 2,
            best.w * 2,
            best.h * 2,
            best.score,
        )
