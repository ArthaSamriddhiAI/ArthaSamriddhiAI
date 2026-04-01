"""LangGraph StateGraph — the governance orchestration pipeline.

Flow:
  receive_intent → freeze_evidence → supervisor_dispatch → run_agents
  → collect_reasoning → (loop or proceed) → rule_engine_evaluate
  → permission_filter → record_decision
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from artha.common.clock import get_clock
from artha.common.types import DecisionID
from artha.config import settings
from artha.evidence.schemas import ArtifactType, EvidenceSnapshot
from artha.evidence.service import EvidenceService
from artha.evidence.store.artifact import ArtifactStore
from artha.evidence.store.repository import EvidenceRepository
from artha.evidence.store.snapshot import EvidenceSnapshotService
from artha.governance.agents.base import AgentOutput, ProposedAction
from artha.governance.intent.models import GovernanceIntent
from artha.governance.intent.parser import validate_intent
from artha.governance.orchestrator.nodes import run_agent
from artha.governance.orchestrator.state import OrchestratorState
from artha.governance.orchestrator.supervisor import Supervisor
from artha.governance.permissions.filter import PermissionFilter
from artha.governance.permissions.models import PermissionOutcome
from artha.governance.rules.engine import RuleEngine
from artha.governance.rules.models import RuleEvaluation, RuleSet
from artha.governance.rules.repository import RuleRepository
from artha.llm.base import LLMProvider

from sqlalchemy.ext.asyncio import AsyncSession


class GovernancePipeline:
    """Builds and runs the LangGraph orchestration pipeline."""

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMProvider,
        rules_dir: Path | None = None,
    ) -> None:
        self._session = session
        self._llm = llm
        self._rules_dir = rules_dir or Path("rules")
        self._supervisor = Supervisor(llm)
        self._rule_engine = RuleEngine()
        self._permission_filter = PermissionFilter()
        self._rule_repo = RuleRepository(session, self._rules_dir)
        self._store = ArtifactStore(session)
        self._evidence_repo = EvidenceRepository(self._store)
        self._snapshot_service = EvidenceSnapshotService(session, self._evidence_repo)

    async def run(self, intent: GovernanceIntent) -> OrchestratorState:
        """Execute the full governance pipeline for an intent."""
        # Validate
        validate_intent(intent)

        decision_id = DecisionID(str(uuid.uuid4()))

        # Initialize state
        state: OrchestratorState = {
            "intent": intent,
            "evidence_snapshot": None,
            "evidence_context": {},
            "agent_outputs": [],
            "agents_to_consult": [],
            "loop_count": 0,
            "synthesis_complete": False,
            "rule_set": None,
            "rule_evaluations": [],
            "permission_outcome": None,
            "decision_id": decision_id,
            "status": "processing",
            "error": None,
        }

        try:
            # Step 1: Compute evidence
            evidence_svc = EvidenceService(self._session)
            artifact_ids = await evidence_svc.compute_full_evidence(
                intent.symbols, intent.holdings or None
            )

            # Step 2: Freeze evidence snapshot
            snapshot = await self._snapshot_service.freeze(decision_id)
            state["evidence_snapshot"] = snapshot

            # Build evidence context for agents
            evidence_context = await self._build_evidence_context(artifact_ids)
            evidence_context["intent_type"] = intent.intent_type.value
            evidence_context["intent_parameters"] = intent.parameters
            if intent.holdings:
                evidence_context["current_holdings"] = intent.holdings
            state["evidence_context"] = evidence_context

            # Step 3: Snapshot rules
            rule_set = await self._rule_repo.snapshot_rule_set()
            state["rule_set"] = rule_set

            # Step 4: Agent consultation loop
            max_loops = settings.max_orchestrator_loops
            for loop_i in range(max_loops + 1):
                state["loop_count"] = loop_i

                # Supervisor decides which agents to consult
                dispatch = await self._supervisor.decide_agents(
                    intent=intent,
                    prior_outputs=state["agent_outputs"],
                    evidence_context=evidence_context,
                    loop_count=loop_i,
                    max_loops=max_loops,
                )

                if dispatch.synthesis_complete or not dispatch.agents:
                    state["synthesis_complete"] = True
                    break

                # Run dispatched agents
                for agent_id in dispatch.agents:
                    output = await run_agent(agent_id, evidence_context, self._llm)
                    state["agent_outputs"] = state["agent_outputs"] + [output]

            # Step 5: Collect all proposed actions from agents
            all_proposed = self._collect_proposed_actions(state["agent_outputs"])

            # Step 6: Rule engine evaluation
            all_evaluations: list[tuple[ProposedAction, list[RuleEvaluation]]] = []
            for action in all_proposed:
                action_context = self._build_action_context(action, evidence_context, state)
                evals = self._rule_engine.evaluate_action(rule_set, action_context)
                all_evaluations.append((action, evals))
                state["rule_evaluations"].extend(evals)

            # Step 7: Permission filter
            permission_outcome = self._permission_filter.evaluate(
                decision_id, all_evaluations
            )
            state["permission_outcome"] = permission_outcome

            # Step 8: Determine final status
            state["status"] = permission_outcome.overall_status.value

        except Exception as e:
            state["status"] = "error"
            state["error"] = str(e)

        # Step 9: Persist decision record
        try:
            await self._save_decision_record(state, intent)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to save decision record: {e}")

        return state

    async def _save_decision_record(
        self, state: OrchestratorState, intent: GovernanceIntent
    ) -> None:
        """Persist the decision to governance_decisions table."""
        from artha.governance.models import GovernanceDecisionRow
        snapshot = state.get("evidence_snapshot")
        rule_set = state.get("rule_set")
        # Serialize full result for retrieval
        agent_outputs = [a.model_dump(mode="json") for a in state.get("agent_outputs", [])]
        rule_evals = [r.model_dump(mode="json") for r in state.get("rule_evaluations", [])]
        perm = state.get("permission_outcome")
        result_data = {
            "agent_count": len(agent_outputs),
            "rule_count": len(rule_evals),
            "initiator": intent.initiator,
            "parameters": intent.parameters,
            "symbols": intent.symbols,
            "holdings": intent.holdings,
            "agent_outputs": agent_outputs,
            "rule_evaluations": rule_evals,
            "permission_outcome": perm.model_dump(mode="json") if perm else None,
        }
        row = GovernanceDecisionRow(
            id=state["decision_id"],
            intent_id=intent.id,
            intent_type=intent.intent_type.value,
            status=state["status"],
            rule_set_version_id=rule_set.version_id if rule_set else None,
            evidence_snapshot_id=snapshot.id if snapshot else None,
            result_json=json.dumps(result_data, default=str),
            created_at=intent.created_at,
            completed_at=get_clock().now(),
        )
        self._session.add(row)
        await self._session.flush()

    async def _build_evidence_context(
        self, artifact_ids: dict[str, str]
    ) -> dict[str, Any]:
        """Build the context dict that agents will see."""
        context: dict[str, Any] = {}
        for key, aid in artifact_ids.items():
            artifact = await self._store.get(aid)
            context[key] = artifact.data
        return context

    def _collect_proposed_actions(
        self, agent_outputs: list[AgentOutput]
    ) -> list[ProposedAction]:
        """Collect all proposed actions from agent outputs, deduplicating by symbol."""
        seen: dict[str, ProposedAction] = {}
        for output in agent_outputs:
            for action in output.proposed_actions:
                # Last agent's proposal wins for same symbol
                seen[action.symbol] = action
        return list(seen.values())

    def _build_action_context(
        self,
        action: ProposedAction,
        evidence_context: dict[str, Any],
        state: OrchestratorState,
    ) -> dict[str, Any]:
        """Build the context for evaluating rules against a specific action."""
        # Extract relevant evidence data
        risk_data = evidence_context.get("risk_estimate", {})
        regime_data = evidence_context.get("regime_classification", {})
        portfolio_data = evidence_context.get("portfolio_state", {})

        per_symbol_risk = risk_data.get("per_symbol", {}).get(action.symbol, {})

        current_holdings = state["intent"].holdings or {}
        is_new = action.symbol not in current_holdings

        return {
            "symbol": action.symbol,
            "action_type": action.action,
            "action_target_weight": action.target_weight or 0.0,
            "is_new_position": is_new,
            "symbol_risk_level": per_symbol_risk.get("risk_level", "medium"),
            "portfolio_risk_score": risk_data.get("portfolio_risk_score", 0.0),
            "regime": regime_data.get("regime", "stable"),
            "sector_weight_after": action.target_weight or 0.0,  # Simplified
            "position_count": portfolio_data.get("risk_metrics", {}).get("position_count", 0),
            "max_single_position": portfolio_data.get("risk_metrics", {}).get(
                "max_single_position", 0.0
            ),
            # Rule parameters are merged by the engine
        }
