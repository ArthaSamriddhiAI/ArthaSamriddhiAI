"""Cluster 1 chunk 1.2 — C0 LLM client wrapper tests.

The wrapper turns SmartLLMRouter responses into the C0-shaped result
types (``IntentDetectionResult`` / ``SlotExtractionResult``) and turns
every router-side failure mode into a typed :class:`LLMFallback`.

Tests stub :class:`SmartLLMRouter.call` directly so we don't depend on a
configured provider or network.
"""

from __future__ import annotations

import pytest

from artha.api_v2.c0 import llm_client
from artha.api_v2.c0.llm_client import LLMFallback
from artha.api_v2.llm.providers import LLMCallResponse
from artha.api_v2.llm.router_runtime import (
    LLMCallFailedError,
    LLMKillSwitchActiveError,
    LLMNotConfiguredError,
)


class _StubRouter:
    """Minimal SmartLLMRouter stand-in that returns whatever is configured."""

    def __init__(self, *, content: str | None = None, raises: Exception | None = None):
        self._content = content
        self._raises = raises
        self.last_request = None

    async def call(self, db, request):  # noqa: ARG002 — db unused in stub
        self.last_request = request
        if self._raises is not None:
            raise self._raises
        return LLMCallResponse(
            content=self._content or "",
            provider="mistral",
            model="mistral-small-latest",
            tokens_used=10,
            latency_ms=42,
            request_id="req-stub",
        )


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------


class TestDetectIntent:
    @pytest.mark.asyncio
    async def test_happy_path_parses_intent_and_fields(self):
        router = _StubRouter(
            content='{"intent": "investor_onboarding", '
            '"extracted_fields": {"name": "Rajesh Kumar"}}'
        )
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="onboard rajesh"
        )
        assert not isinstance(result, LLMFallback)
        assert result.intent == "investor_onboarding"
        assert result.extracted_fields == {"name": "Rajesh Kumar"}
        assert result.llm_provider == "mistral"
        assert result.llm_latency_ms == 42

    @pytest.mark.asyncio
    async def test_extracted_fields_default_to_empty_dict(self):
        router = _StubRouter(
            content='{"intent": "investor_onboarding"}'
        )
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="hi"
        )
        assert not isinstance(result, LLMFallback)
        assert result.extracted_fields == {}

    @pytest.mark.asyncio
    async def test_intent_defaults_to_general_question_when_missing(self):
        router = _StubRouter(content='{"extracted_fields": {}}')
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="hi"
        )
        assert not isinstance(result, LLMFallback)
        assert result.intent == "general_question"

    @pytest.mark.asyncio
    async def test_age_string_is_coerced_to_int(self):
        router = _StubRouter(
            content='{"intent": "investor_onboarding", '
            '"extracted_fields": {"age": "30"}}'
        )
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="he's 30"
        )
        assert result.extracted_fields["age"] == 30

    @pytest.mark.asyncio
    async def test_strips_markdown_fences_around_json(self):
        router = _StubRouter(
            content='```json\n{"intent": "investor_onboarding", "extracted_fields": {}}\n```'
        )
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="hi"
        )
        assert not isinstance(result, LLMFallback)
        assert result.intent == "investor_onboarding"

    @pytest.mark.asyncio
    async def test_malformed_json_returns_fallback(self):
        router = _StubRouter(content="not json at all")
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="hi"
        )
        assert isinstance(result, LLMFallback)
        assert result.failure_type == "malformed_response"

    @pytest.mark.asyncio
    async def test_not_configured_returns_fallback(self):
        router = _StubRouter(raises=LLMNotConfiguredError("not configured"))
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="hi"
        )
        assert isinstance(result, LLMFallback)
        assert result.failure_type == "not_configured"

    @pytest.mark.asyncio
    async def test_kill_switch_returns_fallback(self):
        router = _StubRouter(raises=LLMKillSwitchActiveError("killed"))
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="hi"
        )
        assert isinstance(result, LLMFallback)
        assert result.failure_type == "kill_switch"

    @pytest.mark.asyncio
    async def test_provider_failure_returns_fallback_with_failure_type(self):
        router = _StubRouter(
            raises=LLMCallFailedError(
                "auth failed", failure_type="auth_error", provider="mistral"
            )
        )
        result = await llm_client.detect_intent(
            db=None, router=router, user_message="hi"
        )
        assert isinstance(result, LLMFallback)
        assert result.failure_type == "auth_error"

    @pytest.mark.asyncio
    async def test_request_marked_json_response_format(self):
        router = _StubRouter(content='{"intent": "general_question", "extracted_fields": {}}')
        await llm_client.detect_intent(
            db=None, router=router, user_message="hi"
        )
        assert router.last_request.response_format == "json"
        assert router.last_request.caller_id == "c0_intent_detector"


# ---------------------------------------------------------------------------
# Slot extraction
# ---------------------------------------------------------------------------


class TestExtractSlots:
    @pytest.mark.asyncio
    async def test_happy_path_parses_fields_and_confidence(self):
        router = _StubRouter(
            content='{"extracted_fields": {"email": "x@example.com", "phone": "+919876543210"}, '
            '"extraction_confidence": "high"}'
        )
        result = await llm_client.extract_slots(
            db=None,
            router=router,
            user_response="x@example.com and 9876543210",
            current_prompt="What's the email and phone?",
            expected_fields=["email", "phone"],
        )
        assert not isinstance(result, LLMFallback)
        assert result.extracted_fields == {
            "email": "x@example.com",
            "phone": "+919876543210",
        }
        assert result.extraction_confidence == "high"

    @pytest.mark.asyncio
    async def test_invalid_confidence_normalises_to_medium(self):
        router = _StubRouter(
            content='{"extracted_fields": {"name": "X"}, "extraction_confidence": "weird"}'
        )
        result = await llm_client.extract_slots(
            db=None,
            router=router,
            user_response="X",
            current_prompt="name?",
            expected_fields=["name"],
        )
        assert not isinstance(result, LLMFallback)
        assert result.extraction_confidence == "medium"

    @pytest.mark.asyncio
    async def test_risk_appetite_lowered_and_underscored(self):
        router = _StubRouter(
            content='{"extracted_fields": {"risk_appetite": "Moderate"}, '
            '"extraction_confidence": "high"}'
        )
        result = await llm_client.extract_slots(
            db=None,
            router=router,
            user_response="moderate",
            current_prompt="risk?",
            expected_fields=["risk_appetite"],
        )
        assert result.extracted_fields["risk_appetite"] == "moderate"

    @pytest.mark.asyncio
    async def test_time_horizon_with_spaces_underscored(self):
        router = _StubRouter(
            content='{"extracted_fields": {"time_horizon": "over 5 years"}, '
            '"extraction_confidence": "high"}'
        )
        result = await llm_client.extract_slots(
            db=None,
            router=router,
            user_response="over 5 years",
            current_prompt="horizon?",
            expected_fields=["time_horizon"],
        )
        assert result.extracted_fields["time_horizon"] == "over_5_years"

    @pytest.mark.asyncio
    async def test_empty_string_value_is_dropped(self):
        router = _StubRouter(
            content='{"extracted_fields": {"name": "X", "age": ""}, '
            '"extraction_confidence": "high"}'
        )
        result = await llm_client.extract_slots(
            db=None,
            router=router,
            user_response="X",
            current_prompt="name?",
            expected_fields=["name", "age"],
        )
        assert "age" not in result.extracted_fields
        assert result.extracted_fields["name"] == "X"

    @pytest.mark.asyncio
    async def test_malformed_json_returns_fallback(self):
        router = _StubRouter(content="not json")
        result = await llm_client.extract_slots(
            db=None,
            router=router,
            user_response="X",
            current_prompt="name?",
            expected_fields=["name"],
        )
        assert isinstance(result, LLMFallback)
        assert result.failure_type == "malformed_response"

    @pytest.mark.asyncio
    async def test_router_failure_returns_fallback(self):
        router = _StubRouter(
            raises=LLMCallFailedError(
                "rate limit", failure_type="rate_limit", provider="mistral"
            )
        )
        result = await llm_client.extract_slots(
            db=None,
            router=router,
            user_response="X",
            current_prompt="name?",
            expected_fields=["name"],
        )
        assert isinstance(result, LLMFallback)
        assert result.failure_type == "rate_limit"
