"""§15.6.1 / §15.6.6 / §15.12.1 — channel-layer schemas.

  * `C0ParseOutput` (§10.1.3 + §15.6.1) — what the conversational channel
    emits after parsing an inbound advisor input. Pre-tags intent, extracts
    entities, surfaces ambiguity flags.
  * `LibrarianSession` (§8.7 + §15.6.6) — session-level memory across
    multi-turn advisor conversations.
  * `Turn`, `PendingAmbiguity`, `PendingFollowup` — the pieces that compose
    a `LibrarianSession`.

`N0Alert` itself lives in `canonical/monitoring.py` (Pass 13). Pass 14 adds
the lifecycle states + dedupe metadata via small extension types here so
the channel mechanics can carry them without changing the alert schema.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import (
    CaseIntent,
    ConfidenceField,
    InputsUsedManifest,
)

# ===========================================================================
# §10.1.3 / §15.6.1 — C0 parse output
# ===========================================================================


class C0AmbiguityType(str, Enum):
    """§10.1.4 — taxonomy of ambiguity flags C0 surfaces."""

    CLIENT_NAME_AMBIGUOUS = "client_name_ambiguous"
    PRODUCT_AMBIGUOUS = "product_ambiguous"
    INTENT_AMBIGUOUS = "intent_ambiguous"
    AMOUNT_AMBIGUOUS = "amount_ambiguous"
    HORIZON_AMBIGUOUS = "horizon_ambiguous"
    REFERENT_UNRESOLVED = "referent_unresolved"  # anaphora, e.g. "for him"


class C0ChannelSource(str, Enum):
    """§10.1.2 — which surface delivered the input."""

    UI_CHAT = "ui_chat"
    API = "api"
    VOICE = "voice"
    N0_RESPONSE = "n0_response"


class C0ExtractedEntities(BaseModel):
    """§10.1.3 — structured entities pulled from the raw input.

    Optional fields are populated only when C0 is confident. Anything
    unresolved surfaces as a corresponding ambiguity flag instead of being
    guessed.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str | None = None
    client_name_raw: str | None = None  # the verbatim mention; useful for review
    product_id: str | None = None
    product_name_raw: str | None = None
    action_verb: str | None = None  # "review", "rebalance", "sell", ...
    time_period: str | None = None  # "next quarter", "FY26-27", ...
    amount_inr: float | None = None
    horizon: str | None = None  # short_term / medium_term / long_term


class C0SessionMetadata(BaseModel):
    """§10.1.3 — session continuity + provenance metadata."""

    model_config = ConfigDict(extra="forbid")

    continuity: bool = False  # True iff this is a follow-on turn within a session
    session_id: str | None = None
    parent_turn_id: str | None = None
    timestamp: datetime
    channel_source: C0ChannelSource = C0ChannelSource.UI_CHAT


class C0ParseOutput(BaseModel):
    """§15.6.1 — C0's structured output."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["c0_parser"] = "c0_parser"
    case_id: str | None = None
    advisor_id: str
    firm_id: str
    raw_text: str

    parsed_intent: CaseIntent
    parsed_intent_confidence: ConfidenceField
    extracted_entities: C0ExtractedEntities = Field(default_factory=C0ExtractedEntities)
    ambiguity_flags: list[C0AmbiguityType] = Field(default_factory=list)
    session_metadata: C0SessionMetadata
    parser_version: str = "0.1.0"

    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    timestamp: datetime


# ===========================================================================
# §8.7 / §15.6.6 — M0.Librarian session schema
# ===========================================================================


class LibrarianTurn(BaseModel):
    """§15.6.6 — one turn captured in the session log."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str  # ULID
    timestamp: datetime
    channel: C0ChannelSource
    raw_text: str
    parsed_intent: CaseIntent | None = None
    parsed_intent_confidence: ConfidenceField | None = None
    downstream_event_ids: list[str] = Field(default_factory=list)


class PendingAmbiguity(BaseModel):
    """§15.6.6 — an unresolved ambiguity tracked across turns."""

    model_config = ConfigDict(extra="forbid")

    ambiguity_id: str
    description: str
    introduced_turn_id: str
    resolved: bool = False
    resolved_turn_id: str | None = None


class PendingFollowup(BaseModel):
    """§15.6.6 — a follow-up the system promised that hasn't been delivered."""

    model_config = ConfigDict(extra="forbid")

    followup_id: str
    description: str
    introduced_turn_id: str
    promised_by_turn_id: str | None = None
    resolved: bool = False
    resolved_turn_id: str | None = None


class LibrarianSession(BaseModel):
    """§15.6.6 — a single multi-turn session.

    Authoritative state lives here; LLM retrieval framing operates over a
    read-only snapshot and never invents content.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    advisor_id: str
    firm_id: str
    client_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None

    turns: list[LibrarianTurn] = Field(default_factory=list)
    running_summary: str = ""
    pending_ambiguities: list[PendingAmbiguity] = Field(default_factory=list)
    pending_followups: list[PendingFollowup] = Field(default_factory=list)

    summary_token_budget: int = 1500


# ===========================================================================
# §10.2 — N0 lifecycle extension
# ===========================================================================


class AlertDeliveryState(str, Enum):
    """§10.2.4 — the four-state alert lifecycle."""

    QUEUED = "queued"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"


class AlertEngagementType(str, Enum):
    """§10.2.4 — taxonomy of engagement events tracked on each alert."""

    OPENED = "opened"
    DISMISSED = "dismissed"
    DRILLED_DOWN = "drilled_down"
    RESPONDED = "responded"
    ACKNOWLEDGED = "acknowledged"


class AlertEngagementEvent(BaseModel):
    """§15.12.1 — one row of the engagement_log."""

    model_config = ConfigDict(extra="forbid")

    event_type: AlertEngagementType
    timestamp: datetime
    advisor_id: str
    note: str = ""


class AlertClosureMetadata(BaseModel):
    """§15.12.1 — closure metadata when an alert ends its lifecycle."""

    model_config = ConfigDict(extra="forbid")

    closure_at: datetime
    closure_reason: str
    successor_alert_id: str | None = None


# ===========================================================================
# Internal LLM-output schemas
# ===========================================================================


class _LlmC0ParseOutput(BaseModel):
    """Internal C0 LLM output — string-typed for mock-provider compatibility."""

    model_config = ConfigDict(extra="forbid")

    parsed_intent_value: str  # validated against CaseIntent enum
    parsed_intent_confidence: ConfidenceField
    extracted_entities: C0ExtractedEntities = Field(default_factory=C0ExtractedEntities)
    ambiguity_flags: list[str] = Field(default_factory=list)


class _LlmLibrarianRetrievalOutput(BaseModel):
    """Internal Librarian retrieval LLM output.

    `cited_turn_ids` MUST be a non-empty subset of the session's turn_ids
    when `summary` is non-empty — this is the discipline check that suppresses
    invented retrievals (§8.7.6 Test 4 fidelity).
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    cited_turn_ids: list[str] = Field(default_factory=list)
    no_relevant_turns: bool = False


__all__ = [
    "AlertClosureMetadata",
    "AlertDeliveryState",
    "AlertEngagementEvent",
    "AlertEngagementType",
    "C0AmbiguityType",
    "C0ChannelSource",
    "C0ExtractedEntities",
    "C0ParseOutput",
    "C0SessionMetadata",
    "LibrarianSession",
    "LibrarianTurn",
    "PendingAmbiguity",
    "PendingFollowup",
    "_LlmC0ParseOutput",
    "_LlmLibrarianRetrievalOutput",
]
