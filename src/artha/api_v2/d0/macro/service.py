"""MacroSnapshot service helpers used by the JSONFixtureAdapter and router."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.d0.event_names import (
    CANONICAL_ENTITY_CREATED,
    CANONICAL_ENTITY_UPDATED,
)
from artha.api_v2.d0.macro.models import MacroSnapshot
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def list_macro_snapshots(
    db: AsyncSession,
    *,
    country_code: str | None = None,
    snapshot_period: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[MacroSnapshot], int]:
    """Filtered + paginated macro-snapshot query, newest first."""
    base = select(MacroSnapshot)
    count_base = select(func.count()).select_from(MacroSnapshot)

    filters = []
    if country_code is not None:
        filters.append(MacroSnapshot.country_code == country_code)
    if snapshot_period is not None:
        filters.append(MacroSnapshot.snapshot_period == snapshot_period)

    if filters:
        base = base.where(*filters)
        count_base = count_base.where(*filters)

    base = (
        base.order_by(MacroSnapshot.snapshot_date.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = list((await db.execute(base)).scalars())
    total = (await db.execute(count_base)).scalar_one() or 0
    return rows, int(total)


async def get_macro_snapshot(
    db: AsyncSession, *, macro_snapshot_id: str
) -> MacroSnapshot | None:
    return (
        await db.execute(
            select(MacroSnapshot).where(
                MacroSnapshot.macro_snapshot_id == macro_snapshot_id
            )
        )
    ).scalar_one_or_none()


async def find_by_natural_key(
    db: AsyncSession, *, country_code: str, snapshot_period: str
) -> MacroSnapshot | None:
    return (
        await db.execute(
            select(MacroSnapshot).where(
                MacroSnapshot.country_code == country_code,
                MacroSnapshot.snapshot_period == snapshot_period,
            )
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


_INDICATOR_FIELDS: tuple[str, ...] = (
    "gdp_growth_pct",
    "cpi_inflation_pct",
    "wpi_inflation_pct",
    "repo_rate_pct",
    "reverse_repo_rate_pct",
    "bond_yield_10y_pct",
    "fx_usd_inr",
    "unemployment_rate_pct",
    "notes",
    "themes",
)


async def upsert_macro_snapshot(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    source_identifier: str,
    adapter_run_id: str,
    staging_record_id: str | None,
    source_subkey: str | None = None,
    firm_id: str | None = None,
) -> tuple[MacroSnapshot, bool]:
    """Insert or update one MacroSnapshot.

    Identity = (country_code, snapshot_period). Returns ``(row, created)``.
    """
    country_code = payload["country_code"]
    snapshot_period = payload["snapshot_period"]

    existing = await find_by_natural_key(
        db,
        country_code=country_code,
        snapshot_period=snapshot_period,
    )
    now = datetime.now(timezone.utc)

    snapshot_date = payload["snapshot_date"]
    if isinstance(snapshot_date, str):
        snapshot_date = date.fromisoformat(snapshot_date)

    if existing is None:
        row = MacroSnapshot(
            macro_snapshot_id=str(ULID()),
            country_code=country_code,
            snapshot_period=snapshot_period,
            snapshot_date=snapshot_date,
            source_identifier=source_identifier,
            source_subkey=source_subkey,
            staging_record_id=staging_record_id,
            adapter_run_id=adapter_run_id,
            created_at=now,
            last_modified_at=now,
            schema_version=1,
            themes=payload.get("themes", []) or [],
        )
        for key in _INDICATOR_FIELDS:
            if key in payload:
                setattr(row, key, payload[key])
        db.add(row)
        await db.flush()
        await emit_event(
            db,
            event_name=CANONICAL_ENTITY_CREATED,
            payload={
                "entity_type": "MacroSnapshot",
                "entity_id": row.macro_snapshot_id,
                "country_code": country_code,
                "snapshot_period": snapshot_period,
                "source_identifier": source_identifier,
                "adapter_run_id": adapter_run_id,
            },
            firm_id=firm_id,
        )
        return row, True

    existing.snapshot_date = snapshot_date
    for key in _INDICATOR_FIELDS:
        if key in payload:
            setattr(existing, key, payload[key])
    existing.source_identifier = source_identifier
    existing.source_subkey = source_subkey
    existing.staging_record_id = staging_record_id
    existing.adapter_run_id = adapter_run_id
    existing.last_modified_at = now
    await db.flush()
    await emit_event(
        db,
        event_name=CANONICAL_ENTITY_UPDATED,
        payload={
            "entity_type": "MacroSnapshot",
            "entity_id": existing.macro_snapshot_id,
            "country_code": country_code,
            "snapshot_period": snapshot_period,
            "source_identifier": source_identifier,
            "adapter_run_id": adapter_run_id,
        },
        firm_id=firm_id,
    )
    return existing, False
