"""Fund-level manual-flag service — cluster 8 chunk 8.3 §6.1.

Per-fund flags invalidate the E7 Mutual Fund cache when an analyst
knows a fund-level override is needed (e.g., manager departure
confirmation, regulatory notice, undisclosed AUM cliff).

Invariant: at most one *active* flag per (firm_id, fund_id) pair at a
time, enforced at the application layer.  When
:func:`create_fund_flag` is called for a fund that already has an
active flag, the prior one is auto-cleared.

Operations:

- :func:`get_active_fund_flag_id` — read-only lookup used by the phase
  dispatcher to populate the E7 cache key component.
- :func:`create_fund_flag` — raise a flag for a fund.
- :func:`clear_fund_flag` — clear the active flag for a fund.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.agents.cache.models_cluster8 import FundLevelManualFlag


@dataclass(frozen=True)
class FundFlagSnapshot:
    """Immutable view of a :class:`FundLevelManualFlag` row."""

    manual_flag_id: str
    firm_id: str
    fund_id: str
    advisor_id: str
    reason: str
    active_from: datetime
    cleared_at: datetime | None
    cleared_by: str | None
    is_active: bool


def _to_snapshot(row: FundLevelManualFlag) -> FundFlagSnapshot:
    return FundFlagSnapshot(
        manual_flag_id=row.manual_flag_id,
        firm_id=row.firm_id,
        fund_id=row.fund_id,
        advisor_id=row.advisor_id,
        reason=row.reason,
        active_from=row.active_from,
        cleared_at=row.cleared_at,
        cleared_by=row.cleared_by,
        is_active=row.is_active,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_active_fund_flag_id(
    db: AsyncSession,
    *,
    firm_id: str,
    fund_id: str,
) -> str | None:
    """Return the ``manual_flag_id`` of the active flag for ``fund_id``.

    Returns ``None`` if no flag is active.  Used by the phase dispatcher
    to populate the E7 cache key component.
    """
    row = await _load_active_flag(db, firm_id=firm_id, fund_id=fund_id)
    return row.manual_flag_id if row is not None else None


async def get_active_fund_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    fund_id: str,
) -> FundFlagSnapshot | None:
    """Return the full snapshot of the active flag for ``fund_id``."""
    row = await _load_active_flag(db, firm_id=firm_id, fund_id=fund_id)
    return _to_snapshot(row) if row is not None else None


# ---------------------------------------------------------------------------
# Mutate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundFlagMutation:
    """Outcome of a fund flag create/clear."""

    fund_id: str
    new_flag: FundFlagSnapshot | None
    superseded_flag_id: str | None


async def create_fund_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    fund_id: str,
    advisor_id: str,
    reason: str,
    now: datetime | None = None,
) -> FundFlagMutation:
    """Set a fresh active flag for ``fund_id``.

    Auto-clears any pre-existing active flag for this
    (firm_id, fund_id) pair.
    """
    if not fund_id:
        raise ValueError("fund_id is required")
    if not reason:
        raise ValueError("reason is required")

    moment = now or datetime.now(timezone.utc)

    superseded = await _load_active_flag(db, firm_id=firm_id, fund_id=fund_id)
    superseded_id = superseded.manual_flag_id if superseded is not None else None
    if superseded is not None:
        superseded.is_active = False
        superseded.cleared_at = moment
        superseded.cleared_by = advisor_id

    new_id = str(ULID())
    new_row = FundLevelManualFlag(
        manual_flag_id=new_id,
        firm_id=firm_id,
        fund_id=fund_id,
        advisor_id=advisor_id,
        reason=reason,
        active_from=moment,
        cleared_at=None,
        cleared_by=None,
        created_at=moment,
        is_active=True,
    )
    db.add(new_row)
    await db.flush()

    return FundFlagMutation(
        fund_id=fund_id,
        new_flag=_to_snapshot(new_row),
        superseded_flag_id=superseded_id,
    )


async def clear_fund_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    fund_id: str,
    cleared_by: str,
    now: datetime | None = None,
) -> FundFlagMutation:
    """Clear the active flag for ``fund_id`` (no-op if none was active)."""
    moment = now or datetime.now(timezone.utc)

    row = await _load_active_flag(db, firm_id=firm_id, fund_id=fund_id)
    if row is None:
        return FundFlagMutation(
            fund_id=fund_id, new_flag=None, superseded_flag_id=None,
        )

    superseded_id = row.manual_flag_id
    row.is_active = False
    row.cleared_at = moment
    row.cleared_by = cleared_by
    await db.flush()

    return FundFlagMutation(
        fund_id=fund_id, new_flag=None, superseded_flag_id=superseded_id,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_active_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    fund_id: str,
) -> FundLevelManualFlag | None:
    stmt = (
        select(FundLevelManualFlag)
        .where(
            FundLevelManualFlag.firm_id == firm_id,
            FundLevelManualFlag.fund_id == fund_id,
            FundLevelManualFlag.is_active.is_(True),
        )
        .order_by(FundLevelManualFlag.active_from.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


__all__ = [
    "FundFlagMutation",
    "FundFlagSnapshot",
    "clear_fund_flag",
    "create_fund_flag",
    "get_active_fund_flag",
    "get_active_fund_flag_id",
]
