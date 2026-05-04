"""Claude provider adapter — FR Entry 16.0 §3.2.

Talks to Anthropic's Messages API at ``https://api.anthropic.com/v1/messages``
via :mod:`httpx`. Default model: ``claude-sonnet-4-5-20250929`` (cost-
effective for cluster 1's bounded tasks; per-agent tiering with Opus is
deferred to v2).

Anthropic has no native ``response_format`` parameter — JSON mode is
prompt-driven. When the caller passes ``response_format="json"`` the
adapter prepends a system prompt instructing the model to reply with valid
JSON only; the executor (one level up) is responsible for any further
parsing or re-prompting.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from artha.api_v2.llm.providers.base import (
    LLMCallRequest,
    LLMCallResponse,
    ProviderAdapter,
    ProviderAuthError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
)

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_API_VERSION = "2023-06-01"

JSON_MODE_SYSTEM_PROMPT = (
    "Reply with a single valid JSON object and no surrounding prose. "
    "Do not wrap the JSON in markdown fences."
)


class ClaudeAdapter(ProviderAdapter):
    """Concrete adapter for Anthropic's Messages API."""

    provider_name = "claude"

    async def complete(
        self, request: LLMCallRequest, *, timeout_seconds: int
    ) -> LLMCallResponse:
        model = request.model or self._default_model
        body = _build_request_body(request, model=model)
        request_id = str(uuid.uuid4())

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                http_response = await client.post(
                    CLAUDE_API_URL,
                    json=body,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": CLAUDE_API_VERSION,
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Claude request timed out after {timeout_seconds}s",
                provider=self.provider_name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderTransientError(
                f"Claude network error: {exc}", provider=self.provider_name
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if http_response.status_code in (401, 403):
            raise ProviderAuthError(
                "Claude rejected the configured API key (status %d)"
                % http_response.status_code,
                provider=self.provider_name,
            )
        if http_response.status_code == 429:
            raise ProviderRateLimitError(
                "Claude rate limit hit (status 429)",
                provider=self.provider_name,
            )
        if 500 <= http_response.status_code < 600:
            raise ProviderTransientError(
                "Claude server error (status %d)" % http_response.status_code,
                provider=self.provider_name,
            )
        if http_response.status_code >= 400:
            raise ProviderInvalidResponseError(
                "Claude rejected the request (status %d): %s"
                % (http_response.status_code, http_response.text[:500]),
                provider=self.provider_name,
            )

        try:
            payload = http_response.json()
        except ValueError as exc:
            raise ProviderInvalidResponseError(
                f"Claude response was not valid JSON: {exc}",
                provider=self.provider_name,
            ) from exc

        return _parse_response(
            payload,
            request_id=request_id,
            model=model,
            latency_ms=latency_ms,
            provider_name=self.provider_name,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_request_body(request: LLMCallRequest, *, model: str) -> dict[str, Any]:
    """Translate the router's :class:`LLMCallRequest` into Anthropic's payload.

    Anthropic separates the ``system`` prompt from ``messages``; we do too.
    JSON mode is prompt-driven — the system slot gets the JSON instruction.
    """
    user_messages: list[dict[str, Any]] = []
    system_chunks: list[str] = []

    if request.messages:
        for m in request.messages:
            if m.role == "system":
                system_chunks.append(m.content)
            else:
                user_messages.append({"role": m.role, "content": m.content})
    else:
        user_messages.append({"role": "user", "content": request.prompt or ""})

    if request.response_format == "json":
        system_chunks.insert(0, JSON_MODE_SYSTEM_PROMPT)

    body: dict[str, Any] = {
        "model": model,
        "messages": user_messages,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    }
    if system_chunks:
        body["system"] = "\n\n".join(system_chunks)
    return body


def _parse_response(
    payload: dict[str, Any],
    *,
    request_id: str,
    model: str,
    latency_ms: int,
    provider_name: str,
) -> LLMCallResponse:
    """Pull content + token counts from Anthropic's response shape.

    Anthropic returns ``content`` as a list of blocks (``[{"type": "text",
    "text": "..."}, ...]``); we concatenate any ``text`` blocks into one
    string so the router stays text-shape regardless of provider.
    """
    blocks = payload.get("content")
    if not isinstance(blocks, list) or not blocks:
        raise ProviderInvalidResponseError(
            "Claude response missing content blocks", provider=provider_name
        )

    text_parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
    if not text_parts:
        raise ProviderInvalidResponseError(
            "Claude response had no text blocks", provider=provider_name
        )

    usage = payload.get("usage") or {}
    tokens_used = int(usage.get("input_tokens", 0)) + int(
        usage.get("output_tokens", 0)
    )

    return LLMCallResponse(
        content="\n".join(text_parts),
        provider=provider_name,
        model=str(payload.get("model") or model),
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        request_id=request_id,
        raw=payload,
    )
