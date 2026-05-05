"""D0 admin REST router — chunk 3.1 + 3.4 audit-role surface.

Chunk 3.1 endpoints (skeleton):

- ``GET    /api/v2/admin/adapters``                       — list registered
- ``GET    /api/v2/admin/adapters/{source_identifier}``   — adapter detail
- ``POST   /api/v2/admin/adapters/{source_identifier}/run`` — trigger run
- ``GET    /api/v2/admin/staging``                        — staging query
- ``GET    /api/v2/admin/staging/{staging_record_id}``    — staging detail
- ``GET    /api/v2/admin/data-freshness``                 — freshness table

Chunk 3.4 will add: snapshot create/list/detail/verify/diff/browse
endpoints + the canonical-entity browser endpoints.

Permission gates: read endpoints require ``d0:admin:read``; write
(adapter run) requires ``d0:admin:write``. Cluster 3 grants both to
the audit role; CIO + compliance get read only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.d0 import freshness_service, registry, staging
from artha.api_v2.d0.adapter_base import D0Adapter
from artha.api_v2.d0.event_names import (
    ADAPTER_RUN_COMPLETED,
    ADAPTER_RUN_FAILED,
    ADAPTER_RUN_STARTED,
)
from artha.api_v2.d0.schemas import (
    AdapterListResponse,
    AdapterRunRequest,
    AdapterRunResponse,
    AdapterStatusRead,
    FreshnessResponse,
    StagingRecordDetail,
    StagingRecordRead,
    StagingRecordsListResponse,
)
from artha.api_v2.observability.t1 import emit_event
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/admin", tags=["d0_admin"])


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


@router.get("/adapters", response_model=AdapterListResponse)
async def list_adapters(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
):
    """List all registered adapters with their health status."""
    rows: list[AdapterStatusRead] = []
    for adapter in registry.list_adapters():
        health = await adapter.health_check()
        rows.append(
            AdapterStatusRead(
                source_identifier=adapter.source_identifier,
                supported_entity_types=adapter.supported_entity_types,
                healthy=health.healthy,
                last_successful_fetch_at=health.last_successful_fetch_at,
                last_error_message=health.error_message,
            )
        )
    return AdapterListResponse(adapters=rows)


@router.get(
    "/adapters/{source_identifier}", response_model=AdapterStatusRead
)
async def get_adapter_detail(
    source_identifier: str,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
):
    """One adapter's status detail."""
    try:
        adapter: D0Adapter = registry.get_adapter(source_identifier)
    except registry.AdapterNotRegisteredError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Adapter not registered",
            detail=str(exc),
        )
    health = await adapter.health_check()
    return AdapterStatusRead(
        source_identifier=adapter.source_identifier,
        supported_entity_types=adapter.supported_entity_types,
        healthy=health.healthy,
        last_successful_fetch_at=health.last_successful_fetch_at,
        last_error_message=health.error_message,
    )


@router.post(
    "/adapters/{source_identifier}/run",
    response_model=AdapterRunResponse,
    status_code=status.HTTP_200_OK,
)
async def run_adapter(
    source_identifier: str,
    body: AdapterRunRequest,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_WRITE))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Trigger an adapter run.

    ``mode``:
    - ``full`` (default): fetch + write canonical entities atomically.
    - ``validation``: fetch + validate only; no canonical entity writes.
    """
    try:
        adapter: D0Adapter = registry.get_adapter(source_identifier)
    except registry.AdapterNotRegisteredError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Adapter not registered",
            detail=str(exc),
        )

    async with db.begin():
        await emit_event(
            db,
            event_name=ADAPTER_RUN_STARTED,
            payload={
                "source_identifier": source_identifier,
                "mode": body.mode,
                "triggered_by": actor.user_id,
            },
            firm_id=actor.firm_id,
        )

    try:
        async with db.begin():
            result = await adapter.run(db, mode=body.mode)
    except Exception as exc:
        async with db.begin():
            await emit_event(
                db,
                event_name=ADAPTER_RUN_FAILED,
                payload={
                    "source_identifier": source_identifier,
                    "mode": body.mode,
                    "error": str(exc),
                },
                firm_id=actor.firm_id,
            )
        return problem_response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Adapter run failed",
            detail=str(exc),
        )

    async with db.begin():
        await emit_event(
            db,
            event_name=ADAPTER_RUN_COMPLETED,
            payload={
                "source_identifier": source_identifier,
                "run_id": result.run_id,
                "status": result.status,
                "staging_records_created": result.staging_records_created,
                "canonical_entities_created": result.canonical_entities_created,
                "canonical_entities_updated": result.canonical_entities_updated,
                "error_count": len(result.errors),
            },
            firm_id=actor.firm_id,
        )

    return AdapterRunResponse(
        run_id=result.run_id,
        status=result.status,
        started_at=result.started_at,
        completed_at=result.completed_at,
        staging_records_created=result.staging_records_created,
        canonical_entities_created=result.canonical_entities_created,
        canonical_entities_updated=result.canonical_entities_updated,
        error_count=len(result.errors),
        metadata=result.metadata,
    )


# ---------------------------------------------------------------------------
# Staging records
# ---------------------------------------------------------------------------


@router.get("/staging", response_model=StagingRecordsListResponse)
async def list_staging(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    source: str | None = None,
    adapter_run_id: str | None = None,
    limit: int = 100,
):
    """Query staging records by source / adapter_run_id."""
    rows = await staging.list_staging_records(
        db,
        source_identifier=source,
        adapter_run_id=adapter_run_id,
        limit=min(max(1, limit), 500),
    )
    return StagingRecordsListResponse(
        records=[
            StagingRecordRead(
                staging_record_id=r.staging_record_id,
                source_identifier=r.source_identifier,
                source_subkey=r.source_subkey,
                adapter_run_id=r.adapter_run_id,
                raw_content_format=r.raw_content_format,
                raw_content_hash=r.raw_content_hash,
                raw_content_size_bytes=r.raw_content_size_bytes,
                fetched_at=r.fetched_at,
                source_metadata=r.source_metadata,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


@router.get(
    "/staging/{staging_record_id}", response_model=StagingRecordDetail
)
async def get_staging(
    staging_record_id: str,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """One staging record's full detail (including raw_content)."""
    row = await staging.get_staging_record(
        db, staging_record_id=staging_record_id
    )
    if row is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Staging record not found",
            detail=f"No staging record with id={staging_record_id!r}",
        )
    return StagingRecordDetail(
        staging_record_id=row.staging_record_id,
        source_identifier=row.source_identifier,
        source_subkey=row.source_subkey,
        adapter_run_id=row.adapter_run_id,
        raw_content_format=row.raw_content_format,
        raw_content_hash=row.raw_content_hash,
        raw_content_size_bytes=row.raw_content_size_bytes,
        fetched_at=row.fetched_at,
        source_metadata=row.source_metadata,
        created_at=row.created_at,
        raw_content=row.raw_content,
    )


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


@router.get("/data-freshness", response_model=FreshnessResponse)
async def get_data_freshness(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Freshness table for the audit-role admin UI (FR 10.5 §4.1)."""
    rows = await freshness_service.build_freshness_rows(db)
    return FreshnessResponse(rows=rows)
