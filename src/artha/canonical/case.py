"""Section 15.3.2 — case_object.

A case is the unit of work that flows through the system: a proposal evaluation,
a diagnostic, a rebalance trigger, a meeting briefing, etc. Per Thesis 4.3, every
case fires both lenses (portfolio + proposal); `dominant_lens` picks the framing
for the human-facing artifact.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import (
    CaseIntent,
    ConfidenceField,
    INRAmountField,
    VersionPins,
)


class DominantLens(str, Enum):
    """Per Thesis 4.3, every case has one dominant framing for the artifact."""

    PORTFOLIO = "portfolio"
    PROPOSAL = "proposal"


class CaseStatus(str, Enum):
    """Section 15.3.2."""

    IN_PROGRESS = "in_progress"
    AWAITING_DECISION = "awaiting_decision"
    DECIDED = "decided"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


class CaseChannel(str, Enum):
    """Section 15.3.2 — which channel produced the inbound event."""

    C0 = "c0"
    FORM = "form"
    API = "api"
    N0_RESPONSE = "n0_response"
    SYSTEM_TRIGGER = "system_trigger"


class LensMetadata(BaseModel):
    """Per Thesis 4.3 — both lenses fire on every case; metadata captures relevance."""

    model_config = ConfigDict(extra="forbid")

    lenses_fired: list[DominantLens]
    relevance: dict[str, ConfidenceField] = Field(default_factory=dict)


class ProposedAction(BaseModel):
    """Section 15.3.2 — present on proposal-dominant cases."""

    model_config = ConfigDict(extra="forbid")

    target_product: str
    ticket_size_inr: INRAmountField | None = None
    structure: str | None = None
    source_of_funds: str | None = None


class CaseObject(BaseModel):
    """The case-level canonical object (Section 15.3.2)."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    client_id: str
    firm_id: str
    advisor_id: str
    created_at: datetime
    intent: CaseIntent
    intent_confidence: ConfidenceField
    dominant_lens: DominantLens
    lens_metadata: LensMetadata
    current_status: CaseStatus

    payload: dict[str, Any] = Field(default_factory=dict)
    channel: CaseChannel

    proposed_action: ProposedAction | None = None
    routing_metadata: dict[str, Any] = Field(default_factory=dict)
    pinned_versions: VersionPins | None = None
