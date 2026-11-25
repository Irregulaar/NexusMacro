"""Launcher environment tests (PyInstaller leakage)."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from nexusmacro.config import Config
from nexusmacro.launcher import GamescopeLauncher


class LauncherEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config()
        self.launcher = GamescopeLauncher(self.config)

    def test_bundled_library_path_is_removed_for_children(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LD_LIBRARY_PATH": "/tmp/_MEI123",
                "LD_PRELOAD": "/tmp/_MEI123/libfoo.so",
                "PYTHONHOME": "/tmp/_MEI123",
                "PYTHONPATH": "/tmp/_MEI123",
                "QT_SCALE_FACTOR": "1.5",
            },
            clear=False,
        ):
            env = self.launcher.clean_env()
            self.assertNotIn("LD_LIBRARY_PATH", env)
            self.assertNotIn("LD_PRELOAD", env)
            self.assertNotIn("PYTHONHOME", env)
            self.assertNotIn("PYTHONPATH", env)
            self.assertNotIn("QT_SCALE_FACTOR", env)
            self.assertIn("PATH", env)

    def test_system_gamescope_uses_x11_sdl_when_display_exists(self) -> None:
        with patch.dict(
            os.environ,
            {"DISPLAY": ":0", "WAYLAND_DISPLAY": "", "LD_LIBRARY_PATH": "/tmp/_MEI"},
            clear=False,
        ):
            env = self.launcher._environment(Path("/usr/bin/gamescope"))
            self.assertEqual(env.get("SDL_VIDEODRIVER"), "x11")
            self.assertNotIn("LD_LIBRARY_PATH", env)

    def test_system_gamescope_uses_wayland_sdl_without_x11(self) -> None:
        with patch.dict(
            os.environ,
            {"DISPLAY": "", "WAYLAND_DISPLAY": "wayland-0"},
            clear=False,
        ):
            env = self.launcher._environment(Path("/usr/bin/gamescope"))
            self.assertEqual(env.get("SDL_VIDEODRIVER"), "wayland")

    def test_vendor_gamescope_gets_its_own_library_path(self) -> None:
        gamescope = Path("/tmp/vendor/gamescope/usr/bin/gamescope")
        with patch.dict(
            os.environ,
            {"DISPLAY": ":0", "LD_LIBRARY_PATH": "/tmp/_MEI"},
            clear=False,
        ):
            env = self.launcher._environment(gamescope)
            self.assertEqual(
                env.get("LD_LIBRARY_PATH"), "/tmp/vendor/gamescope/usr/lib"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
