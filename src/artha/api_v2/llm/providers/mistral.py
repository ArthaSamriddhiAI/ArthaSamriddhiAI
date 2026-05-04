"""Mistral provider adapter — FR Entry 16.0 §3.1.

Talks to ``https://api.mistral.ai/v1/chat/completions`` via :mod:`httpx`.
Default model: ``mistral-small-latest`` (the free-tier model adequate for
cluster 1's intent + extraction work).

Native ``response_format`` support (``{"type": "json_object"}``) is used
when the caller asks for ``response_format="json"`` so the LLM is
constrained to valid JSON output. (Anthropic, by contrast, has no such
parameter — see :mod:`artha.api_v2.llm.providers.claude`.)
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from artha.api_v2.llm.providers.base import (
    LLMCallRequest,
    LLMCallResponse,
    Message,
    ProviderAdapter,
    ProviderAuthError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralAdapter(ProviderAdapter):
    """Concrete adapter for Mistral's chat completions endpoint."""

    provider_name = "mistral"

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
                    MISTRAL_API_URL,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Mistral request timed out after {timeout_seconds}s",
                provider=self.provider_name,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderTransientError(
                f"Mistral network error: {exc}", provider=self.provider_name
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        if http_response.status_code in (401, 403):
            raise ProviderAuthError(
                "Mistral rejected the configured API key (status %d)"
                % http_response.status_code,
                provider=self.provider_name,
            )
        if http_response.status_code == 429:
            raise ProviderRateLimitError(
                "Mistral rate limit hit (status 429)",
                provider=self.provider_name,
            )
        if 500 <= http_response.status_code < 600:
            raise ProviderTransientError(
                "Mistral server error (status %d)" % http_response.status_code,
                provider=self.provider_name,
            )
        if http_response.status_code >= 400:
            # Other 4xx — bad-request shaped, treat as malformed by adapter so
            # we surface it without retrying.
            raise ProviderInvalidResponseError(
                "Mistral rejected the request (status %d): %s"
                % (http_response.status_code, http_response.text[:500]),
                provider=self.provider_name,
            )

        try:
            payload = http_response.json()
        except ValueError as exc:
            raise ProviderInvalidResponseError(
                f"Mistral response was not valid JSON: {exc}",
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
    """Translate the router's :class:`LLMCallRequest` into Mistral's payload."""
    if request.messages:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
    else:
        # No structured turn list — wrap the prompt as a single user message
        # (Mistral requires at least one ``user`` turn).
        messages = [{"role": "user", "content": request.prompt or ""}]

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    }
    if request.response_format == "json":
        # Mistral's native JSON mode (per https://docs.mistral.ai/api/).
        body["response_format"] = {"type": "json_object"}
    return body


def _parse_response(
    payload: dict[str, Any],
    *,
    request_id: str,
    model: str,
    latency_ms: int,
    provider_name: str,
) -> LLMCallResponse:
    """Pull content + token counts from Mistral's response shape."""
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderInvalidResponseError(
            f"Mistral response missing content: {exc}", provider=provider_name
        ) from exc

    usage = payload.get("usage") or {}
    tokens_used = int(usage.get("total_tokens", 0))

    return LLMCallResponse(
        content=content,
        provider=provider_name,
        model=str(payload.get("model") or model),
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        request_id=request_id,
        raw=payload,
    )


def _silence_unused_message_import() -> None:  # pragma: no cover
    # Keep the Message import alive for type completeness when callers wire
    # multi-turn requests through this module.
    _ = Message
