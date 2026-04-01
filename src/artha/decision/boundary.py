"""Decision boundary — freeze evidence + rules atomically at decision moment."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.types import DecisionID
from artha.decision.models import DecisionBoundary
from artha.evidence.store.artifact import ArtifactStore
from artha.evidence.store.repository import EvidenceRepository
from artha.evidence.store.snapshot import EvidenceSnapshotService
from artha.governance.rules.repository import RuleRepository

from pathlib import Path


class DecisionBoundaryService:
    """Atomically freezes evidence and rule set version at decision time.

    After this point, the evidence snapshot and rule set become
    immutable historical references for this decision.
    """

    def __init__(self, session: AsyncSession, rules_dir: Path | None = None) -> None:
        self._session = session
        self._store = ArtifactStore(session)
        self._evidence_repo = EvidenceRepository(self._store)
        self._snapshot_service = EvidenceSnapshotService(session, self._evidence_repo)
        self._rule_repo = RuleRepository(session, rules_dir or Path("rules"))

    async def freeze(self, decision_id: DecisionID) -> DecisionBoundary:
        """Freeze evidence and rules for a decision.

        Both operations happen within the same database transaction,
        ensuring atomicity.
        """
        # Freeze evidence
        evidence_snapshot = await self._snapshot_service.freeze(decision_id)

        # Snapshot rule set
        rule_set = await self._rule_repo.snapshot_rule_set()

        return DecisionBoundary(
            decision_id=decision_id,
            evidence_snapshot=evidence_snapshot,
            rule_set_version_id=rule_set.version_id,
            frozen_at=get_clock().now(),
        )
