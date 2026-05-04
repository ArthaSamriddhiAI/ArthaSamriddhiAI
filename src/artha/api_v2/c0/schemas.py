"""Pydantic request/response schemas for the C0 conversational surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.api_v2.investors.schemas import InvestorRead

# ---------------------------------------------------------------------------
# Conversation read shapes
# ---------------------------------------------------------------------------


class MessageRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    sender: Literal["user", "system"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class ConversationRead(BaseModel):
    """Full conversation envelope returned to the chat UI.

    ``investor`` is populated only after action execution succeeds, so the
    success card can be rendered without a follow-up fetch.
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    user_id: str
    intent: str | None
    state: str
    collected_slots: dict[str, Any]
    status: Literal["active", "completed", "abandoned", "error"]
    started_at: datetime
    last_message_at: datetime
    completed_at: datetime | None
    investor_id: str | None
    investor: InvestorRead | None = None
    messages: list[MessageRead]


class ConversationSummary(BaseModel):
    """Sidebar list shape — leaner than :class:`ConversationRead`."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    intent: str | None
    state: str
    status: Literal["active", "completed", "abandoned", "error"]
    started_at: datetime
    last_message_at: datetime
    preview: str  # first user message, truncated


class ConversationsListResponse(BaseModel):
    conversations: list[ConversationSummary]


# ---------------------------------------------------------------------------
# Action shapes
# ---------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    """``POST /api/v2/conversations`` body — empty by design.

    The first user message creates the first turn via the post-message
    endpoint; the start endpoint just allocates the conversation row.
    """

    model_config = ConfigDict(extra="forbid")


class PostMessageRequest(BaseModel):
    """One user-typed message into an existing conversation."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)


class ConfirmActionRequest(BaseModel):
    """User clicked ``Confirm and Create`` on the confirmation card."""

    model_config = ConfigDict(extra="forbid")


class CancelConversationRequest(BaseModel):
    """User explicitly cancelled the conversation (or the UI sends this on
    navigate-away)."""

    model_config = ConfigDict(extra="forbid")
