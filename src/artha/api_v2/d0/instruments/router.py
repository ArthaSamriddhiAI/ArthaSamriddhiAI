"""Admin instrument-browse router (cluster 3 chunk 3.2).

Endpoints:

- ``GET /api/v2/admin/instruments``         — paginated list with filters
- ``GET /api/v2/admin/instruments/{id}``    — one row's full detail
- ``GET /api/v2/admin/sebi-categories``     — every category in the SEBI
                                              map (UI dropdown source)

All endpoints gate on :data:`Permission.D0_ADMIN_READ`. Cluster 3
chunk 3.4 will expose the same data through the audit-role admin UI.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.d0.instruments import sebi_mapping, service
from artha.api_v2.d0.instruments.schemas import (
    InstrumentListResponse,
    InstrumentRead,
)
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/admin", tags=["d0_admin_instruments"])


def _to_read(row) -> InstrumentRead:
    return InstrumentRead(
        instrument_id=row.instrument_id,
        isin=row.isin,
        amfi_scheme_code=row.amfi_scheme_code,
        exchange_ticker=row.exchange_ticker,
        name=row.name,
        short_name=row.short_name,
        asset_class=row.asset_class,
        vehicle_type=row.vehicle_type,
        sebi_category=row.sebi_category,
        sebi_subcategory=row.sebi_subcategory,
        classification_confidence=row.classification_confidence,
        issuer_name=row.issuer_name,
        amc_name=row.amc_name,
        riskometer_label=row.riskometer_label,
        status=row.status,
        inception_date=row.inception_date,
        source_identifier=row.source_identifier,
        source_subkey=row.source_subkey,
        staging_record_id=row.staging_record_id,
        adapter_run_id=row.adapter_run_id,
        created_at=row.created_at,
        last_modified_at=row.last_modified_at,
        schema_version=row.schema_version,
    )


@router.get("/instruments", response_model=InstrumentListResponse)
async def list_instruments_endpoint(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    asset_class: str | None = None,
    vehicle_type: str | None = None,
    sebi_category: str | None = None,
    instrument_status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Paginated instrument browser."""
    rows, total = await service.list_instruments(
        db,
        asset_class=asset_class,
        vehicle_type=vehicle_type,
        sebi_category=sebi_category,
        status=instrument_status,
        search=search,
        limit=min(max(1, limit), 500),
        offset=max(0, offset),
    )
    return InstrumentListResponse(
        instruments=[_to_read(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/instruments/{instrument_id}", response_model=InstrumentRead)
async def get_instrument_endpoint(
    instrument_id: str,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    row = await service.get_instrument(db, instrument_id=instrument_id)
    if row is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Instrument not found",
            detail=f"No instrument with id={instrument_id!r}",
        )
    return _to_read(row)


@router.get("/sebi-categories")
async def list_sebi_categories(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
):
    """List every SEBI category with its asset_class + vehicle_type pair.

    The admin UI's filter dropdown reads from this so the catalogue stays
    in sync with the mapping table without a separate frontend constant.
    """
    return {
        "categories": [
            {
                "category": cat,
                "asset_class": sebi_mapping.SEBI_CATEGORY_MAP[cat][0],
                "vehicle_type": sebi_mapping.SEBI_CATEGORY_MAP[cat][1],
            }
            for cat in sebi_mapping.all_categories()
        ]
    }
