"""Desktop-aware UI scaling tests."""

from __future__ import annotations

import unittest

from nexusmacro.ui_scale import desktop_scale


class UiScaleTest(unittest.TestCase):
    def test_1080p_is_the_design_baseline(self) -> None:
        self.assertEqual(desktop_scale(1920, 1080), 1.0)

    def test_1440p_scales_up(self) -> None:
        self.assertEqual(desktop_scale(2560, 1440), 1.33)

    def test_4k_scales_up(self) -> None:
        self.assertEqual(desktop_scale(3840, 2160), 2.0)

    def test_small_screens_are_clamped(self) -> None:
        self.assertEqual(desktop_scale(1366, 768), 0.80)
        self.assertEqual(desktop_scale(1280, 720), 0.80)

    def test_invalid_screen_does_not_break(self) -> None:
        self.assertEqual(desktop_scale(0, 1080), 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
