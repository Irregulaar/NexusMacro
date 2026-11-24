"""Tests for the color-based shop detector."""

from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np

from nexusmacro.config import Config
from nexusmacro.shopvision import ShopVision
from nexusmacro.vision import Matcher

ROOT = Path(__file__).resolve().parent.parent


class ShopVisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config()
        self.matcher = Matcher(
            ROOT / "templates", ROOT / "templates", self.config
        )
        self.vision = ShopVision(self.matcher)

    def _shop_frame(self, scales: tuple[float, ...]) -> np.ndarray:
        frame = np.full((720, 1280, 3), (26, 44, 75), np.uint8)
        template = cv2.imread(str(ROOT / "templates" / "buybutton.png"))
        y = 100
        for scale in scales:
            image = cv2.resize(
                template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
            height, width = image.shape[:2]
            frame[y : y + height, 400 : 400 + width] = image
            y += height + 30
        return frame

    def test_buy_buttons_at_multiple_scales(self) -> None:
        frame = self._shop_frame((0.8, 1.0, 1.2))
        buys = self.vision.buy_buttons(frame)
        self.assertEqual(len(buys), 3)
        self.assertTrue(self.vision.shop_open(frame))

    def test_no_false_positive_on_plain_frame(self) -> None:
        frame = np.full((720, 1280, 3), (26, 44, 75), np.uint8)
        self.assertEqual(self.vision.buy_buttons(frame), [])
        self.assertFalse(self.vision.shop_open(frame))

    def test_buy_button_has_expected_geometry(self) -> None:
        frame = self._shop_frame((1.0,))
        buy = self.vision.buy_buttons(frame)[0]
        self.assertGreater(buy.w, buy.h)
        self.assertGreaterEqual(buy.score, 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
