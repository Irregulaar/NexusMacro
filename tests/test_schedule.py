"""Spawner schedule tests."""

import unittest
from datetime import datetime

from nexusmacro.schedule import (
    is_spawner_window,
    next_spawner_refresh,
    spawner_countdown_text,
)


class ScheduleTest(unittest.TestCase):
    def test_window(self) -> None:
        self.assertTrue(
            is_spawner_window(datetime(2026, 1, 1, 12, 5, 0), 55)[0]
        )
        self.assertTrue(
            is_spawner_window(datetime(2026, 1, 1, 12, 5, 54), 55)[0]
        )
        self.assertFalse(
            is_spawner_window(datetime(2026, 1, 1, 12, 5, 55), 55)[0]
        )
        self.assertFalse(
            is_spawner_window(datetime(2026, 1, 1, 12, 6, 0), 55)[0]
        )

    def test_next_refresh(self) -> None:
        self.assertEqual(
            next_spawner_refresh(datetime(2026, 1, 1, 12, 4, 30)),
            datetime(2026, 1, 1, 12, 5, 0),
        )
        self.assertEqual(
            next_spawner_refresh(datetime(2026, 1, 1, 12, 5, 0)),
            datetime(2026, 1, 1, 12, 5, 0),
        )
        self.assertEqual(
            next_spawner_refresh(datetime(2026, 1, 1, 12, 5, 30)),
            datetime(2026, 1, 1, 12, 10, 0),
        )

    def test_countdown_text(self) -> None:
        self.assertIn(
            "refresh window open",
            spawner_countdown_text(datetime(2026, 1, 1, 12, 5, 1), 55),
        )
        self.assertIn(
            "04:30",
            spawner_countdown_text(datetime(2026, 1, 1, 12, 5, 30), 20),
        )


if __name__ == "__main__":
    unittest.main()
