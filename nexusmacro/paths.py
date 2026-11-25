"""Nexus Macro paths (works from source and from a PyInstaller binary)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

DISPLAY_NAME = "Nexus Macro"
APP_NAME = "NexusMacro"
LEGACY_APP_NAME = "TowerPilot"  # only used to migrate old installs
APP_VERSION = "1.5.6"


def bundle_root() -> Path:
    """Folder containing templates/assets/vendor."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def _xdg_config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    return Path(value) if value else Path.home() / ".config"


def _migrate_legacy_dirs() -> None:
    """Copy the old TowerPilot config/data once, so nothing is lost."""
    import shutil

    try:
        old_config = _xdg_config_home() / LEGACY_APP_NAME
        new_config = _xdg_config_home() / APP_NAME
        if old_config.is_dir() and not new_config.exists():
            shutil.copytree(old_config, new_config)
    except Exception:
        pass
    try:
        old_data = _xdg_data_home() / LEGACY_APP_NAME
        new_data = _xdg_data_home() / APP_NAME
        if old_data.is_dir() and not new_data.exists():
            shutil.copytree(old_data, new_data)
    except Exception:
        pass


def _xdg_data_home() -> Path:
    value = os.environ.get("XDG_DATA_HOME")
    return Path(value) if value else Path.home() / ".local" / "share"


def _is_project_root(path: Path) -> bool:
    try:
        return path.is_dir() and (
            (path / "app.py").is_file() or (path / "templates").is_dir()
        )
    except OSError:
        return False


def project_root() -> Optional[Path]:
    """Portable project folder, when Nexus Macro is running from it.

    Priority:
      1. NEXUSMACRO_HOME (explicit override).
      2. For the installed binary: ~/.local/bin/NexusMacro.home written by
         install.sh with the project path.
      3. The source tree (this file is inside <project>/nexusmacro).
      4. The current working directory, if it looks like the project.
    """
    override = os.environ.get("NEXUSMACRO_HOME", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if _is_project_root(candidate):
            return candidate.resolve()

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        marker = executable.with_name(executable.name + ".home")
        try:
            candidate = Path(marker.read_text(encoding="utf-8").strip())
            if _is_project_root(candidate):
                return candidate.expanduser().resolve()
        except Exception:
            pass
    else:
        candidate = Path(__file__).resolve().parent.parent
        if _is_project_root(candidate):
            return candidate

    candidate = Path.cwd()
    if _is_project_root(candidate):
        return candidate.resolve()
    return None


def _migrate_config_to(path: Path) -> None:
    """Copy the old XDG config once, so switching to portable keeps settings."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        legacy = _xdg_config_home() / APP_NAME
        old_config = legacy / "config.json"
        new_config = path / "config.json"
        if old_config.is_file() and not new_config.exists():
            shutil.copy2(old_config, new_config)
        old_templates = legacy / "templates"
        if old_templates.is_dir():
            shutil.copytree(
                old_templates, path / "templates", dirs_exist_ok=True
            )
    except Exception:
        pass


def config_dir() -> Path:
    root = project_root()
    if root is not None:
        path = root / "config"
        _migrate_config_to(path)
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = _xdg_config_home() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    path = _xdg_data_home() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def captures_dir() -> Path:
    path = data_dir() / "captures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_template_dir() -> Path:
    path = config_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "config.json"


def bundled_template_dir() -> Path:
    return resource_path("templates")


def icon_path() -> Path:
    return resource_path("assets", "icon.png")


def icon_paths() -> list[Path]:
    """All bundled icon sizes, smallest first (Qt can pick for HiDPI)."""
    result = []
    for name in ("icon_64.png", "icon.png", "icon_512.png"):
        path = resource_path("assets", name)
        if path.exists():
            result.append(path)
    return result or [icon_path()]


def gamescope_vendor_bin() -> Path:
    return resource_path("vendor", "gamescope", "usr", "bin", "gamescope")


_migrate_legacy_dirs()
