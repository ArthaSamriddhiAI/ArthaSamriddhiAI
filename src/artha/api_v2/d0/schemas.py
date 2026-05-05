"""Pydantic shapes for the D0 admin surface (chunks 3.1 + 3.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AdapterStatusRead(BaseModel):
    """Read shape for ``GET /api/v2/admin/adapters`` rows."""

    model_config = ConfigDict(extra="forbid")

    source_identifier: str
    supported_entity_types: list[str]
    healthy: bool
    last_successful_fetch_at: datetime | None
    last_error_message: str | None


class AdapterListResponse(BaseModel):
    adapters: list[AdapterStatusRead]


class AdapterRunRequest(BaseModel):
    """``POST /api/v2/admin/adapters/{source}/run`` body."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "full"  # "full" | "validation"


class AdapterRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    started_at: datetime
    completed_at: datetime
    staging_records_created: int
    canonical_entities_created: dict[str, int]
    canonical_entities_updated: dict[str, int]
    error_count: int
    metadata: dict[str, Any]


class StagingRecordRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staging_record_id: str
    source_identifier: str
    source_subkey: str | None
    adapter_run_id: str
    raw_content_format: str
    raw_content_hash: str
    raw_content_size_bytes: int
    fetched_at: datetime
    source_metadata: dict[str, Any]
    created_at: datetime


class StagingRecordsListResponse(BaseModel):
    records: list[StagingRecordRead]


class StagingRecordDetail(StagingRecordRead):
    """Detail view includes the raw_content payload."""

    raw_content: Any


# ---------------------------------------------------------------------------
# Freshness (chunk 3.1 + 3.4)
# ---------------------------------------------------------------------------


class FreshnessRow(BaseModel):
    """One row of the ``GET /api/v2/admin/data-freshness`` table."""

    model_config = ConfigDict(extra="forbid")

    entity_table: str
    record_count: int
    latest_last_modified_at: datetime | None
    threshold_seconds: int
    threshold_human: str
    freshness_status: str  # fresh | stale | very_stale
    age_seconds: int


class FreshnessResponse(BaseModel):
    rows: list[FreshnessRow]
