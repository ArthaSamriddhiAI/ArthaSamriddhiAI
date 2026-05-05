"""Staging-record helpers (FR Entry 10.2 §3).

Pure DB helpers used by adapters to write staging records and by the
admin router to query them. The hash + size computation is centralised
here so every adapter stamps content-hashed records identically.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.d0.event_names import STAGING_RECORD_CREATED
from artha.api_v2.d0.models import StagingRecord
from artha.api_v2.observability.t1 import emit_event


def canonical_json_bytes(value: Any) -> bytes:
    """Produce deterministic UTF-8 bytes for hashing.

    Matches FR 10.2 §3.2: sorted keys, no whitespace beyond what
    ``json.dumps`` produces by default, ``ensure_ascii=False`` so non-ASCII
    content keeps its native bytes (cheaper hashing).
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_content_hash(value: Any) -> str:
    """SHA-256 hex digest of the canonical-JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


async def record_staging(
    db: AsyncSession,
    *,
    source_identifier: str,
    adapter_run_id: str,
    raw_content: Any,
    raw_content_format: str = "json",
    source_subkey: str | None = None,
    source_metadata: dict[str, Any] | None = None,
    fetched_at: datetime | None = None,
    firm_id: str | None = None,
) -> StagingRecord:
    """Insert one staging record + emit ``staging_record_created`` T1 event.

    Returns the created row so callers (typically the JSONFixtureAdapter)
    can attach the staging_record_id to subsequent canonical entity rows
    via their provenance fields.
    """
    canonical = canonical_json_bytes(raw_content)
    now = datetime.now(timezone.utc)
    row = StagingRecord(
        staging_record_id=str(ULID()),
        source_identifier=source_identifier,
        source_subkey=source_subkey,
        adapter_run_id=adapter_run_id,
        raw_content=raw_content,
        raw_content_format=raw_content_format,
        raw_content_hash=hashlib.sha256(canonical).hexdigest(),
        raw_content_size_bytes=len(canonical),
        fetched_at=fetched_at or now,
        source_metadata=source_metadata or {},
        created_at=now,
        schema_version=1,
    )
    db.add(row)
    await db.flush()

    await emit_event(
        db,
        event_name=STAGING_RECORD_CREATED,
        payload={
            "staging_record_id": row.staging_record_id,
            "source_identifier": source_identifier,
            "adapter_run_id": adapter_run_id,
            "raw_content_hash": row.raw_content_hash,
            "raw_content_size_bytes": row.raw_content_size_bytes,
        },
        firm_id=firm_id,
    )
    return row


async def list_staging_records(
    db: AsyncSession,
    *,
    source_identifier: str | None = None,
    adapter_run_id: str | None = None,
    limit: int = 100,
) -> list[StagingRecord]:
    """List staging records filtered by source_identifier and/or run id.

    Records returned newest-first (by ``fetched_at``).
    """
    stmt = select(StagingRecord).order_by(StagingRecord.fetched_at.desc())
    if source_identifier is not None:
        stmt = stmt.where(StagingRecord.source_identifier == source_identifier)
    if adapter_run_id is not None:
        stmt = stmt.where(StagingRecord.adapter_run_id == adapter_run_id)
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars())


async def get_staging_record(
    db: AsyncSession, *, staging_record_id: str
) -> StagingRecord | None:
    result = await db.execute(
        select(StagingRecord).where(
            StagingRecord.staging_record_id == staging_record_id
        )
    )
    return result.scalar_one_or_none()
