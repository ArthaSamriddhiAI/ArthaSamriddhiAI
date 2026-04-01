"""Evidence snapshot — atomically freeze evidence at a decision boundary."""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.types import DecisionID, SnapshotID
from artha.evidence.models import EvidenceSnapshotRow
from artha.evidence.schemas import ArtifactType, EvidenceSnapshot
from artha.evidence.store.repository import EvidenceRepository


SNAPSHOT_ARTIFACT_TYPES = [
    ArtifactType.MARKET_SNAPSHOT,
    ArtifactType.FEATURE_SET,
    ArtifactType.RISK_ESTIMATE,
    ArtifactType.VOLATILITY_ESTIMATE,
    ArtifactType.REGIME_CLASSIFICATION,
    ArtifactType.PORTFOLIO_STATE,
]


class EvidenceSnapshotService:
    def __init__(self, session: AsyncSession, repository: EvidenceRepository) -> None:
        self._session = session
        self._repository = repository

    async def freeze(self, decision_id: DecisionID) -> EvidenceSnapshot:
        """Freeze current evidence state for a decision. Atomic operation."""
        latest = await self._repository.get_latest_of_each(SNAPSHOT_ARTIFACT_TYPES)
        artifact_ids = [a.id for a in latest.values()]

        snapshot_id = SnapshotID(str(uuid.uuid4()))
        now = get_clock().now()

        row = EvidenceSnapshotRow(
            id=snapshot_id,
            decision_id=decision_id,
            artifact_ids_json=json.dumps(artifact_ids),
            frozen_at=now,
        )
        self._session.add(row)
        await self._session.flush()

        return EvidenceSnapshot(
            id=snapshot_id,
            decision_id=decision_id,
            artifact_ids=artifact_ids,
            frozen_at=now,
        )

    async def get_by_decision(self, decision_id: DecisionID) -> EvidenceSnapshot | None:
        from sqlalchemy import select
        stmt = select(EvidenceSnapshotRow).where(
            EvidenceSnapshotRow.decision_id == decision_id
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return EvidenceSnapshot(
            id=row.id,
            decision_id=row.decision_id,
            artifact_ids=json.loads(row.artifact_ids_json),
            frozen_at=row.frozen_at,
        )
