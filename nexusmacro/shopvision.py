"""Fast color-based shop detection for Nexus Macro.

The shop UI has distinctive colors that do not depend on the UI scale:
green Buy buttons, a red close button, and a tan scrollbar thumb.  Template
matching alone was slow and failed whenever the shop rendered at a slightly
different scale, so color signatures are the primary signal and templates are
only used to confirm the close/scroll shapes.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .vision import Match, Matcher


class ShopVision:
    def __init__(self, matcher: Matcher) -> None:
        self.matcher = matcher
        self._close_template = matcher.template_data("close", 1.0)

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _ncc(
        patch_gray: np.ndarray,
        template_gray: np.ndarray,
        mask: np.ndarray,
    ) -> float:
        selected = mask > 0
        if not np.any(selected):
            return 0.0
        a = patch_gray[selected].astype(np.float32)
        b = template_gray[selected].astype(np.float32)
        a -= a.mean()
        b -= b.mean()
        den = float(np.linalg.norm(a) * np.linalg.norm(b))
        if den < 1e-6:
            return 0.0
        return float(np.dot(a, b) / den)

    @staticmethod
    def _white_count(hsv: np.ndarray) -> int:
        return int(
            np.count_nonzero((hsv[:, :, 2] > 195) & (hsv[:, :, 1] < 80))
        )

    # -- Buy ----------------------------------------------------------------

    def buy_buttons(self, frame: np.ndarray) -> list[Match]:
        """Find green Buy buttons at any UI scale."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (52, 80, 80), (90, 255, 255))
        # Opening removes thin green card borders/glows that would otherwise
        # merge with the solid button fill.
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        frame_w = frame.shape[1]
        results: list[Match] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if not (60 <= w <= 230 and 16 <= h <= 75):
                continue
            # Keep the search inside the shop panel; the green cash display
            # sits in the bottom-left corner of the game HUD.
            if x < frame_w * 0.20 or x + w > frame_w * 0.92:
                continue
            aspect = w / max(1, h)
            if not (2.5 <= aspect <= 6.5):
                continue
            green = int(np.count_nonzero(mask[y : y + h, x : x + w]))
            fill = green / max(1, w * h)
            # Real Buy buttons are a solid green fill (>= 0.5); foliage and
            # other green UI art are much patchier.
            if fill < 0.50:
                continue
            white = self._white_count(hsv[y : y + h, x : x + w])
            if white < 20:
                continue
            score = min(0.99, 0.55 + fill * 0.25 + min(white, 300) / 1500.0)
            if score < float(self.matcher.config.shop_threshold):
                continue
            results.append(Match("buy", x, y, w, h, score))
        results.sort(key=lambda item: (item.y, item.x))
        return results

    # -- Close --------------------------------------------------------------

    def close_button(self, frame: np.ndarray) -> Optional[Match]:
        """Find the red close X of the shop panel."""
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        red = cv2.inRange(hsv, (0, 80, 80), (10, 255, 255)) | cv2.inRange(
            hsv, (170, 80, 80), (179, 255, 255)
        )
        contours, _ = cv2.findContours(
            red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        best: Optional[Match] = None
        pad = 8
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if not (18 <= w <= 70 and 18 <= h <= 70):
                continue
            aspect = w / max(1, h)
            if not (0.55 <= aspect <= 1.8):
                continue
            if self._white_count(hsv[y : y + h, x : x + w]) < 8:
                continue
            region = (
                max(0, x - pad),
                max(0, y - pad),
                min(width - max(0, x - pad), w + pad * 2),
                min(height - max(0, y - pad), h + pad * 2),
            )
            match = self.matcher.best(
                frame, "close", threshold=0.65, scale=1.0, region=region
            )
            if match is not None and (
                best is None or match.score > best.score
            ):
                best = match
        if best is not None:
            return best
        # Last resort: native-scale template over the right half.
        return self.matcher.best(
            frame,
            "close",
            threshold=0.65,
            scale=1.0,
            region=(width // 2, 0, width // 2, height),
        )

    # -- Scrollbar ----------------------------------------------------------

    def scrollbar(self, frame: np.ndarray) -> Optional[Match]:
        """Find the shop scrollbar thumb."""
        # The thumb is a narrow tan/gold bar on the right side of the panel.
        height, width = frame.shape[:2]
        x0 = int(width * 0.55)
        hsv = cv2.cvtColor(frame[:, x0:], cv2.COLOR_BGR2HSV)
        tan = cv2.inRange(hsv, (15, 25, 80), (70, 160, 230))
        tan = cv2.morphologyEx(
            tan, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)
        )
        contours, _ = cv2.findContours(
            tan, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        best: Optional[Match] = None
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if not (5 <= w <= 30 and 50 <= h <= height * 0.85):
                continue
            if w / max(1, h) > 0.4:
                continue
            candidate = Match(
                "scroll", x0 + x, y, w, h, min(0.95, h / 400.0)
            )
            if best is None or candidate.h > best.h:
                best = candidate
        if best is not None:
            return best
        # Fall back to the template at the native scale (the panel is fixed).
        return self.matcher.best(frame, "scroll", threshold=0.60, scale=1.0)

    # -- shop state ---------------------------------------------------------

    def shop_open(self, frame: np.ndarray) -> bool:
        # Buy buttons take ~8 ms; the close check is only needed when the shop
        # happens to be fully sold out.
        if self.buy_buttons(frame):
            return True
        return self.close_button(frame) is not None
