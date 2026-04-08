"""API request/response schemas for the Governance layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from artha.governance.agents.analysis.models import AnalysisEnvelope
from artha.governance.agents.base import AgentOutput
from artha.governance.intent.models import IntentSource, IntentType
from artha.governance.permissions.models import PermissionOutcome
from artha.governance.rules.models import RuleEvaluation


class SubmitIntentRequest(BaseModel):
    intent_type: IntentType
    source: IntentSource = IntentSource.HUMAN
    initiator: str = "user"
    symbols: list[str]
    holdings: dict[str, float] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class GovernanceResult(BaseModel):
    decision_id: str
    intent_type: str
    status: str
    analysis_envelope: AnalysisEnvelope | None = None
    agent_outputs: list[AgentOutput] = Field(default_factory=list)
    rule_evaluations: list[RuleEvaluation] = Field(default_factory=list)
    permission_outcome: PermissionOutcome | None = None
    evidence_snapshot_id: str | None = None
    error: str | None = None
