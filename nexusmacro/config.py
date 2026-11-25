"""Persistent Nexus Macro configuration."""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .paths import config_file

# Set by Config.load() when the file could not be read completely. The UI
# shows this instead of silently falling back to defaults (which used to look
# like "my settings were erased").
LAST_LOAD_ERROR = ""


@dataclass
class Config:
    # Features
    auto_battle: bool = True
    auto_spawners: bool = True
    auto_fuse: bool = False
    fuse_wait_seconds: float = 5.0
    auto_best_place: bool = False
    auto_reconnect: bool = True
    classic_forfeit_checked: bool = False
    classic_forfeit_on: bool = False

    # Vision
    threshold: float = 0.88
    scale: float = 1.0
    ignore_spawner_timer: int = 31
    ignore_buy_price: float = 0.45

    # Buying / scrolling
    buy_clicks: int = 5
    buy_click_delay: float = 0.05
    max_buy_buttons: int = 20
    max_cycle_buy_clicks: int = 250
    scroll_method: str = "wheel"  # drag | wheel
    scroll_drag_px: int = 220
    scroll_drag_ms: int = 450
    scroll_probe_steps: int = 4
    scroll_settle_delay: float = 1.2
    max_scrolls: int = 15
    close_shop: bool = True
    spawner_preference: str = "auto"  # auto | 1 | 2
    spawner_timing: str = "clock"  # clock | interval | continuous
    spawner_buy_on_start: bool = True
    spawner_window_seconds: int = 55
    spawner_interval_minutes: int = 5
    spawner_poll_seconds: int = 30
    spawner_threshold: float = 0.80
    shop_threshold: float = 0.75

    # Pacing
    action_delay: float = 0.07
    battle_poll: float = 1.0
    battle_cooldown: float = 2.0
    idle_poll: float = 0.6
    cycle_delay: float = 1.0
    shop_open_timeout: float = 8.0

    # Game / gamescope
    auto_join: bool = True
    game_place_id: str = "113140456364856"
    window_width: int = 1280
    window_height: int = 720
    gamescope_backend: str = "sdl"
    gamescope_fps: int = 60
    gamescope_grab_cursor: bool = False
    minimize_on_start: bool = True
    gamescope_path: str = ""
    display: str = ""
    window_class: str = "org.vinegarhq.Sober"

    # Misc
    save_debug_frames: bool = True
    config_version: int = 2

    # -- persistencia -------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        global LAST_LOAD_ERROR
        LAST_LOAD_ERROR = ""
        target = path or config_file()
        if not target.exists():
            return cls()
        try:
            text = target.read_text(encoding="utf-8")
        except Exception as exc:
            LAST_LOAD_ERROR = f"Cannot read {target}: {exc}"
            return cls()
        try:
            raw = json.loads(text)
        except Exception as exc:
            LAST_LOAD_ERROR = f"Invalid JSON in {target}: {exc}"
            _backup_broken(target)
            return cls()
        if not isinstance(raw, dict):
            LAST_LOAD_ERROR = f"{target} does not contain a JSON object."
            _backup_broken(target)
            return cls()

        valid = {f.name: f.type for f in fields(cls)}
        data: dict[str, Any] = {}
        problems: list[str] = []
        for key, value in raw.items():
            if key not in valid:
                continue
            try:
                data[key] = _coerce(value, valid[key])
            except Exception:
                problems.append(f"{key}={value!r}")
        if problems:
            LAST_LOAD_ERROR = (
                "Ignored invalid setting(s): " + ", ".join(problems[:6])
            )
        try:
            cfg = cls(**data)
        except Exception as exc:
            LAST_LOAD_ERROR = f"Could not build config: {exc}"
            return cls()

        try:
            version = int(data.get("config_version", 1) or 1)
        except Exception:
            version = 1
        if version < 2:
            # Version 2 introduced the visible window mode and auto-minimize.
            cfg.gamescope_backend = "sdl"
            cfg.minimize_on_start = True
            cfg.config_version = 2
        cfg.validate()
        if version < 2:
            try:
                cfg.save(target)
            except Exception:
                pass
        return cfg

    def game_uri(self) -> str:
        """Deep link used by Sober to join the configured experience."""
        if not self.auto_join or not self.game_place_id:
            return ""
        return f"roblox://experience?placeId={self.game_place_id}"

    def save(self, path: Path | None = None) -> None:
        target = path or config_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if target.exists():
                shutil.copyfile(target, target.with_suffix(".json.bak"))
        except Exception:
            pass
        tmp = target.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n"
            )
            handle.flush()
            try:
                import os

                os.fsync(handle.fileno())
            except Exception:
                pass
        tmp.replace(target)

    def validate(self) -> None:
        self.auto_battle = bool(self.auto_battle)
        self.auto_spawners = bool(self.auto_spawners)
        self.auto_fuse = bool(self.auto_fuse)
        self.fuse_wait_seconds = _clamp(self.fuse_wait_seconds, 0.0, 15.0, 5.0)
        self.auto_best_place = bool(self.auto_best_place)
        self.auto_reconnect = bool(self.auto_reconnect)
        self.auto_join = bool(self.auto_join)
        self.classic_forfeit_checked = bool(self.classic_forfeit_checked)
        self.classic_forfeit_on = bool(self.classic_forfeit_on)
        self.gamescope_grab_cursor = bool(self.gamescope_grab_cursor)
        digits = re.search(r"(\d{6,25})", str(self.game_place_id or ""))
        self.game_place_id = digits.group(1) if digits else ""
        self.threshold = _clamp(self.threshold, 0.50, 0.99, 0.88)
        self.scale = _clamp(self.scale, 0.50, 2.00, 1.0)
        self.ignore_spawner_timer = int(_clamp(self.ignore_spawner_timer, 0, 80, 31))
        self.ignore_buy_price = _clamp(self.ignore_buy_price, 0.0, 0.80, 0.45)
        self.buy_clicks = int(_clamp(self.buy_clicks, 1, 20, 5))
        self.buy_click_delay = _clamp(self.buy_click_delay, 0.0, 2.0, 0.05)
        self.max_buy_buttons = int(_clamp(self.max_buy_buttons, 1, 30, 20))
        self.max_cycle_buy_clicks = int(_clamp(self.max_cycle_buy_clicks, 10, 1000, 250))
        self.scroll_drag_px = int(_clamp(self.scroll_drag_px, 20, 800, 220))
        self.scroll_drag_ms = int(_clamp(self.scroll_drag_ms, 100, 5000, 450))
        self.scroll_probe_steps = int(_clamp(self.scroll_probe_steps, 2, 30, 4))
        self.scroll_settle_delay = _clamp(self.scroll_settle_delay, 0.0, 5.0, 1.2)
        self.max_scrolls = int(_clamp(self.max_scrolls, 1, 50, 15))
        self.spawner_window_seconds = int(
            _clamp(self.spawner_window_seconds, 5, 60, 55)
        )
        self.spawner_interval_minutes = int(
            _clamp(self.spawner_interval_minutes, 1, 60, 5)
        )
        self.spawner_poll_seconds = int(
            _clamp(self.spawner_poll_seconds, 5, 300, 30)
        )
        self.spawner_threshold = _clamp(self.spawner_threshold, 0.50, 0.99, 0.80)
        self.shop_threshold = _clamp(self.shop_threshold, 0.50, 0.99, 0.75)
        if self.spawner_timing not in ("clock", "interval", "continuous"):
            self.spawner_timing = "clock"
        self.action_delay = _clamp(self.action_delay, 0.0, 5.0, 0.07)
        self.battle_poll = _clamp(self.battle_poll, 0.2, 15.0, 1.0)
        self.battle_cooldown = _clamp(self.battle_cooldown, 0.5, 30.0, 2.0)
        self.idle_poll = _clamp(self.idle_poll, 0.2, 15.0, 0.6)
        self.cycle_delay = _clamp(self.cycle_delay, 0.0, 60.0, 1.0)
        self.shop_open_timeout = _clamp(self.shop_open_timeout, 0.5, 20.0, 8.0)
        self.window_width = int(_clamp(self.window_width, 320, 3840, 1280))
        self.window_height = int(_clamp(self.window_height, 240, 2160, 720))
        self.gamescope_fps = int(_clamp(self.gamescope_fps, 15, 240, 60))
        if self.scroll_method not in ("drag", "wheel"):
            self.scroll_method = "wheel"
        if self.spawner_preference not in ("auto", "1", "2"):
            self.spawner_preference = "auto"
        if self.gamescope_backend not in ("headless", "wayland", "sdl"):
            self.gamescope_backend = "sdl"

    def copy(self) -> "Config":
        return Config(**asdict(self))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off", ""):
            return False
        return bool(text)
    return bool(value)


def _coerce(value: Any, kind: Any) -> Any:
    """Convert one JSON value to the dataclass field type."""
    name = str(kind)
    if name in ("bool", "<class 'bool'>"):
        return _as_bool(value)
    if name in ("int", "<class 'int'>"):
        return int(float(value))
    if name in ("float", "<class 'float'>"):
        return float(value)
    if name in ("str", "<class 'str'>"):
        return "" if value is None else str(value)
    return value


def _backup_broken(target: Path) -> None:
    """Keep a copy of an unreadable config instead of overwriting it."""
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copyfile(target, target.with_name(f"config.invalid-{stamp}.json"))
    except Exception:
        pass
