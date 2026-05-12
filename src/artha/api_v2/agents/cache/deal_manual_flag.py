"""Deal-level manual-flag service — cluster 9 chunk 9.2 §1.4.

Per-deal flags invalidate the E5.DealView cache when an analyst knows a
deal-level override is needed (e.g. material MCA filing confirmed,
valuation event, co-investor exit, distress signal).

Invariant: at most one *active* flag per (firm_id, deal_id) pair at a
time, enforced at the application layer.  When :func:`create_deal_flag`
is called for a deal that already has an active flag, the prior one is
auto-cleared.

Operations:

- :func:`get_active_deal_flag_id` — read-only lookup used by the phase
  dispatcher to populate the E5.DealView cache key component.
- :func:`get_active_deal_flag` — full snapshot of the active flag.
- :func:`create_deal_flag` — raise a flag for a deal.
- :func:`clear_deal_flag` — clear the active flag for a deal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.agents.cache.models_cluster9 import DealLevelManualFlag


@dataclass(frozen=True)
class DealFlagSnapshot:
    """Immutable view of a :class:`DealLevelManualFlag` row."""

    manual_flag_id: str
    firm_id: str
    deal_id: str
    advisor_id: str
    reason: str
    invalidates_e5dv: bool
    active_from: datetime
    cleared_at: datetime | None
    cleared_by: str | None
    is_active: bool


def _to_snapshot(row: DealLevelManualFlag) -> DealFlagSnapshot:
    return DealFlagSnapshot(
        manual_flag_id=row.manual_flag_id,
        firm_id=row.firm_id,
        deal_id=row.deal_id,
        advisor_id=row.advisor_id,
        reason=row.reason,
        invalidates_e5dv=row.invalidates_e5dv,
        active_from=row.active_from,
        cleared_at=row.cleared_at,
        cleared_by=row.cleared_by,
        is_active=row.is_active,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_active_deal_flag_id(
    db: AsyncSession,
    *,
    firm_id: str,
    deal_id: str,
) -> str | None:
    """Return the ``manual_flag_id`` of the active flag for ``deal_id``.

    Returns ``None`` if no flag is active.  Used by the phase dispatcher
    to populate the E5.DealView cache key component.
    """
    row = await _load_active_flag(db, firm_id=firm_id, deal_id=deal_id)
    return row.manual_flag_id if row is not None else None


async def get_active_deal_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    deal_id: str,
) -> DealFlagSnapshot | None:
    """Return the full snapshot of the active flag for ``deal_id``."""
    row = await _load_active_flag(db, firm_id=firm_id, deal_id=deal_id)
    return _to_snapshot(row) if row is not None else None


# ---------------------------------------------------------------------------
# Mutate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DealFlagMutation:
    """Outcome of a deal flag create/clear."""

    deal_id: str
    new_flag: DealFlagSnapshot | None
    superseded_flag_id: str | None


async def create_deal_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    deal_id: str,
    advisor_id: str,
    reason: str,
    invalidates_e5dv: bool = True,
    now: datetime | None = None,
) -> DealFlagMutation:
    """Set a fresh active flag for ``deal_id``.

    Auto-clears any pre-existing active flag for this
    (firm_id, deal_id) pair.
    """
    if not deal_id:
        raise ValueError("deal_id is required")
    if not reason:
        raise ValueError("reason is required")

    moment = now or datetime.now(timezone.utc)

    superseded = await _load_active_flag(db, firm_id=firm_id, deal_id=deal_id)
    superseded_id = (
        superseded.manual_flag_id if superseded is not None else None
    )
    if superseded is not None:
        superseded.is_active = False
        superseded.cleared_at = moment
        superseded.cleared_by = advisor_id

    new_id = str(ULID())
    new_row = DealLevelManualFlag(
        manual_flag_id=new_id,
        firm_id=firm_id,
        deal_id=deal_id,
        advisor_id=advisor_id,
        reason=reason,
        invalidates_e5dv=invalidates_e5dv,
        active_from=moment,
        cleared_at=None,
        cleared_by=None,
        created_at=moment,
        is_active=True,
    )
    db.add(new_row)
    await db.flush()

    return DealFlagMutation(
        deal_id=deal_id,
        new_flag=_to_snapshot(new_row),
        superseded_flag_id=superseded_id,
    )


async def clear_deal_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    deal_id: str,
    cleared_by: str,
    now: datetime | None = None,
) -> DealFlagMutation:
    """Clear the active flag for ``deal_id`` (no-op if none was active)."""
    moment = now or datetime.now(timezone.utc)

    row = await _load_active_flag(db, firm_id=firm_id, deal_id=deal_id)
    if row is None:
        return DealFlagMutation(
            deal_id=deal_id,
            new_flag=None,
            superseded_flag_id=None,
        )

    superseded_id = row.manual_flag_id
    row.is_active = False
    row.cleared_at = moment
    row.cleared_by = cleared_by
    await db.flush()

    return DealFlagMutation(
        deal_id=deal_id,
        new_flag=None,
        superseded_flag_id=superseded_id,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_active_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    deal_id: str,
) -> DealLevelManualFlag | None:
    stmt = (
        select(DealLevelManualFlag)
        .where(
            DealLevelManualFlag.firm_id == firm_id,
            DealLevelManualFlag.deal_id == deal_id,
            DealLevelManualFlag.is_active.is_(True),
        )
        .order_by(DealLevelManualFlag.active_from.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


__all__ = [
    "DealFlagMutation",
    "DealFlagSnapshot",
    "clear_deal_flag",
    "create_deal_flag",
    "get_active_deal_flag",
    "get_active_deal_flag_id",
]
