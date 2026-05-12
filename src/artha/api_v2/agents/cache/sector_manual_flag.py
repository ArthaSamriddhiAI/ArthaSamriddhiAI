"""Sector-level manual-flag service — cluster 8 chunk 8.2 §2.3.

Per-sector flags invalidate the E2.SectorView cache when an analyst
knows a sector-level manual override is needed (e.g., a sudden
regulatory action, an unexpected sector shock).

Invariant: at most one *active* flag per (firm_id, sector_code) pair at
a time, enforced at the application layer.  When
:func:`create_sector_flag` is called for a sector that already has an
active flag, the prior one is auto-cleared.

Operations:

- :func:`get_active_sector_flag_id` — read-only lookup used by the
  phase dispatcher to populate the E2.SectorView cache key component.
- :func:`create_sector_flag` — raise a flag for a sector.
- :func:`clear_sector_flag` — clear the active flag for a sector.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.agents.cache.models_cluster8 import SectorLevelManualFlag


@dataclass(frozen=True)
class SectorFlagSnapshot:
    """Immutable view of a :class:`SectorLevelManualFlag` row."""

    manual_flag_id: str
    firm_id: str
    sector_code: str
    advisor_id: str
    reason: str
    active_from: datetime
    cleared_at: datetime | None
    cleared_by: str | None
    is_active: bool


def _to_snapshot(row: SectorLevelManualFlag) -> SectorFlagSnapshot:
    return SectorFlagSnapshot(
        manual_flag_id=row.manual_flag_id,
        firm_id=row.firm_id,
        sector_code=row.sector_code,
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


async def get_active_sector_flag_id(
    db: AsyncSession,
    *,
    firm_id: str,
    sector_code: str,
) -> str | None:
    """Return the ``manual_flag_id`` of the active flag for ``sector_code``.

    Returns ``None`` if no flag is active.  Used by the phase dispatcher
    to populate the E2.SectorView cache key component.
    """
    row = await _load_active_flag(db, firm_id=firm_id, sector_code=sector_code)
    return row.manual_flag_id if row is not None else None


async def get_active_sector_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    sector_code: str,
) -> SectorFlagSnapshot | None:
    """Return the full snapshot of the active flag for ``sector_code``."""
    row = await _load_active_flag(db, firm_id=firm_id, sector_code=sector_code)
    return _to_snapshot(row) if row is not None else None


# ---------------------------------------------------------------------------
# Mutate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectorFlagMutation:
    """Outcome of a sector flag create/clear."""

    sector_code: str
    new_flag: SectorFlagSnapshot | None
    superseded_flag_id: str | None


async def create_sector_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    sector_code: str,
    advisor_id: str,
    reason: str,
    now: datetime | None = None,
) -> SectorFlagMutation:
    """Set a fresh active flag for ``sector_code``.

    Auto-clears any pre-existing active flag for this
    (firm_id, sector_code) pair.
    """
    if not sector_code:
        raise ValueError("sector_code is required")
    if not reason:
        raise ValueError("reason is required")

    moment = now or datetime.now(timezone.utc)

    superseded = await _load_active_flag(
        db, firm_id=firm_id, sector_code=sector_code,
    )
    superseded_id = superseded.manual_flag_id if superseded is not None else None
    if superseded is not None:
        superseded.is_active = False
        superseded.cleared_at = moment
        superseded.cleared_by = advisor_id

    new_id = str(ULID())
    new_row = SectorLevelManualFlag(
        manual_flag_id=new_id,
        firm_id=firm_id,
        sector_code=sector_code,
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

    return SectorFlagMutation(
        sector_code=sector_code,
        new_flag=_to_snapshot(new_row),
        superseded_flag_id=superseded_id,
    )


async def clear_sector_flag(
    db: AsyncSession,
    *,
    firm_id: str,
    sector_code: str,
    cleared_by: str,
    now: datetime | None = None,
) -> SectorFlagMutation:
    """Clear the active flag for ``sector_code`` (no-op if none was active)."""
    moment = now or datetime.now(timezone.utc)

    row = await _load_active_flag(db, firm_id=firm_id, sector_code=sector_code)
    if row is None:
        return SectorFlagMutation(
            sector_code=sector_code,
            new_flag=None,
            superseded_flag_id=None,
        )

    superseded_id = row.manual_flag_id
    row.is_active = False
    row.cleared_at = moment
    row.cleared_by = cleared_by
    await db.flush()

    return SectorFlagMutation(
        sector_code=sector_code,
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
    sector_code: str,
) -> SectorLevelManualFlag | None:
    stmt = (
        select(SectorLevelManualFlag)
        .where(
            SectorLevelManualFlag.firm_id == firm_id,
            SectorLevelManualFlag.sector_code == sector_code,
            SectorLevelManualFlag.is_active.is_(True),
        )
        .order_by(SectorLevelManualFlag.active_from.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


__all__ = [
    "SectorFlagMutation",
    "SectorFlagSnapshot",
    "clear_sector_flag",
    "create_sector_flag",
    "get_active_sector_flag",
    "get_active_sector_flag_id",
]
