"""Governance service — entry point for governance pipeline execution."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from artha.governance.intent.models import GovernanceIntent
from artha.governance.orchestrator.graph import GovernancePipeline
from artha.governance.orchestrator.state import OrchestratorState
from artha.governance.schemas import GovernanceResult
from artha.llm.base import LLMProvider
from artha.llm.registry import get_provider


class GovernanceService:
    def __init__(
        self,
        session: AsyncSession,
        llm: LLMProvider | None = None,
        rules_dir: Path | None = None,
    ) -> None:
        self._session = session
        self._llm = llm or get_provider()
        self._rules_dir = rules_dir

    async def process_intent(self, intent: GovernanceIntent) -> GovernanceResult:
        """Run the full governance pipeline for an intent."""
        pipeline = GovernancePipeline(
            session=self._session,
            llm=self._llm,
            rules_dir=self._rules_dir,
        )

        state = await pipeline.run(intent)
        return self._state_to_result(state)

    def _state_to_result(self, state: OrchestratorState) -> GovernanceResult:
        snapshot = state.get("evidence_snapshot")
        return GovernanceResult(
            decision_id=state["decision_id"],
            intent_type=state["intent"].intent_type.value,
            status=state["status"],
            agent_outputs=state.get("agent_outputs", []),
            rule_evaluations=state.get("rule_evaluations", []),
            permission_outcome=state.get("permission_outcome"),
            evidence_snapshot_id=snapshot.id if snapshot else None,
            error=state.get("error"),
        )
