"""Governance intent models — what the system is being asked to do."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from artha.common.clock import get_clock
from artha.common.types import IntentID


class IntentType(str, Enum):
    REBALANCE = "rebalance"
    RISK_REVIEW = "risk_review"
    TRADE_PROPOSAL = "trade_proposal"
    SCHEDULED_EVALUATION = "scheduled_evaluation"


class IntentSource(str, Enum):
    HUMAN = "human"
    SCHEDULED = "scheduled"
    TRIGGER = "trigger"


class GovernanceIntent(BaseModel):
    """A request for the governance system to evaluate and act."""

    id: IntentID = Field(default_factory=lambda: IntentID(str(uuid.uuid4())))
    intent_type: IntentType
    source: IntentSource = IntentSource.HUMAN
    initiator: str = "system"
    parameters: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)
    holdings: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: get_clock().now())
    metadata: dict[str, Any] = Field(default_factory=dict)
