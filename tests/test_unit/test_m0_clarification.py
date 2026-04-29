"""Pass 7 — clarification protocol orchestrator tests (§9.4).

One round-trip cap, response generation, T1-friendly dialog shape, length
budget warning, LLM-unavailable degradation.
"""

from __future__ import annotations

import pytest

from artha.common.standards import (
    CLARIFICATION_MAX_ROUNDS,
    CLARIFICATION_RESPONSE_TOKEN_MAX,
    ClarificationRequest,
)
from artha.llm.providers.mock import MockProvider
from artha.m0.clarification import (
    ClarificationCapExceededError,
    M0ClarificationProtocol,
)


def _request(
    *,
    requesting_agent: str = "e6_aif_cat_2",
    field: str = "commitment_period_status",
) -> ClarificationRequest:
    return ClarificationRequest(
        requesting_agent=requesting_agent,
        clarification_field=field,
        reason=f"{field} missing from input bundle",
        candidate_values=[],
    )


# ===========================================================================
# Stub response (no LLM)
# ===========================================================================


@pytest.mark.asyncio
async def test_stub_response_returned_without_provider():
    proto = M0ClarificationProtocol()
    dialog = await proto.respond("case_001", _request())
    assert dialog.response_text is not None
    assert dialog.responding_actor == "m0_stub"
    assert dialog.response_token_count is not None
    assert dialog.response_token_count > 0


@pytest.mark.asyncio
async def test_stub_response_includes_field_name():
    proto = M0ClarificationProtocol()
    dialog = await proto.respond("case_001", _request(field="redemption_window"))
    assert "redemption_window" in (dialog.response_text or "")


# ===========================================================================
# §9.4 — One round-trip cap
# ===========================================================================


@pytest.mark.asyncio
async def test_one_round_trip_cap_enforced():
    proto = M0ClarificationProtocol()
    await proto.respond("case_001", _request())
    with pytest.raises(ClarificationCapExceededError):
        await proto.respond("case_001", _request())


@pytest.mark.asyncio
async def test_different_agents_have_independent_budgets():
    proto = M0ClarificationProtocol()
    await proto.respond(
        "case_001", _request(requesting_agent="e1_financial_risk")
    )
    # Different agent — cap not exceeded
    dialog = await proto.respond(
        "case_001", _request(requesting_agent="e6_aif_cat_2")
    )
    assert dialog.response_text is not None


@pytest.mark.asyncio
async def test_different_cases_have_independent_budgets():
    proto = M0ClarificationProtocol()
    await proto.respond("case_001", _request())
    # Same agent but different case
    dialog = await proto.respond("case_002", _request())
    assert dialog.response_text is not None


@pytest.mark.asyncio
async def test_remaining_budget_starts_at_max():
    proto = M0ClarificationProtocol()
    assert proto.remaining_budget("case_001", "e6_aif_cat_2") == CLARIFICATION_MAX_ROUNDS


@pytest.mark.asyncio
async def test_remaining_budget_zero_after_use():
    proto = M0ClarificationProtocol()
    await proto.respond("case_001", _request())
    assert proto.remaining_budget("case_001", "e6_aif_cat_2") == 0


@pytest.mark.asyncio
async def test_reset_clears_round_trips():
    proto = M0ClarificationProtocol()
    await proto.respond("case_001", _request())
    proto.reset()
    # After reset, the cap is fresh
    dialog = await proto.respond("case_001", _request())
    assert dialog.response_text is not None


# ===========================================================================
# LLM-backed response
# ===========================================================================


@pytest.mark.asyncio
async def test_llm_response_used_when_provider_given():
    mock = MockProvider()
    mock.set_response(
        "Field requested:",
        "The commitment period extends through 2031-06-15 per the fund prospectus, "
        "with quarterly capital calls expected through Q2 2027.",
    )
    proto = M0ClarificationProtocol(provider=mock)
    dialog = await proto.respond("case_001", _request())
    assert dialog.responding_actor == "m0"
    assert "2031-06-15" in (dialog.response_text or "")


@pytest.mark.asyncio
async def test_llm_failure_falls_back_with_clear_message():
    class _FailingProvider:
        name = "failing"

        async def complete(self, request):
            raise RuntimeError("LLM unavailable")

        async def complete_structured(self, request, output_type):
            raise RuntimeError("LLM unavailable")

    proto = M0ClarificationProtocol(provider=_FailingProvider())
    dialog = await proto.respond("case_001", _request())
    # Service emits a graceful degradation message rather than raising
    assert dialog.response_text is not None
    assert "unavailable" in dialog.response_text.lower()


# ===========================================================================
# Length budget surfaces warning but doesn't reject
# ===========================================================================


@pytest.mark.asyncio
async def test_oversize_response_still_returned_with_count():
    mock = MockProvider()
    mock.set_response("Field requested:", " ".join(["word"] * 500))
    proto = M0ClarificationProtocol(provider=mock)
    dialog = await proto.respond("case_001", _request())
    # Service warns but doesn't reject — A1 surfaces the over-budget event
    assert dialog.response_text is not None
    assert dialog.response_token_count is not None
    assert dialog.response_token_count > CLARIFICATION_RESPONSE_TOKEN_MAX


# ===========================================================================
# Dialog shape captures both halves verbatim
# ===========================================================================


@pytest.mark.asyncio
async def test_dialog_request_preserved():
    proto = M0ClarificationProtocol()
    request = _request(field="capital_call_schedule")
    dialog = await proto.respond("case_001", request)
    assert dialog.request == request
    assert dialog.response_text is not None
