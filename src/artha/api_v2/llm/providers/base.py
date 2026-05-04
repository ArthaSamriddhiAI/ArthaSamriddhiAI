"""Provider-adapter abstract base — FR Entry 16.0 §2.2 + §3.

Every concrete provider adapter (Mistral, Claude, future) implements this
single interface so the SmartLLMRouter executor can call into them
uniformly. The internal API + response shapes mirror the FR section
verbatim — anything that diverges is a router-side concern, not adapter
business.

Adapter contract (FR 16.0 §3.3):

- Translate an :class:`LLMCallRequest` into the provider's native HTTP call.
- Block until a response is available or until the deadline given by the
  router (the ``timeout_seconds`` parameter to :meth:`ProviderAdapter.complete`).
- On success, return :class:`LLMCallResponse` populated from the provider
  response.
- On failure, raise the appropriate :class:`ProviderError` subclass so the
  executor can decide whether to retry, fail-fast, or surface to the caller.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Request + response shapes (mirrors FR 16.0 §2.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """One turn in a structured chat-style request."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMCallRequest:
    """Internal call shape consumed by every provider adapter.

    Either ``prompt`` (a single combined string) or ``messages`` (a structured
    turn list) must be set. ``messages`` wins when both are present.
    """

    caller_id: str
    prompt: str | None = None
    messages: list[Message] | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    response_format: Literal["text", "json"] = "text"
    # Optional provider-specific override; otherwise the adapter's configured
    # default model is used.
    model: str | None = None


@dataclass(frozen=True)
class LLMCallResponse:
    """Internal response shape returned by every provider adapter."""

    content: str
    provider: str
    model: str
    tokens_used: int
    latency_ms: int
    request_id: str
    raw: dict[str, Any] = field(default_factory=dict)  # For debugging / future use.


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base class for adapter errors. Carries the provider name + a
    machine-readable failure type used by T1 telemetry."""

    failure_type: str = "provider_error"

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider or "unknown"


class ProviderRateLimitError(ProviderError):
    """Provider returned a 429 (or equivalent rate-limit signal). Retriable."""

    failure_type = "rate_limit"


class ProviderTimeoutError(ProviderError):
    """The HTTP call did not finish within ``timeout_seconds``. Retriable."""

    failure_type = "timeout"


class ProviderTransientError(ProviderError):
    """5xx server error, network failure, or other transient issue. Retriable."""

    failure_type = "transient"


class ProviderAuthError(ProviderError):
    """The configured API key was rejected (401/403). Non-retriable."""

    failure_type = "auth_error"


class ProviderInvalidResponseError(ProviderError):
    """The provider returned a 2xx with a body the adapter could not parse
    (missing fields, JSON-mode failure, etc.). Non-retriable."""

    failure_type = "malformed_response"


# ---------------------------------------------------------------------------
# Adapter base class
# ---------------------------------------------------------------------------


class ProviderAdapter(ABC):
    """Abstract base for every provider adapter.

    Subclasses receive the decrypted API key + the configured default model
    + the global request timeout from the executor. Each subclass owns its
    HTTP shape; the executor handles retries, rate limiting, and telemetry.
    """

    #: Provider name, e.g. ``"mistral"`` or ``"claude"``. Returned in
    #: :class:`LLMCallResponse.provider`.
    provider_name: str

    def __init__(self, *, api_key: str, default_model: str) -> None:
        if not api_key:
            raise ValueError(
                f"{self.provider_name} adapter requires a non-empty API key"
            )
        self._api_key = api_key
        self._default_model = default_model

    @abstractmethod
    async def complete(
        self, request: LLMCallRequest, *, timeout_seconds: int
    ) -> LLMCallResponse:
        """Execute one LLM call and return the response.

        Raises one of the :class:`ProviderError` subclasses on failure.
        """
        raise NotImplementedError
