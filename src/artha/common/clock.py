"""Auditable system clock — injectable, freezable for tests."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Real system clock using UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock(SystemClock):
    """Test clock frozen at a specific time, advanceable manually."""

    def __init__(self, frozen_at: datetime | None = None) -> None:
        self._frozen_at = frozen_at or datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._frozen_at

    def advance_to(self, dt: datetime) -> None:
        self._frozen_at = dt


_clock: SystemClock = SystemClock()


def get_clock() -> SystemClock:
    return _clock


def set_clock(clock: SystemClock) -> None:
    global _clock
    _clock = clock
