"""One-time Classic Forfeit setting check."""

from __future__ import annotations

from .context import Runtime
from .detection import ClassicRow, ScreenDetector


class ClassicForfeit:
    """Open Roblox settings once, find Classic Forfeit and turn it ON.

    The setting is under the in-game settings panel, which needs scrolling to
    the bottom. The result is stored in the config by the engine so it is
    checked only once, ever.
    """

    def __init__(self, runtime: Runtime, detector: ScreenDetector) -> None:
        self.runtime = runtime
        self.detector = detector

    def ensure(self) -> bool:
        frame = self.runtime.capture()
        row = self.detector.classic_forfeit_row(frame)
        opened = row is not None
        try:
            if row is None:
                gear = self.detector.settings_button(frame)
                if gear is None:
                    self.runtime.log(
                        "Classic Forfeit: settings button not found.", "warning"
                    )
                    return False
                self.runtime.click_match(gear, "Settings opened")
                self.runtime.sleep(0.8)
                frame = self.runtime.capture()
                # The X confirms the panel actually opened. Without it,
                # scrolling would hit the game map and Escape could close an
                # unrelated menu.
                close = self.detector.settings_close(frame)
                if close is None:
                    for _ in range(3):
                        self.runtime.sleep(0.3)
                        frame = self.runtime.capture()
                        close = self.detector.settings_close(frame)
                        if close is not None:
                            break
                if close is None:
                    self.runtime.save_debug(
                        frame,
                        "settings_panel_not_open",
                        "Clicked the settings gear but the panel X was not found",
                    )
                    self.runtime.log(
                        "Classic Forfeit: settings panel did not open.",
                        "warning",
                    )
                    return False
                opened = True

            for attempt in range(14):
                frame = self.runtime.capture()
                row = self.detector.classic_forfeit_row(frame)
                if row is not None:
                    return self._apply(row)
                close = self.detector.settings_close(frame)
                if close is None:
                    self.runtime.log(
                        "Classic Forfeit: settings panel closed while scrolling.",
                        "warning",
                    )
                    return False
                if attempt == 0:
                    self.runtime.log(
                        "Classic Forfeit: scrolling settings to the bottom.",
                        "info",
                    )
                h, w = frame.shape[:2]
                # Inside the settings panel, not below it.
                self.runtime.backend.scroll(
                    -2, x=int(w * 0.15), y=int(h * 0.38)
                )
                self.runtime.sleep(0.35)

            self.runtime.save_debug(
                self.runtime.capture(),
                "classic_forfeit_not_found",
                "Settings panel opened but the Classic Forfeit row was not found",
            )
            self.runtime.log(
                "Classic Forfeit: row not found after scrolling; will retry.",
                "warning",
            )
            return False
        finally:
            if opened:
                try:
                    frame = self.runtime.capture()
                    close = self.detector.settings_close(frame)
                    if close is not None:
                        self.runtime.click_match(close, "Settings closed")
                    else:
                        self.runtime.key("Escape")
                    self.runtime.sleep(0.25)
                except Exception:
                    pass

    def _apply(self, row: ClassicRow) -> bool:
        if row.on:
            self.runtime.log("Classic Forfeit: already ON.", "success")
            return True

        toggle_x = row.match.x + int(row.match.w * 0.85)
        toggle_y = row.match.y + int(row.match.h * 0.30)
        self.runtime.log("Classic Forfeit: OFF; enabling it.", "action")
        self.runtime.click(toggle_x, toggle_y)
        self.runtime.sleep(0.7)

        after = self.runtime.capture()
        check = self.detector.classic_forfeit_row(after)
        if check is not None and check.on:
            self.runtime.log("Classic Forfeit: enabled and verified.", "success")
            return True

        # One retry: some panels animate the toggle.
        self.runtime.click(toggle_x, toggle_y)
        self.runtime.sleep(0.7)
        after = self.runtime.capture()
        check = self.detector.classic_forfeit_row(after)
        if check is not None and check.on:
            self.runtime.log("Classic Forfeit: enabled and verified.", "success")
            return True

        self.runtime.save_debug(
            after,
            "classic_forfeit_not_enabled",
            "Clicked the Classic Forfeit toggle but it is not green",
        )
        self.runtime.log(
            "Classic Forfeit: could not verify the toggle; will retry.",
            "warning",
        )
        return False
