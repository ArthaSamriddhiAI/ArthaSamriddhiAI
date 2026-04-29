"""Pass 7 — M0.Briefer tests against §8.8.8 acceptance.

Length compliance, verdict-anticipation rejection, trigger appropriateness,
verbatim T1 capture, A1 accountability hook (lint flags surface).
"""

from __future__ import annotations

import pytest

from artha.canonical.m0_briefer import (
    BriefingTrigger,
    M0BrieferInput,
    M0BrieferOutput,
)
from artha.llm.providers.mock import MockProvider
from artha.m0.briefer import M0Briefer


def _briefer_with_response(text: str) -> M0Briefer:
    """Return a Briefer whose mock provider always emits `text` on completion."""
    mock = MockProvider()
    mock.set_response("Trigger:", text)  # match the user-prompt's "Trigger:" header
    return M0Briefer(mock)


def _baseline_input(
    *, trigger: BriefingTrigger = BriefingTrigger.STRUCTURAL_ANOMALY
) -> M0BrieferInput:
    return M0BrieferInput(
        target_agent="e1_financial_risk",
        case_bundle={"case_id": "case_001", "client_id": "c1"},
        trigger_flag=trigger,
    )


# ===========================================================================
# §8.8.8 Test 1 — Length compliance
# ===========================================================================


class TestLengthCompliance:
    @pytest.mark.asyncio
    async def test_briefing_within_budget_passes(self):
        # 200-token briefing
        text = " ".join(["word"] * 200)
        briefer = _briefer_with_response(text)
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is not None
        assert out.briefing_metadata is not None
        assert out.briefing_metadata.token_count == 200

    @pytest.mark.asyncio
    async def test_briefing_too_short_skipped(self):
        # 50 tokens — below the 100-token floor
        text = " ".join(["word"] * 50)
        briefer = _briefer_with_response(text)
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is None
        assert out.skip_reason is not None
        assert "length_violation" in out.skip_reason

    @pytest.mark.asyncio
    async def test_briefing_too_long_skipped(self):
        # 400 tokens — above the 300-token ceiling
        text = " ".join(["word"] * 400)
        briefer = _briefer_with_response(text)
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is None
        assert out.skip_reason is not None
        assert "length_violation" in out.skip_reason


# ===========================================================================
# §8.8.8 Test 2 — Verdict-anticipation lint
# ===========================================================================


class TestVerdictAnticipationLint:
    @pytest.mark.asyncio
    async def test_clean_briefing_passes(self):
        text = (
            "The client recently restructured their family trust and the proposed "
            "AIF would be the first illiquid commitment under the new structure. "
            "The cascade timing relative to existing capital calls warrants careful "
            "evaluation. Cross-border tax treaty considerations may apply. "
        ) * 3  # pad to ~100 tokens
        briefer = _briefer_with_response(text)
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is not None

    @pytest.mark.asyncio
    async def test_high_risk_assertion_caught(self):
        # Verdict-anticipating language → lint blocks
        text = (
            "This is a high risk case given the client's recent retirement. "
            "The proposed AIF should not proceed without further review. "
        ) * 8  # pad to ~100 tokens
        briefer = _briefer_with_response(text)
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is None
        assert out.skip_reason is not None
        assert "lint_violation" in out.skip_reason

    @pytest.mark.asyncio
    async def test_recommendation_language_caught(self):
        text = (
            "My recommendation is to approve this proposal. "
            "The client has the capacity and intent to proceed. "
        ) * 8
        briefer = _briefer_with_response(text)
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is None
        assert "lint_violation" in (out.skip_reason or "")

    @pytest.mark.asyncio
    async def test_lint_violations_captured_in_metadata(self):
        # Long enough to clear the 100-token floor; the lint catches the
        # verdict-anticipating language before any other check.
        text = "This case must be escalated immediately. " * 20
        briefer = _briefer_with_response(text)
        out = await briefer.generate(_baseline_input())
        # Even though briefing_text is None, metadata captures the lint reason
        assert out.briefing_metadata is not None
        assert len(out.briefing_metadata.lint_violations) > 0


# ===========================================================================
# §8.8.8 Test 3 — SKIP path
# ===========================================================================


class TestSkipPath:
    @pytest.mark.asyncio
    async def test_skip_emitted_when_no_non_redundant_context(self):
        briefer = _briefer_with_response("SKIP")
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is None
        assert out.skip_reason == "llm_emitted_skip"

    @pytest.mark.asyncio
    async def test_skip_lowercase_also_recognised(self):
        briefer = _briefer_with_response("skip")
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is None


# ===========================================================================
# §8.8.8 Test 4 — Verbatim capture
# ===========================================================================


class TestVerbatimCapture:
    @pytest.mark.asyncio
    async def test_briefing_text_captured_verbatim(self):
        text = (
            "Family trust recently amended; new beneficiary structure requires "
            "fresh suitability review. Cascade timing of capital calls overlaps "
            "with existing AIF Cat II commitment running through 2027. "
        ) * 5  # ~140 tokens, within the 100-300 budget
        briefer = _briefer_with_response(text)
        out = await briefer.generate(_baseline_input())
        # Service strips surrounding whitespace; otherwise text is verbatim.
        assert out.briefing_text == text.strip()


# ===========================================================================
# Trigger flag passthrough
# ===========================================================================


class TestTriggerPassthrough:
    @pytest.mark.asyncio
    async def test_trigger_flag_in_metadata(self):
        text = " ".join(["word"] * 150)
        briefer = _briefer_with_response(text)
        out = await briefer.generate(
            _baseline_input(trigger=BriefingTrigger.OUT_OF_BUCKET)
        )
        assert out.briefing_metadata is not None
        assert out.briefing_metadata.trigger_flag is BriefingTrigger.OUT_OF_BUCKET


# ===========================================================================
# LLM unavailable
# ===========================================================================


class _FailingProvider:
    name = "failing"

    async def complete(self, request):
        raise RuntimeError("LLM unavailable")

    async def complete_structured(self, request, output_type):
        raise RuntimeError("LLM unavailable")


class TestLlmUnavailable:
    @pytest.mark.asyncio
    async def test_llm_failure_returns_skip(self):
        briefer = M0Briefer(_FailingProvider())
        out = await briefer.generate(_baseline_input())
        assert out.briefing_text is None
        assert out.skip_reason is not None
        assert "llm_unavailable" in out.skip_reason


# ===========================================================================
# Output schema round-trip
# ===========================================================================


def test_output_round_trips():
    text = " ".join(["word"] * 150)
    out = M0BrieferOutput(briefing_text=text, briefing_metadata=None)
    round_tripped = M0BrieferOutput.model_validate_json(out.model_dump_json())
    assert round_tripped == out
