"""Shop session: buy, scroll and close, only after a spawner click."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..shopvision import ShopVision
from ..vision import Match
from .context import Runtime


@dataclass
class ShopScan:
    buys: list[Match]
    close: Optional[Match]
    scroll: Optional[Match]

    @property
    def open(self) -> bool:
        """A real shop needs its close button plus something inside it."""
        return self.close is not None and (
            bool(self.buys) or self.scroll is not None
        )


class ShopSession:
    """Owns every action inside the spawner shop.

    A session is only created after the macro clicked a spawner. Nothing in
    this class scans the general game screen for Buy buttons.
    """

    def __init__(self, runtime: Runtime, vision: Optional[ShopVision] = None) -> None:
        self.runtime = runtime
        self.vision = vision or ShopVision(runtime.matcher)

    # -- detection ----------------------------------------------------------

    def scan(self, frame: np.ndarray) -> ShopScan:
        buys = self.vision.buy_buttons(frame)
        close = self.vision.close_button(frame)
        scroll = None if buys else self.vision.scrollbar(frame)
        return ShopScan(buys, close, scroll)

    def is_open(self, frame: np.ndarray) -> bool:
        return self.scan(frame).open

    def wait_opened(self, timeout: Optional[float] = None) -> bool:
        config = self.runtime.config
        deadline = time.monotonic() + (
            config.shop_open_timeout if timeout is None else timeout
        )
        while time.monotonic() < deadline:
            self.runtime.check_stop()
            frame = self.runtime.capture()
            scan = self.scan(frame)
            # A lone red X is not a shop: the leaderboard and the map also
            # have red elements. Buy buttons or a scrollbar must accompany it.
            if scan.open:
                self.runtime.log(
                    f"Shop detected: {len(scan.buys)} Buy button(s), "
                    f"close={'yes' if scan.close else 'no'}.",
                    "success",
                )
                self.runtime.emit_preview(
                    frame,
                    scan.buys[:5] or ([scan.close] if scan.close else []),
                )
                return True
            self.runtime.sleep(0.10)
        return False

    # -- full cycle ---------------------------------------------------------

    def run(self) -> tuple[int, int]:
        self.runtime.status("Buying spawners...")
        clicks, scrolls = self.buy_and_scroll()
        self.runtime.stats.cycles += 1
        self.runtime.stats_changed()
        self.runtime.log(
            f"Shop complete: {clicks} buy clicks and {scrolls} scrolls.",
            "success",
        )
        if self.runtime.config.close_shop:
            self.close()
        self.runtime.sleep(self.runtime.config.cycle_delay)
        return clicks, scrolls

    def buy_and_scroll(self) -> tuple[int, int]:
        config = self.runtime.config
        total_clicks = 0
        scrolls_done = 0
        handled: set[tuple[int, int]] = set()
        empty_scrolls = 0
        missing_shop = 0

        while not self.runtime.stop_event.is_set():
            self.runtime.check_stop()
            frame = self.runtime.capture()
            scan = self.scan(frame)
            buys = self._filter_handled(scan.buys, handled)
            if len(buys) > config.max_buy_buttons:
                buys = buys[: config.max_buy_buttons]
            self.runtime.emit_preview(frame, buys)

            if buys:
                # Buy buttons prove the shop is open even if the close X is
                # briefly not detected while the panel updates.
                missing_shop = 0
                empty_scrolls = 0
                self.runtime.log(
                    f"{len(buys)} visible Buy button(s); "
                    f"{config.buy_clicks} clicks each.",
                    "action",
                )
                for match in buys:
                    self.runtime.check_stop()
                    clicks = self._click_buy(match)
                    total_clicks += clicks
                    handled.add((match.cx, match.cy))
                    self.runtime.sleep(config.action_delay)
                    if total_clicks >= config.max_cycle_buy_clicks:
                        self.runtime.log(
                            "Safety click limit reached for this shop.",
                            "warning",
                        )
                        return total_clicks, scrolls_done
                # Let the panel finish its purchase animation before the
                # next close/scroll scan.
                self.runtime.sleep(0.35)
                continue

            if scan.close is None and scan.scroll is None:
                # The close button can flicker for a moment after buying.
                # Only declare the shop closed after several empty scans.
                missing_shop += 1
                if missing_shop >= 5:
                    self.runtime.log(
                        "Shop is closed; stopping the Buy scan.", "info"
                    )
                    break
                self.runtime.sleep(0.35)
                continue

            missing_shop = 0
            if scrolls_done >= config.max_scrolls:
                self.runtime.log(
                    f"Scroll limit of {config.max_scrolls} reached.",
                    "warning",
                )
                break

            progress = self._scroll_shop(frame, handled)
            scrolls_done += 1
            self.runtime.stats.scrolls += 1
            self.runtime.stats_changed()

            if progress:
                empty_scrolls = 0
                handled.clear()
                # Smooth scrolling keeps moving for a moment: let the list
                # settle before clicking a Buy button at a new position.
                after = self.runtime.capture()
                if self.vision.buy_buttons(after):
                    self.runtime.sleep(config.scroll_settle_delay)
                self.runtime.sleep(config.action_delay)
                continue

            empty_scrolls += 1
            if empty_scrolls >= 2:
                self.runtime.log(
                    "No more Buy buttons after scrolling; end of list.",
                    "success",
                )
                break
            self.runtime.sleep(config.action_delay)

        return total_clicks, scrolls_done

    # -- buying -------------------------------------------------------------

    @staticmethod
    def _filter_handled(
        matches: list[Match],
        handled: set[tuple[int, int]],
    ) -> list[Match]:
        if not handled:
            return matches
        result = []
        for match in matches:
            if any(
                abs(match.cx - hx) <= 22 and abs(match.cy - hy) <= 16
                for hx, hy in handled
            ):
                continue
            result.append(match)
        return result

    def _click_buy(self, match: Match) -> int:
        config = self.runtime.config
        count = max(1, config.buy_clicks)
        series = getattr(self.runtime.backend, "click_series", None)
        if series is not None:
            self.runtime.check_stop()
            try:
                series(
                    match.cx,
                    match.cy,
                    count,
                    max(0.02, config.buy_click_delay),
                )
                self.runtime.stats.buy_clicks += count
                self.runtime.stats_changed()
                return count
            except Exception as exc:
                self.runtime.log(
                    f"click_series failed, falling back to single clicks: {exc}",
                    "warning",
                )
        for index in range(count):
            self.runtime.check_stop()
            self.runtime.backend.click(match.cx, match.cy, park=False)
            self.runtime.stats.buy_clicks += 1
            if index < count - 1:
                self.runtime.sleep(config.buy_click_delay)
        try:
            self.runtime.backend.park_cursor()
        except Exception:
            pass
        self.runtime.stats_changed()
        return count

    # -- scrolling ----------------------------------------------------------

    def _scroll_shop(
        self,
        frame: np.ndarray,
        handled: set[tuple[int, int]],
    ) -> bool:
        if self.runtime.config.scroll_method == "drag":
            if self._scroll_with_bar(handled):
                return True
            return self._scroll_wheel(frame, handled)
        if self._scroll_wheel(frame, handled):
            return True
        return self._scroll_with_bar(handled)

    def _scroll_wheel(
        self,
        frame: np.ndarray,
        handled: set[tuple[int, int]],
    ) -> bool:
        config = self.runtime.config
        height, width = frame.shape[:2]
        notches = max(2, min(10, config.scroll_drag_px // 40))
        for _ in range(notches):
            self.runtime.check_stop()
            self.runtime.backend.scroll(-1, x=width // 2, y=int(height * 0.55))
            self.runtime.sleep(0.02)
        self.runtime.sleep(0.08)
        after = self.runtime.capture()
        buys = self.vision.buy_buttons(after)
        new_buys = self._filter_handled(buys, handled)
        if new_buys:
            self.runtime.emit_preview(after, new_buys)
            return True
        before_thumb = self.vision.scrollbar(frame)
        after_thumb = self.vision.scrollbar(after)
        if (
            before_thumb is not None
            and after_thumb is not None
            and abs(after_thumb.cy - before_thumb.cy) > 3
        ):
            return True
        before_positions = {(m.x, m.y) for m in self.vision.buy_buttons(frame)}
        after_positions = {(m.x, m.y) for m in buys}
        return before_positions != after_positions

    def _scroll_with_bar(
        self,
        handled: set[tuple[int, int]],
    ) -> bool:
        frame = self.runtime.capture()
        scroll = self.vision.scrollbar(frame)
        if scroll is None:
            return False
        before_cy = scroll.cy
        found = self._scroll_drag(scroll, handled)
        if found is not None:
            return True
        after = self.runtime.capture()
        after_thumb = self.vision.scrollbar(after)
        return bool(
            after_thumb is not None
            and abs(after_thumb.cy - before_cy) > 3
        )

    def _scroll_drag(
        self,
        scroll: Match,
        handled: set[tuple[int, int]],
    ) -> Optional[Match]:
        config = self.runtime.config
        steps = max(2, config.scroll_probe_steps)
        distance = max(20, config.scroll_drag_px)
        delay = max(0.05, config.scroll_drag_ms / 1000.0) / steps
        x = scroll.cx
        y = scroll.cy
        probe_every = max(1, steps // 4)
        released = False

        smooth_move = getattr(self.runtime.backend, "smooth_move", None)
        if callable(smooth_move):
            smooth_move(x, y, duration=0.12)
        else:
            self.runtime.backend.move(x, y)
        self.runtime.backend.mouse_down()
        try:
            for step in range(1, steps + 1):
                self.runtime.check_stop()
                self.runtime.backend.move(
                    x, y + int(round(distance * step / steps))
                )
                self.runtime.sleep(delay)
                if step % probe_every == 0:
                    frame = self.runtime.capture()
                    buys = self._filter_handled(
                        self.vision.buy_buttons(frame), handled
                    )
                    if buys:
                        self.runtime.backend.mouse_up()
                        released = True
                        self.runtime.backend.park_cursor()
                        self.runtime.emit_preview(frame, buys)
                        return buys[0]
        finally:
            if not released:
                try:
                    self.runtime.backend.mouse_up()
                except Exception:
                    pass
                try:
                    self.runtime.backend.park_cursor()
                except Exception:
                    pass
        return None

    # -- close --------------------------------------------------------------

    def close(self, attempts: int = 3) -> bool:
        for attempt in range(attempts):
            frame = self.runtime.capture()
            match = self.vision.close_button(frame)
            if match is None and attempt == 0:
                # Give the panel a moment: the X can flicker right after a
                # purchase or during its closing animation.
                self.runtime.sleep(0.40)
                frame = self.runtime.capture()
                match = self.vision.close_button(frame)
            if match is None:
                if attempt == 0:
                    self.runtime.log("Shop is already closed.", "info")
                return True
            self.runtime.click_match(match, "Shop closed")
            for _ in range(6):
                self.runtime.check_stop()
                self.runtime.sleep(0.10)
                after = self.runtime.capture()
                if self.vision.close_button(after) is None:
                    return True
            self.runtime.log(
                f"Close button still visible (attempt {attempt + 1}/{attempts}); "
                "retrying.",
                "warning",
            )
        self.runtime.log("Couldn't close the shop.", "warning")
        return False
