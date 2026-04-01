"""Orchestrator state — TypedDict for LangGraph StateGraph."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from artha.evidence.schemas import EvidenceSnapshot
from artha.governance.agents.base import AgentOutput
from artha.governance.intent.models import GovernanceIntent
from artha.governance.permissions.models import PermissionOutcome
from artha.governance.rules.models import RuleEvaluation, RuleSet


class OrchestratorState(TypedDict, total=False):
    """State flowing through the LangGraph orchestration pipeline."""

    # Input
    intent: GovernanceIntent

    # Evidence
    evidence_snapshot: EvidenceSnapshot | None
    evidence_context: dict[str, Any]

    # Agent outputs (appended by each agent node)
    agent_outputs: Annotated[list[AgentOutput], operator.add]

    # Supervision
    agents_to_consult: list[str]
    loop_count: int
    synthesis_complete: bool

    # Rules
    rule_set: RuleSet | None
    rule_evaluations: list[RuleEvaluation]

    # Permissions
    permission_outcome: PermissionOutcome | None

    # Decision
    decision_id: str
    status: str  # "processing", "approved", "rejected", "escalated"
    error: str | None
