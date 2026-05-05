"""Instrument query + write helpers used by the adapter and the router.

The router stays thin (request → service call → response shape); the
service holds the SQL. Adapters call :func:`upsert_instrument` to land
rows; the admin UI calls :func:`list_instruments` / :func:`get_instrument`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.d0.event_names import (
    CANONICAL_ENTITY_CREATED,
    CANONICAL_ENTITY_UPDATED,
)
from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def list_instruments(
    db: AsyncSession,
    *,
    asset_class: str | None = None,
    vehicle_type: str | None = None,
    sebi_category: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Instrument], int]:
    """Filtered + paginated instrument query.

    Returns ``(rows, total_unfiltered_with_filters)`` so the UI can show
    pagination accurately.
    """
    base = select(Instrument)
    count_base = select(func.count()).select_from(Instrument)

    filters = []
    if asset_class is not None:
        filters.append(Instrument.asset_class == asset_class)
    if vehicle_type is not None:
        filters.append(Instrument.vehicle_type == vehicle_type)
    if sebi_category is not None:
        filters.append(Instrument.sebi_category == sebi_category)
    if status is not None:
        filters.append(Instrument.status == status)
    if search is not None and search.strip():
        like = f"%{search.strip()}%"
        filters.append(
            or_(
                Instrument.name.ilike(like),
                Instrument.isin.ilike(like),
                Instrument.amfi_scheme_code.ilike(like),
                Instrument.exchange_ticker.ilike(like),
            )
        )

    if filters:
        base = base.where(*filters)
        count_base = count_base.where(*filters)

    base = (
        base.order_by(Instrument.name.asc()).limit(limit).offset(offset)
    )

    rows = list((await db.execute(base)).scalars())
    total = (await db.execute(count_base)).scalar_one() or 0
    return rows, int(total)


async def get_instrument(
    db: AsyncSession, *, instrument_id: str
) -> Instrument | None:
    return (
        await db.execute(
            select(Instrument).where(Instrument.instrument_id == instrument_id)
        )
    ).scalar_one_or_none()


async def find_by_identifier(
    db: AsyncSession,
    *,
    isin: str | None = None,
    amfi_scheme_code: str | None = None,
    exchange_ticker: str | None = None,
) -> Instrument | None:
    """Lookup the unique instrument matching whichever identifier is set.

    Tries ISIN first (most authoritative), then AMFI code, then ticker.
    Returns the first match.
    """
    if isin:
        row = (
            await db.execute(select(Instrument).where(Instrument.isin == isin))
        ).scalar_one_or_none()
        if row is not None:
            return row
    if amfi_scheme_code:
        row = (
            await db.execute(
                select(Instrument).where(
                    Instrument.amfi_scheme_code == amfi_scheme_code
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    if exchange_ticker:
        row = (
            await db.execute(
                select(Instrument).where(
                    Instrument.exchange_ticker == exchange_ticker
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    return None


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def upsert_instrument(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    source_identifier: str,
    adapter_run_id: str,
    staging_record_id: str | None,
    source_subkey: str | None = None,
    firm_id: str | None = None,
) -> tuple[Instrument, bool]:
    """Insert or update one Instrument row.

    Returns ``(row, created)`` where ``created`` is True for new rows.
    Identity resolution: ISIN → AMFI code → exchange ticker, in that
    order. Hits a :data:`CANONICAL_ENTITY_CREATED` or
    :data:`CANONICAL_ENTITY_UPDATED` T1 event on every successful write.
    """
    existing = await find_by_identifier(
        db,
        isin=payload.get("isin"),
        amfi_scheme_code=payload.get("amfi_scheme_code"),
        exchange_ticker=payload.get("exchange_ticker"),
    )
    now = datetime.now(timezone.utc)

    if existing is None:
        row = Instrument(
            instrument_id=str(ULID()),
            isin=payload.get("isin"),
            amfi_scheme_code=payload.get("amfi_scheme_code"),
            exchange_ticker=payload.get("exchange_ticker"),
            name=payload["name"],
            short_name=payload.get("short_name"),
            asset_class=payload["asset_class"],
            vehicle_type=payload["vehicle_type"],
            sebi_category=payload.get("sebi_category"),
            sebi_subcategory=payload.get("sebi_subcategory"),
            classification_confidence=payload.get(
                "classification_confidence", "high"
            ),
            issuer_name=payload.get("issuer_name"),
            amc_name=payload.get("amc_name"),
            riskometer_label=payload.get("riskometer_label"),
            status=payload.get("status", "active"),
            inception_date=payload.get("inception_date"),
            source_identifier=source_identifier,
            source_subkey=source_subkey,
            staging_record_id=staging_record_id,
            adapter_run_id=adapter_run_id,
            created_at=now,
            last_modified_at=now,
            schema_version=1,
        )
        db.add(row)
        await db.flush()
        await emit_event(
            db,
            event_name=CANONICAL_ENTITY_CREATED,
            payload={
                "entity_type": "Instrument",
                "entity_id": row.instrument_id,
                "source_identifier": source_identifier,
                "adapter_run_id": adapter_run_id,
            },
            firm_id=firm_id,
        )
        return row, True

    # Existing — patch in place. Cluster 3 demo-stage adapters always
    # overwrite; future live adapters may want delta-only updates.
    for key in (
        "isin",
        "amfi_scheme_code",
        "exchange_ticker",
        "name",
        "short_name",
        "asset_class",
        "vehicle_type",
        "sebi_category",
        "sebi_subcategory",
        "classification_confidence",
        "issuer_name",
        "amc_name",
        "riskometer_label",
        "status",
        "inception_date",
    ):
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
            "entity_type": "Instrument",
            "entity_id": existing.instrument_id,
            "source_identifier": source_identifier,
            "adapter_run_id": adapter_run_id,
        },
        firm_id=firm_id,
    )
    return existing, False
