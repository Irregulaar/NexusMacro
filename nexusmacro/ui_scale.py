"""Desktop-aware UI scaling for the fixed 880x560 window."""

from __future__ import annotations

# The design was made for a 1280x720 game on a 1920x1080 desktop. The window
# is 880x560 logical pixels, which is ~46% of the width and ~52% of the height
# of that screen. Scale the whole Qt UI by the same ratio on other desktops.
BASE_WIDTH = 1920
BASE_HEIGHT = 1080
MIN_SCALE = 0.80
MAX_SCALE = 2.0


def desktop_scale(screen_width: int, screen_height: int) -> float:
    """Return a Qt scale factor so the window keeps its relative size."""
    if screen_width <= 0 or screen_height <= 0:
        return 1.0
    raw = min(screen_width / BASE_WIDTH, screen_height / BASE_HEIGHT)
    return round(max(MIN_SCALE, min(MAX_SCALE, raw)), 2)
