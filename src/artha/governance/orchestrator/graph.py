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

        # Initialize trace builder — records every step as a node in the causal DAG
        # Trace is non-critical: pipeline continues even if tracing fails
        from artha.accountability.trace.graph import DecisionTraceBuilder
        from artha.accountability.trace.models import TraceNodeType
        trace = DecisionTraceBuilder(self._session, decision_id)
        _trace_ok = True  # Flag to skip tracing if first attempt fails

        async def _trace(node_type, data, parent_ids=None):
            nonlocal _trace_ok
            if not _trace_ok:
                return "no-trace"
            try:
                return await trace.add_node(node_type, data, parent_ids)
            except Exception:
                _trace_ok = False
                try:
                    await self._session.rollback()
                except Exception:
                    pass
                return "no-trace"

        try:
            # ── TRACE: Intent Received ──
            intent_node = await _trace(TraceNodeType.INTENT_RECEIVED, {
                "intent_id": intent.id, "intent_type": intent.intent_type.value,
                "source": intent.source.value, "initiator": intent.initiator,
                "symbols": intent.symbols, "holdings_count": len(intent.holdings or {}),
                "parameters_keys": list(intent.parameters.keys()),
            })

            # Step 1: Compute evidence
            evidence_svc = EvidenceService(self._session)
            artifact_ids = await evidence_svc.compute_full_evidence(
                intent.symbols, intent.holdings or None
            )

            # Step 2: Freeze evidence snapshot
            snapshot = await self._snapshot_service.freeze(decision_id)
            state["evidence_snapshot"] = snapshot

            # ── TRACE: Evidence Frozen ──
            evidence_node = await _trace(TraceNodeType.EVIDENCE_FROZEN, {
                "snapshot_id": snapshot.id, "artifact_ids": snapshot.artifact_ids,
                "artifact_count": len(snapshot.artifact_ids),
                "frozen_at": str(snapshot.frozen_at),
            }, parent_ids=[intent_node])

            # Build evidence context for agents
            evidence_context = await self._build_evidence_context(artifact_ids)
            evidence_context["intent_type"] = intent.intent_type.value
            evidence_context["intent_parameters"] = intent.parameters
            if intent.holdings:
                evidence_context["current_holdings"] = intent.holdings

            # Inject investor risk profile if investor_id provided
            investor_id = intent.parameters.get("investor_id")
            if investor_id:
                try:
                    from artha.investor.service import InvestorService
                    inv_svc = InvestorService(self._session)
                    profile = await inv_svc.get_profile(investor_id)
                    if profile:
                        evidence_context["investor_risk_profile"] = {
                            "investor_id": investor_id,
                            "overall_score": profile.overall_score,
                            "risk_category": profile.risk_category.value,
                            "constraints": profile.effective_constraints.model_dump(),
                            "family_complexity_score": profile.family_complexity_score,
                            "category_scores": profile.category_scores,
                        }
                except Exception:
                    pass

            state["evidence_context"] = evidence_context

            # Step 3: Snapshot rules
            rule_set = await self._rule_repo.snapshot_rule_set()
            state["rule_set"] = rule_set

            # Step 4: Agent consultation loop
            max_loops = settings.max_orchestrator_loops
            last_agent_nodes: list[str] = []

            for loop_i in range(max_loops + 1):
                state["loop_count"] = loop_i

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

                for agent_id in dispatch.agents:
                    # ── TRACE: Agent Invoked ──
                    invoke_node = await _trace(TraceNodeType.AGENT_INVOKED, {
                        "agent_id": agent_id, "loop": loop_i,
                        "dispatch_reasoning": dispatch.reasoning,
                    }, parent_ids=[evidence_node])

                    output = await run_agent(agent_id, evidence_context, self._llm)
                    state["agent_outputs"] = state["agent_outputs"] + [output]

                    # ── TRACE: Agent Output ──
                    output_node = await _trace(TraceNodeType.AGENT_OUTPUT, {
                        "agent_id": output.agent_id, "agent_name": output.agent_name,
                        "risk_level": output.risk_level.value, "confidence": output.confidence,
                        "drivers": output.drivers, "flags": output.flags,
                        "proposed_actions_count": len(output.proposed_actions),
                        "reasoning_summary": output.reasoning_summary[:200] if output.reasoning_summary else "",
                    }, parent_ids=[invoke_node])
                    last_agent_nodes.append(output_node)

            # Step 5: Collect all proposed actions
            all_proposed = self._collect_proposed_actions(state["agent_outputs"])

            # Step 6: Rule engine evaluation
            all_evaluations: list[tuple[ProposedAction, list[RuleEvaluation]]] = []
            for action in all_proposed:
                action_context = self._build_action_context(action, evidence_context, state)
                evals = self._rule_engine.evaluate_action(rule_set, action_context)
                all_evaluations.append((action, evals))
                state["rule_evaluations"].extend(evals)

                # ── TRACE: Rule Evaluated (per action) ──
                passed_count = sum(1 for e in evals if e.passed)
                failed_count = sum(1 for e in evals if not e.passed)
                hard_fails = [e.rule_name for e in evals if not e.passed and e.severity.value == "hard"]
                soft_fails = [e.rule_name for e in evals if not e.passed and e.severity.value == "soft"]
                await _trace(TraceNodeType.RULE_EVALUATED, {
                    "symbol": action.symbol, "action": action.action,
                    "target_weight": action.target_weight,
                    "rules_passed": passed_count, "rules_failed": failed_count,
                    "hard_violations": hard_fails, "soft_violations": soft_fails,
                    "total_rules": len(evals),
                }, parent_ids=last_agent_nodes or [evidence_node])

            # Step 7: Permission filter
            permission_outcome = self._permission_filter.evaluate(
                decision_id, all_evaluations
            )
            state["permission_outcome"] = permission_outcome

            # Step 8: Determine final status
            state["status"] = permission_outcome.overall_status.value

            # ── TRACE: Permission Outcome ──
            perm_type = {
                "approved": TraceNodeType.PERMISSION_GRANTED,
                "rejected": TraceNodeType.PERMISSION_DENIED,
                "escalation_required": TraceNodeType.ESCALATION_REQUIRED,
            }.get(state["status"], TraceNodeType.PERMISSION_DENIED)

            perm_data = {
                "overall_status": state["status"],
                "actions_approved": sum(1 for p in permission_outcome.permissions if p.status.value == "approved"),
                "actions_rejected": sum(1 for p in permission_outcome.permissions if p.status.value == "rejected"),
                "actions_escalated": sum(1 for p in permission_outcome.permissions if p.status.value == "escalation_required"),
                "requires_human_approval": permission_outcome.requires_human_approval,
            }
            if permission_outcome.permissions:
                perm_data["rejection_reasons"] = []
                perm_data["escalation_reasons"] = []
                for p in permission_outcome.permissions:
                    perm_data["rejection_reasons"].extend(p.rejection_reasons)
                    perm_data["escalation_reasons"].extend(p.escalation_reasons)

            await _trace(perm_type, perm_data, parent_ids=last_agent_nodes or [evidence_node])

        except Exception as e:
            state["status"] = "error"
            state["error"] = str(e)
            # ── TRACE: Error ──
            try:
                await _trace(TraceNodeType.ERROR, {
                    "error_type": type(e).__name__, "error_message": str(e)[:500],
                }, parent_ids=[intent_node] if 'intent_node' in dir() else [])
            except Exception:
                pass

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
            # Investor risk profile constraints (for investor-specific rules)
            **self._get_investor_constraints(evidence_context),
            # Rule parameters are merged by the engine
        }

    def _get_investor_constraints(self, evidence_context: dict[str, Any]) -> dict[str, Any]:
        """Extract investor constraints for rule evaluation context."""
        profile = evidence_context.get("investor_risk_profile", {})
        constraints = profile.get("constraints", {})
        return {
            "investor_risk_category": profile.get("risk_category", "moderate"),
            "investor_max_volatility": constraints.get("max_volatility", 0.20),
            "investor_max_drawdown": constraints.get("max_drawdown", 0.25),
            "investor_equity_ceiling": constraints.get("equity_allocation_max", 0.70),
            "investor_horizon": constraints.get("investment_horizon", "medium"),
            "family_complexity_score": profile.get("family_complexity_score", 0),
        }
