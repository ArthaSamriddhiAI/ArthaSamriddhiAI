"""Model portfolio REST router (cluster 4 chunks 4.1, 4.2, 4.3).

Chunk 4.1 ships these read-only endpoints:

- ``GET /api/v2/model-portfolio/instruments``         — paginated list with
                                                       filters
- ``GET /api/v2/model-portfolio/instruments/{id}``    — detail
- ``GET /api/v2/model-portfolio/preferred``           — 3x3 matrix overview
- ``GET /api/v2/model-portfolio/preferred/{rp}/{h}``  — cell detail
- ``GET /api/v2/model-portfolio/preferred/by-instrument/{id}`` — reverse
- ``GET /api/v2/model-portfolio/health``              — admin summary

All gated on :data:`Permission.MODEL_PORTFOLIO_READ` (advisor + CIO +
compliance + audit). Chunk 4.2 / 4.3 add the write endpoints which
require ``MODEL_PORTFOLIO_WRITE`` (CIO only).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.m2 import cells, service
from artha.api_v2.m2.models import PreferredPortfolioEntry
from artha.api_v2.m2.schemas import (
    CellDetailResponse,
    CellRoleSummary,
    CellSummary,
    HealthResponse,
    InstrumentInPreferredEntry,
    InstrumentInPreferredResponse,
    InstrumentListResponse,
    InstrumentWithTagsRead,
    MatrixOverviewResponse,
    PreferredPortfolioEntryRead,
)
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/model-portfolio", tags=["m2_model_portfolio"])


# ---------------------------------------------------------------------------
# Read-shape converters
# ---------------------------------------------------------------------------


def _instrument_to_read(inst: Instrument) -> InstrumentWithTagsRead:
    return InstrumentWithTagsRead(
        instrument_id=inst.instrument_id,
        isin=inst.isin,
        amfi_scheme_code=inst.amfi_scheme_code,
        exchange_ticker=inst.exchange_ticker,
        name=inst.name,
        asset_class=inst.asset_class,
        vehicle_type=inst.vehicle_type,
        sebi_category=inst.sebi_category,
        amc_name=inst.amc_name,
        riskometer_label=inst.riskometer_label,
        status=inst.status,
        inception_date=inst.inception_date,
        model_portfolio_tags=list(inst.model_portfolio_tags or []),
        model_portfolio_tags_modified_at=inst.model_portfolio_tags_modified_at,
        model_portfolio_tags_modified_by=inst.model_portfolio_tags_modified_by,
        last_modified_at=inst.last_modified_at,
        schema_version=inst.schema_version,
    )


def _entry_to_read(
    entry: PreferredPortfolioEntry, *, instrument: Instrument
) -> PreferredPortfolioEntryRead:
    target_cell = cells.cell_id(entry.risk_profile, entry.horizon)
    has_match = target_cell in (instrument.model_portfolio_tags or [])
    return PreferredPortfolioEntryRead(
        entry_id=entry.entry_id,
        risk_profile=entry.risk_profile,
        horizon=entry.horizon,
        instrument_id=entry.instrument_id,
        instrument_name=instrument.name,
        instrument_asset_class=instrument.asset_class,
        instrument_vehicle_type=instrument.vehicle_type,
        instrument_amc_name=instrument.amc_name,
        instrument_sebi_category=instrument.sebi_category,
        position_role=entry.position_role,
        rank_within_role=entry.rank_within_role,
        notes=entry.notes,
        has_matching_tag=has_match,
        created_at=entry.created_at,
        created_by=entry.created_by,
        created_via=entry.created_via,
        last_modified_at=entry.last_modified_at,
        last_modified_by=entry.last_modified_by,
    )


# ---------------------------------------------------------------------------
# Instrument list + detail
# ---------------------------------------------------------------------------


@router.get("/instruments", response_model=InstrumentListResponse)
async def list_instruments_endpoint(
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_READ)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    asset_class: str | None = None,
    vehicle_type: str | None = None,
    sebi_category: str | None = None,
    tag_include: list[str] | None = Query(default=None),
    tag_exclude: list[str] | None = Query(default=None),
    untagged_only: bool = False,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Paginated instrument-with-tags list. Chunk 4.2 reads the same
    endpoint with richer query strings."""
    rows, total = await service.list_instruments_with_tags(
        db,
        asset_class=asset_class,
        vehicle_type=vehicle_type,
        sebi_category=sebi_category,
        tag_includes=tag_include,
        tag_excludes=tag_exclude,
        untagged_only=untagged_only,
        search=search,
        limit=min(max(1, limit), 500),
        offset=max(0, offset),
    )
    return InstrumentListResponse(
        instruments=[_instrument_to_read(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/instruments/{instrument_id}", response_model=InstrumentWithTagsRead
)
async def get_instrument_endpoint(
    instrument_id: str,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_READ)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    inst = await service.get_instrument(db, instrument_id=instrument_id)
    if inst is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Instrument not found",
            detail=f"No instrument with id={instrument_id!r}",
        )
    return _instrument_to_read(inst)


# ---------------------------------------------------------------------------
# Preferred portfolio matrix + cell detail
# ---------------------------------------------------------------------------


@router.get("/preferred", response_model=MatrixOverviewResponse)
async def matrix_overview_endpoint(
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_READ)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """3x3 matrix overview — cell counts + last-modified + top-3 cores."""
    counts, last_modified, top_cores = await service.matrix_overview(db)

    cell_summaries: list[CellSummary] = []
    total_entries = 0
    overall_last_modified = None
    for rp in cells.RISK_PROFILES:
        for h in cells.HORIZONS:
            role_counts = counts[(rp, h)]
            n = sum(role_counts.values())
            total_entries += n
            lm = last_modified.get((rp, h))
            if lm is not None and (
                overall_last_modified is None or lm > overall_last_modified
            ):
                overall_last_modified = lm
            cell_summaries.append(
                CellSummary(
                    risk_profile=rp,
                    horizon=h,
                    cell_id=cells.cell_id(rp, h),
                    counts=CellRoleSummary(
                        core=role_counts["core"],
                        satellite=role_counts["satellite"],
                        optional=role_counts["optional"],
                    ),
                    last_modified_at=lm,
                    top_core_names=top_cores.get((rp, h), []),
                )
            )

    return MatrixOverviewResponse(
        cells=cell_summaries,
        total_entries=total_entries,
        last_modified_at=overall_last_modified,
    )


@router.get(
    "/preferred/by-instrument/{instrument_id}",
    response_model=InstrumentInPreferredResponse,
)
async def by_instrument_endpoint_pre(
    instrument_id: str,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_READ)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Reverse lookup — where this instrument appears across cells.

    Declared BEFORE ``/preferred/{risk_profile}/{horizon}`` so the literal
    ``by-instrument`` segment doesn't get matched as a ``risk_profile``
    placeholder.
    """
    inst = await service.get_instrument(db, instrument_id=instrument_id)
    if inst is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Instrument not found",
            detail=f"No instrument with id={instrument_id!r}",
        )
    entries = await service.list_entries_for_instrument(
        db, instrument_id=instrument_id
    )
    return InstrumentInPreferredResponse(
        instrument_id=instrument_id,
        instrument_name=inst.name,
        appearances=[
            InstrumentInPreferredEntry(
                entry_id=e.entry_id,
                risk_profile=e.risk_profile,
                horizon=e.horizon,
                cell_id=cells.cell_id(e.risk_profile, e.horizon),
                position_role=e.position_role,
                rank_within_role=e.rank_within_role,
            )
            for e in entries
        ],
    )


@router.get(
    "/preferred/{risk_profile}/{horizon}", response_model=CellDetailResponse
)
async def cell_detail_endpoint(
    risk_profile: str,
    horizon: str,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_READ)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Per-cell detail with entries grouped by role."""
    if risk_profile not in cells.RISK_PROFILES or horizon not in cells.HORIZONS:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Cell not found",
            detail=f"No cell at ({risk_profile}, {horizon})",
        )

    entries = await service.list_cell_entries(
        db, risk_profile=risk_profile, horizon=horizon
    )
    # Resolve instruments for the response.
    instrument_ids = [e.instrument_id for e in entries]
    if instrument_ids:
        from sqlalchemy import select as _select

        rows = list(
            (
                await db.execute(
                    _select(Instrument).where(
                        Instrument.instrument_id.in_(instrument_ids)
                    )
                )
            ).scalars()
        )
        by_id = {r.instrument_id: r for r in rows}
    else:
        by_id = {}

    core: list[PreferredPortfolioEntryRead] = []
    satellite: list[PreferredPortfolioEntryRead] = []
    optional: list[PreferredPortfolioEntryRead] = []
    last_modified = None
    for entry in entries:
        inst = by_id.get(entry.instrument_id)
        if inst is None:
            # Orphaned entry — referenced instrument missing. Skip from
            # the response but log defensively.
            continue
        read = _entry_to_read(entry, instrument=inst)
        if entry.position_role == "core":
            core.append(read)
        elif entry.position_role == "satellite":
            satellite.append(read)
        else:
            optional.append(read)
        if last_modified is None or entry.last_modified_at > last_modified:
            last_modified = entry.last_modified_at

    return CellDetailResponse(
        risk_profile=risk_profile,
        horizon=horizon,
        cell_id=cells.cell_id(risk_profile, horizon),
        core=core,
        satellite=satellite,
        optional=optional,
        last_modified_at=last_modified,
    )


# ---------------------------------------------------------------------------
# Health summary (chunk 4.1 §implementation_notes)
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
async def health_endpoint(
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_READ)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    summary = await service.health_summary(db)
    by_cell = {
        cell: CellRoleSummary(
            core=counts.get("core", 0),
            satellite=counts.get("satellite", 0),
            optional=counts.get("optional", 0),
        )
        for cell, counts in summary["preferred_entries_by_cell"].items()
    }
    return HealthResponse(
        tagged_instruments_count=summary["tagged_instruments_count"],
        untagged_instruments_count=summary["untagged_instruments_count"],
        total_instruments=summary["total_instruments"],
        total_preferred_entries=summary["total_preferred_entries"],
        preferred_entries_by_cell=by_cell,
        last_tag_modification_at=summary["last_tag_modification_at"],
        last_preferred_modification_at=summary["last_preferred_modification_at"],
    )
