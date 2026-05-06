"""Snapshot pinner — bridges a case to cluster 3's Snapshot machinery.

FR Entry 20.1 §5.2 step 2-5 in code. The chunk 5.3 case creator calls
:func:`pin_snapshot_for_case` after inserting the case row in
``opening`` status; this captures a snapshot of the canonical-entity
universe via cluster 3's snapshot service and persists the resulting
``snapshot_bundle_id`` on the case row (immutability enforced by the
repository).

Cluster 3 already has the SnapshotAssembler implementation
(``artha.api_v2.d0.snapshot.service.create_snapshot``). We wrap it so
case-creation callers don't have to know the cluster-3 internals; the
wrapper:

- chooses a deterministic ``trigger_type='case_creation'`` value
- forwards ``trigger_context`` containing case identity + case-mode
  metadata so audit replay can correlate snapshots with cases
- propagates the ``is_seed_data`` flag so seeded-case snapshots get
  tagged for the seed-reset path
- emits ``case_creation_snapshot_failed`` T1 event on failure (chunk
  5.3 transitions the case to ``failed`` if this raises; we don't do
  the transition here to keep the pinner's responsibility narrow).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.cases import event_names, repository
from artha.api_v2.cases.models import Case
from artha.api_v2.d0.snapshot import service as snapshot_service
from artha.api_v2.observability.t1 import emit_event


class SnapshotPinningError(RuntimeError):
    """Raised when SnapshotAssembler fails to produce a bundle.

    Caller (chunk 5.3 case creator) is responsible for transitioning
    the case to ``failed`` + closed_reason='failed' after catching this.
    """


@dataclass(frozen=True)
class SnapshotPinResult:
    snapshot_bundle_id: str
    content_hash: str
    entity_counts: dict[str, int]


async def pin_snapshot_for_case(
    db: AsyncSession,
    *,
    case: Case,
    actor_user_id: str,
    firm_id: str | None = None,
) -> SnapshotPinResult:
    """Capture a snapshot bundle and pin it to the case.

    Wraps ``snapshot_service.create_snapshot`` then calls
    ``repository.update_snapshot_bundle``. Idempotent — if the case
    already has a non-null ``snapshot_bundle_id`` we return its current
    pin without re-calling the assembler (FR 20.1 §4.1 immutability).
    """
    if case.snapshot_bundle_id is not None:
        # Idempotent: a fresh fetch would re-confirm the same value.
        # Caller's intent is "the case is pinned"; report the current
        # pin without reassembling.
        return SnapshotPinResult(
            snapshot_bundle_id=case.snapshot_bundle_id,
            content_hash="<already_pinned>",
            entity_counts={},
        )

    description = (
        f"case_creation snapshot — case {case.case_id} ({case.case_mode})"
    )
    trigger_context = {
        "case_id": case.case_id,
        "investor_id": case.investor_id,
        "case_mode": case.case_mode,
        "case_intent": case.case_intent,
        "is_seed_data": case.is_seed_data,
    }

    try:
        snapshot = await snapshot_service.create_snapshot(
            db,
            description=description,
            trigger_type="case_creation",
            trigger_context=trigger_context,
            created_by=actor_user_id,
            firm_id=firm_id,
        )
    except Exception as exc:  # noqa: BLE001 — wrap + re-raise as our error
        await emit_event(
            db,
            event_name=event_names.CASE_CREATION_SNAPSHOT_FAILED,
            payload={
                "case_id": case.case_id,
                "error": str(exc),
            },
            firm_id=firm_id,
        )
        raise SnapshotPinningError(
            f"SnapshotAssembler failed for case {case.case_id!r}: {exc}"
        ) from exc

    # Tag the snapshot row with is_seed_data so the cluster 5.6 reset
    # path can collect snapshots associated with seeded cases.
    if case.is_seed_data:
        snapshot.is_seed_data = True
        await db.flush()

    await repository.update_snapshot_bundle(
        db,
        case=case,
        snapshot_bundle_id=snapshot.snapshot_id,
        firm_id=firm_id,
    )

    return SnapshotPinResult(
        snapshot_bundle_id=snapshot.snapshot_id,
        content_hash=snapshot.content_hash,
        entity_counts=dict(snapshot.entity_counts or {}),
    )


__all__ = [
    "SnapshotPinResult",
    "SnapshotPinningError",
    "pin_snapshot_for_case",
]
