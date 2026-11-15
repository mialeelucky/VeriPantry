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


class OffsetClock:
    """Starts at a given time and runs in real time from there.

    Used with recorded upstream data (B6): the demo begins at the moment the
    fixture was recorded, and deadlines and countdowns still move.
    """

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("OffsetClock needs a timezone-aware datetime")
        self._start = start
        self._boot = datetime.now(HELSINKI)

    def now(self) -> datetime:
        return self._start + (datetime.now(HELSINKI) - self._boot)


def parse_api_time(value: str | None) -> datetime | None:
    """Parse upstream timestamps such as ``2026-11-15T17:00:00+0200``."""
    if not value:
        return None
    return datetime.fromisoformat(value)
