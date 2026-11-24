#!/usr/bin/env python3
"""Generate the README screenshots without touching the real config."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import nexusmacro.config as config_module  # noqa: E402
import nexusmacro.ui_pages as ui_pages  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from nexusmacro.config import Config  # noqa: E402
from nexusmacro.engine import Stats  # noqa: E402
from nexusmacro.ui import MainWindow  # noqa: E402

SAMPLE_LOG = [
    ("success", "Engine connected to :2 (1280x720)."),
    ("info", "Spawner timing: clock. Next refresh at 14:00:00."),
    ("action", "Spawner shop opened: (796, 641) score 1.00."),
    ("success", "Shop detected: 6 Buy button(s), close=yes."),
    ("action", "6 visible Buy button(s); 5 clicks each."),
    ("success", "Shop complete: 30 buy clicks and 2 scrolls."),
    ("info", "Leaderboard hidden (Tab)."),
    ("success", "Build menu opened (verified)."),
    ("action", "Fuse clicked: (305, 292) score 0.81."),
    ("success", "Fuse: completed."),
    ("action", "Best Place clicked: (324, 182) score 0.99."),
    ("success", "Best Place: completed."),
    ("warning", "Reconnect detected; restarting Sober/gamescope."),
]

PAGES = (
    "connection",
    "automation",
    "settings",
    "log",
    "about",
)


def main() -> int:
    app = QApplication([])
    original = config_module.config_file
    # Display the real project path in About, but make save a no-op so the
    # real config is never written by this script.
    # Neutral paths for the README screenshots: never expose the local user.
    config_module.config_file = lambda: Path(
        "/home/you/.config/NexusMacro/config.json"
    )
    ui_pages.captures_dir = lambda: Path(
        "/home/you/.local/share/NexusMacro/captures"
    )
    window = MainWindow(Config(), demo=True)
    window.config.save = lambda *args, **kwargs: None  # type: ignore[method-assign]
    window._save_timer.stop()
    window.footer_save.setText("Saved 14:20")
    window._update_stats(
        Stats(battles=42, buy_clicks=315, scrolls=18, cycles=6)
    )
    for level, message in SAMPLE_LOG:
        window.log_view.append_log(message, level)
    window.show()
    app.processEvents()

    out = ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(PAGES):
        window._switch_page(index)
        app.processEvents()
        path = out / f"{index + 1:02d}-{name}.png"
        if not window.grab().save(str(path)):
            print(f"FAIL: could not save {path}")
            return 1
        print(path)

    config_module.config_file = original
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
