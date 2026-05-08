"""LLM client wrapper (cluster 7 chunk 7.1 §9).

Two implementations:

- :class:`AnthropicLLMClient` — production wrapper around the Anthropic
  SDK. Honours the per-prompt ``llm_model`` / ``max_tokens`` /
  ``temperature`` from the cluster-6 enriched skill.md.
- :class:`MockLLMClient` — test-only client backed by a per-call
  ``responses`` queue + ``error_queue`` for failure-injection testing.
  Used in CI so we don't burn API tokens or introduce non-determinism.

The shim framework (:mod:`.shim`) treats both clients uniformly via the
:class:`LLMClient` protocol. When the case pipeline flips an agent
from ``stub`` to ``real`` (chunk 7.1 §config), the dispatcher
constructs whichever client the runtime config selects.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from artha.api_v2.agents.prompt_loader import PromptPayload


class LLMCallError(RuntimeError):
    """Raised when an LLM call fails. Caller (dispatcher) retries
    per the cluster-7 retry policy."""


@dataclass(frozen=True)
class LLMResponse:
    """Structured LLM response.

    ``text`` is the model's textual output (typically a JSON object as
    a string for cluster-7 agents). Token counts feed cache + cost
    telemetry.
    """

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stop_reason: str = "end_turn"


class LLMClient(Protocol):
    """Minimal call surface the shim framework depends on."""

    def complete(self, prompt: PromptPayload) -> LLMResponse:
        """Call the model with ``prompt`` and return a
        :class:`LLMResponse`. Raise :class:`LLMCallError` on transient
        failure (the dispatcher will retry)."""
        ...


# ---------------------------------------------------------------------------
# Production client
# ---------------------------------------------------------------------------


class AnthropicLLMClient:
    """Production wrapper around the Anthropic Messages API.

    Caller is responsible for instantiating the underlying
    ``anthropic.Anthropic`` client (so credentials + base URL come
    from the firm's :mod:`artha.config` instead of being baked in here).

    ``api_timeout_seconds`` defaults to 60s per chunk 7.1 §9.4.
    Streaming is intentionally disabled — verdicts are structured JSON;
    streaming offers no UX benefit and complicates parsing.
    """

    def __init__(
        self,
        *,
        anthropic_client: Any,
        api_timeout_seconds: float = 60.0,
    ) -> None:
        self._client = anthropic_client
        self._timeout = api_timeout_seconds

    def complete(self, prompt: PromptPayload) -> LLMResponse:
        try:
            resp = self._client.messages.create(
                model=prompt.llm_model,
                max_tokens=prompt.max_tokens,
                temperature=prompt.temperature,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.user}],
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001 — wrap as our error
            raise LLMCallError(
                f"anthropic_messages_create_failed: {exc}",
            ) from exc

        text = _extract_text(resp)
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            model=getattr(resp, "model", prompt.llm_model),
            stop_reason=getattr(resp, "stop_reason", "end_turn") or "end_turn",
        )


def _extract_text(resp: Any) -> str:
    """Pull the plain-text content out of an Anthropic Message response.

    The SDK returns ``content`` as a list of ``ContentBlock`` objects;
    we concatenate the ``text`` blocks.
    """
    content = getattr(resp, "content", None) or []
    pieces: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            pieces.append(text)
    return "".join(pieces)


# ---------------------------------------------------------------------------
# Mock client (tests)
# ---------------------------------------------------------------------------


@dataclass
class MockLLMClient:
    """Test-only :class:`LLMClient` backed by a queue of canned responses.

    Two queues:

    - ``responses``: text strings or :class:`LLMResponse` instances
      handed out in order on successful calls.
    - ``error_queue``: per-call exceptions to raise *before* consuming
      from ``responses``. Use for failure-injection (e.g. simulating a
      transient timeout that the dispatcher should retry past).

    Use ``responses=["...", "..."]`` for the simple happy path, or
    ``error_queue=[LLMCallError("timeout"), None]`` to simulate one
    transient failure followed by success.
    """

    responses: list[str | LLMResponse] = field(default_factory=list)
    error_queue: list[Exception | None] = field(default_factory=list)
    call_log: list[PromptPayload] = field(default_factory=list)

    def complete(self, prompt: PromptPayload) -> LLMResponse:
        self.call_log.append(prompt)

        # Pop the next error (if any). ``None`` slots mean "no error
        # for this call".
        if self.error_queue:
            err = self.error_queue.pop(0)
            if err is not None:
                raise err

        if not self.responses:
            raise LLMCallError(
                "MockLLMClient: response queue exhausted",
            )
        nxt = self.responses.pop(0)
        if isinstance(nxt, LLMResponse):
            return nxt
        return LLMResponse(
            text=nxt,
            input_tokens=0,
            output_tokens=len(nxt) // 4,  # rough heuristic for tests
            model=prompt.llm_model,
        )

    @classmethod
    def with_responses(
        cls,
        responses: Iterable[str | LLMResponse],
    ) -> MockLLMClient:
        return cls(responses=list(responses))


__all__ = [
    "AnthropicLLMClient",
    "LLMCallError",
    "LLMClient",
    "LLMResponse",
    "MockLLMClient",
]
