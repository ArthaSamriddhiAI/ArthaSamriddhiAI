"""Analyst manual-flag service — cluster 8 chunk 8.2 §2.1.

Updated in cluster 8 to use :class:`StockLevelManualFlag`
(``v2_stock_level_manual_flags``), which is the generalised
per-stock flag that covers both E1 and E2.StockInSector
invalidation.  The public API is unchanged from cluster 7 so
:mod:`.runtime` and existing callers need no updates; column
renames are absorbed internally:

  cluster-7 E1ManualFlag   →  cluster-8 StockLevelManualFlag
  ─────────────────────────   ─────────────────────────────────
  flagged_by                   advisor_id
  flagged_at                   active_from
  (no firm_id)                 firm_id (default "default_firm")
  (no invalidates_*)           invalidates_e1=True, invalidates_e2sis=True
  schema_version=1             schema_version=2

The ``ManualFlagSnapshot`` dataclass retains the cluster-7 field
names (``flagged_by``, ``flagged_at``) for backward compatibility
with any existing callers that read those fields.

Invariant: at most one *active* flag per ticker at a time.
Application-layer enforcement keeps the schema portable across
SQLite + Postgres (no partial unique index syntax).  When
:func:`create_manual_flag` is called for a ticker that already
has an active flag, the prior flag is auto-cleared first.

Operations:

- :func:`create_manual_flag` — flip a flag for ``ticker``.
  Atomically clears any pre-existing active flag, drops E1 cache
  rows for the superseded ``manual_flag_id``, and emits the
  ``cache_invalidated_manual`` T1 event.
- :func:`clear_manual_flag` — clear the active flag for ``ticker``.
- :func:`get_active_manual_flag_for_ticker` — read-only lookup the
  shim input-builders use to populate the cache key component.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.agents.cache import repository_cluster8 as c8repo
from artha.api_v2.agents.cache.models_cluster8 import StockLevelManualFlag
from artha.api_v2.agents.cache.repository import invalidate_for_manual_flag


@dataclass(frozen=True)
class ManualFlagSnapshot:
    """Immutable view of a :class:`StockLevelManualFlag` row.

    ``flagged_by`` and ``flagged_at`` are kept as cluster-7 names
    mapped from ``advisor_id`` and ``active_from`` respectively.
    """

    manual_flag_id: str
    ticker: str
    flagged_by: str       # mapped from advisor_id
    flagged_at: datetime  # mapped from active_from
    cleared_at: datetime | None
    cleared_by: str | None
    reason: str
    is_active: bool


def _to_snapshot(row: StockLevelManualFlag) -> ManualFlagSnapshot:
    return ManualFlagSnapshot(
        manual_flag_id=row.manual_flag_id,
        ticker=row.ticker,
        flagged_by=row.advisor_id,
        flagged_at=row.active_from,
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
    stmt = select(StockLevelManualFlag).where(
        StockLevelManualFlag.manual_flag_id == manual_flag_id,
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
    firm_id: str = "default_firm",
    now: datetime | None = None,
) -> ManualFlagMutation:
    """Set a fresh active flag for ``ticker``.

    Auto-clears any pre-existing active flag (one-active-per-ticker
    invariant) and drops E1 cache rows that referenced the superseded
    ``manual_flag_id``.

    Args:
        ticker: NSE ticker symbol.
        flagged_by: Advisor / system ID raising the flag (stored as
            ``advisor_id`` in the new schema).
        reason: Free-text reason for the flag.
        firm_id: Firm context.  Defaults to ``"default_firm"`` for
            backward compatibility when not supplied.
        now: Override the current UTC time (used in tests).
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
    new_row = StockLevelManualFlag(
        manual_flag_id=new_id,
        firm_id=firm_id,
        ticker=ticker,
        advisor_id=flagged_by,
        reason=reason,
        active_from=moment,
        cleared_at=None,
        cleared_by=None,
        created_at=moment,
        invalidates_e1=True,
        invalidates_e2sis=True,
        is_active=True,
        schema_version=2,
    )
    db.add(new_row)
    await db.flush()

    invalidated = await invalidate_for_manual_flag(
        db, ticker=ticker, superseded_flag_id=superseded_id,
    )
    # Also invalidate E2.StockInSector cache for this ticker (chunk 8.2 §2.1).
    await c8repo.invalidate_e2sis_for_stock_flag(
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
    await c8repo.invalidate_e2sis_for_stock_flag(
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
) -> StockLevelManualFlag | None:
    stmt = (
        select(StockLevelManualFlag)
        .where(
            StockLevelManualFlag.ticker == ticker,
            StockLevelManualFlag.is_active.is_(True),
        )
        .order_by(StockLevelManualFlag.active_from.desc())
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
