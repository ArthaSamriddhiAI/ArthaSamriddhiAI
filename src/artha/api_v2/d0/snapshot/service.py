"""Snapshot service — create + list + verify + diff helpers.

Cluster 3 uses Approach A (FR 10.4 §2.3): the snapshot's
``serialised_payload`` carries the full state of every canonical entity
table at snapshot time. Bit-identical replay is straightforward — the
verifier re-serialises the payload through the same canonical-JSON path
and recomputes the hash. Drift between hashes is fatal.

Snapshot scope: every canonical entity table currently registered with
the freshness service. As clusters add more entities (Holding,
Portfolio, etc.) those tables get pulled in automatically because
``_TABLE_TO_MODEL`` in :mod:`artha.api_v2.d0.freshness_service` is the
single source of truth.

Diff strategy: per-entity-table by primary key. A row exists in A but
not B → ``removed``; B but not A → ``added``; same key but different
content → ``changed`` (carrying both sides). The diff is a structured
dict, not a free-form string, so the admin UI can render any shape.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.d0 import freshness_service
from artha.api_v2.d0.event_names import (
    SNAPSHOT_CREATED,
    SNAPSHOT_DIFF_COMPUTED,
    SNAPSHOT_RETRIEVED,
    SNAPSHOT_VERIFICATION_FAILED,
    SNAPSHOT_VERIFICATION_RUN,
)
from artha.api_v2.d0.models import Snapshot
from artha.api_v2.d0.staging import canonical_json_bytes
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


async def _capture_table_rows(
    db: AsyncSession, *, table_name: str, model: Any
) -> list[dict[str, Any]]:
    """Read every row of one canonical-entity table as a dict.

    Sorted by primary key when the model exposes a primary-key column —
    this keeps the canonical-JSON bytes deterministic across runs of the
    same DB state, which is what makes content-hash verification work.
    """
    pk_col = _primary_key(model)
    stmt = select(model)
    if pk_col is not None:
        stmt = stmt.order_by(pk_col.asc())
    rows = list((await db.execute(stmt)).scalars())
    out: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {}
        for col in model.__table__.columns:
            value = getattr(row, col.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif hasattr(value, "isoformat"):  # date / time
                value = value.isoformat()
            record[col.name] = value
        out.append(record)
    return out


def _primary_key(model: Any) -> Any | None:
    pks = list(model.__table__.primary_key.columns)
    return pks[0] if pks else None


async def create_snapshot(
    db: AsyncSession,
    *,
    description: str | None = None,
    trigger_type: str = "manual",
    trigger_context: dict[str, Any] | None = None,
    created_by: str,
    firm_id: str | None = None,
) -> Snapshot:
    """Capture every canonical-entity table into one Snapshot row."""
    table_to_model = freshness_service._TABLE_TO_MODEL  # noqa: SLF001
    payload: dict[str, Any] = {}
    counts: dict[str, int] = {}
    associated_runs: set[str] = set()
    for table_name, model in table_to_model.items():
        rows = await _capture_table_rows(
            db, table_name=table_name, model=model
        )
        payload[table_name] = rows
        counts[table_name] = len(rows)
        for row in rows:
            run_id = row.get("adapter_run_id")
            if run_id:
                associated_runs.add(str(run_id))

    canonical = canonical_json_bytes(payload)
    content_hash = hashlib.sha256(canonical).hexdigest()
    now = datetime.now(timezone.utc)

    row = Snapshot(
        snapshot_id=str(ULID()),
        created_at=now,
        created_by=created_by,
        description=description,
        trigger_type=trigger_type,
        trigger_context=trigger_context or {},
        entity_counts=counts,
        content_hash=content_hash,
        serialised_payload=payload,
        serialised_payload_size_bytes=len(canonical),
        source_metadata={},
        associated_adapter_run_ids=sorted(associated_runs),
        verified_at=None,
        verified_status="never_verified",
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    await emit_event(
        db,
        event_name=SNAPSHOT_CREATED,
        payload={
            "snapshot_id": row.snapshot_id,
            "trigger_type": trigger_type,
            "entity_counts": counts,
            "content_hash": content_hash,
            "size_bytes": row.serialised_payload_size_bytes,
        },
        firm_id=firm_id,
    )
    return row


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def list_snapshots(
    db: AsyncSession,
    *,
    trigger_type: str | None = None,
    verified_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Snapshot], int]:
    base = select(Snapshot)
    count_base = select(func.count()).select_from(Snapshot)
    filters = []
    if trigger_type is not None:
        filters.append(Snapshot.trigger_type == trigger_type)
    if verified_status is not None:
        filters.append(Snapshot.verified_status == verified_status)
    if filters:
        base = base.where(*filters)
        count_base = count_base.where(*filters)
    base = (
        base.order_by(Snapshot.created_at.desc()).limit(limit).offset(offset)
    )
    rows = list((await db.execute(base)).scalars())
    total = (await db.execute(count_base)).scalar_one() or 0
    return rows, int(total)


async def get_snapshot(
    db: AsyncSession,
    *,
    snapshot_id: str,
    emit_retrieval_event: bool = True,
    firm_id: str | None = None,
) -> Snapshot | None:
    row = (
        await db.execute(
            select(Snapshot).where(Snapshot.snapshot_id == snapshot_id)
        )
    ).scalar_one_or_none()
    if row is not None and emit_retrieval_event:
        await emit_event(
            db,
            event_name=SNAPSHOT_RETRIEVED,
            payload={"snapshot_id": snapshot_id},
            firm_id=firm_id,
        )
    return row


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


async def verify_snapshot(
    db: AsyncSession,
    *,
    snapshot_id: str,
    firm_id: str | None = None,
) -> Snapshot:
    """Re-serialise the payload + compare hash.

    Updates the snapshot row's ``verified_status`` + ``verified_at`` and
    emits the appropriate T1 event. Raises :class:`KeyError` when the
    snapshot doesn't exist.
    """
    row = await get_snapshot(
        db,
        snapshot_id=snapshot_id,
        emit_retrieval_event=False,
    )
    if row is None:
        raise KeyError(f"Snapshot {snapshot_id!r} not found")

    canonical = canonical_json_bytes(row.serialised_payload)
    recomputed = hashlib.sha256(canonical).hexdigest()
    now = datetime.now(timezone.utc)

    await emit_event(
        db,
        event_name=SNAPSHOT_VERIFICATION_RUN,
        payload={
            "snapshot_id": snapshot_id,
            "stored_hash": row.content_hash,
            "recomputed_hash": recomputed,
        },
        firm_id=firm_id,
    )

    if recomputed != row.content_hash:
        row.verified_status = "verification_failed"
        row.verified_at = now
        await db.flush()
        await emit_event(
            db,
            event_name=SNAPSHOT_VERIFICATION_FAILED,
            payload={
                "snapshot_id": snapshot_id,
                "stored_hash": row.content_hash,
                "recomputed_hash": recomputed,
            },
            firm_id=firm_id,
        )
        return row

    row.verified_status = "verified"
    row.verified_at = now
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


_PK_BY_TABLE: dict[str, str] = {
    "instruments": "instrument_id",
    "macro_snapshots": "macro_snapshot_id",
    "industry_reports": "industry_report_id",
    "investors": "investor_id",
    "households": "household_id",
    "mandates": "mandate_id",
    "mandate_versions": "version_id",
}


def _diff_table(
    *, table_name: str, a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    pk = _PK_BY_TABLE.get(table_name)
    if pk is None:
        # Fallback: treat row-equality by canonical JSON without keying.
        return {
            "added": [r for r in b_rows if r not in a_rows],
            "removed": [r for r in a_rows if r not in b_rows],
            "changed": [],
        }
    a_idx = {r[pk]: r for r in a_rows if pk in r}
    b_idx = {r[pk]: r for r in b_rows if pk in r}
    added = [b_idx[k] for k in b_idx.keys() - a_idx.keys()]
    removed = [a_idx[k] for k in a_idx.keys() - b_idx.keys()]
    changed: list[dict[str, Any]] = []
    for k in a_idx.keys() & b_idx.keys():
        if a_idx[k] != b_idx[k]:
            changed.append(
                {"key": k, "before": a_idx[k], "after": b_idx[k]}
            )
    return {"added": added, "removed": removed, "changed": changed}


async def diff_snapshots(
    db: AsyncSession,
    *,
    snapshot_a_id: str,
    snapshot_b_id: str,
    firm_id: str | None = None,
) -> dict[str, Any]:
    """Compute a structured per-table diff between two snapshots."""
    a = await get_snapshot(
        db, snapshot_id=snapshot_a_id, emit_retrieval_event=False
    )
    b = await get_snapshot(
        db, snapshot_id=snapshot_b_id, emit_retrieval_event=False
    )
    if a is None:
        raise KeyError(f"Snapshot {snapshot_a_id!r} not found")
    if b is None:
        raise KeyError(f"Snapshot {snapshot_b_id!r} not found")

    a_payload: dict[str, list[dict[str, Any]]] = a.serialised_payload or {}
    b_payload: dict[str, list[dict[str, Any]]] = b.serialised_payload or {}
    all_tables = sorted(set(a_payload.keys()) | set(b_payload.keys()))

    per_table: dict[str, dict[str, Any]] = {}
    for table in all_tables:
        per_table[table] = _diff_table(
            table_name=table,
            a_rows=a_payload.get(table, []) or [],
            b_rows=b_payload.get(table, []) or [],
        )

    summary = {
        table: {
            "added": len(rows["added"]),
            "removed": len(rows["removed"]),
            "changed": len(rows["changed"]),
        }
        for table, rows in per_table.items()
    }

    await emit_event(
        db,
        event_name=SNAPSHOT_DIFF_COMPUTED,
        payload={
            "snapshot_a_id": snapshot_a_id,
            "snapshot_b_id": snapshot_b_id,
            "summary": summary,
        },
        firm_id=firm_id,
    )

    return {
        "snapshot_a_id": snapshot_a_id,
        "snapshot_b_id": snapshot_b_id,
        "summary": summary,
        "per_table": per_table,
    }
