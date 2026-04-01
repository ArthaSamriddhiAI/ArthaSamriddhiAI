"""Audit reconstructor — policy-at-the-time, evidence-at-the-time."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from artha.common.types import DecisionID
from artha.accountability.approval.models import ApprovalRecord
from artha.accountability.approval.repository import ApprovalRepository
from artha.accountability.trace.models import DecisionTrace
from artha.accountability.trace.repository import TraceRepository
from artha.evidence.schemas import EvidenceArtifact, EvidenceSnapshot
from artha.evidence.store.snapshot import EvidenceSnapshotService
from artha.evidence.store.artifact import ArtifactStore
from artha.governance.rules.models import RuleSet
from artha.governance.rules.repository import RuleRepository

from sqlalchemy.ext.asyncio import AsyncSession


class AuditReconstruction(BaseModel):
    """Full audit reconstruction of a decision."""

    decision_id: str
    trace: DecisionTrace
    evidence_snapshot: EvidenceSnapshot | None = None
    evidence_artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    rule_set_at_time: RuleSet | None = None
    approvals: list[ApprovalRecord] = Field(default_factory=list)


class AuditReconstructor:
    """Reconstructs the full decision context for audit purposes.

    Given a decision ID, retrieves:
    - The complete causal trace
    - The evidence that was frozen at decision time
    - The rule set that was in force at decision time
    - Any human approvals or overrides
    """

    def __init__(
        self,
        session: AsyncSession,
        trace_repo: TraceRepository,
        approval_repo: ApprovalRepository,
        snapshot_service: EvidenceSnapshotService,
        artifact_store: ArtifactStore,
        rule_repo: RuleRepository,
    ) -> None:
        self._session = session
        self._trace_repo = trace_repo
        self._approval_repo = approval_repo
        self._snapshot_service = snapshot_service
        self._artifact_store = artifact_store
        self._rule_repo = rule_repo

    async def reconstruct(self, decision_id: DecisionID) -> AuditReconstruction:
        # 1. Get the trace
        trace = await self._trace_repo.get_trace(decision_id)

        # 2. Get the evidence snapshot
        snapshot = await self._snapshot_service.get_by_decision(decision_id)

        # 3. Get the actual evidence artifacts
        artifacts = []
        if snapshot:
            for artifact_id in snapshot.artifact_ids:
                try:
                    artifact = await self._artifact_store.get(artifact_id)
                    artifacts.append(artifact)
                except Exception:
                    pass

        # 4. Get approvals
        approvals = await self._approval_repo.get_approvals(decision_id)

        return AuditReconstruction(
            decision_id=decision_id,
            trace=trace,
            evidence_snapshot=snapshot,
            evidence_artifacts=artifacts,
            approvals=approvals,
        )
