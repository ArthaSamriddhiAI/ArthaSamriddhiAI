"""Admin macro-snapshot browse router (cluster 3 chunk 3.3).

Endpoints:

- ``GET /api/v2/admin/macro-snapshots``         — paginated list
- ``GET /api/v2/admin/macro-snapshots/{id}``    — one snapshot's detail

Both gate on :data:`Permission.D0_ADMIN_READ`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.d0.macro import service
from artha.api_v2.d0.macro.schemas import (
    MacroSnapshotListResponse,
    MacroSnapshotRead,
)
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/admin", tags=["d0_admin_macro"])


def _to_read(row) -> MacroSnapshotRead:
    return MacroSnapshotRead(
        macro_snapshot_id=row.macro_snapshot_id,
        country_code=row.country_code,
        snapshot_period=row.snapshot_period,
        snapshot_date=row.snapshot_date,
        gdp_growth_pct=row.gdp_growth_pct,
        cpi_inflation_pct=row.cpi_inflation_pct,
        wpi_inflation_pct=row.wpi_inflation_pct,
        repo_rate_pct=row.repo_rate_pct,
        reverse_repo_rate_pct=row.reverse_repo_rate_pct,
        bond_yield_10y_pct=row.bond_yield_10y_pct,
        fx_usd_inr=row.fx_usd_inr,
        unemployment_rate_pct=row.unemployment_rate_pct,
        notes=row.notes,
        themes=row.themes or [],
        source_identifier=row.source_identifier,
        source_subkey=row.source_subkey,
        staging_record_id=row.staging_record_id,
        adapter_run_id=row.adapter_run_id,
        created_at=row.created_at,
        last_modified_at=row.last_modified_at,
        schema_version=row.schema_version,
    )


@router.get("/macro-snapshots", response_model=MacroSnapshotListResponse)
async def list_macro_snapshots_endpoint(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    country_code: str | None = None,
    snapshot_period: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    rows, total = await service.list_macro_snapshots(
        db,
        country_code=country_code,
        snapshot_period=snapshot_period,
        limit=min(max(1, limit), 500),
        offset=max(0, offset),
    )
    return MacroSnapshotListResponse(
        snapshots=[_to_read(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/macro-snapshots/{macro_snapshot_id}",
    response_model=MacroSnapshotRead,
)
async def get_macro_snapshot_endpoint(
    macro_snapshot_id: str,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    row = await service.get_macro_snapshot(
        db, macro_snapshot_id=macro_snapshot_id
    )
    if row is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="MacroSnapshot not found",
            detail=f"No macro snapshot with id={macro_snapshot_id!r}",
        )
    return _to_read(row)
