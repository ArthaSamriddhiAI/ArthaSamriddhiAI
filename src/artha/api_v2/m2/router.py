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
    BulkTagAddRequest,
    BulkTagOperationResponse,
    BulkTagRemoveRequest,
    BulkTagReplaceRequest,
    CellDetailResponse,
    CellDuplicateRequest,
    CellOperationResponse,
    CellReorderRequest,
    CellRoleSummary,
    CellSummary,
    CreatePreferredEntryRequest,
    HealthResponse,
    InstrumentInPreferredEntry,
    InstrumentInPreferredResponse,
    InstrumentListResponse,
    InstrumentWithTagsRead,
    MatrixOverviewResponse,
    PreferredPortfolioEntryRead,
    TagResetRequest,
    TagSetRequest,
    UpdatePreferredEntryRequest,
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


# ---------------------------------------------------------------------------
# Chunk 4.2: tag editing write endpoints (CIO-only)
# ---------------------------------------------------------------------------


@router.put(
    "/instruments/{instrument_id}/tags",
    response_model=InstrumentWithTagsRead,
)
async def replace_instrument_tags_endpoint(
    instrument_id: str,
    body: TagSetRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Replace one instrument's tag set. CIO-only (chunk 4.2)."""
    try:
        canonical = service.validate_tag_set(body.tags)
    except ValueError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Invalid tag set",
            detail=str(exc),
        )
    async with db.begin():
        inst = await service.get_instrument(db, instrument_id=instrument_id)
        if inst is None:
            return problem_response(
                status=status.HTTP_404_NOT_FOUND,
                title="Instrument not found",
                detail=f"No instrument with id={instrument_id!r}",
            )
        updated = await service.update_instrument_tags(
            db,
            instrument=inst,
            new_tags=canonical,
            actor_user_id=actor.user_id,
            change_type="single",
            firm_id=actor.firm_id,
        )
    return _instrument_to_read(updated)


@router.post(
    "/instruments/tags/bulk-add",
    response_model=BulkTagOperationResponse,
)
async def bulk_add_tag_endpoint(
    body: BulkTagAddRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Add one tag to many instruments. Atomic bulk write (chunk 4.2)."""
    try:
        async with db.begin():
            counts = await service.bulk_add_tag(
                db,
                tag=body.tag,
                instrument_ids=body.instrument_ids,
                actor_user_id=actor.user_id,
                firm_id=actor.firm_id,
            )
    except ValueError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Invalid tag",
            detail=str(exc),
        )
    return BulkTagOperationResponse(
        affected_count=counts["affected"],
        skipped_count=counts["skipped"],
        failed_count=counts["failed"],
        operation="bulk_add",
    )


@router.post(
    "/instruments/tags/bulk-remove",
    response_model=BulkTagOperationResponse,
)
async def bulk_remove_tag_endpoint(
    body: BulkTagRemoveRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Remove one tag from many instruments (chunk 4.2)."""
    try:
        async with db.begin():
            counts = await service.bulk_remove_tag(
                db,
                tag=body.tag,
                instrument_ids=body.instrument_ids,
                actor_user_id=actor.user_id,
                firm_id=actor.firm_id,
            )
    except ValueError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Invalid tag",
            detail=str(exc),
        )
    return BulkTagOperationResponse(
        affected_count=counts["affected"],
        skipped_count=counts["skipped"],
        failed_count=counts["failed"],
        operation="bulk_remove",
    )


@router.post(
    "/instruments/tags/bulk-replace",
    response_model=BulkTagOperationResponse,
)
async def bulk_replace_tags_endpoint(
    body: BulkTagReplaceRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Overwrite the tag set of many instruments with the same value
    (chunk 4.2)."""
    try:
        async with db.begin():
            counts = await service.bulk_replace_tags(
                db,
                tags=body.tags,
                instrument_ids=body.instrument_ids,
                actor_user_id=actor.user_id,
                firm_id=actor.firm_id,
            )
    except ValueError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Invalid tag set",
            detail=str(exc),
        )
    return BulkTagOperationResponse(
        affected_count=counts["affected"],
        skipped_count=counts["skipped"],
        failed_count=counts["failed"],
        operation="bulk_replace",
    )


@router.post(
    "/instruments/tags/reset-to-default",
    response_model=BulkTagOperationResponse,
)
async def reset_tags_to_default_endpoint(
    body: TagResetRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Reset tags for the given instrument IDs (or all, when empty) to
    the FR 13.3 default rules. Used by the chunk 4.2 admin UI's "reset
    to default" affordance with explicit confirmation."""
    instrument_ids: list[str] | None = body.instrument_ids or None
    async with db.begin():
        counts = await service.reset_tags_to_default(
            db,
            instrument_ids=instrument_ids,
            actor_user_id=actor.user_id,
            firm_id=actor.firm_id,
        )
    return BulkTagOperationResponse(
        affected_count=counts["affected"],
        skipped_count=counts["skipped"],
        failed_count=counts["failed"],
        operation="reset_to_default",
    )


# ---------------------------------------------------------------------------
# Chunk 4.3: preferred portfolio entry write endpoints (CIO-only)
# ---------------------------------------------------------------------------


def _entry_to_read_with_db_lookup(
    entry,  # PreferredPortfolioEntry
    *,
    instrument,  # Instrument
) -> PreferredPortfolioEntryRead:
    return _entry_to_read(entry, instrument=instrument)


@router.post(
    "/preferred",
    response_model=PreferredPortfolioEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_preferred_entry_endpoint(
    body: CreatePreferredEntryRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Create a new preferred portfolio entry (chunk 4.3)."""
    async with db.begin():
        inst = await service.get_instrument(db, instrument_id=body.instrument_id)
        if inst is None:
            return problem_response(
                status=status.HTTP_404_NOT_FOUND,
                title="Instrument not found",
                detail=f"No instrument with id={body.instrument_id!r}",
            )
        existing = await service.find_entry_by_natural_key(
            db,
            risk_profile=body.risk_profile,
            horizon=body.horizon,
            instrument_id=body.instrument_id,
        )
        if existing is not None:
            return problem_response(
                status=status.HTTP_409_CONFLICT,
                title="Entry already exists",
                detail=(
                    f"An entry for {body.instrument_id!r} in "
                    f"({body.risk_profile}, {body.horizon}) already exists."
                ),
            )
        entry = await service.create_preferred_entry(
            db,
            risk_profile=body.risk_profile,
            horizon=body.horizon,
            instrument_id=body.instrument_id,
            position_role=body.position_role,
            rank_within_role=body.rank_within_role,
            notes=body.notes,
            actor_user_id=actor.user_id,
            firm_id=actor.firm_id,
        )
    return _entry_to_read(entry, instrument=inst)


@router.put(
    "/preferred/{entry_id}",
    response_model=PreferredPortfolioEntryRead,
)
async def update_preferred_entry_endpoint(
    entry_id: str,
    body: UpdatePreferredEntryRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Update an entry's role / rank / notes (chunk 4.3)."""
    async with db.begin():
        entry = await service.get_entry(db, entry_id=entry_id)
        if entry is None:
            return problem_response(
                status=status.HTTP_404_NOT_FOUND,
                title="Entry not found",
                detail=f"No preferred portfolio entry with id={entry_id!r}",
            )
        updated = await service.modify_preferred_entry(
            db,
            entry=entry,
            position_role=body.position_role,
            rank_within_role=body.rank_within_role,
            notes=body.notes,
            actor_user_id=actor.user_id,
            firm_id=actor.firm_id,
        )
        inst = await service.get_instrument(db, instrument_id=updated.instrument_id)
    if inst is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Instrument missing",
            detail=(
                f"Entry references instrument {updated.instrument_id!r} "
                "which is not in the catalogue."
            ),
        )
    return _entry_to_read(updated, instrument=inst)


@router.delete(
    "/preferred/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_preferred_entry_endpoint(
    entry_id: str,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Remove a preferred portfolio entry (chunk 4.3)."""
    async with db.begin():
        entry = await service.get_entry(db, entry_id=entry_id)
        if entry is None:
            return problem_response(
                status=status.HTTP_404_NOT_FOUND,
                title="Entry not found",
                detail=f"No preferred portfolio entry with id={entry_id!r}",
            )
        await service.delete_preferred_entry(
            db,
            entry=entry,
            actor_user_id=actor.user_id,
            firm_id=actor.firm_id,
        )
    return None


@router.post(
    "/preferred/{risk_profile}/{horizon}/reorder",
    response_model=CellOperationResponse,
)
async def reorder_cell_endpoint(
    risk_profile: str,
    horizon: str,
    body: CellReorderRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Atomic role + rank update for every entry in a cell (chunk 4.3)."""
    if risk_profile not in cells.RISK_PROFILES or horizon not in cells.HORIZONS:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Cell not found",
            detail=f"No cell at ({risk_profile}, {horizon})",
        )
    async with db.begin():
        counts = await service.reorder_cell(
            db,
            risk_profile=risk_profile,
            horizon=horizon,
            items=[item.model_dump() for item in body.items],
            actor_user_id=actor.user_id,
            firm_id=actor.firm_id,
        )
    return CellOperationResponse(
        risk_profile=risk_profile,
        horizon=horizon,
        affected_count=counts["affected"],
        skipped_count=counts["skipped"],
        operation="reorder",
    )


@router.post(
    "/preferred/{risk_profile}/{horizon}/duplicate-from",
    response_model=CellOperationResponse,
)
async def duplicate_cell_endpoint(
    risk_profile: str,
    horizon: str,
    body: CellDuplicateRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Duplicate entries from a source cell into the target cell (chunk 4.3)."""
    if risk_profile not in cells.RISK_PROFILES or horizon not in cells.HORIZONS:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Cell not found",
            detail=f"No target cell at ({risk_profile}, {horizon})",
        )
    if (
        body.source_risk_profile not in cells.RISK_PROFILES
        or body.source_horizon not in cells.HORIZONS
    ):
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Invalid source cell",
            detail=(
                f"({body.source_risk_profile}, {body.source_horizon}) is not "
                "a valid cell."
            ),
        )
    if (body.source_risk_profile, body.source_horizon) == (risk_profile, horizon):
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Source equals target",
            detail="Source and target cells must differ.",
        )
    async with db.begin():
        counts = await service.duplicate_cell(
            db,
            target_risk_profile=risk_profile,
            target_horizon=horizon,
            source_risk_profile=body.source_risk_profile,
            source_horizon=body.source_horizon,
            actor_user_id=actor.user_id,
            skip_existing=body.skip_existing,
            only_matching_tags=body.only_matching_tags,
            firm_id=actor.firm_id,
        )
    return CellOperationResponse(
        risk_profile=risk_profile,
        horizon=horizon,
        affected_count=counts["affected"],
        skipped_count=counts["skipped"],
        operation="duplicate",
    )


@router.post(
    "/preferred/{risk_profile}/{horizon}/reset-to-default",
    response_model=CellOperationResponse,
)
async def reset_cell_endpoint(
    risk_profile: str,
    horizon: str,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Reset one cell to the default fixture content (chunk 4.3)."""
    from artha.config import settings

    if risk_profile not in cells.RISK_PROFILES or horizon not in cells.HORIZONS:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Cell not found",
            detail=f"No cell at ({risk_profile}, {horizon})",
        )
    async with db.begin():
        counts = await service.reset_cell_to_default(
            db,
            risk_profile=risk_profile,
            horizon=horizon,
            fixture_path=settings.samriddhi_default_model_portfolio_path,
            actor_user_id=actor.user_id,
            firm_id=actor.firm_id,
        )
    return CellOperationResponse(
        risk_profile=risk_profile,
        horizon=horizon,
        affected_count=counts["loaded"],
        skipped_count=counts["deleted"],
        operation="reset_cell",
    )


@router.post(
    "/preferred/reset-to-default",
    response_model=CellOperationResponse,
)
async def reset_all_preferred_endpoint(
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MODEL_PORTFOLIO_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Wipe + reload entire preferred portfolio from the default fixture
    (chunk 4.3 admin tools, requires strong confirmation in the UI)."""
    from artha.config import settings

    async with db.begin():
        counts = await service.reset_all_preferred_to_default(
            db,
            fixture_path=settings.samriddhi_default_model_portfolio_path,
            actor_user_id=actor.user_id,
            firm_id=actor.firm_id,
        )
    return CellOperationResponse(
        risk_profile="aggressive",  # placeholder — operation is firm-wide
        horizon="long_term",
        affected_count=counts["loaded"],
        skipped_count=counts["deleted"],
        operation="reset_all",
    )
