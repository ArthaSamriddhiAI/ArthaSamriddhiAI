"""Investor-level manual-flag service — cluster 9 chunk 9.3 §5.

Per-investor flags invalidate the E4 Behavioural cache when an analyst
knows an investor-level override is needed (e.g. confirmed panic event,
advisor notes a material behavioural shift, AUM change warrants a fresh
read).

Invariant: at most one *active* flag per (firm_id, investor_id) pair at
a time, enforced at the application layer.  When
:func:`create_investor_flag` is called for an investor that already has
an active flag, the prior one is auto-cleared.

Operations:

- :func:`get_active_investor_flag_id` — read-only lookup used by the
  phase dispatcher to populate the E4 cache key component.
- :func:`get_active_investor_flag` — full snapshot of the active flag.
- :func:`create_investor_flag` — raise a flag for an investor.
- :func:`clear_investor_flag` — clear the active flag for an investor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.agents.cache.models_cluster9 import InvestorLevelManualFlag


@dataclass(frozen=True)
class InvestorFlagSnapshot:
    """Immutable view of an :class:`InvestorLevelManualFlag` row."""

    manual_flag_id: str
    firm_id: str
    investor_id: str
    advisor_id: str
    reason: str
    invalidates_e4: bool
    active_from: datetime
    cleared_at: datetime | None
    cleared_by: str | None
    is_active: bool


def _to_snapshot(row: InvestorLevelManualFlag) -> InvestorFlagSnapshot:
    return InvestorFlagSnapshot(
        manual_flag_id=row.manual_flag_id,
        firm_id=row.firm_id,
        investor_id=row.investor_id,
        advisor_id=row.advisor_id,
        reason=row.reason,
        invalidates_e4=row.invalidates_e4,
        active_from=row.active_from,
        cleared_at=row.cleared_at,
        cleared_by=row.cleared_by,
        is_active=row.is_active,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_active_investor_flag_id(
    db: AsyncSession,
    *,
    firm_id: str,
    investor_id: str,
) -> str | None:
    """Return the ``manual_flag_id`` of the active flag for ``investor_id``.

    Returns ``None`` if no flag is active.  Used by the phase dispatcher
    to populate the E4 cache key component.
    """
    row = await _load_active_flag(db, firm_id=firm_id, investor_id=investor_id)
    return row.manual_flag_id if row is not None else None


async def get_active_investor_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    investor_id: str,
) -> InvestorFlagSnapshot | None:
    """Return the full snapshot of the active flag for ``investor_id``."""
    row = await _load_active_flag(
        db, firm_id=firm_id, investor_id=investor_id,
    )
    return _to_snapshot(row) if row is not None else None


# ---------------------------------------------------------------------------
# Mutate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvestorFlagMutation:
    """Outcome of an investor flag create/clear."""

    investor_id: str
    new_flag: InvestorFlagSnapshot | None
    superseded_flag_id: str | None


async def create_investor_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    investor_id: str,
    advisor_id: str,
    reason: str,
    invalidates_e4: bool = True,
    now: datetime | None = None,
) -> InvestorFlagMutation:
    """Set a fresh active flag for ``investor_id``.

    Auto-clears any pre-existing active flag for this
    (firm_id, investor_id) pair.
    """
    if not investor_id:
        raise ValueError("investor_id is required")
    if not reason:
        raise ValueError("reason is required")

    moment = now or datetime.now(timezone.utc)

    superseded = await _load_active_flag(
        db, firm_id=firm_id, investor_id=investor_id,
    )
    superseded_id = (
        superseded.manual_flag_id if superseded is not None else None
    )
    if superseded is not None:
        superseded.is_active = False
        superseded.cleared_at = moment
        superseded.cleared_by = advisor_id

    new_id = str(ULID())
    new_row = InvestorLevelManualFlag(
        manual_flag_id=new_id,
        firm_id=firm_id,
        investor_id=investor_id,
        advisor_id=advisor_id,
        reason=reason,
        invalidates_e4=invalidates_e4,
        active_from=moment,
        cleared_at=None,
        cleared_by=None,
        created_at=moment,
        is_active=True,
    )
    db.add(new_row)
    await db.flush()

    return InvestorFlagMutation(
        investor_id=investor_id,
        new_flag=_to_snapshot(new_row),
        superseded_flag_id=superseded_id,
    )


async def clear_investor_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    investor_id: str,
    cleared_by: str,
    now: datetime | None = None,
) -> InvestorFlagMutation:
    """Clear the active flag for ``investor_id`` (no-op if none active)."""
    moment = now or datetime.now(timezone.utc)

    row = await _load_active_flag(
        db, firm_id=firm_id, investor_id=investor_id,
    )
    if row is None:
        return InvestorFlagMutation(
            investor_id=investor_id,
            new_flag=None,
            superseded_flag_id=None,
        )

    superseded_id = row.manual_flag_id
    row.is_active = False
    row.cleared_at = moment
    row.cleared_by = cleared_by
    await db.flush()

    return InvestorFlagMutation(
        investor_id=investor_id,
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
    investor_id: str,
) -> InvestorLevelManualFlag | None:
    stmt = (
        select(InvestorLevelManualFlag)
        .where(
            InvestorLevelManualFlag.firm_id == firm_id,
            InvestorLevelManualFlag.investor_id == investor_id,
            InvestorLevelManualFlag.is_active.is_(True),
        )
        .order_by(InvestorLevelManualFlag.active_from.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


__all__ = [
    "InvestorFlagMutation",
    "InvestorFlagSnapshot",
    "clear_investor_flag",
    "create_investor_flag",
    "get_active_investor_flag",
    "get_active_investor_flag_id",
]
