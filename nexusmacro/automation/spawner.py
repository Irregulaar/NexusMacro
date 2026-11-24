"""Spawner discovery, scheduling and the spawner → shop action."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import cv2
import numpy as np

from ..schedule import is_spawner_window
from ..vision import Match
from .context import Runtime
from .navigation import Navigator
from .shop import ShopSession


@dataclass(frozen=True)
class SpawnerDecision:
    reason: str
    window_key: Optional[str] = None


class SpawnerFinder:
    """Find the spawner button at the scale the HUD is currently using."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.last_candidates: list[
            tuple[float, str, float, Match]
        ] = []

    def find(
        self,
        frame: np.ndarray,
        threshold: Optional[float] = None,
        scan_scales: bool = True,
    ) -> tuple[Optional[str], Optional[Match], float]:
        config = self.runtime.config
        threshold = (
            config.spawner_threshold if threshold is None else threshold
        )
        probe = min(threshold, 0.45)
        base_scale = float(config.scale)

        preference = config.spawner_preference
        if preference == "1":
            keys = ("spawner1", "spawner3")
        elif preference == "2":
            keys = ("spawner2",)
        else:
            # Compact first: during a wave it is usually the only one visible.
            keys = ("spawner2", "spawner1", "spawner3")

        def base_pass() -> list[tuple[float, str, float, Match]]:
            found = []
            for key in keys:
                match = self.runtime.matcher.best(
                    frame, key, threshold=probe, scale=base_scale
                )
                if match is not None:
                    found.append((match.score, key, base_scale, match))
                    if match.score >= 0.95:
                        break
            return found

        small: Optional[np.ndarray] = None

        def expand_key(
            key: str, scales: list[float]
        ) -> tuple[Optional[Match], float]:
            nonlocal small
            if small is None:
                height, width = frame.shape[:2]
                small = cv2.resize(
                    frame,
                    (max(1, width // 2), max(1, height // 2)),
                    interpolation=cv2.INTER_AREA,
                )
            best_match: Optional[Match] = None
            best_scale = base_scale
            for scale in scales:
                match = self.runtime.matcher.best(
                    small,
                    key,
                    threshold=probe,
                    scale=max(0.30, scale / 2.0),
                )
                if match is not None:
                    scaled = Match(
                        key,
                        match.x * 2,
                        match.y * 2,
                        match.w * 2,
                        match.h * 2,
                        match.score,
                    )
                    if best_match is None or scaled.score > best_match.score:
                        best_match = scaled
                        best_scale = scale
                if best_match is not None and best_match.score >= 0.95:
                    break
            return best_match, best_scale

        candidates = base_pass()
        best_score = max((item[0] for item in candidates), default=0.0)

        # Safety net: if the lower HUD has nothing convincing, search the
        # whole frame once before failing. Some spawner layouts place the
        # button above the usual bottom band.
        if not candidates or best_score < min(0.60, threshold):
            height, width = frame.shape[:2]
            full_region = (0, 0, width, height)
            for key in keys:
                match = self.runtime.matcher.best(
                    frame,
                    key,
                    threshold=probe,
                    scale=base_scale,
                    region=full_region,
                )
                if match is not None:
                    candidates = [item for item in candidates if item[1] != key]
                    candidates.append((match.score, key, base_scale, match))
            best_score = max((item[0] for item in candidates), default=0.0)

        if scan_scales and best_score < threshold:
            factors = (
                0.95,
                1.05,
                0.90,
                1.10,
                0.85,
                1.15,
                0.80,
                1.20,
                0.75,
                0.70,
                0.65,
                1.30,
            )
            scales = sorted(
                {round(base_scale * factor, 3) for factor in factors}
                - {round(base_scale, 3)}
            )
            for key in keys:
                known = [item[0] for item in candidates if item[1] == key]
                if known and max(known) >= threshold:
                    continue
                match, scale = expand_key(key, scales)
                if match is not None:
                    candidates = [
                        item for item in candidates if item[1] != key
                    ]
                    candidates.append((match.score, key, scale, match))
                    if match.score >= threshold:
                        break

        candidates.sort(key=lambda item: item[0], reverse=True)
        self.last_candidates = candidates
        if not candidates:
            return None, None, base_scale

        best_score, best_key, best_scale, best_match = candidates[0]
        # If the compact match sits inside the big one and scores are close,
        # prefer the big button: it is the more stable target.
        if preference == "auto" and best_key == "spawner2":
            for score, key, scale, match in candidates[1:]:
                if key != "spawner1" or score < best_score - 0.05:
                    continue
                inside = (
                    match.x <= best_match.cx <= match.x + match.w
                    and match.y <= best_match.cy <= match.y + match.h
                )
                if inside:
                    return key, match, scale
        return best_key, best_match, best_scale


class SpawnerScheduler:
    """Decide when a spawner purchase is due. No screen access."""

    def __init__(self, runtime: Runtime, now: Optional[float] = None) -> None:
        self.runtime = runtime
        self.start_time = now if now is not None else time.monotonic()
        self.start_done = False
        self.last_window: Optional[str] = None
        self.last_attempt = self.start_time
        self.next_interval_at = (
            self.start_time
            + max(1, self.runtime.config.spawner_interval_minutes) * 60
        )
        self.retry_at = 0.0

    def due(self, now: Optional[float] = None) -> Optional[SpawnerDecision]:
        config = self.runtime.config
        if not config.auto_spawners:
            return None
        current = time.monotonic() if now is None else now
        timing = config.spawner_timing
        inside = False
        window_key: Optional[str] = None
        if timing == "clock":
            inside, window_key = is_spawner_window(
                datetime.now(), config.spawner_window_seconds
            )

        if (
            config.spawner_buy_on_start
            and not self.start_done
            and not inside
            and current - self.start_time > 2.0
        ):
            self.start_done = True
            return SpawnerDecision("start")

        if timing == "clock" and inside:
            self.start_done = True
            # One successful purchase per refresh window; retry failures
            # every 7 s while the window remains open.
            if window_key != self.last_window and current >= self.retry_at:
                self.retry_at = current + 7.0
                self.last_attempt = current
                return SpawnerDecision("refresh", window_key)

        if timing == "interval" and current >= self.next_interval_at:
            self.next_interval_at = (
                current + max(1, config.spawner_interval_minutes) * 60
            )
            self.last_attempt = current
            return SpawnerDecision("interval")

        if timing == "continuous" and (
            current - self.last_attempt >= config.spawner_poll_seconds
        ):
            self.last_attempt = current
            return SpawnerDecision("continuous")

        return None

    def finish(self, decision: SpawnerDecision, success: bool) -> None:
        if decision.reason == "refresh" and success:
            self.last_window = decision.window_key

    def on_manual_purchase(self, success: bool = True) -> None:
        config = self.runtime.config
        now = time.monotonic()
        if config.spawner_timing == "interval":
            self.next_interval_at = (
                now + max(1, config.spawner_interval_minutes) * 60
            )
        elif config.spawner_timing == "clock" and success:
            inside, window_key = is_spawner_window(
                datetime.now(), config.spawner_window_seconds
            )
            if inside and window_key:
                self.last_window = window_key
        self.last_attempt = now

    def on_config_changed(self, key: str) -> None:
        if key not in (
            "spawner_timing",
            "spawner_interval_minutes",
            "spawner_poll_seconds",
            "spawner_window_seconds",
        ):
            return
        config = self.runtime.config
        self.next_interval_at = (
            time.monotonic()
            + max(1, config.spawner_interval_minutes) * 60
        )
        self.last_attempt = time.monotonic()
        self.retry_at = 0.0

class SpawnerAction:
    """Click a spawner, verify its shop and buy. One attempt per call."""

    def __init__(
        self,
        runtime: Runtime,
        finder: SpawnerFinder,
        shop: ShopSession,
        navigator: Navigator,
    ) -> None:
        self.runtime = runtime
        self.finder = finder
        self.shop = shop
        self.navigator = navigator
        self._cooldown_until = 0.0

    def run(
        self, frame: np.ndarray, reason: str, force: bool = False
    ) -> bool:
        config = self.runtime.config
        now = time.monotonic()
        if not force and now < self._cooldown_until:
            self.runtime.log(
                "Spawner action cooling down after a failed attempt.",
                "info",
            )
            return False

        if self.navigator.handle_discard(frame):
            return False

        # A leftover shop is closed, never bought from. Buying is only valid
        # after this macro clicks a spawner.
        if self.shop.is_open(frame):
            self.runtime.log(
                "A shop was already open; closing it before the spawner click.",
                "info",
            )
            self.shop.close()
            frame = self.runtime.capture()
            if self.shop.is_open(frame):
                self.runtime.log(
                    "The open shop could not be closed; skipping this attempt.",
                    "warning",
                )
                self._cooldown_until = now + 10.0
                return False

        key, match, scale = self.finder.find(frame, scan_scales=True)
        candidates = self.finder.last_candidates
        if candidates:
            summary = ", ".join(
                f"{candidate_key} {score:.2f}@{candidate_scale:.2f}"
                for score, candidate_key, candidate_scale, _match in candidates[:3]
            )
            self.runtime.log(f"Spawner candidates: {summary}.", "info")
        if match is None:
            self.runtime.log(
                "No spawner button detected. Check the spawner templates, "
                "resolution and scale.",
                "warning",
            )
            self.runtime.save_debug(frame, "spawner_not_found", reason)
            self._cooldown_until = time.monotonic() + 10.0
            return False
        if match.score < config.spawner_threshold:
            self.runtime.log(
                "No spawner above threshold. Best candidate: "
                f"{key} scale {scale:.2f} score {match.score:.2f}.",
                "warning",
            )
            self.runtime.save_debug(
                frame,
                "spawner_not_found",
                f"{reason}: score {match.score:.2f} < "
                f"{config.spawner_threshold:.2f}",
            )
            self._cooldown_until = time.monotonic() + 10.0
            return False

        self.runtime.log(
            f"Spawner detected ({reason}): {key}, scale {scale:.2f}, "
            f"score {match.score:.2f}.",
            "success",
        )
        self.runtime.click_match(match, "Spawner shop opened")
        self.runtime.stats.spawner_opens += 1
        self.runtime.stats_changed()
        self.runtime.emit_preview(frame, [match])
        self.runtime.sleep(config.action_delay)
        if self.shop.wait_opened():
            self._cooldown_until = 0.0
            self.shop.run()
            return True

        # The click did not open a shop (disabled spawner, wrong target or a
        # battle overlay). Do not keep clicking the same place every retry.
        self._cooldown_until = time.monotonic() + 15.0
        post_click = self.runtime.capture()
        self.runtime.save_debug(
            post_click, "shop_not_detected", f"{reason}: after spawner click"
        )
        self.runtime.log(
            "Shop UI not detected after clicking the spawner button. "
            "Debug capture saved.",
            "warning",
        )
        self.runtime.sleep(config.cycle_delay)
        return False
