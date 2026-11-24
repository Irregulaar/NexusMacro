"""Config persistence tests for the Qt window."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import nexusmacro.config as config_module  # noqa: E402
import nexusmacro.ui as ui_module  # noqa: E402
from nexusmacro.config import Config  # noqa: E402
from nexusmacro.ui import MainWindow  # noqa: E402
from unittest.mock import patch  # noqa: E402


class UiConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"
        self.original = config_module.config_file
        config_module.config_file = lambda: self.path
        self.window = MainWindow(Config())
        self.window._set_running(False)

    def tearDown(self) -> None:
        self.window._set_running(False)
        self.window.close()
        config_module.config_file = self.original
        self.tmp.cleanup()

    def _wait_save(self) -> None:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)

    def test_feature_toggle_saves_immediately(self) -> None:
        self.window._set_config("auto_fuse", True)
        self._wait_save()
        data = json.loads(self.path.read_text())
        self.assertTrue(data["auto_fuse"])

    def test_toggle_stays_enabled_while_running(self) -> None:
        self.window._set_running(True)
        self.assertTrue(self.window.battle_toggle.isEnabled())
        self.window._set_config("auto_battle", False)
        self._wait_save()
        data = json.loads(self.path.read_text())
        self.assertFalse(data["auto_battle"])
        self.window._set_running(False)

    def test_numeric_change_saves_after_debounce(self) -> None:
        self.window._set_config("buy_clicks", 9)
        self._wait_save()
        data = json.loads(self.path.read_text())
        self.assertEqual(data["buy_clicks"], 9)

    def test_uncommitted_spin_value_is_synced_on_save(self) -> None:
        widget = self.window._fields["max_scrolls"]
        widget.blockSignals(True)
        widget.setValue(22)
        widget.blockSignals(False)
        self.window._save_config_now()
        data = json.loads(self.path.read_text())
        self.assertEqual(data["max_scrolls"], 22)

    def test_stop_cancels_auto_reconnect(self) -> None:
        self.window._set_running(True)
        self.window._engine_expected = True
        self.window._game_expected = True
        with patch.object(ui_module.QTimer, "singleShot"):
            self.window._stop_engine()
        self.assertFalse(self.window._engine_expected)
        self.assertFalse(self.window._game_expected)
        self.window._set_running(False)

    def test_window_option_saves(self) -> None:
        self.window._set_config("gamescope_grab_cursor", True)
        self._wait_save()
        data = json.loads(self.path.read_text())
        self.assertTrue(data["gamescope_grab_cursor"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
