"""Decision boundary models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from artha.evidence.schemas import EvidenceSnapshot
from artha.governance.rules.models import RuleSet


class DecisionBoundary(BaseModel):
    """The frozen state at the moment of decision."""

    decision_id: str
    evidence_snapshot: EvidenceSnapshot
    rule_set_version_id: str
    frozen_at: datetime


class DecisionRecord(BaseModel):
    """Complete record of a governance decision."""

    decision_id: str
    intent_id: str
    intent_type: str
    status: str
    boundary: DecisionBoundary | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    completed_at: datetime | None = None
