"""Spawner refresh schedule helpers."""

from __future__ import annotations

from datetime import datetime, timedelta


def is_spawner_window(
    now: datetime | None = None,
    window_seconds: int = 55,
) -> tuple[bool, str | None]:
    """Return (inside_refresh_window, window_key) at hh:mm:00 every 5 min."""
    current = now or datetime.now()
    if current.minute % 5 != 0:
        return False, None
    limit = max(5, min(60, int(window_seconds)))
    if current.second >= limit:
        return False, None
    return True, current.strftime("%Y%m%d%H%M")


def next_spawner_refresh(now: datetime | None = None) -> datetime:
    """Next hh:mm:00 boundary (the current boundary if we're before it)."""
    current = now or datetime.now()
    if current.minute % 5 == 0 and current.second == 0:
        return current.replace(microsecond=0)
    minutes = (5 - current.minute % 5) % 5
    target = current.replace(second=0, microsecond=0) + timedelta(
        minutes=minutes or 5
    )
    if target <= current:
        target += timedelta(minutes=5)
    return target


def spawner_countdown_text(
    now: datetime | None = None,
    window_seconds: int = 55,
) -> str:
    current = now or datetime.now()
    inside, _ = is_spawner_window(current, window_seconds)
    if inside:
        return "Spawner refresh window open"
    target = next_spawner_refresh(current)
    remaining = max(0, int((target - current).total_seconds()))
    minutes, seconds = divmod(remaining, 60)
    return f"Next spawner refresh in {minutes:02d}:{seconds:02d}"


def spawner_refresh_time_text(now: datetime | None = None) -> str:
    target = next_spawner_refresh(now)
    return target.strftime("%H:%M:%S")
