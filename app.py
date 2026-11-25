#!/usr/bin/env python3
"""Nexus Macro entry point."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

# El backend de Qt debe elegirse antes de crear QApplication.
if "--ui-selftest" in sys.argv or "--ui-config-test" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _run_selftest() -> int:
    import cv2
    import numpy as np

    from nexusmacro.config import Config
    from nexusmacro.paths import bundled_template_dir, user_template_dir
    from nexusmacro.vision import Matcher, SPECS_BY_KEY

    config = Config()
    matcher = Matcher(bundled_template_dir(), user_template_dir(), config)
    frame = np.full((720, 1280, 3), (18, 26, 36), np.uint8)
    cv2.rectangle(frame, (50, 60), (1150, 460), (22, 24, 39), -1)

    placements = (
        ("battle", 600, 560),
        ("spawner1", 260, 560),
        ("buy", 430, 120),
        ("buy", 430, 180),
        ("scroll", 900, 100),
    )
    for key, x, y in placements:
        path = matcher.template_path(key)
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            print(f"FAIL: could not read {path}")
            return 1
        bgr = image[:, :, :3] if image.ndim == 3 and image.shape[2] == 4 else image
        if bgr.ndim == 2:
            bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
        h, w = bgr.shape[:2]
        frame[y : y + h, x : x + w] = bgr

    matches = matcher.detect_all(frame)
    keys = {match.key for match in matches}
    buys = [match for match in matches if match.key == "buy"]
    print(f"Detections: {sorted(keys)} · Buy: {len(buys)}")
    if not {"battle", "spawner1", "scroll"}.issubset(keys):
        print("FAIL: missing base detections.")
        return 1
    if len(buys) < 2:
        print("FAIL: the two Buy buttons were not detected.")
        return 1
    if any(match.score < 0.85 for match in matches):
        print("FAIL: a detection has a low score.")
        return 1
    print("SELFTEST OK")
    return 0


def _run_ui_selftest(output: Path) -> int:
    import tempfile

    from PySide6.QtCore import QLocale, QLockFile
    from PySide6.QtWidgets import QApplication

    import nexusmacro.config as config_module
    from nexusmacro.config import Config
    from nexusmacro.ui import MainWindow

    config_module.config_file = lambda: (
        Path(tempfile.mkdtemp()) / "config.json"
    )

    QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))
    app = QApplication(sys.argv)
    app.setApplicationName("NexusMacro")
    window = MainWindow(Config(), demo=True)
    window.resize(1280, 840)
    window.show()
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    output.parent.mkdir(parents=True, exist_ok=True)
    ok = window.grab().save(str(output))
    print(f"UI saved to {output}" if ok else "FAIL: could not save the UI")
    window.close()
    return 0 if ok else 1


def _run_doctor() -> int:
    """Print installation diagnostics without opening the UI or the game."""
    import platform
    import shutil
    import subprocess

    from nexusmacro.config import Config, config_file
    from nexusmacro.launcher import GamescopeLauncher
    from nexusmacro.paths import (
        APP_VERSION,
        DISPLAY_NAME,
        bundled_template_dir,
        data_dir,
        project_root,
        user_template_dir,
    )
    from nexusmacro.vision import SPECS_BY_KEY, Matcher

    print(f"{DISPLAY_NAME} {APP_VERSION}")
    print(f"System: {platform.platform()}")
    print(f"Python: {platform.python_version()} · frozen={getattr(sys, 'frozen', False)}")
    for key in (
        "XDG_SESSION_TYPE",
        "WAYLAND_DISPLAY",
        "DISPLAY",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
    ):
        print(f"{key}={os.environ.get(key, '')!r}")
    print(f"Project: {project_root()}")
    print(f"Config: {config_file()} (exists={config_file().exists()})")
    print(f"Data: {data_dir()}")
    print(f"User templates: {user_template_dir()}")

    launcher = GamescopeLauncher(Config())
    clean = launcher.clean_env()
    for tool in ("flatpak", "xdg-open"):
        print(f"{tool}: {shutil.which(tool) or 'NOT FOUND'}")
    gamescope = launcher.find_gamescope()
    print(f"gamescope: {gamescope or 'NOT FOUND'}")
    if shutil.which("flatpak"):
        try:
            version = subprocess.run(
                ["flatpak", "--version"],
                capture_output=True,
                text=True,
                env=clean,
                timeout=10,
                check=False,
            )
            print(f"flatpak version: {version.stdout.strip() or version.stderr.strip()}")
            info = subprocess.run(
                ["flatpak", "info", "org.vinegarhq.Sober"],
                capture_output=True,
                text=True,
                env=clean,
                timeout=15,
                check=False,
            )
            status = "OK" if info.returncode == 0 else "FAILED"
            print(f"flatpak Sober: {status} (exit {info.returncode})")
            detail = (info.stderr or info.stdout or "").strip()
            if detail:
                print(detail[:1500])
        except Exception as exc:
            print(f"flatpak check failed: {exc}")
    if gamescope:
        try:
            version = subprocess.run(
                [str(gamescope), "--version"],
                capture_output=True,
                text=True,
                env=launcher._environment(gamescope),
                timeout=10,
                check=False,
            )
            print(
                "gamescope version: "
                + (version.stdout.strip() or version.stderr.strip())
            )
        except Exception as exc:
            print(f"gamescope check failed: {exc}")

    matcher = Matcher(
        bundled_template_dir(),
        user_template_dir(),
        Config(),
    )
    missing = [
        spec.filename
        for spec in SPECS_BY_KEY.values()
        if not matcher.template_path(spec.key).exists()
    ]
    print(f"Templates: {len(SPECS_BY_KEY) - len(missing)}/{len(SPECS_BY_KEY)} present")
    if missing:
        print("Missing:", ", ".join(missing))
    return 0


def _run_ui_config_test() -> int:
    """Open the real window offscreen and prove widget changes hit disk."""
    import json
    import tempfile

    from PySide6.QtWidgets import QApplication

    import nexusmacro.config as config_module
    from nexusmacro.config import Config
    from nexusmacro.ui import MainWindow

    target = Path(tempfile.mkdtemp()) / "config.json"
    config_module.config_file = lambda: target
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(Config())
    window._set_running(False)

    # Real feature toggle (signals included).
    window.fuse_toggle.setChecked(True)
    window.place_toggle.setChecked(True)

    # A value typed into a spin box without pressing Enter.
    spin = window._fields["max_scrolls"]
    spin.blockSignals(True)
    spin.setValue(23)
    spin.blockSignals(False)

    # Window option from the Connection tab.
    window._fields["gamescope_grab_cursor"].setChecked(True)

    window._save_config_now()
    data = json.loads(target.read_text(encoding="utf-8"))
    problems = []
    if data.get("auto_fuse") is not True:
        problems.append("auto_fuse")
    if data.get("auto_best_place") is not True:
        problems.append("auto_best_place")
    if data.get("max_scrolls") != 23:
        problems.append("max_scrolls")
    if data.get("gamescope_grab_cursor") is not True:
        problems.append("gamescope_grab_cursor")

    window._running = False
    window.close()
    # The close handler must keep the values too.
    data = json.loads(target.read_text(encoding="utf-8"))
    if data.get("auto_fuse") is not True or data.get("max_scrolls") != 23:
        problems.append("close-save")

    if problems:
        print("FAIL: not saved: " + ", ".join(problems))
        return 1
    print("UI CONFIG SAVE OK")
    return 0


def _run_launch_test() -> int:
    from nexusmacro.config import Config
    from nexusmacro.launcher import GamescopeLauncher

    config = Config()
    launcher = GamescopeLauncher(config)
    ready = threading.Event()
    failed = threading.Event()
    result: dict = {}

    def on_log(message: str, level: str) -> None:
        print(f"[{level}] {message}", flush=True)

    def on_status(message: str) -> None:
        print(f"[status] {message}", flush=True)

    def on_ready(info: dict) -> None:
        result.update(info)
        ready.set()

    def on_error(message: str) -> None:
        print(f"[error] {message}", flush=True)
        failed.set()

    launcher.start_async(on_log, on_status, on_ready, on_error, kill_existing=True)
    deadline = time.monotonic() + 200
    while time.monotonic() < deadline:
        if ready.is_set():
            print(f"READY: {result}")
            launcher.stop()
            return 0
        if failed.is_set():
            launcher.stop()
            return 1
        time.sleep(0.25)
    print("FAIL: timeout")
    launcher.stop()
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="NexusMacro",
        description="Build a Tower Defense autopilot.",
    )
    parser.add_argument("--version", action="store_true", help="Show the version.")
    parser.add_argument(
        "--config-path",
        action="store_true",
        help="Print the active config.json path and exit.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Print installation diagnostics and exit.",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Test the detector and templates without opening the UI.",
    )
    parser.add_argument(
        "--ui-selftest",
        action="store_true",
        help="Render the UI to /tmp/nexusmacro_ui.png and exit.",
    )
    parser.add_argument(
        "--ui-config-test",
        action="store_true",
        help="Test that UI changes persist to config.json and exit.",
    )
    parser.add_argument(
        "--launch-test",
        action="store_true",
        help="Test launching and stopping headless Sober.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Open the UI with a demo preview.",
    )
    args = parser.parse_args(argv)

    if args.version:
        from nexusmacro.paths import APP_VERSION, DISPLAY_NAME

        print(f"{DISPLAY_NAME} {APP_VERSION}")
        return 0
    if args.config_path:
        from nexusmacro.config import config_file

        print(config_file())
        return 0
    if args.doctor:
        return _run_doctor()
    if args.selftest:
        return _run_selftest()
    if args.ui_selftest:
        return _run_ui_selftest(Path("/tmp/nexusmacro_ui.png"))
    if args.ui_config_test:
        return _run_ui_config_test()
    if args.launch_test:
        return _run_launch_test()

    from PySide6.QtCore import QLocale, QLockFile, Qt
    from PySide6.QtGui import QFont, QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from nexusmacro.config import Config
    from nexusmacro.paths import (
        APP_VERSION,
        DISPLAY_NAME,
        data_dir,
        icon_paths,
    )
    from nexusmacro.ui_scale import desktop_scale
    from nexusmacro.ui import MainWindow

    QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("NexusMacro")
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setOrganizationName("NexusMacro")
    app.setApplicationVersion(APP_VERSION)
    app.setDesktopFileName("NexusMacro")
    app.setStyle("Fusion")
    try:
        app.setFont(QFont("Noto Sans", 10))
    except Exception:
        pass
    try:
        icon = QIcon()
        for path in icon_paths():
            icon.addFile(str(path))
        if not icon.isNull():
            app.setWindowIcon(icon)
    except Exception:
        pass

    # Scale the whole fixed-size UI with the desktop, then re-exec once so Qt
    # applies the factor before creating any window. The design base is
    # 1920x1080 (880x560 is ~46% x ~52% of it). Respect an explicit override.
    if not os.environ.get("QT_SCALE_FACTOR") and not os.environ.get(
        "NEXUSMACRO_SCALE_APPLIED"
    ):
        screen = app.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            scale = desktop_scale(geometry.width(), geometry.height())
            if abs(scale - 1.0) > 0.02:
                os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
                os.environ["NEXUSMACRO_SCALE_APPLIED"] = "1"
                if getattr(sys, "frozen", False):
                    exec_args = [sys.executable, *sys.argv[1:]]
                else:
                    exec_args = [sys.executable, *sys.argv]
                os.execv(exec_args[0], exec_args)

    lock = QLockFile(str(data_dir() / "app.lock"))
    lock.setStaleLockTime(5000)
    if not lock.tryLock(100):
        QMessageBox.warning(
            None,
            DISPLAY_NAME,
            f"{DISPLAY_NAME} is already running.\n\n"
            "Close the other window before opening a new one; this protects "
            "your settings from being overwritten.",
        )
        return 1
    app._nexus_lock = lock

    config = Config.load()
    window = MainWindow(config, demo=args.demo)
    screen = app.primaryScreen()
    if screen is not None:
        geometry = screen.availableGeometry()
        window.move(geometry.center() - window.rect().center())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
