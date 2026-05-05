"""Snapshot admin router — chunk 3.4 audit-role surface."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.d0.snapshot import service
from artha.api_v2.d0.snapshot.schemas import (
    SnapshotCreateRequest,
    SnapshotDetail,
    SnapshotDiffResponse,
    SnapshotListResponse,
    SnapshotSummary,
    SnapshotVerifyResponse,
)
from artha.api_v2.d0.staging import canonical_json_bytes
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/admin", tags=["d0_admin_snapshots"])


def _to_summary(row) -> SnapshotSummary:
    return SnapshotSummary(
        snapshot_id=row.snapshot_id,
        created_at=row.created_at,
        created_by=row.created_by,
        description=row.description,
        trigger_type=row.trigger_type,
        entity_counts=row.entity_counts or {},
        content_hash=row.content_hash,
        serialised_payload_size_bytes=row.serialised_payload_size_bytes,
        associated_adapter_run_ids=row.associated_adapter_run_ids or [],
        verified_at=row.verified_at,
        verified_status=row.verified_status,
        schema_version=row.schema_version,
    )


def _to_detail(row) -> SnapshotDetail:
    return SnapshotDetail(
        snapshot_id=row.snapshot_id,
        created_at=row.created_at,
        created_by=row.created_by,
        description=row.description,
        trigger_type=row.trigger_type,
        trigger_context=row.trigger_context or {},
        entity_counts=row.entity_counts or {},
        content_hash=row.content_hash,
        serialised_payload=row.serialised_payload or {},
        serialised_payload_size_bytes=row.serialised_payload_size_bytes,
        source_metadata=row.source_metadata or {},
        associated_adapter_run_ids=row.associated_adapter_run_ids or [],
        verified_at=row.verified_at,
        verified_status=row.verified_status,
        schema_version=row.schema_version,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "/snapshots",
    response_model=SnapshotSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_snapshot_endpoint(
    body: SnapshotCreateRequest,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_WRITE))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    async with db.begin():
        row = await service.create_snapshot(
            db,
            description=body.description,
            trigger_type=body.trigger_type,
            trigger_context=body.trigger_context,
            created_by=actor.user_id,
            firm_id=actor.firm_id,
        )
    return _to_summary(row)


# ---------------------------------------------------------------------------
# List + detail
# ---------------------------------------------------------------------------


@router.get("/snapshots", response_model=SnapshotListResponse)
async def list_snapshots_endpoint(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    trigger_type: str | None = None,
    verified_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    rows, total = await service.list_snapshots(
        db,
        trigger_type=trigger_type,
        verified_status=verified_status,
        limit=min(max(1, limit), 500),
        offset=max(0, offset),
    )
    return SnapshotListResponse(
        snapshots=[_to_summary(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotDetail)
async def get_snapshot_endpoint(
    snapshot_id: str,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    row = await service.get_snapshot(
        db, snapshot_id=snapshot_id, firm_id=actor.firm_id
    )
    if row is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Snapshot not found",
            detail=f"No snapshot with id={snapshot_id!r}",
        )
    return _to_detail(row)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


@router.post(
    "/snapshots/{snapshot_id}/verify",
    response_model=SnapshotVerifyResponse,
)
async def verify_snapshot_endpoint(
    snapshot_id: str,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_WRITE))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        async with db.begin():
            row = await service.verify_snapshot(
                db, snapshot_id=snapshot_id, firm_id=actor.firm_id
            )
    except KeyError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Snapshot not found",
            detail=str(exc),
        )

    canonical = canonical_json_bytes(row.serialised_payload)
    recomputed = hashlib.sha256(canonical).hexdigest()
    return SnapshotVerifyResponse(
        snapshot_id=row.snapshot_id,
        stored_hash=row.content_hash,
        recomputed_hash=recomputed,
        verified_status=row.verified_status,
        verified_at=row.verified_at,
    )


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


@router.get("/snapshots-diff", response_model=SnapshotDiffResponse)
async def diff_snapshots_endpoint(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    a: str,
    b: str,
):
    try:
        async with db.begin():
            result = await service.diff_snapshots(
                db,
                snapshot_a_id=a,
                snapshot_b_id=b,
                firm_id=actor.firm_id,
            )
    except KeyError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Snapshot not found",
            detail=str(exc),
        )
    return SnapshotDiffResponse(**result)
