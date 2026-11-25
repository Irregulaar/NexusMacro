"""Engine logic tests with a simulated game."""

from __future__ import annotations

import shutil
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from nexusmacro.config import Config
from nexusmacro.engine import Engine, EngineCallbacks
from nexusmacro.vision import Matcher

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str) -> np.ndarray:
    image = cv2.imread(str(ROOT / "templates" / name), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Missing {name}")
    if image.ndim == 3 and image.shape[2] == 4:
        return image[:, :, :3]
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return image


class FakeGame:
    """Juego simulado que dibuja los templates reales y reacciona a clics."""

    def __init__(self) -> None:
        self.display_name = ":99"
        self.mode = "menu"
        self.scroll_offset = 0
        self.max_scroll = 240
        self.items = [{"bought": False, "clicks": 0} for _ in range(12)]
        self.current_x = 640
        self.current_y = 360
        self.dragging = False
        self.drag_last_y = 0
        self.battle_clicks = 0
        self.close_clicks = 0
        self.spawner_clicks = 0
        self.clicked_positions: list[tuple[int, int]] = []

    # -- backend ------------------------------------------------------------

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def ping(self) -> bool:
        return True

    @property
    def size(self) -> tuple[int, int]:
        return 1280, 720

    @property
    def width(self) -> int:
        return 1280

    @property
    def height(self) -> int:
        return 720

    def capture(self) -> np.ndarray:
        frame = np.full((720, 1280, 3), (18, 26, 36), np.uint8)
        cv2.rectangle(frame, (280, 60), (1180, 680), (22, 24, 39), -1)
        if self.mode == "menu":
            # The real game puts these buttons in the bottom bar.
            self._paste(frame, "battle1.png", 600, 560)
            self._paste(frame, "spawners1.png", 800, 560)
        elif self.mode == "shop":
            self._paste(frame, "closebutton.png", 1100, 100)
            for index, item in enumerate(self.items):
                if item["bought"]:
                    continue
                y = 120 + index * 60 - self.scroll_offset
                if 80 <= y <= 660:
                    self._paste(frame, "buybutton.png", 400, y)
            thumb_y = 80 + self.scroll_offset
            self._paste(frame, "scrollspawner.png", 1000, thumb_y)
        return frame

    def _paste(self, frame: np.ndarray, name: str, x: int, y: int) -> None:
        image = _load(name)
        h, w = image.shape[:2]
        if y + h <= frame.shape[0] and x + w <= frame.shape[1]:
            frame[y : y + h, x : x + w] = image

    def _buy_rects(self) -> list[tuple[int, int, int, int, int]]:
        result = []
        for index, item in enumerate(self.items):
            if item["bought"]:
                continue
            y = 120 + index * 60 - self.scroll_offset
            if 80 <= y <= 660:
                result.append((400, y, 105, 28, index))
        return result

    def click(self, x: int, y: int, button: int = 1, park: bool | None = None) -> None:
        self.current_x, self.current_y = x, y
        self.clicked_positions.append((x, y))
        if self.mode == "menu":
            if 600 <= x <= 703 and 560 <= y <= 661:
                self.battle_clicks += 1
                self.mode = "battle"
                return
            if 800 <= x <= 887 and 560 <= y <= 662:
                self.spawner_clicks += 1
                self.mode = "shop"
                self.scroll_offset = 0
                return
        elif self.mode == "shop":
            if 1100 <= x <= 1131 and 100 <= y <= 130:
                self.close_clicks += 1
                self.mode = "menu"
                return
            for bx, by, bw, bh, index in self._buy_rects():
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    item = self.items[index]
                    item["clicks"] += 1
                    if item["clicks"] >= 5:
                        item["bought"] = True
                    return

    def move(self, x: int, y: int) -> None:
        self.current_x, self.current_y = x, y
        if self.dragging:
            delta = y - self.drag_last_y
            self.scroll_offset = max(
                0, min(self.max_scroll, self.scroll_offset + delta)
            )
            self.drag_last_y = y

    def mouse_down(self, button: int = 1) -> None:
        if self.mode == "shop":
            thumb_y = 80 + self.scroll_offset
            if 1000 <= self.current_x <= 1012 and thumb_y <= self.current_y <= thumb_y + 189:
                self.dragging = True
                self.drag_last_y = self.current_y

    def mouse_up(self, button: int = 1) -> None:
        self.dragging = False

    def park_cursor(self) -> None:
        self.current_x, self.current_y = 1278, 718

    def scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> None:
        if self.mode == "shop":
            self.scroll_offset = max(
                0, min(self.max_scroll, self.scroll_offset - clicks * 30)
            )

    def focus(self) -> None:
        pass

    def key(self, name: str) -> None:
        pass


class StaticShopBackend(FakeGame):
    """Backend whose capture never changes, like an unresponsive shop."""

    def __init__(self, frame: np.ndarray) -> None:
        super().__init__()
        self.mode = "shop"
        self.frame = frame
        self.static_clicks = 0
        self.static_wheels = 0

    def capture(self) -> np.ndarray:
        return self.frame.copy()

    def click(self, x, y, button=1, park=None) -> None:
        self.static_clicks += 1

    def click_series(self, x, y, count, delay=0.04, button=1) -> None:
        self.static_clicks += count

    def scroll(self, clicks, x=None, y=None) -> None:
        self.static_wheels += abs(clicks)


class ScrollingShopBackend(FakeGame):
    """Shop that only reveals Buy buttons after the wheel scrolls."""

    def __init__(self, initial: np.ndarray, scrolled: np.ndarray) -> None:
        super().__init__()
        self.mode = "shop"
        self.initial = initial
        self.scrolled = scrolled
        self.show_scrolled = False
        self.wheels = 0
        self.buy_clicks = 0

    def capture(self) -> np.ndarray:
        source = self.scrolled if self.show_scrolled else self.initial
        return source.copy()

    def scroll(self, clicks, x=None, y=None) -> None:
        self.wheels += abs(clicks)
        self.show_scrolled = True

    def click_series(self, x, y, count, delay=0.04, button=1) -> None:
        self.buy_clicks += count

    def click(self, x, y, button=1, park=None) -> None:
        pass


class EngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config()
        self.config.threshold = 0.88
        self.config.scale = 1.0
        self.config.buy_clicks = 5
        self.config.buy_click_delay = 0.0
        self.config.action_delay = 0.0
        self.config.battle_cooldown = 0.0
        self.config.cycle_delay = 0.0
        self.config.idle_poll = 0.0
        self.config.scroll_drag_ms = 100
        self.config.scroll_probe_steps = 4
        self.config.shop_open_timeout = 2.0
        self.config.max_scrolls = 20
        self.config.close_shop = True
        self.config.spawner_timing = "clock"
        self.config.spawner_buy_on_start = False
        # The one-time Classic Forfeit check has its own test.
        self.config.classic_forfeit_checked = True
        self.matcher = Matcher(ROOT / "templates", ROOT / "templates", self.config)
        self.stop = threading.Event()

    def _callbacks(self):
        events = []
        callbacks = EngineCallbacks(
            log=lambda message, level="info": events.append((level, message)),
            status=lambda text: None,
            stats=lambda stats: None,
            preview=lambda frame, matches: None,
        )
        return callbacks, events

    def test_auto_battle(self) -> None:
        self.config.auto_battle = True
        self.config.auto_spawners = False
        fake = FakeGame()
        callbacks, events = self._callbacks()
        engine = Engine(fake, self.config, self.matcher, callbacks, self.stop)
        engine.tick(fake.capture())
        self.assertEqual(fake.battle_clicks, 1)
        self.assertEqual(engine.stats.battles, 1)
        self.assertTrue(any("Battle started" in message for _, message in events))

    def test_spawner_shop_buy_and_scroll(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = True
        fake = FakeGame()
        callbacks, events = self._callbacks()
        engine = Engine(fake, self.config, self.matcher, callbacks, self.stop)
        engine.request_spawner_purchase()
        engine.tick(fake.capture())
        self.assertEqual(fake.spawner_clicks, 1)
        self.assertEqual(engine.stats.spawner_opens, 1)
        self.assertTrue(all(item["bought"] for item in fake.items))
        self.assertEqual(engine.stats.buy_clicks, len(fake.items) * 5)
        self.assertGreaterEqual(engine.stats.scrolls, 1)
        self.assertEqual(fake.mode, "menu")
        self.assertEqual(fake.close_clicks, 1)
        self.assertTrue(any("Shop complete" in message for _, message in events))

    def test_shop_scan_finds_buttons_at_other_scale(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = True
        fake = FakeGame()
        fake.mode = "shop"
        callbacks, _ = self._callbacks()
        engine = Engine(fake, self.config, self.matcher, callbacks, self.stop)
        scale, buys, scroll, close = engine._shop_scan(
            fake.capture(), preferred_scale=0.95
        )
        self.assertAlmostEqual(scale, 1.0, places=1)
        self.assertGreaterEqual(len(buys), 1)
        self.assertIsNotNone(scroll)
        self.assertIsNotNone(close)

    def test_open_shop_is_closed_before_the_spawner_cycle(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = True
        fake = FakeGame()
        fake.mode = "shop"
        callbacks, events = self._callbacks()
        engine = Engine(fake, self.config, self.matcher, callbacks, self.stop)
        engine.request_spawner_purchase()
        # First tick closes the leftover shop; the manual request stays queued.
        engine.tick(fake.capture())
        # The next tick runs a clean spawner cycle.
        engine.tick(fake.capture())
        self.assertEqual(fake.close_clicks, 2)
        self.assertEqual(fake.spawner_clicks, 1)
        self.assertTrue(all(item["bought"] for item in fake.items))
        self.assertEqual(fake.mode, "menu")
        self.assertGreater(engine.stats.cycles, 0)

    def test_manual_spawner_purchase(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = True
        self.config.spawner_timing = "clock"
        self.config.spawner_buy_on_start = False
        # The one-time Classic Forfeit check has its own test.
        self.config.classic_forfeit_checked = True
        fake = FakeGame()
        callbacks, events = self._callbacks()
        engine = Engine(fake, self.config, self.matcher, callbacks, self.stop)
        engine.request_spawner_purchase()
        engine.tick(fake.capture())
        self.assertTrue(all(item["bought"] for item in fake.items))
        self.assertEqual(engine.stats.buy_clicks, len(fake.items) * 5)
        self.assertTrue(any("Manual spawner" in message for _, message in events))

    def test_static_shop_does_not_reclick_forever(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = True
        self.config.scroll_method = "wheel"
        frame = np.full((720, 1280, 3), (26, 44, 75), np.uint8)
        buy = _load("buybutton.png")
        for index in range(3):
            y = 120 + index * 60
            frame[y : y + buy.shape[0], 400 : 400 + buy.shape[1]] = buy
        close = _load("closebutton.png")
        frame[100 : 100 + close.shape[0], 1100 : 1100 + close.shape[1]] = close
        fake = StaticShopBackend(frame)
        callbacks, events = self._callbacks()
        engine = Engine(fake, self.config, self.matcher, callbacks, self.stop)
        clicks, scrolls = engine._buy_and_scroll()
        self.assertEqual(clicks, 3 * self.config.buy_clicks)
        self.assertEqual(fake.static_clicks, 3 * self.config.buy_clicks)
        self.assertLessEqual(scrolls, 2)

    def test_battle_continue_template_is_detected(self) -> None:
        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        template = _load("battle2.png")
        frame[560 : 560 + template.shape[0], 600 : 600 + template.shape[1]] = template
        engine = Engine(
            FakeGame(), self.config, self.matcher, self._callbacks()[0], self.stop
        )
        match = engine._find_battle(frame)
        self.assertIsNotNone(match)
        self.assertEqual(match.key, "battle2")

    def test_current_spawner_template_is_detected(self) -> None:
        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        template = _load("spawnerbutton3.png")
        frame[590 : 590 + template.shape[0], 760 : 760 + template.shape[1]] = template
        engine = Engine(
            FakeGame(), self.config, self.matcher, self._callbacks()[0], self.stop
        )
        key, match, scale = engine._find_spawner(frame)
        self.assertEqual(key, "spawner3")
        self.assertIsNotNone(match)
        self.assertAlmostEqual(scale, 1.0, places=1)

    def test_compact_spawner_is_found_at_small_scales(self) -> None:
        self.config.spawner_threshold = 0.80
        engine = Engine(
            FakeGame(), self.config, self.matcher, self._callbacks()[0], self.stop
        )
        template = _load("spawners2.png")
        for factor in (0.9, 1.0, 1.2):
            image = cv2.resize(template, None, fx=factor, fy=factor)
            frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
            frame[400 : 400 + image.shape[0], 820 : 820 + image.shape[1]] = image
            key, match, scale = engine._find_spawner(frame)
            self.assertEqual(key, "spawner2", f"scale {factor}")
            self.assertIsNotNone(match)
            self.assertGreaterEqual(match.score, 0.80)
            self.assertLess(abs(scale - factor), 0.07)

    def test_spawner_scan_expands_when_native_scale_is_weak(self) -> None:
        self.config.spawner_threshold = 0.80
        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        template = _load("spawners1.png")
        scaled = cv2.resize(template, None, fx=0.8, fy=0.8)
        frame[600 : 600 + scaled.shape[0], 790 : 790 + scaled.shape[1]] = scaled
        engine = Engine(
            FakeGame(), self.config, self.matcher, self._callbacks()[0], self.stop
        )
        key, match, scale = engine._find_spawner(frame)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match.score, 0.80)
        self.assertAlmostEqual(scale, 0.8, places=1)

    def test_scroll_settle_delay_before_clicking(self) -> None:
        self.config.scroll_method = "wheel"
        self.config.scroll_settle_delay = 1.2
        self.config.buy_clicks = 5
        initial = np.full((720, 1280, 3), (26, 44, 75), np.uint8)
        close = _load("closebutton.png")
        initial[100 : 100 + close.shape[0], 1100 : 1100 + close.shape[1]] = close
        scrolled = initial.copy()
        buy = _load("buybutton.png")
        for index in range(3):
            y = 200 + index * 60
            scrolled[y : y + buy.shape[0], 400 : 400 + buy.shape[1]] = buy
        fake = ScrollingShopBackend(initial, scrolled)
        engine = Engine(
            fake, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        sleeps: list[float] = []
        engine.runtime.sleep = lambda seconds: sleeps.append(seconds)
        clicks, scrolls = engine._buy_and_scroll()
        self.assertEqual(clicks, 3 * 5)
        self.assertEqual(fake.buy_clicks, 3 * 5)
        self.assertGreaterEqual(scrolls, 1)
        self.assertTrue(
            any(abs(value - 1.2) < 1e-6 for value in sleeps),
            "expected the 1.2 s settle delay after scrolling",
        )

    def test_build_action_clicks_fuse_twice_and_stops(self) -> None:
        self.config.fuse_wait_seconds = 0.0
        engine = Engine(
            FakeGame(), self.config, self.matcher, self._callbacks()[0], self.stop
        )
        engine.runtime.sleep = lambda seconds: None

        class BuildMenuBackend(FakeGame):
            def __init__(self) -> None:
                super().__init__()
                self.frames: list[np.ndarray] = []
                self.index = 0
                self.clicks: list[tuple[int, int]] = []

            def capture(self) -> np.ndarray:
                return self.frames[min(self.index, len(self.frames) - 1)].copy()

            def click(self, x, y, button=1, park=None) -> None:
                self.clicks.append((x, y))
                self.index = min(self.index + 1, len(self.frames) - 1)

        frame0 = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        build = _load("build1.png")
        frame0[600 : 600 + build.shape[0], 700 : 700 + build.shape[1]] = build
        frame1 = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        fuse = _load("fuseallbutton.png")
        stop = _load("stopbutton.png")
        frame1[300 : 300 + fuse.shape[0], 500 : 500 + fuse.shape[1]] = fuse
        frame1[600 : 600 + stop.shape[0], 700 : 700 + stop.shape[1]] = stop
        frame2 = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        frame2[600 : 600 + stop.shape[0], 700 : 700 + stop.shape[1]] = stop

        backend = BuildMenuBackend()
        backend.frames = [frame0, frame1, frame2]
        engine.backend = backend
        self.assertTrue(engine._run_build_action("fuse", frame0, allow_forfeit=False))
        self.assertEqual(len(backend.clicks), 4)

    def test_clock_spawner_runs_once_per_window(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = True
        self.config.spawner_timing = "clock"
        self.config.spawner_buy_on_start = False
        fake = FakeGame()
        engine = Engine(
            fake, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        reasons: list[str] = []
        engine._run_spawner_cycle = (  # type: ignore[method-assign]
            lambda frame, reason: (reasons.append(reason), True)[1]
        )
        frame = fake.capture()
        with patch(
            "nexusmacro.automation.spawner.is_spawner_window",
            return_value=(True, "window-1"),
        ):
            engine.tick(frame)
            engine.tick(frame)
            engine.tick(frame)
        self.assertEqual(reasons, ["refresh"])

    def test_play_button_is_clicked(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = False
        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        play = _load("playbutton.png")
        frame[600 : 600 + play.shape[0], 500 : 500 + play.shape[1]] = play
        fake = FakeGame()
        engine = Engine(
            fake, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        self.assertTrue(engine.tick(frame))
        self.assertTrue(fake.clicked_positions)

    def test_tab_is_not_pressed_without_tab_image(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = False

        class KeyBackend(FakeGame):
            def __init__(self) -> None:
                super().__init__()
                self.keys: list[str] = []

            def key(self, name: str) -> None:
                self.keys.append(name)

        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        backend = KeyBackend()
        engine = Engine(
            backend, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        engine._tab_after = 0.0
        engine._maybe_hide_leaderboard(frame)
        engine._maybe_hide_leaderboard(frame)
        self.assertEqual(backend.keys, [])
        self.assertFalse(engine._tab_done)

    def test_tab_presses_when_the_image_is_visible(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = False

        class KeyBackend(FakeGame):
            def __init__(self) -> None:
                super().__init__()
                self.keys: list[str] = []

            def key(self, name: str) -> None:
                self.keys.append(name)

        blank = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        tab_frame = blank.copy()
        tab = _load("tabimage.png")
        tab_frame[60 : 60 + tab.shape[0], 940 : 940 + tab.shape[1]] = tab
        backend = KeyBackend()
        engine = Engine(
            backend, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        engine._tab_after = 0.0
        engine._last_tab_scan = 0.0
        engine._maybe_hide_leaderboard(blank)
        self.assertEqual(backend.keys, [])
        engine._last_tab_scan = 0.0
        engine._maybe_hide_leaderboard(tab_frame)
        self.assertEqual(backend.keys, ["Tab"])
        self.assertTrue(engine._tab_done)

    def test_tab_detects_a_scaled_header(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = False

        class KeyBackend(FakeGame):
            def __init__(self) -> None:
                super().__init__()
                self.keys: list[str] = []

            def key(self, name: str) -> None:
                self.keys.append(name)

        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        tab = _load("tabimage.png")
        scaled = cv2.resize(tab, None, fx=0.9, fy=0.9)
        frame[60 : 60 + scaled.shape[0], 940 : 940 + scaled.shape[1]] = scaled
        backend = KeyBackend()
        engine = Engine(
            backend, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        engine._tab_after = 0.0
        engine._last_tab_scan = 0.0
        engine._maybe_hide_leaderboard(frame)
        self.assertEqual(backend.keys, ["Tab"])

    def test_play_click_rearms_tab(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = False

        class KeyBackend(FakeGame):
            def __init__(self) -> None:
                super().__init__()
                self.keys: list[str] = []

            def key(self, name: str) -> None:
                self.keys.append(name)

        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        play = _load("playbutton.png")
        frame[600 : 600 + play.shape[0], 500 : 500 + play.shape[1]] = play
        backend = KeyBackend()
        engine = Engine(
            backend, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        engine._tab_done = True
        engine.tick(frame)
        self.assertFalse(engine._tab_done)
        tab_frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        tab = _load("tabimage.png")
        tab_frame[60 : 60 + tab.shape[0], 940 : 940 + tab.shape[1]] = tab
        engine._tab_after = 0.0
        engine._last_tab_scan = 0.0
        engine._maybe_hide_leaderboard(tab_frame)
        self.assertEqual(backend.keys, ["Tab"])
        self.assertTrue(engine._tab_done)

    def test_play_click_still_works_after_tab(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = False
        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        play = _load("playbutton.png")
        frame[600 : 600 + play.shape[0], 500 : 500 + play.shape[1]] = play
        fake = FakeGame()
        engine = Engine(
            fake, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        engine._tab_done = True
        self.assertTrue(engine.tick(frame))
        self.assertTrue(fake.clicked_positions)

    def test_no_buy_clicks_outside_a_spawner_cycle(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = True
        self.config.spawner_timing = "interval"
        self.config.spawner_buy_on_start = False
        fake = FakeGame()
        fake.mode = "shop"
        engine = Engine(
            fake, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        engine._next_interval_at = float("inf")
        engine.tick(fake.capture())
        self.assertEqual(engine.stats.buy_clicks, 0)
        self.assertEqual(engine.stats.cycles, 0)
        self.assertTrue(all(item["clicks"] == 0 for item in fake.items))

    def test_saved_battle_discard_button_is_clicked(self) -> None:
        self.config.auto_battle = False
        self.config.auto_spawners = False
        frame = np.full((720, 1280, 3), (20, 9, 7), np.uint8)
        discard = _load("discardbutton.png")
        frame[500 : 500 + discard.shape[0], 500 : 500 + discard.shape[1]] = discard
        fake = FakeGame()
        engine = Engine(
            fake, self.config, self.matcher, self._callbacks()[0], self.stop
        )
        engine._discard_until = float("inf")
        self.assertTrue(engine.tick(frame))
        self.assertTrue(fake.clicked_positions)
        self.assertEqual(engine._discard_until, 0.0)

    def test_no_action_when_nothing_visible(self) -> None:
        self.config.auto_battle = True
        self.config.auto_spawners = True
        self.config.spawner_timing = "interval"
        fake = FakeGame()
        fake.mode = "battle"
        callbacks, _ = self._callbacks()
        engine = Engine(fake, self.config, self.matcher, callbacks, self.stop)
        self.assertFalse(engine.tick(fake.capture()))
        self.assertEqual(fake.battle_clicks, 0)
        self.assertEqual(fake.spawner_clicks, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
