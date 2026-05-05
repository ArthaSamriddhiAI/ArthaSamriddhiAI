"""Pydantic shapes for the snapshot admin surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SnapshotSummary(BaseModel):
    """Lightweight read shape for the list endpoint (no payload)."""

    snapshot_id: str
    created_at: datetime
    created_by: str
    description: str | None
    trigger_type: str
    entity_counts: dict[str, int]
    content_hash: str
    serialised_payload_size_bytes: int
    associated_adapter_run_ids: list[str]
    verified_at: datetime | None
    verified_status: str
    schema_version: int


class SnapshotDetail(SnapshotSummary):
    """Full read shape — includes the serialised_payload."""

    trigger_context: dict[str, Any]
    source_metadata: dict[str, Any]
    serialised_payload: dict[str, Any]


class SnapshotListResponse(BaseModel):
    snapshots: list[SnapshotSummary]
    total: int
    limit: int
    offset: int


class SnapshotCreateRequest(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    trigger_type: str = Field(default="manual", max_length=40)
    trigger_context: dict[str, Any] = Field(default_factory=dict)


class SnapshotVerifyResponse(BaseModel):
    snapshot_id: str
    stored_hash: str
    recomputed_hash: str
    verified_status: str
    verified_at: datetime | None


class SnapshotDiffResponse(BaseModel):
    snapshot_a_id: str
    snapshot_b_id: str
    summary: dict[str, dict[str, int]]
    per_table: dict[str, dict[str, Any]]
