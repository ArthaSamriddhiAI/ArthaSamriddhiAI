"""Permission outcome models — transforms 'could do' into 'may do'."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from artha.governance.agents.base import ProposedAction
from artha.governance.rules.models import RuleEvaluation


class PermissionStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATION_REQUIRED = "escalation_required"


class ActionPermission(BaseModel):
    """Permission outcome for a single proposed action."""

    action: ProposedAction
    status: PermissionStatus
    rule_evaluations: list[RuleEvaluation] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)


class PermissionOutcome(BaseModel):
    """Aggregate permission outcome for all proposed actions."""

    decision_id: str
    permissions: list[ActionPermission] = Field(default_factory=list)
    overall_status: PermissionStatus = PermissionStatus.APPROVED
    requires_human_approval: bool = False
