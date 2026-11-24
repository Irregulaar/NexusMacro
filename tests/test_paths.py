"""Portable project config path tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nexusmacro.paths as paths


class PortableConfigTest(unittest.TestCase):
    def test_project_home_uses_project_config_and_migrates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = base / "NexusMacro"
            project.mkdir()
            (project / "app.py").write_text("", encoding="utf-8")
            (project / "templates").mkdir()

            legacy = base / "xdg" / "NexusMacro"
            legacy.mkdir(parents=True)
            (legacy / "config.json").write_text(
                json.dumps({"auto_fuse": True}), encoding="utf-8"
            )

            with patch.dict(
                os.environ,
                {
                    "NEXUSMACRO_HOME": str(project),
                    "XDG_CONFIG_HOME": str(base / "xdg"),
                },
            ):
                self.assertEqual(paths.project_root(), project.resolve())
                self.assertEqual(paths.config_dir(), project / "config")
                config = project / "config" / "config.json"
                self.assertTrue(config.exists())
                self.assertTrue(json.loads(config.read_text())["auto_fuse"])

    def test_no_portable_root_falls_back_to_xdg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            invalid = base / "not-a-project"
            invalid.mkdir()
            with patch.object(
                paths, "_is_project_root", return_value=False
            ), patch.dict(
                os.environ,
                {
                    "NEXUSMACRO_HOME": str(invalid),
                    "XDG_CONFIG_HOME": str(base / "xdg"),
                },
            ):
                self.assertEqual(
                    paths.config_dir(), base / "xdg" / "NexusMacro"
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
