"""Injectable clock so every time-dependent decision is deterministic in tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

HELSINKI = ZoneInfo("Europe/Helsinki")


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(HELSINKI)


class FixedClock:
    """A clock that only moves when told to."""

    def __init__(self, at: datetime):
        if at.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = at

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now = self._now + timedelta(**kwargs)

    def set(self, at: datetime) -> None:
        self._now = at


def parse_api_time(value: str | None) -> datetime | None:
    """Parse upstream timestamps such as ``2026-11-15T17:00:00+0200``."""
    if not value:
        return None
    return datetime.fromisoformat(value)
