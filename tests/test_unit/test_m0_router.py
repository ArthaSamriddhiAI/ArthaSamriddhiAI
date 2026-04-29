"""Pass 6 — M0.Router tests against §8.3.8 acceptance.

Pre-tag agreement, override on contradiction, ambiguity surfacing,
schema compliance, determinism, and the LLM-unavailable fallback path.
"""

from __future__ import annotations

import pytest

from artha.canonical.case import CaseChannel
from artha.canonical.m0_router import (
    M0RouterClassification,
    M0RouterInput,
    M0RouterOutput,
)
from artha.common.types import CaseIntent, RunMode
from artha.llm.providers.mock import MockProvider
from artha.m0.router import (
    HIGH_PRE_TAG_CONFIDENCE,
    LOW_CONFIDENCE_THRESHOLD,
    M0Router,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _mock_with_classification(
    intent: CaseIntent, confidence: float = 0.9, reasoning: str = "ok"
) -> MockProvider:
    """Return a MockProvider that emits the given classification on any prompt."""
    mock = MockProvider()
    mock.set_structured_response(
        "Classify the intent",  # text always present in our user prompt
        {
            "intent_type_value": intent.value,
            "confidence": confidence,
            "reasoning": reasoning,
        },
    )
    return mock


class _FailingProvider:
    """Mock that raises on any LLM call — exercises the §8.3.7 fallback path."""

    name = "failing"

    async def complete(self, request):  # pragma: no cover (router uses structured only)
        raise RuntimeError("LLM unavailable")

    async def complete_structured(self, request, output_type):
        raise RuntimeError("LLM unavailable")


# ===========================================================================
# Section 8.3.8 Test 1 — pre-tag agreement
# ===========================================================================


@pytest.mark.asyncio
async def test_high_confidence_pre_tag_is_confirmed_without_llm():
    # Mock provider that would crash if called; only the deterministic path should run
    router = M0Router(_FailingProvider())
    input = M0RouterInput(
        channel=CaseChannel.C0,
        pre_tag=CaseIntent.CASE,
        pre_tag_confidence=0.95,
        payload={"client_id": "c1", "case_topic": "evaluate Cat II AIF"},
    )
    out = await router.classify(input)
    assert out.intent_type is CaseIntent.CASE
    assert out.intent_confidence == pytest.approx(0.95)
    assert out.routing_metadata.get("path") == "pre_tag_confirmed"
    assert out.clarification_required is False


@pytest.mark.asyncio
async def test_pre_tag_at_high_confidence_threshold_confirmed():
    router = M0Router(_FailingProvider())
    input = M0RouterInput(
        channel=CaseChannel.FORM,
        pre_tag=CaseIntent.REBALANCE_TRIGGER,
        pre_tag_confidence=HIGH_PRE_TAG_CONFIDENCE,
        payload={"client_id": "c1"},
    )
    out = await router.classify(input)
    assert out.intent_type is CaseIntent.REBALANCE_TRIGGER


# ===========================================================================
# Section 8.3.8 Test 2 — override on contradiction (low pre-tag → LLM)
# ===========================================================================


@pytest.mark.asyncio
async def test_low_confidence_pre_tag_triggers_llm_override():
    # Pre-tag says knowledge_query at 0.5; LLM classifies as case at 0.85
    mock = _mock_with_classification(CaseIntent.CASE, confidence=0.85)
    router = M0Router(mock)
    input = M0RouterInput(
        channel=CaseChannel.C0,
        pre_tag=CaseIntent.KNOWLEDGE_QUERY,
        pre_tag_confidence=0.5,
        payload={"text": "Should I add this Cat II AIF for client c1?"},
    )
    out = await router.classify(input)
    assert out.intent_type is CaseIntent.CASE
    assert out.intent_confidence == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_no_pre_tag_invokes_llm():
    mock = _mock_with_classification(CaseIntent.DIAGNOSTIC, confidence=0.9)
    router = M0Router(mock)
    input = M0RouterInput(
        channel=CaseChannel.C0,
        payload={"text": "How is Sharma's portfolio doing?"},
    )
    out = await router.classify(input)
    assert out.intent_type is CaseIntent.DIAGNOSTIC


# ===========================================================================
# Section 8.3.8 Test 3 — ambiguity surfacing (clarification)
# ===========================================================================


@pytest.mark.asyncio
async def test_low_llm_confidence_triggers_clarification():
    # LLM returns confidence 0.3 (below threshold)
    mock = _mock_with_classification(CaseIntent.CASE, confidence=0.3, reasoning="ambiguous")
    router = M0Router(mock)
    input = M0RouterInput(
        channel=CaseChannel.C0,
        payload={"text": "remind me what we did last quarter"},
    )
    out = await router.classify(input)
    assert out.clarification_required is True
    assert out.clarification_payload is not None
    assert out.intent_confidence == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_clarification_threshold_boundary():
    # At exactly LOW_CONFIDENCE_THRESHOLD, no clarification
    mock = _mock_with_classification(CaseIntent.CASE, confidence=LOW_CONFIDENCE_THRESHOLD)
    router = M0Router(mock)
    input = M0RouterInput(channel=CaseChannel.C0, payload={"text": "x"})
    out = await router.classify(input)
    assert out.clarification_required is False


# ===========================================================================
# Section 8.3.8 Test 4 — schema compliance
# ===========================================================================


@pytest.mark.asyncio
async def test_router_output_round_trips_via_json():
    mock = _mock_with_classification(CaseIntent.CASE, confidence=0.9)
    router = M0Router(mock)
    input = M0RouterInput(
        channel=CaseChannel.C0,
        payload={"client_id": "c1", "text": "evaluate Cat II AIF"},
    )
    out = await router.classify(input)
    round_tripped = M0RouterOutput.model_validate_json(out.model_dump_json())
    assert round_tripped == out


@pytest.mark.asyncio
async def test_invalid_intent_string_from_llm_emits_clarification():
    """LLM returns a string not in CaseIntent enum → Router surfaces clarification."""
    mock = MockProvider()
    mock.set_structured_response(
        "Classify the intent",
        {"intent_type_value": "not_a_canonical_intent", "confidence": 0.9, "reasoning": ""},
    )
    router = M0Router(mock)
    input = M0RouterInput(channel=CaseChannel.C0, payload={"text": "x"})
    out = await router.classify(input)
    assert out.clarification_required is True
    assert out.routing_metadata.get("path") == "llm_invalid_intent"


# ===========================================================================
# Section 8.3.8 Test 5 — determinism
# ===========================================================================


@pytest.mark.asyncio
async def test_same_input_same_provider_same_output():
    mock = _mock_with_classification(CaseIntent.CASE, confidence=0.9)
    router = M0Router(mock)
    input = M0RouterInput(
        channel=CaseChannel.C0,
        pre_tag=CaseIntent.CASE,
        pre_tag_confidence=0.95,
        payload={"client_id": "c1"},
    )
    out_a = await router.classify(input)
    out_b = await router.classify(input)
    assert out_a == out_b


# ===========================================================================
# Section 8.3.7 — LLM unavailable fallback
# ===========================================================================


@pytest.mark.asyncio
async def test_llm_unavailable_falls_back_to_pre_tag():
    router = M0Router(_FailingProvider())
    input = M0RouterInput(
        channel=CaseChannel.C0,
        pre_tag=CaseIntent.CASE,
        pre_tag_confidence=0.6,  # below the high threshold so LLM would normally run
        payload={"client_id": "c1"},
    )
    out = await router.classify(input)
    assert out.intent_type is CaseIntent.CASE
    assert out.routing_metadata.get("path") == "llm_unavailable_pre_tag_fallback"
    # Confidence is downgraded to reflect LLM unavailability
    assert out.intent_confidence < 0.6


@pytest.mark.asyncio
async def test_llm_unavailable_no_pre_tag_surfaces_clarification():
    router = M0Router(_FailingProvider())
    input = M0RouterInput(channel=CaseChannel.C0, payload={"text": "x"})
    out = await router.classify(input)
    assert out.clarification_required is True
    assert out.routing_metadata.get("path") == "llm_unavailable_no_pre_tag"


# ===========================================================================
# Pipeline mode plumbing (Thesis 4.2)
# ===========================================================================


@pytest.mark.asyncio
async def test_router_emits_run_mode_case_for_case_intent():
    mock = _mock_with_classification(CaseIntent.CASE, confidence=0.9)
    router = M0Router(mock)
    out = await router.classify(M0RouterInput(channel=CaseChannel.C0, payload={"text": "x"}))
    assert out.run_mode is RunMode.CASE


@pytest.mark.asyncio
async def test_router_emits_diagnostic_run_mode_for_diagnostic_intent():
    mock = _mock_with_classification(CaseIntent.DIAGNOSTIC, confidence=0.9)
    router = M0Router(mock)
    input_event = M0RouterInput(channel=CaseChannel.C0, payload={"text": "health check"})
    out = await router.classify(input_event)
    assert out.run_mode is RunMode.DIAGNOSTIC


@pytest.mark.asyncio
async def test_router_emits_briefing_run_mode_for_briefing_intent():
    mock = _mock_with_classification(CaseIntent.BRIEFING, confidence=0.9)
    router = M0Router(mock)
    out = await router.classify(M0RouterInput(channel=CaseChannel.C0, payload={"text": "brief me"}))
    assert out.run_mode is RunMode.BRIEFING


# ===========================================================================
# Routing metadata
# ===========================================================================


@pytest.mark.asyncio
async def test_routing_metadata_carries_client_id_when_present():
    router = M0Router(_FailingProvider())
    input = M0RouterInput(
        channel=CaseChannel.FORM,
        pre_tag=CaseIntent.CASE,
        pre_tag_confidence=0.95,
        payload={"client_id": "c42", "case_topic": "Cat II AIF"},
    )
    out = await router.classify(input)
    assert out.routing_metadata["client_id"] == "c42"
    assert out.routing_metadata["case_topic"] == "Cat II AIF"
    assert out.routing_metadata["intent_type"] == "case"


@pytest.mark.asyncio
async def test_routing_metadata_carries_alert_id_for_monitoring_response():
    router = M0Router(_FailingProvider())
    input = M0RouterInput(
        channel=CaseChannel.N0_RESPONSE,
        pre_tag=CaseIntent.MONITORING_RESPONSE,
        pre_tag_confidence=0.95,
        payload={"alert_id": "alert_001"},
    )
    out = await router.classify(input)
    assert out.routing_metadata["alert_id"] == "alert_001"


# ===========================================================================
# Internal classification schema
# ===========================================================================


def test_m0_router_classification_round_trips():
    c = M0RouterClassification(
        intent_type_value="case",
        confidence=0.9,
        reasoning="explicit case keywords detected",
    )
    round_tripped = M0RouterClassification.model_validate_json(c.model_dump_json())
    assert round_tripped == c
