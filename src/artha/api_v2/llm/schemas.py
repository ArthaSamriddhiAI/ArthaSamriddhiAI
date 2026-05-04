"""Pydantic request/response schemas for the SmartLLMRouter surface.

Mirrors the chunk plan §1.3 endpoints:

- ``GET  /api/v2/llm/config`` → :class:`LLMConfigRead`
- ``PUT  /api/v2/llm/config`` → :class:`LLMConfigUpdateRequest`
- ``POST /api/v2/llm/test-connection`` → :class:`TestConnectionRequest`
                                       → :class:`TestConnectionResponse`
- ``POST /api/v2/llm/kill-switch/...`` → :class:`KillSwitchResponse`
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.api_v2.llm.providers import SUPPORTED_PROVIDERS

ProviderName = Literal["mistral", "claude"]


# ---------------------------------------------------------------------------
# GET /api/v2/llm/config
# ---------------------------------------------------------------------------


class LLMConfigRead(BaseModel):
    """Settings UI read shape — never includes plaintext API keys.

    The ``mistral_api_key_masked`` / ``claude_api_key_masked`` strings are
    populated from :func:`mask_api_key` (e.g. ``"sk-A****"``) so the CIO can
    see whether a key is configured without the secret leaving the server.
    """

    model_config = ConfigDict(extra="forbid")

    active_provider: ProviderName | None
    mistral_api_key_masked: str | None
    claude_api_key_masked: str | None
    default_mistral_model: str
    default_claude_model: str
    rate_limit_calls_per_minute: int
    request_timeout_seconds: int
    kill_switch_active: bool
    is_configured: bool  # True if active_provider is set + corresponding key exists.
    updated_at: datetime | None
    updated_by: str | None
    supported_providers: list[str] = Field(default_factory=lambda: list(SUPPORTED_PROVIDERS))


# ---------------------------------------------------------------------------
# PUT /api/v2/llm/config
# ---------------------------------------------------------------------------


class LLMConfigUpdateRequest(BaseModel):
    """CIO-edited update payload.

    All fields optional so the UI can send partial updates (e.g., switch
    active provider without re-typing keys). Empty-string API keys are
    treated as "no change"; a sentinel ``"__clear__"`` value would delete a
    key but cluster 1 doesn't expose that surface (CIO updates keys, never
    deletes).
    """

    model_config = ConfigDict(extra="forbid")

    active_provider: ProviderName | None = None
    mistral_api_key: str | None = None  # plaintext on the wire from CIO browser → server
    claude_api_key: str | None = None
    default_mistral_model: str | None = Field(default=None, max_length=64)
    default_claude_model: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------------------
# POST /api/v2/llm/test-connection
# ---------------------------------------------------------------------------


class TestConnectionRequest(BaseModel):
    """Request body for the ``Test Connection`` button.

    Either ``api_key`` is given (test the user-typed key before saving) or
    omitted (test the currently-saved key for the chosen provider). Cluster
    1's UI sends the typed key so the user can verify before persisting.
    """

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName
    api_key: str | None = None  # plaintext; never logged.


class TestConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    provider: ProviderName
    detail: str
    failure_type: str | None = None
    latency_ms: int | None = None


# ---------------------------------------------------------------------------
# POST /api/v2/llm/kill-switch/...
# ---------------------------------------------------------------------------


class KillSwitchResponse(BaseModel):
    """Returned from the kill-switch activate / deactivate endpoints."""

    model_config = ConfigDict(extra="forbid")

    kill_switch_active: bool
    activated_at: datetime | None
    activated_by: str | None
