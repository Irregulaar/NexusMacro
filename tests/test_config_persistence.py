"""Config file robustness: never lose settings because of one bad value."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import nexusmacro.config as config_module
from nexusmacro.config import Config


class ConfigPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_roundtrip_keeps_custom_values(self) -> None:
        config = Config()
        config.auto_fuse = True
        config.auto_best_place = True
        config.max_scrolls = 23
        config.gamescope_grab_cursor = True
        config.gamescope_backend = "wayland"
        config.save(self.path)
        loaded = Config.load(self.path)
        self.assertTrue(loaded.auto_fuse)
        self.assertTrue(loaded.auto_best_place)
        self.assertEqual(loaded.max_scrolls, 23)
        self.assertTrue(loaded.gamescope_grab_cursor)
        self.assertEqual(loaded.gamescope_backend, "wayland")

    def test_one_invalid_value_does_not_reset_the_rest(self) -> None:
        config = Config()
        config.auto_fuse = True
        config.max_scrolls = 23
        config.save(self.path)
        raw = json.loads(self.path.read_text())
        raw["threshold"] = "not-a-number"
        raw["buy_clicks"] = "7"
        self.path.write_text(json.dumps(raw))

        loaded = Config.load(self.path)
        self.assertTrue(loaded.auto_fuse)
        self.assertEqual(loaded.max_scrolls, 23)
        self.assertEqual(loaded.buy_clicks, 7)
        self.assertEqual(loaded.threshold, 0.88)
        self.assertIn("threshold", config_module.LAST_LOAD_ERROR)

    def test_invalid_json_is_backed_up(self) -> None:
        self.path.write_text("{broken json")
        loaded = Config.load(self.path)
        self.assertTrue(loaded.auto_battle)
        backups = list(self.path.parent.glob("config.invalid-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertIn("Invalid JSON", config_module.LAST_LOAD_ERROR)

    def test_save_keeps_a_backup_of_the_previous_file(self) -> None:
        first = Config()
        first.max_scrolls = 11
        first.save(self.path)
        second = Config()
        second.max_scrolls = 12
        second.save(self.path)
        backup = self.path.with_suffix(".json.bak")
        self.assertTrue(backup.exists())
        self.assertEqual(
            json.loads(backup.read_text())["max_scrolls"], 11
        )
        self.assertEqual(json.loads(self.path.read_text())["max_scrolls"], 12)

    def test_bool_strings_are_parsed(self) -> None:
        raw = Config().as_dict()
        raw["auto_fuse"] = "true"
        raw["auto_best_place"] = "false"
        self.path.write_text(json.dumps(raw))
        loaded = Config.load(self.path)
        self.assertTrue(loaded.auto_fuse)
        self.assertFalse(loaded.auto_best_place)


if __name__ == "__main__":
    unittest.main(verbosity=2)
