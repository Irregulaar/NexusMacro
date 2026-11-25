"""Pure screen detection: reads frames, never clicks or changes state."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from ..vision import Match
from .context import Runtime


@dataclass
class ClassicRow:
    match: Match
    on: bool


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
        """The leaderboard header crop: Tab is needed only while this shows.

        The header has a dark panel behind the text, so masked matching scores
        poorly. Unmasked TM_CCOEFF_NORMED over the top-right band finds it
        reliably (the header is the global maximum in that band).
        """
        height, width = frame.shape[:2]
        rx = int(width * 0.55)
        ry = 0
        rw = width - rx
        rh = int(height * 0.30)
        region = frame[ry : ry + rh, rx : rx + rw]
        if region.size == 0:
            return None
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        best: Optional[Match] = None
        for scale in (0.85, 0.90, 0.95, 1.00, 1.05):
            try:
                data = self.runtime.matcher.template_data(
                    "tabimage", scale=scale
                )
            except Exception:
                continue
            if gray.shape[0] < data.height or gray.shape[1] < data.width:
                continue
            result = cv2.matchTemplate(
                gray, data.gray, cv2.TM_CCOEFF_NORMED
            )
            result = np.nan_to_num(
                result, nan=-1.0, posinf=-1.0, neginf=-1.0
            )
            _, score, _, location = cv2.minMaxLoc(result)
            if score < 0.45:
                continue
            if best is None or score > best.score:
                x, y = location
                best = Match(
                    "tabimage",
                    rx + x,
                    ry + y,
                    data.width,
                    data.height,
                    float(score),
                )
        return best

    def forfeit(self, frame: np.ndarray) -> Optional[Match]:
        return self.runtime.find(frame, "forfeit", 0.72)

    def settings_button(self, frame: np.ndarray) -> Optional[Match]:
        return self.runtime.find(frame, "settingsbutton", 0.72)

    def classic_forfeit_row(
        self, frame: np.ndarray
    ) -> Optional[ClassicRow]:
        """Locate the Classic Forfeit row and read its ON/OFF toggle.

        The bundled template shows ON, so the left label/description crop is
        used for matching; the toggle colour is sampled separately. This works
        with both ON and OFF rows.
        """
        height, width = frame.shape[:2]
        region_h = int(height * 0.98)
        region_w = int(width * 0.48)
        if region_h <= 0 or region_w <= 0:
            return None
        region = frame[:region_h, :region_w]
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        best: Optional[ClassicRow] = None
        for scale in (0.9, 0.95, 1.0, 1.05, 1.1):
            try:
                data = self.runtime.matcher.template_data(
                    "classicforfeitsetting", scale=scale
                )
            except Exception:
                continue
            label_w = max(8, int(data.width * 0.70))
            label = data.gray[:, :label_w]
            if gray.shape[0] < label.shape[0] or gray.shape[1] < label.shape[1]:
                continue
            result = cv2.matchTemplate(gray, label, cv2.TM_CCOEFF_NORMED)
            result = np.nan_to_num(
                result, nan=-1.0, posinf=-1.0, neginf=-1.0
            )
            _, score, _, location = cv2.minMaxLoc(result)
            if score < 0.55:
                continue
            if best is not None and score <= best.match.score:
                continue
            x, y = location
            tx0 = x + int(data.width * 0.68)
            tx1 = min(region_w, x + data.width)
            ty0 = y
            ty1 = min(region_h, y + int(data.height * 0.55))
            on = False
            if tx1 > tx0 and ty1 > ty0:
                toggle = cv2.cvtColor(
                    frame[ty0:ty1, tx0:tx1], cv2.COLOR_BGR2HSV
                )
                green = cv2.inRange(
                    toggle, (35, 60, 60), (95, 255, 255)
                )
                area = max(1, (tx1 - tx0) * (ty1 - ty0))
                on = int(np.count_nonzero(green)) / area >= 0.08
            best = ClassicRow(
                Match(
                    "classicforfeitsetting",
                    x,
                    y,
                    data.width,
                    data.height,
                    float(score),
                ),
                on,
            )
        return best

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
