"""Analyst manual-flag service (cluster 7 chunk 7.2 §3.2.b).

Per-ticker flags rotate the E1 cache key so the next E1 call for that
ticker bypasses the stale verdict and produces a fresh one.

Invariant: at most one *active* flag per ticker at a time. Application-
layer enforcement keeps the schema portable across SQLite + Postgres
(no partial unique index syntax). When :func:`create_manual_flag` is
called for a ticker that already has an active flag, the prior flag
is auto-cleared first.

Operations (chunk 7.2 §3.2.b):

- :func:`create_manual_flag` — flip a flag for ``ticker``. Atomically
  clears any pre-existing active flag, drops cache rows for the
  superseded ``manual_flag_id``, and emits the
  ``cache_invalidated_manual`` T1 event.
- :func:`clear_manual_flag` — clear the active flag for ``ticker``.
  Drops cache rows referencing it and emits the same T1 event.
- :func:`get_active_manual_flag_for_ticker` — read-only lookup the
  E1 shim's input-builder uses to populate the cache key component.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.agents.cache.models import E1ManualFlag
from artha.api_v2.agents.cache.repository import invalidate_for_manual_flag


@dataclass(frozen=True)
class ManualFlagSnapshot:
    """Immutable view of an :class:`E1ManualFlag` row."""

    manual_flag_id: str
    ticker: str
    flagged_by: str
    flagged_at: datetime
    cleared_at: datetime | None
    cleared_by: str | None
    reason: str
    is_active: bool


def _to_snapshot(row: E1ManualFlag) -> ManualFlagSnapshot:
    return ManualFlagSnapshot(
        manual_flag_id=row.manual_flag_id,
        ticker=row.ticker,
        flagged_by=row.flagged_by,
        flagged_at=row.flagged_at,
        cleared_at=row.cleared_at,
        cleared_by=row.cleared_by,
        reason=row.reason,
        is_active=row.is_active,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_active_manual_flag_for_ticker(
    db: AsyncSession,
    *,
    ticker: str,
) -> ManualFlagSnapshot | None:
    """Return the currently-active flag for ``ticker`` if any."""
    row = await _load_active_flag(db, ticker=ticker)
    return _to_snapshot(row) if row is not None else None


async def get_manual_flag(
    db: AsyncSession,
    *,
    manual_flag_id: str,
) -> ManualFlagSnapshot | None:
    stmt = select(E1ManualFlag).where(
        E1ManualFlag.manual_flag_id == manual_flag_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    return _to_snapshot(row) if row is not None else None


# ---------------------------------------------------------------------------
# Mutate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualFlagMutation:
    """Outcome of a flag create/clear that the caller emits as a T1 event."""

    ticker: str
    new_flag: ManualFlagSnapshot | None
    superseded_flag_id: str | None
    cache_rows_invalidated: int


async def create_manual_flag(
    db: AsyncSession,
    *,
    ticker: str,
    flagged_by: str,
    reason: str,
    now: datetime | None = None,
) -> ManualFlagMutation:
    """Set a fresh active flag for ``ticker``.

    Auto-clears any pre-existing active flag (one-active-per-ticker
    invariant) and drops cache rows that referenced the superseded
    ``manual_flag_id``.
    """
    if not ticker:
        raise ValueError("ticker is required")
    if not reason:
        raise ValueError("reason is required")

    moment = now or datetime.now(timezone.utc)

    superseded = await _load_active_flag(db, ticker=ticker)
    superseded_id = superseded.manual_flag_id if superseded is not None else None
    if superseded is not None:
        superseded.is_active = False
        superseded.cleared_at = moment
        superseded.cleared_by = flagged_by

    new_id = str(ULID())
    new_row = E1ManualFlag(
        manual_flag_id=new_id,
        ticker=ticker,
        flagged_by=flagged_by,
        flagged_at=moment,
        cleared_at=None,
        cleared_by=None,
        reason=reason[:200],
        is_active=True,
        schema_version=1,
    )
    db.add(new_row)
    await db.flush()

    invalidated = await invalidate_for_manual_flag(
        db, ticker=ticker, superseded_flag_id=superseded_id,
    )

    return ManualFlagMutation(
        ticker=ticker,
        new_flag=_to_snapshot(new_row),
        superseded_flag_id=superseded_id,
        cache_rows_invalidated=invalidated,
    )


async def clear_manual_flag(
    db: AsyncSession,
    *,
    ticker: str,
    cleared_by: str,
    now: datetime | None = None,
) -> ManualFlagMutation:
    """Clear the active flag for ``ticker`` (no-op if none was active)."""
    moment = now or datetime.now(timezone.utc)

    row = await _load_active_flag(db, ticker=ticker)
    if row is None:
        return ManualFlagMutation(
            ticker=ticker,
            new_flag=None,
            superseded_flag_id=None,
            cache_rows_invalidated=0,
        )

    superseded_id = row.manual_flag_id
    row.is_active = False
    row.cleared_at = moment
    row.cleared_by = cleared_by
    await db.flush()

    invalidated = await invalidate_for_manual_flag(
        db, ticker=ticker, superseded_flag_id=superseded_id,
    )

    return ManualFlagMutation(
        ticker=ticker,
        new_flag=None,
        superseded_flag_id=superseded_id,
        cache_rows_invalidated=invalidated,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_active_flag(
    db: AsyncSession,
    *,
    ticker: str,
) -> E1ManualFlag | None:
    stmt = (
        select(E1ManualFlag)
        .where(
            E1ManualFlag.ticker == ticker,
            E1ManualFlag.is_active.is_(True),
        )
        .order_by(E1ManualFlag.flagged_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


__all__ = [
    "ManualFlagMutation",
    "ManualFlagSnapshot",
    "clear_manual_flag",
    "create_manual_flag",
    "get_active_manual_flag_for_ticker",
    "get_manual_flag",
]
