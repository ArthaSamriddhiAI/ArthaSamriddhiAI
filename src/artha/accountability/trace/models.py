"""Trace node types and Pydantic models for the decision trace DAG."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TraceNodeType(str, Enum):
    INTENT_RECEIVED = "intent_received"
    EVIDENCE_FROZEN = "evidence_frozen"
    AGENT_INVOKED = "agent_invoked"
    AGENT_OUTPUT = "agent_output"
    RULE_EVALUATED = "rule_evaluated"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    ESCALATION_REQUIRED = "escalation_required"
    HUMAN_APPROVAL = "human_approval"
    EXECUTION_SUBMITTED = "execution_submitted"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_SYNTHESIZED = "analysis_synthesized"
    ERROR = "error"


class TraceNode(BaseModel):
    """A node in the causal decision trace graph."""

    id: str
    decision_id: str
    node_type: TraceNodeType
    parent_node_ids: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DecisionTrace(BaseModel):
    """Complete decision trace — a causal DAG."""

    decision_id: str
    nodes: list[TraceNode] = Field(default_factory=list)
    root_node_id: str | None = None
