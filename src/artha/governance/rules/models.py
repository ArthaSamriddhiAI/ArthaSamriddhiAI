"""Rule and rule evaluation models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from artha.common.types import RuleID, RuleSetVersionID


class RuleSeverity(str, Enum):
    HARD = "hard"  # Violation blocks action
    SOFT = "soft"  # Violation triggers escalation
    INFO = "info"  # Logged but does not block


class RuleCategory(str, Enum):
    EXPOSURE_LIMIT = "exposure_limit"
    RISK_CONSTRAINT = "risk_constraint"
    REGULATORY = "regulatory"
    CONCENTRATION = "concentration"


class Rule(BaseModel):
    """A governance rule — deterministic, versioned, executable."""

    id: RuleID = Field(default_factory=lambda: RuleID(str(uuid.uuid4())))
    name: str
    description: str
    category: RuleCategory
    severity: RuleSeverity
    condition: str  # Python expression evaluated in sandboxed context
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class RuleSet(BaseModel):
    """A versioned collection of rules in effect at a point in time."""

    version_id: RuleSetVersionID = Field(
        default_factory=lambda: RuleSetVersionID(str(uuid.uuid4()))
    )
    rules: list[Rule]
    created_at: datetime


class RuleEvaluation(BaseModel):
    """Result of evaluating a single rule against an action."""

    rule_id: RuleID
    rule_name: str
    severity: RuleSeverity
    passed: bool
    condition: str
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
