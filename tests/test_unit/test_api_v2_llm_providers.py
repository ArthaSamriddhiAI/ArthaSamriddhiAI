"""Cluster 1 chunk 1.3 — provider-adapter test suite.

Covers Mistral + Claude adapters via :class:`httpx.MockTransport`:

- happy-path round-trip + response parsing
- request body shape (JSON mode for both)
- 401/403 → ``ProviderAuthError``
- 429 → ``ProviderRateLimitError``
- 5xx → ``ProviderTransientError``
- timeout → ``ProviderTimeoutError``
- malformed JSON → ``ProviderInvalidResponseError``

Per FR Entry 16.0 §3.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

import artha.api_v2.llm.providers.claude as claude_mod
import artha.api_v2.llm.providers.mistral as mistral_mod
from artha.api_v2.llm.providers import (
    ClaudeAdapter,
    LLMCallRequest,
    Message,
    MistralAdapter,
    ProviderAuthError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
)

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _make_mistral_response(content: str = "OK", total_tokens: int = 5) -> dict[str, Any]:
    return {
        "id": "mistral-resp-1",
        "model": "mistral-small-latest",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": total_tokens},
    }


def _make_claude_response(
    text: str = "OK", in_tokens: int = 3, out_tokens: int = 2
) -> dict[str, Any]:
    return {
        "id": "msg_01ABC",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5-20250929",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": in_tokens, "output_tokens": out_tokens},
    }


def _patch_httpx(monkeypatch, handler):
    """Swap :class:`httpx.AsyncClient` for one driven by ``handler``."""

    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        # Drop pre-existing transport (if any) and inject the mock.
        kwargs.pop("transport", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# ===========================================================================
# 1. Mistral adapter
# ===========================================================================


class TestMistralAdapter:
    @pytest.mark.asyncio
    async def test_happy_path_returns_response(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=_make_mistral_response("OK"))

        _patch_httpx(monkeypatch, handler)

        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        resp = await adapter.complete(
            LLMCallRequest(caller_id="test", prompt="hi"),
            timeout_seconds=10,
        )
        assert resp.content == "OK"
        assert resp.provider == "mistral"
        assert resp.model == "mistral-small-latest"
        assert resp.tokens_used == 5
        assert captured["url"] == mistral_mod.MISTRAL_API_URL
        assert captured["auth"] == "Bearer sk-test"
        assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
        assert captured["body"]["model"] == "mistral-small-latest"

    @pytest.mark.asyncio
    async def test_json_response_format_sets_response_format(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_make_mistral_response('{"k":1}'))

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        await adapter.complete(
            LLMCallRequest(caller_id="t", prompt="give json", response_format="json"),
            timeout_seconds=10,
        )
        assert captured["body"]["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_messages_list_passed_through(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_make_mistral_response())

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        msgs = [
            Message(role="system", content="You are concise."),
            Message(role="user", content="Hello"),
        ]
        await adapter.complete(
            LLMCallRequest(caller_id="t", messages=msgs),
            timeout_seconds=10,
        )
        assert captured["body"]["messages"] == [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Hello"},
        ]

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, monkeypatch):
        def handler(request):
            return httpx.Response(401, json={"error": "bad key"})

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-bad", default_model="mistral-small-latest")
        with pytest.raises(ProviderAuthError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit(self, monkeypatch):
        def handler(request):
            return httpx.Response(429, json={"error": "rate limit"})

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        with pytest.raises(ProviderRateLimitError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_500_raises_transient(self, monkeypatch):
        def handler(request):
            return httpx.Response(503, text="upstream busy")

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        with pytest.raises(ProviderTransientError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_400_raises_invalid_response(self, monkeypatch):
        def handler(request):
            return httpx.Response(400, text="bad request")

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        with pytest.raises(ProviderInvalidResponseError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout(self, monkeypatch):
        def handler(request):
            raise httpx.TimeoutException("simulated timeout")

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        with pytest.raises(ProviderTimeoutError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_malformed_response_body_raises_invalid_response(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, text="not json")

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        with pytest.raises(ProviderInvalidResponseError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_response_missing_choices_raises_invalid_response(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json={"choices": []})

        _patch_httpx(monkeypatch, handler)
        adapter = MistralAdapter(api_key="sk-test", default_model="mistral-small-latest")
        with pytest.raises(ProviderInvalidResponseError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    def test_constructor_rejects_empty_key(self):
        with pytest.raises(ValueError):
            MistralAdapter(api_key="", default_model="mistral-small-latest")


# ===========================================================================
# 2. Claude adapter
# ===========================================================================


class TestClaudeAdapter:
    @pytest.mark.asyncio
    async def test_happy_path_returns_response(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            captured["x_api_key"] = request.headers.get("x-api-key")
            captured["anthropic_version"] = request.headers.get("anthropic-version")
            return httpx.Response(200, json=_make_claude_response("OK"))

        _patch_httpx(monkeypatch, handler)
        adapter = ClaudeAdapter(api_key="sk-ant-test", default_model="claude-sonnet-4-5-20250929")
        resp = await adapter.complete(
            LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
        )
        assert resp.content == "OK"
        assert resp.provider == "claude"
        assert resp.tokens_used == 5
        assert captured["url"] == claude_mod.CLAUDE_API_URL
        assert captured["x_api_key"] == "sk-ant-test"
        assert captured["anthropic_version"] == claude_mod.CLAUDE_API_VERSION
        assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_json_response_format_prepends_system_prompt(self, monkeypatch):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_make_claude_response('{"k":1}'))

        _patch_httpx(monkeypatch, handler)
        adapter = ClaudeAdapter(api_key="sk-ant", default_model="claude-sonnet-4-5-20250929")
        await adapter.complete(
            LLMCallRequest(caller_id="t", prompt="give json", response_format="json"),
            timeout_seconds=10,
        )
        assert "JSON" in captured["body"]["system"]

    @pytest.mark.asyncio
    async def test_messages_split_system_from_chat(self, monkeypatch):
        captured = {}

        def handler(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_make_claude_response())

        _patch_httpx(monkeypatch, handler)
        adapter = ClaudeAdapter(api_key="sk-ant", default_model="claude-sonnet-4-5-20250929")
        await adapter.complete(
            LLMCallRequest(
                caller_id="t",
                messages=[
                    Message(role="system", content="Be concise."),
                    Message(role="user", content="Hello"),
                ],
            ),
            timeout_seconds=10,
        )
        assert captured["body"]["system"] == "Be concise."
        assert captured["body"]["messages"] == [{"role": "user", "content": "Hello"}]

    @pytest.mark.asyncio
    async def test_concatenates_multiple_text_blocks(self, monkeypatch):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "text", "text": "World"},
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                    "model": "claude-sonnet-4-5-20250929",
                },
            )

        _patch_httpx(monkeypatch, handler)
        adapter = ClaudeAdapter(api_key="sk-ant", default_model="claude-sonnet-4-5-20250929")
        resp = await adapter.complete(
            LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
        )
        assert resp.content == "Hello\nWorld"

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, monkeypatch):
        def handler(request):
            return httpx.Response(401, json={"error": "bad key"})

        _patch_httpx(monkeypatch, handler)
        adapter = ClaudeAdapter(api_key="sk-ant-bad", default_model="claude-sonnet-4-5-20250929")
        with pytest.raises(ProviderAuthError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit(self, monkeypatch):
        def handler(request):
            return httpx.Response(429, json={"error": "rate limit"})

        _patch_httpx(monkeypatch, handler)
        adapter = ClaudeAdapter(api_key="sk-ant", default_model="claude-sonnet-4-5-20250929")
        with pytest.raises(ProviderRateLimitError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_503_raises_transient(self, monkeypatch):
        def handler(request):
            return httpx.Response(503, text="busy")

        _patch_httpx(monkeypatch, handler)
        adapter = ClaudeAdapter(api_key="sk-ant", default_model="claude-sonnet-4-5-20250929")
        with pytest.raises(ProviderTransientError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )

    @pytest.mark.asyncio
    async def test_response_missing_text_block_raises_invalid_response(self, monkeypatch):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "tool_use", "name": "x"}],
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                },
            )

        _patch_httpx(monkeypatch, handler)
        adapter = ClaudeAdapter(api_key="sk-ant", default_model="claude-sonnet-4-5-20250929")
        with pytest.raises(ProviderInvalidResponseError):
            await adapter.complete(
                LLMCallRequest(caller_id="t", prompt="hi"), timeout_seconds=10
            )
