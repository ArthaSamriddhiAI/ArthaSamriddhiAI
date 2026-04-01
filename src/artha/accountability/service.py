"""Accountability service."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.types import DecisionID
from artha.accountability.approval.models import ApprovalAction, ApprovalRecord
from artha.accountability.approval.repository import ApprovalRepository
from artha.accountability.audit.reconstructor import AuditReconstruction, AuditReconstructor
from artha.accountability.audit.repository import AuditRepository
from artha.accountability.trace.models import DecisionTrace
from artha.accountability.trace.repository import TraceRepository
from artha.evidence.store.artifact import ArtifactStore
from artha.evidence.store.repository import EvidenceRepository
from artha.evidence.store.snapshot import EvidenceSnapshotService
from artha.governance.rules.repository import RuleRepository


class AccountabilityService:
    def __init__(self, session: AsyncSession, rules_dir: Path | None = None) -> None:
        self._session = session
        self._trace_repo = TraceRepository(session)
        self._approval_repo = ApprovalRepository(session)
        self._audit_repo = AuditRepository(session)
        self._store = ArtifactStore(session)
        self._evidence_repo = EvidenceRepository(self._store)
        self._snapshot_service = EvidenceSnapshotService(session, self._evidence_repo)
        self._rule_repo = RuleRepository(session, rules_dir or Path("rules"))

    async def get_trace(self, decision_id: str) -> DecisionTrace:
        return await self._trace_repo.get_trace(DecisionID(decision_id))

    async def submit_approval(
        self,
        decision_id: str,
        approver: str,
        action: ApprovalAction,
        rationale: str | None = None,
        conditions: str | None = None,
    ) -> ApprovalRecord:
        return await self._approval_repo.record_approval(
            DecisionID(decision_id), approver, action, rationale, conditions
        )

    async def get_approvals(self, decision_id: str) -> list[ApprovalRecord]:
        return await self._approval_repo.get_approvals(DecisionID(decision_id))

    async def reconstruct(self, decision_id: str) -> AuditReconstruction:
        reconstructor = AuditReconstructor(
            session=self._session,
            trace_repo=self._trace_repo,
            approval_repo=self._approval_repo,
            snapshot_service=self._snapshot_service,
            artifact_store=self._store,
            rule_repo=self._rule_repo,
        )
        return await reconstructor.reconstruct(DecisionID(decision_id))

    async def list_decisions(self, limit: int = 50) -> list[str]:
        return await self._audit_repo.list_decisions(limit)
