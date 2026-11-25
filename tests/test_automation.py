"""Tests for the refactored automation pieces (no Qt)."""

from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from nexusmacro.automation.context import EngineCallbacks, Runtime
from nexusmacro.automation.detection import ScreenDetector
from nexusmacro.automation.navigation import Navigator
from nexusmacro.automation.spawner import SpawnerScheduler
from nexusmacro.config import Config
from nexusmacro.vision import Match, Matcher

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str) -> np.ndarray:
    return cv2.imread(str(ROOT / "templates" / name), cv2.IMREAD_UNCHANGED)


def _paste(frame: np.ndarray, name: str, x: int, y: int) -> None:
    image = _load(name)
    h, w = image.shape[:2]
    frame[y : y + h, x : x + w] = image


class _Backend:
    def __init__(self, frame: np.ndarray) -> None:
        self.frame = frame
        self.clicks: list[tuple[int, int]] = []

    def capture(self) -> np.ndarray:
        return self.frame

    def click(self, x, y, button=1, park=None) -> None:
        self.clicks.append((x, y))

    def key(self, name: str) -> None:
        pass

    def scroll(self, clicks, x=None, y=None) -> None:
        pass


class _RuntimeStub:
    def __init__(self, config: Config) -> None:
        self.config = config


class SchedulerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config()
        self.config.spawner_buy_on_start = False
        self.config.auto_spawners = True
        self.runtime = _RuntimeStub(self.config)

    def test_clock_purchases_once_per_window(self) -> None:
        self.config.spawner_timing = "clock"
        scheduler = SpawnerScheduler(self.runtime, now=100.0)
        with patch(
            "nexusmacro.automation.spawner.is_spawner_window",
            return_value=(True, "window-1"),
        ):
            decision = scheduler.due(now=101.0)
            self.assertIsNotNone(decision)
            self.assertEqual(decision.reason, "refresh")
            scheduler.finish(decision, success=True)
            self.assertIsNone(scheduler.due(now=102.0))

    def test_clock_retries_after_failure(self) -> None:
        self.config.spawner_timing = "clock"
        scheduler = SpawnerScheduler(self.runtime, now=100.0)
        with patch(
            "nexusmacro.automation.spawner.is_spawner_window",
            return_value=(True, "window-1"),
        ):
            decision = scheduler.due(now=101.0)
            scheduler.finish(decision, success=False)
            self.assertIsNone(scheduler.due(now=102.0))
            retry = scheduler.due(now=108.5)
            self.assertIsNotNone(retry)
            self.assertEqual(retry.reason, "refresh")

    def test_interval_resets_after_due(self) -> None:
        self.config.spawner_timing = "interval"
        self.config.spawner_interval_minutes = 5
        scheduler = SpawnerScheduler(self.runtime, now=100.0)
        self.assertIsNone(scheduler.due(now=101.0))
        decision = scheduler.due(now=self.config.spawner_interval_minutes * 60 + 101)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "interval")
        self.assertIsNone(scheduler.due(now=self.config.spawner_interval_minutes * 60 + 102))

    def test_continuous_polls(self) -> None:
        self.config.spawner_timing = "continuous"
        self.config.spawner_poll_seconds = 30
        scheduler = SpawnerScheduler(self.runtime, now=100.0)
        scheduler.last_attempt = 100.0
        self.assertIsNone(scheduler.due(now=110.0))
        decision = scheduler.due(now=131.0)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "continuous")

    def test_disabled_scheduler_never_fires(self) -> None:
        self.config.auto_spawners = False
        scheduler = SpawnerScheduler(self.runtime, now=100.0)
        self.assertIsNone(scheduler.due(now=10000.0))

    def test_config_change_resets_interval(self) -> None:
        self.config.spawner_timing = "interval"
        scheduler = SpawnerScheduler(self.runtime, now=100.0)
        old = scheduler.next_interval_at
        self.config.spawner_interval_minutes = 10
        scheduler.on_config_changed("spawner_interval_minutes")
        self.assertGreater(scheduler.next_interval_at, old)


class DetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config()
        self.frame = np.full((720, 1280, 3), (18, 26, 36), np.uint8)
        self.backend = _Backend(self.frame)
        callbacks = EngineCallbacks(
            log=lambda *a: None,
            status=lambda *a: None,
            stats=lambda *a: None,
            preview=lambda *a: None,
        )
        self.runtime = Runtime(
            self.backend,
            self.config,
            Matcher(ROOT / "templates", ROOT / "templates", self.config),
            callbacks,
            threading.Event(),
        )
        self.detector = ScreenDetector(self.runtime)

    def test_play_and_discard_templates(self) -> None:
        frame = self.frame.copy()
        _paste(frame, "playbutton.png", 500, 600)
        self.assertIsNotNone(self.detector.play(frame))
        frame = self.frame.copy()
        _paste(frame, "discardbutton.png", 500, 500)
        self.assertIsNotNone(self.detector.discard(frame))

    def test_forfeit_means_battle_active(self) -> None:
        frame = self.frame.copy()
        _paste(frame, "forfeitbutton.png", 600, 560)
        self.assertTrue(self.detector.battle_active(frame))
        self.assertTrue(self.detector.game_ui(frame))
        self.assertFalse(self.detector.idle_match(frame))

    def test_red_build_badge_is_not_a_discard_button(self) -> None:
        frame = self.frame.copy()
        # A wide red Build-menu badge on the left, with white text.
        cv2.rectangle(frame, (80, 175), (240, 200), (0, 0, 200), -1)
        cv2.putText(
            frame,
            "7/7 Traps",
            (90, 194),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
        )
        self.assertIsNone(self.detector.discard(frame))

    def test_false_discard_fallback_is_clicked_once(self) -> None:
        self.config.save_debug_frames = False
        self.runtime.sleep = lambda seconds: None
        fake = Match("discard", 500, 500, 235, 29, 0.60)
        self.detector.discard = lambda frame: fake  # type: ignore[method-assign]
        navigator = Navigator(self.runtime, self.detector)
        self.assertFalse(navigator.handle_discard(self.frame))
        self.assertEqual(len(self.backend.clicks), 1)
        self.assertFalse(navigator.handle_discard(self.frame))
        self.assertEqual(len(self.backend.clicks), 1)

    def test_settings_button_and_classic_forfeit_row(self) -> None:
        frame = self.frame.copy()
        _paste(frame, "settingsbutton.png", 230, 20)
        _paste(frame, "classicforfeitsetting.png", 30, 500)
        self.assertIsNotNone(self.detector.settings_button(frame))
        row = self.detector.classic_forfeit_row(frame)
        self.assertIsNotNone(row)
        self.assertTrue(row.on)

    def test_classic_forfeit_row_can_read_off(self) -> None:
        frame = self.frame.copy()
        _paste(frame, "classicforfeitsetting.png", 30, 500)
        row_image = _load("classicforfeitsetting.png")
        h, w = row_image.shape[:2]
        frame[500 : 500 + int(h * 0.55), 30 + int(w * 0.68) : 30 + w] = (
            45,
            45,
            45,
        )
        row = self.detector.classic_forfeit_row(frame)
        self.assertIsNotNone(row)
        self.assertFalse(row.on)

    def test_battle_button_means_idle_match(self) -> None:
        frame = self.frame.copy()
        _paste(frame, "battle1.png", 600, 560)
        self.assertTrue(self.detector.idle_match(frame))
        self.assertFalse(self.detector.battle_active(frame))


class EngineRefactorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config()
        self.config.auto_battle = False
        self.config.auto_spawners = False
        self.config.battle_cooldown = 0.0
        self.config.action_delay = 0.0
        self.config.idle_poll = 0.0
        self.config.classic_forfeit_checked = True
        self.stop = threading.Event()
        callbacks = EngineCallbacks(
            log=lambda *a: None,
            status=lambda *a: None,
            stats=lambda *a: None,
            preview=lambda *a: None,
        )
        from nexusmacro.engine import Engine

        self.frame = np.full((720, 1280, 3), (18, 26, 36), np.uint8)
        _paste(self.frame, "battle1.png", 600, 560)
        self.backend = _Backend(self.frame)
        self.engine = Engine(
            self.backend,
            self.config,
            Matcher(ROOT / "templates", ROOT / "templates", self.config),
            callbacks,
            self.stop,
        )
        self.engine.runtime.sleep = lambda seconds: None

    def test_pre_battle_failure_retries_with_backoff(self) -> None:
        self.config.auto_fuse = True
        calls: list[set[str]] = []
        self.engine.build.run_many = (  # type: ignore[method-assign]
            lambda kinds, frame, allow_forfeit: (
                calls.append(set(kinds)),
                set(),
            )[1]
        )
        self.engine.tick(self.frame)
        self.assertEqual(calls, [{"fuse"}])
        self.engine.tick(self.frame)
        self.assertEqual(calls, [{"fuse"}])
        self.engine._pre_battle_retry_at = 0.0
        self.engine.tick(self.frame)
        self.assertEqual(calls, [{"fuse"}, {"fuse"}])

    def test_pre_battle_success_is_not_repeated(self) -> None:
        self.config.auto_fuse = True
        calls: list[set[str]] = []
        self.engine.build.run_many = (  # type: ignore[method-assign]
            lambda kinds, frame, allow_forfeit: (
                calls.append(set(kinds)),
                set(kinds),
            )[1]
        )
        self.engine.tick(self.frame)
        self.engine.tick(self.frame)
        self.assertEqual(calls, [{"fuse"}])

    def test_leftover_build_menu_is_closed(self) -> None:
        frame = self.frame.copy()
        _paste(frame, "stopbutton.png", 700, 600)
        self.backend.frame = frame
        self.assertTrue(self.engine.tick(frame))
        self.assertTrue(self.backend.clicks)
        self.assertGreaterEqual(self.backend.clicks[0][0], 700)

    def test_classic_forfeit_is_checked_once(self) -> None:
        self.config.classic_forfeit_checked = False
        self.config.save_debug_frames = False
        frame = self.frame.copy()
        _paste(frame, "settingsbutton.png", 230, 20)
        _paste(frame, "classicforfeitsetting.png", 30, 500)
        self.backend.frame = frame
        events: list[tuple[str, bool]] = []
        self.engine.runtime.callbacks.config_changed = (
            lambda key, value: events.append((key, value))
        )
        self.assertTrue(self.engine.tick(frame))
        self.assertTrue(self.engine.config.classic_forfeit_checked)
        self.assertTrue(self.engine.config.classic_forfeit_on)
        self.assertIn(("classic_forfeit_checked", True), events)
        clicks = len(self.backend.clicks)
        self.engine.tick(frame)
        self.assertEqual(len(self.backend.clicks), clicks)

    def test_reconnect_button_requests_restart_without_clicking(self) -> None:
        self.config.save_debug_frames = False
        frame = self.frame.copy()
        _paste(frame, "reconnectbutton.png", 400, 300)
        restarts: list[str] = []
        self.engine.runtime.callbacks.restart_game = (
            lambda reason: restarts.append(reason)
        )
        self.assertTrue(self.engine.tick(frame))
        self.assertEqual(self.backend.clicks, [])
        self.assertEqual(len(restarts), 1)
        self.assertTrue(self.engine._restart_sent)
        self.engine.tick(frame)
        self.assertEqual(len(restarts), 1)
        self.assertEqual(self.backend.clicks, [])

    def test_manual_optional_runs_on_the_main_engine(self) -> None:
        self.config.auto_fuse = True
        calls: list[tuple[str, bool]] = []
        done: list[bool] = []
        self.engine.runtime.callbacks.manual_done = lambda: done.append(True)
        self.engine.build.run = (  # type: ignore[method-assign]
            lambda kind, frame, allow_forfeit: (
                calls.append((kind, allow_forfeit)),
                True,
            )[1]
        )
        self.engine.request_optional_action("fuse")
        self.assertTrue(self.engine.tick(self.frame))
        self.assertEqual(calls, [("fuse", True)])
        self.assertIn("fuse", self.engine._pre_battle_done)
        self.assertEqual(done, [True])

    def test_spawner_failure_sets_a_cooldown(self) -> None:
        self.config.shop_open_timeout = 0.15
        self.config.cycle_delay = 0.0
        self.config.spawner_threshold = 0.80
        frame = np.full((720, 1280, 3), (18, 26, 36), np.uint8)
        _paste(frame, "spawners2.png", 1200, 500)
        self.backend.frame = frame
        self.assertFalse(self.engine.spawner_action.run(frame, "test"))
        clicks_after_first = len(self.backend.clicks)
        self.assertGreaterEqual(clicks_after_first, 1)
        self.assertFalse(self.engine.spawner_action.run(frame, "test"))
        # Only the first attempt clicked the spawner; the second was cooling
        # down and must not click it again.
        self.assertEqual(len(self.backend.clicks), clicks_after_first)
        # An explicit manual request bypasses the automatic cooldown.
        self.engine.spawner_action.run(frame, "manual", force=True)
        self.assertGreater(len(self.backend.clicks), clicks_after_first)

    def test_update_config_applies_to_runtime_and_scheduler(self) -> None:
        new = self.engine.config.copy()
        new.spawner_interval_minutes = 9
        old_next = self.engine.scheduler.next_interval_at
        self.engine.update_config(new, "spawner_interval_minutes")
        self.assertEqual(self.engine.config.spawner_interval_minutes, 9)
        self.assertIs(self.engine.matcher.config, self.engine.config)
        self.assertGreater(self.engine.scheduler.next_interval_at, old_next)


class BuildMenuTest(unittest.TestCase):
    def test_fuse_and_place_share_one_build_menu(self) -> None:
        build_frame = np.full((720, 1280, 3), (18, 26, 36), np.uint8)
        _paste(build_frame, "build1.png", 600, 560)
        menu_frame = np.full((720, 1280, 3), (18, 26, 36), np.uint8)
        _paste(menu_frame, "fuseallbutton.png", 250, 280)
        _paste(menu_frame, "placebestbutton.png", 300, 175)
        _paste(menu_frame, "stopbutton.png", 700, 600)

        class Backend:
            def __init__(self) -> None:
                self.mode = "closed"
                self.clicks: list[tuple[int, int]] = []

            def capture(self):
                return (
                    menu_frame.copy()
                    if self.mode == "menu"
                    else build_frame.copy()
                )

            def click(self, x, y, button=1, park=None):
                self.clicks.append((x, y))
                if 600 <= x <= 700 and 560 <= y <= 660:
                    self.mode = "menu"

            def key(self, name):
                pass

            def scroll(self, clicks, x=None, y=None):
                pass

        backend = Backend()
        config = Config()
        config.fuse_wait_seconds = 0.0
        config.action_delay = 0.0
        config.save_debug_frames = False
        callbacks = EngineCallbacks(
            log=lambda *a: None,
            status=lambda *a: None,
            stats=lambda *a: None,
            preview=lambda *a: None,
        )
        runtime = Runtime(
            backend,
            config,
            Matcher(ROOT / "templates", ROOT / "templates", config),
            callbacks,
            threading.Event(),
        )
        runtime.sleep = lambda seconds: None
        detector = ScreenDetector(runtime)
        navigator = Navigator(runtime, detector)
        from nexusmacro.automation.build import BuildMenu

        menu = BuildMenu(runtime, detector, navigator)
        completed = menu.run_many({"fuse", "place"}, build_frame, False)
        self.assertEqual(completed, {"fuse", "place"})
        build_clicks = [
            (x, y) for x, y in backend.clicks if 600 <= x <= 700 and 560 <= y <= 660
        ]
        fuse_clicks = [
            (x, y) for x, y in backend.clicks if 250 <= x <= 370 and 280 <= y <= 320
        ]
        place_clicks = [
            (x, y) for x, y in backend.clicks if 300 <= x <= 360 and 175 <= y <= 200
        ]
        stop_clicks = [
            (x, y) for x, y in backend.clicks if 700 <= x <= 790 and 600 <= y <= 690
        ]
        self.assertEqual(len(build_clicks), 1)
        self.assertEqual(len(fuse_clicks), 2)
        self.assertEqual(len(place_clicks), 2)
        self.assertEqual(len(stop_clicks), 1)


class ShopSessionTest(unittest.TestCase):
    def test_scrolls_after_the_close_button_flickers(self) -> None:
        class FlickerVision:
            def __init__(self) -> None:
                self.close_calls = 0
                self.buy_calls = 0

            def buy_buttons(self, frame):
                self.buy_calls += 1
                if self.buy_calls == 1:
                    return [Match("buy", 400, 200, 100, 30, 0.95)]
                return []

            def close_button(self, frame):
                self.close_calls += 1
                if self.close_calls in (2, 3):
                    return None
                return Match("close", 900, 90, 30, 30, 0.95)

            def scrollbar(self, frame):
                return None

        config = Config()
        config.buy_clicks = 1
        config.action_delay = 0.0
        config.max_scrolls = 2
        config.scroll_method = "wheel"
        config.scroll_settle_delay = 0.0
        config.close_shop = False
        backend = _Backend(np.full((720, 1280, 3), 20, np.uint8))
        callbacks = EngineCallbacks(
            log=lambda *a: None,
            status=lambda *a: None,
            stats=lambda *a: None,
            preview=lambda *a: None,
        )
        runtime = Runtime(
            backend,
            config,
            Matcher(ROOT / "templates", ROOT / "templates", config),
            callbacks,
            threading.Event(),
        )
        runtime.sleep = lambda seconds: None
        from nexusmacro.automation.shop import ShopSession

        session = ShopSession(runtime, vision=FlickerVision())  # type: ignore[arg-type]
        clicks, scrolls = session.buy_and_scroll()
        self.assertEqual(clicks, 1)
        self.assertGreaterEqual(scrolls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
