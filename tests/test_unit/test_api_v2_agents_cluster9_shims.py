"""Cluster 9 chunks 9.2-9.3 — per-shim semantic validation rule tests.

Pins all semantic validation rules for the three new cluster-9 shims:

- E5.FundView: 6 rules (chunk 9.2 §2.6)
- E5.DealView: 5 rules (chunk 9.2 §3.6)
- E4.Behavioural: 6 rules (chunk 9.3 §9)

Also pins derive_window_id bucket arithmetic for E4.

All tests are purely structural (no Anthropic calls); canned JSON strings
are passed directly to shim.parse_output + shim.validate_output.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest

from artha.api_v2.agents.e4_behavioural.schema import (
    BehaviouralVerdict,
    E4BehaviouralOutput,
)
from artha.api_v2.agents.e4_behavioural.shim import (
    E4BehaviouralShim,
    derive_window_id,
)
from artha.api_v2.agents.e5_deal_view.schema import (
    DealStage,
    DealViewVerdict,
    E5DealViewOutput,
)
from artha.api_v2.agents.e5_deal_view.shim import E5DealViewShim
from artha.api_v2.agents.e5_fund_view.schema import (
    E5FundViewOutput,
    FundViewVerdict,
)
from artha.api_v2.agents.e5_fund_view.shim import E5FundViewShim
from artha.api_v2.agents.llm_client import LLMResponse
from artha.api_v2.agents.shim import AgentInputs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_and_validate(
    shim: Any,
    inputs: AgentInputs,
    payload_dict: dict[str, Any],
) -> Any:
    """Parse JSON then validate — returns ValidationResult."""
    verdict = shim.parse_output(
        LLMResponse(text=json.dumps(payload_dict)),
        inputs,
    )
    return shim.validate_output(verdict, inputs)


# ---------------------------------------------------------------------------
# E5.FundView
# ---------------------------------------------------------------------------

# A reasoning_summary that is >=200 chars and has >=3 numeric tokens.
_E5FV_REASONING_GOOD = (
    "Fund shows exceptional track record with IRR 22.5% since 2019 inception. "
    "Target corpus INR 1000 Cr, drawn INR 650 Cr (65% deployment). "
    "Manager Sequoia Capital India has stable 8-year tenure with no key-person "
    "risk events. Fee structure at 2% management fee and 20% carry with 8% "
    "hurdle is at category norm. DPI of 0.8x and TVPI of 2.1x indicate healthy "
    "distribution and value creation. Three portfolio companies have achieved "
    "profitable exits. Strategy consistent with mandate with no focus drift."
)


def _e5fv_inputs(
    aif_id: str = "IN/AIF2/24-25/00123",
    current_manager_name: str = "Sequoia Capital India",
    irr_since_inception_pct: float = 22.5,
    target_corpus_inr_cr: float = 1000.0,
    drawn_corpus_inr_cr: float = 650.0,
) -> AgentInputs:
    return AgentInputs(
        case_id="test_case",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "aif_id": aif_id,
            "aif_category": "Category II",
            "current_manager_name": current_manager_name,
            "irr_since_inception_pct": irr_since_inception_pct,
            "target_corpus_inr_cr": target_corpus_inr_cr,
            "drawn_corpus_inr_cr": drawn_corpus_inr_cr,
            "latest_aif_disclosure_id": "disc_001",
            "fund_manual_flag_id": "null",
        },
    )


def _e5fv_payload(
    *,
    aif_id: str = "IN/AIF2/24-25/00123",
    fund_view_verdict: str = "positive",
    manager_name: str = "Sequoia Capital India",
    tenure_years: float = 8.0,
    irr_since_inception_pct: float = 22.5,
    target_corpus_inr_cr: float = 1000.0,
    drawn_corpus_inr_cr: float = 650.0,
    key_signals: list[dict] | None = None,
    reasoning_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "aif_id": aif_id,
        "fund_view_verdict": fund_view_verdict,
        "manager_quality_assessment": {
            "manager_name": manager_name,
            "tenure_years": tenure_years,
            "continuity_signal": "stable_long_tenure",
            "track_record_quality": "strong",
        },
        "track_record_assessment": {
            "vintage_year": 2019,
            "irr_since_inception_pct": irr_since_inception_pct,
            "dpi_ratio": 0.8,
            "tvpi_ratio": 2.1,
            "consistency_assessment": (
                "Consistent outperformance across 3 vintages since 2015."
            ),
        },
        "capacity_assessment": {
            "target_corpus_inr_cr": target_corpus_inr_cr,
            "drawn_corpus_inr_cr": drawn_corpus_inr_cr,
            "deployment_pacing_signal": "paced_well",
        },
        "strategy_consistency": "consistent_with_mandate",
        "governance_assessment": {
            "intensity": "moderate",
            "key_considerations": [
                "board representation",
                "co-investment rights",
            ],
        },
        "fee_structure_assessment": {
            "management_fee_pct": 2.0,
            "carry_pct": 20.0,
            "hurdle_rate_pct": 8.0,
            "fee_verdict": "at_category_norm",
        },
        "key_signals": key_signals
        or [
            {
                "signal": "Strong IRR of 22.5% since inception",
                "direction": "positive",
                "severity": "high",
            },
            {
                "signal": "DPI 0.8x ahead of schedule",
                "direction": "positive",
                "severity": "medium",
            },
            {
                "signal": "Manager continuity stable for 8 years",
                "direction": "positive",
                "severity": "medium",
            },
        ],
        "confidence": 0.85,
        "reasoning_summary": reasoning_summary or _E5FV_REASONING_GOOD,
    }


class TestE5FundViewShim:
    shim = E5FundViewShim()

    def test_valid_pass(self) -> None:
        inputs = _e5fv_inputs()
        res = _parse_and_validate(self.shim, inputs, _e5fv_payload())
        assert res.success is True
        assert res.error_type is None

    # ------------------------------------------------------------------
    # Rule 1 — aif_id mismatch
    # ------------------------------------------------------------------

    def test_rule_1_aif_id_mismatch_raises_in_parse(self) -> None:
        inputs = _e5fv_inputs(aif_id="IN/AIF2/24-25/00123")
        payload = _e5fv_payload(aif_id="IN/AIF1/24-25/99999")
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(payload)), inputs
            )

    def test_rule_1_aif_id_pass_when_input_omitted(self) -> None:
        # If aif_id not in input payload the identity check is skipped.
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"aif_category": "Category II"},
        )
        payload = _e5fv_payload(aif_id="ANYTHING")
        res = _parse_and_validate(self.shim, inputs, payload)
        # Rule 1 not triggered; rule 2 not triggered (no current_manager_name
        # in input); rules 3-4 not triggered; should pass all rules.
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 2 — manager_name mismatch
    # ------------------------------------------------------------------

    def test_rule_2_manager_name_mismatch(self) -> None:
        inputs = _e5fv_inputs(current_manager_name="Sequoia Capital India")
        payload = _e5fv_payload(manager_name="Completely Different Manager")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_manager_name_mismatch"

    def test_rule_2_manager_name_substring_pass(self) -> None:
        # Input is the full name; output is a shorter substring — still valid.
        inputs = _e5fv_inputs(current_manager_name="Sequoia Capital India")
        payload = _e5fv_payload(manager_name="Sequoia Capital")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_2_manager_name_case_insensitive_pass(self) -> None:
        inputs = _e5fv_inputs(current_manager_name="sequoia capital india")
        payload = _e5fv_payload(manager_name="Sequoia Capital India")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 3 — IRR not grounded
    # ------------------------------------------------------------------

    def test_rule_3_irr_not_grounded_fails(self) -> None:
        # Input IRR 22.5; output 25.0 → deviation 2.5 > 2.0 ppt threshold.
        inputs = _e5fv_inputs(irr_since_inception_pct=22.5)
        payload = _e5fv_payload(irr_since_inception_pct=25.0)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_irr_not_grounded"

    def test_rule_3_irr_within_tolerance_passes(self) -> None:
        # Deviation of 1.5 ppt is within 2.0 ppt tolerance.
        inputs = _e5fv_inputs(irr_since_inception_pct=22.5)
        payload = _e5fv_payload(irr_since_inception_pct=24.0)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_3_irr_skipped_when_no_input(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={
                "aif_id": "IN/AIF2/24-25/00123",
                "aif_category": "Category II",
            },
        )
        payload = _e5fv_payload(irr_since_inception_pct=99.0)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 4 — corpus not grounded
    # ------------------------------------------------------------------

    def test_rule_4_target_corpus_not_grounded(self) -> None:
        # 1000 → 1100: 10% relative deviation > 5% tolerance.
        inputs = _e5fv_inputs(target_corpus_inr_cr=1000.0)
        payload = _e5fv_payload(target_corpus_inr_cr=1100.0)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_corpus_not_grounded"

    def test_rule_4_drawn_corpus_not_grounded(self) -> None:
        # 650 → 750: ~15% relative deviation > 5% tolerance.
        inputs = _e5fv_inputs(drawn_corpus_inr_cr=650.0)
        payload = _e5fv_payload(drawn_corpus_inr_cr=750.0)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_corpus_not_grounded"

    def test_rule_4_corpus_within_tolerance_passes(self) -> None:
        # 1000 → 1030: 3% relative deviation within 5% tolerance.
        inputs = _e5fv_inputs(
            target_corpus_inr_cr=1000.0, drawn_corpus_inr_cr=650.0
        )
        payload = _e5fv_payload(
            target_corpus_inr_cr=1030.0, drawn_corpus_inr_cr=670.0
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 5 — verdict/signals inconsistency
    # ------------------------------------------------------------------

    def test_rule_5_positive_verdict_insufficient_positive_signals(self) -> None:
        # 2 of 5 positive = 40% — below the 60% threshold.
        signals = [
            {"signal": "Strong IRR", "direction": "positive", "severity": "high"},
            {"signal": "DPI ahead", "direction": "positive", "severity": "medium"},
            {"signal": "High fees", "direction": "negative", "severity": "medium"},
            {"signal": "Key-person risk", "direction": "negative", "severity": "high"},
            {"signal": "Slow deployment", "direction": "negative", "severity": "low"},
        ]
        inputs = _e5fv_inputs()
        payload = _e5fv_payload(fund_view_verdict="positive", key_signals=signals)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_5_verdict_signals_inconsistency"

    def test_rule_5_avoid_verdict_positive_gte_negative(self) -> None:
        # 2 positive, 1 negative — avoid needs more negative than positive.
        signals = [
            {"signal": "Strong IRR", "direction": "positive", "severity": "high"},
            {"signal": "DPI ahead", "direction": "positive", "severity": "medium"},
            {"signal": "High fees", "direction": "negative", "severity": "low"},
        ]
        inputs = _e5fv_inputs()
        payload = _e5fv_payload(fund_view_verdict="avoid", key_signals=signals)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_5_verdict_signals_inconsistency"

    def test_rule_5_positive_verdict_exactly_60pct_passes(self) -> None:
        # 3 of 5 positive = 60% — exactly at threshold, should pass.
        signals = [
            {"signal": "Strong IRR", "direction": "positive", "severity": "high"},
            {"signal": "DPI ahead", "direction": "positive", "severity": "medium"},
            {"signal": "Manager tenure", "direction": "positive", "severity": "low"},
            {"signal": "High fees", "direction": "negative", "severity": "medium"},
            {"signal": "Slow deployment", "direction": "negative", "severity": "low"},
        ]
        inputs = _e5fv_inputs()
        payload = _e5fv_payload(fund_view_verdict="positive", key_signals=signals)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_5_avoid_verdict_more_negative_passes(self) -> None:
        signals = [
            {"signal": "Weak IRR", "direction": "negative", "severity": "high"},
            {"signal": "High fees", "direction": "negative", "severity": "high"},
            {"signal": "DPI low", "direction": "positive", "severity": "low"},
        ]
        inputs = _e5fv_inputs()
        payload = _e5fv_payload(fund_view_verdict="avoid", key_signals=signals)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 6 — insufficient quantitative grounding
    # ------------------------------------------------------------------

    def test_rule_6_no_numeric_tokens_in_reasoning(self) -> None:
        # 200+ chars but zero numeric tokens.
        no_numbers = (
            "The fund displays a strong track record anchored in value creation "
            "through disciplined deployment and portfolio governance. The manager "
            "has maintained continuity and strategic focus over time. Fee structure "
            "is at category norm. Deployment pacing has been steady. Governance "
            "engagement is moderate with appropriate board representation rights. "
            "Strategy is fully consistent with its stated mandate without drift."
        )
        inputs = _e5fv_inputs()
        payload = _e5fv_payload(reasoning_summary=no_numbers)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_6_insufficient_quantitative_grounding"

    def test_rule_6_three_numeric_tokens_passes(self) -> None:
        # Exactly 3 numeric tokens: 22.5%, 1000, 650.
        three_tokens = (
            "Fund has IRR of 22.5% since inception. Target corpus is INR 1000 Cr "
            "and drawn corpus is INR 650 Cr. Manager has maintained stable team "
            "and long-standing investor relationships. Deployment pacing has been "
            "appropriate given market conditions. Strategy remains consistent with "
            "the stated mandate. Governance engagement at moderate intensity."
        )
        inputs = _e5fv_inputs()
        payload = _e5fv_payload(reasoning_summary=three_tokens)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Infrastructure: cache key, validate_input, parse errors
    # ------------------------------------------------------------------

    def test_compute_cache_key(self) -> None:
        inputs = _e5fv_inputs()
        key = self.shim.compute_cache_key(inputs)
        assert key == "e5fv:IN/AIF2/24-25/00123:disc_001:null"

    def test_compute_cache_key_no_aif_id(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"aif_category": "Category II"},
        )
        assert self.shim.compute_cache_key(inputs) is None

    def test_compute_cache_key_fallback_no_disclosure(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={
                "aif_id": "IN/AIF2/24-25/00123",
                "aif_category": "Category II",
            },
        )
        key = self.shim.compute_cache_key(inputs)
        assert key == "e5fv:IN/AIF2/24-25/00123:no_disclosure_seeded:null"

    def test_validate_input_missing_aif_id(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"aif_category": "Category II"},
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_validate_input_missing_aif_category(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"aif_id": "IN/AIF2/24-25/00123"},
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_parse_error_on_garbage_json(self) -> None:
        inputs = _e5fv_inputs()
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text="not json at all!!!"), inputs
            )

    def test_parse_error_on_schema_violation(self) -> None:
        inputs = _e5fv_inputs()
        # confidence out of range [0, 1].
        bad_payload = _e5fv_payload()
        bad_payload["confidence"] = 5.0
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(bad_payload)), inputs
            )


# ---------------------------------------------------------------------------
# E5.DealView
# ---------------------------------------------------------------------------

_E5DV_REASONING_GOOD = (
    "Deal series_b round for TechCo at post-money valuation of INR 500 Cr. "
    "Lead investor Accel Partners (tier_1) provides strong validation signal. "
    "Revenue run-rate at INR 120 Cr ARR with 40% YoY growth. "
    "Exit horizon 5 years with IPO probability 0.6 and strategic sale 0.3. "
    "Stage appropriate for AIF II mandate targeting series_b and series_c. "
    "Valuation at market based on SaaS peers at 4x revenue. "
    "Overall deal view is constructive given strong co-investor quality and "
    "growth trajectory."
)


def _e5dv_inputs(
    deal_id: str = "deal_techco_001",
    company_stage: str | None = "series_b",
    valuation_post_money_inr_cr: float | None = 500.0,
    lead_investor: str = "Accel Partners",
) -> AgentInputs:
    payload: dict[str, Any] = {
        "deal_id": deal_id,
        "cin_or_internal": "CIN12345",
        "fund_or_firm_id": "fund_abc",
        "latest_mca_filing_id": "mca_001",
        "deal_manual_flag_id": "null",
    }
    if company_stage is not None:
        payload["company_stage"] = company_stage
    if valuation_post_money_inr_cr is not None:
        payload["valuation_post_money_inr_cr"] = valuation_post_money_inr_cr
    if lead_investor:
        payload["lead_investor"] = lead_investor
    return AgentInputs(
        case_id="test_case",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload=payload,
    )


def _e5dv_payload(
    *,
    deal_id: str = "deal_techco_001",
    deal_view_verdict: str = "constructive",
    current_stage: str = "series_b",
    post_money_inr_cr: float = 500.0,
    lead_investor: str = "Accel Partners",
    material_signals: list[dict] | None = None,
    reasoning_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "deal_id": deal_id,
        "deal_view_verdict": deal_view_verdict,
        "stage_assessment": {
            "current_stage": current_stage,
            "stage_appropriateness": "appropriate_for_mandate",
            "next_round_outlook": "Series C expected in 18 months at ~2x valuation.",
        },
        "valuation_assessment": {
            "post_money_inr_cr": post_money_inr_cr,
            "valuation_multiple_assessment": "at_market",
            "comparables_signal": "SaaS peers trading at 4x ARR; deal at 4.2x.",
        },
        "co_investor_quality": {
            "lead_investor": lead_investor,
            "quality_signal": "tier_1",
        },
        "expected_exit_assessment": {
            "horizon_years": 5,
            "exit_route_likelihood": {
                "ipo": 0.6,
                "strategic_sale": 0.3,
                "secondary": 0.1,
                "write_off": 0.0,
            },
        },
        "material_signals": material_signals
        or [
            {
                "signal": "Top-tier co-investor validation",
                "direction": "positive",
                "severity": "high",
            },
            {
                "signal": "ARR growth 40% YoY",
                "direction": "positive",
                "severity": "high",
            },
        ],
        "confidence": 0.78,
        "reasoning_summary": reasoning_summary or _E5DV_REASONING_GOOD,
    }


class TestE5DealViewShim:
    shim = E5DealViewShim()

    def test_valid_pass(self) -> None:
        inputs = _e5dv_inputs()
        res = _parse_and_validate(self.shim, inputs, _e5dv_payload())
        assert res.success is True
        assert res.error_type is None

    # ------------------------------------------------------------------
    # Rule 1 — deal_id mismatch
    # ------------------------------------------------------------------

    def test_rule_1_deal_id_mismatch_raises_in_parse(self) -> None:
        inputs = _e5dv_inputs(deal_id="deal_techco_001")
        payload = _e5dv_payload(deal_id="deal_other_999")
        with pytest.raises(ValueError, match="deal_id mismatch"):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(payload)), inputs
            )

    def test_rule_1_deal_id_pass_when_input_omitted(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"cin_or_internal": "CIN12345"},
        )
        payload = _e5dv_payload(deal_id="ANYTHING")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 2 — stage mismatch
    # ------------------------------------------------------------------

    def test_rule_2_stage_mismatch(self) -> None:
        inputs = _e5dv_inputs(company_stage="series_b")
        payload = _e5dv_payload(current_stage="series_c")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_stage_mismatch"

    def test_rule_2_stage_match_passes(self) -> None:
        inputs = _e5dv_inputs(company_stage="series_b")
        payload = _e5dv_payload(current_stage="series_b")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_2_stage_skipped_when_not_in_input(self) -> None:
        inputs = _e5dv_inputs(company_stage=None)
        payload = _e5dv_payload(current_stage="pre_ipo")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_2_unknown_input_stage_skipped(self) -> None:
        # Unrecognised stage value in input → check silently skipped.
        inputs = _e5dv_inputs(company_stage="proto_seed")
        payload = _e5dv_payload(current_stage="series_a")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 3 — valuation not grounded
    # ------------------------------------------------------------------

    def test_rule_3_valuation_not_grounded(self) -> None:
        # 500 → 600: 20% relative deviation > 5% tolerance.
        inputs = _e5dv_inputs(valuation_post_money_inr_cr=500.0)
        payload = _e5dv_payload(post_money_inr_cr=600.0)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_valuation_not_grounded"

    def test_rule_3_valuation_within_tolerance_passes(self) -> None:
        # 500 → 520: 4% relative deviation within 5% tolerance.
        inputs = _e5dv_inputs(valuation_post_money_inr_cr=500.0)
        payload = _e5dv_payload(post_money_inr_cr=520.0)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_3_valuation_skipped_when_no_input(self) -> None:
        inputs = _e5dv_inputs(valuation_post_money_inr_cr=None)
        payload = _e5dv_payload(post_money_inr_cr=9999.0)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 4 — co-investor not grounded
    # ------------------------------------------------------------------

    def test_rule_4_co_investor_not_grounded(self) -> None:
        inputs = _e5dv_inputs(lead_investor="Accel Partners")
        payload = _e5dv_payload(lead_investor="Completely Different VC")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_co_investor_not_grounded"

    def test_rule_4_co_investor_substring_passes(self) -> None:
        inputs = _e5dv_inputs(lead_investor="Accel Partners India")
        payload = _e5dv_payload(lead_investor="Accel Partners")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_4_co_investor_case_insensitive_passes(self) -> None:
        inputs = _e5dv_inputs(lead_investor="accel partners")
        payload = _e5dv_payload(lead_investor="Accel Partners")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_4_co_investor_skipped_when_no_input(self) -> None:
        inputs = _e5dv_inputs(lead_investor="")
        payload = _e5dv_payload(lead_investor="Anyone")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 5 — insufficient quantitative grounding
    # ------------------------------------------------------------------

    def test_rule_5_no_numeric_tokens_in_reasoning(self) -> None:
        # 200+ chars but zero numeric tokens.
        no_numbers = (
            "The deal is at a constructive stage with strong co-investor "
            "backing and a robust growth trajectory in the SaaS segment. "
            "The lead investor is a well-known tier-one fund with an "
            "established track record in similar situations. The valuation "
            "multiple is at market relative to comparable transactions. "
            "Exit prospects appear favourable with both IPO and strategic "
            "sale routes plausible given the company profile and sector."
        )
        inputs = _e5dv_inputs()
        payload = _e5dv_payload(reasoning_summary=no_numbers)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_5_insufficient_quantitative_grounding"

    def test_rule_5_three_numeric_tokens_passes(self) -> None:
        three_tokens = (
            "Deal at post-money valuation of INR 500 Cr (series_b). "
            "ARR is INR 120 Cr growing at 40% YoY. Lead investor Accel "
            "Partners (tier_1) validates the round. Exit horizon is 5 years "
            "with IPO route most likely. Stage appropriate for AIF mandate "
            "targeting growth-stage investments. Valuation at market vs peers."
        )
        inputs = _e5dv_inputs()
        payload = _e5dv_payload(reasoning_summary=three_tokens)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Infrastructure: cache key, validate_input, parse errors
    # ------------------------------------------------------------------

    def test_compute_cache_key(self) -> None:
        inputs = _e5dv_inputs()
        key = self.shim.compute_cache_key(inputs)
        assert key == "e5dv:deal_techco_001:fund_abc:mca_001:null"

    def test_compute_cache_key_defaults(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"deal_id": "d1", "cin_or_internal": "CIN1"},
        )
        key = self.shim.compute_cache_key(inputs)
        assert key == "e5dv:d1:direct:no_filing_seeded:null"

    def test_compute_cache_key_no_deal_id(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"cin_or_internal": "CIN1"},
        )
        assert self.shim.compute_cache_key(inputs) is None

    def test_validate_input_missing_deal_id(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"cin_or_internal": "CIN12345"},
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_validate_input_missing_cin(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"deal_id": "deal_001"},
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_parse_error_on_garbage_json(self) -> None:
        inputs = _e5dv_inputs()
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text="{completely broken json{{"), inputs
            )

    def test_parse_error_on_schema_violation(self) -> None:
        inputs = _e5dv_inputs()
        bad_payload = _e5dv_payload()
        # confidence must be in [0, 1].
        bad_payload["confidence"] = -0.5
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(bad_payload)), inputs
            )


# ---------------------------------------------------------------------------
# E4.Behavioural
# ---------------------------------------------------------------------------

# reasoning_summary with >=200 chars and >=2 historical reference tokens
# (case_xxx IDs satisfy the pattern).
_E4_REASONING_GOOD = (
    "Investor inv_001 shows disciplined behaviour across case_alpha and "
    "case_beta. In case_alpha the investor accepted the recommendation without "
    "modification. In case_beta the investor asked clarifying questions and "
    "then accepted. No panic-proxy decisions recorded in 8 cases over 24 months. "
    "Loss aversion bias identified from repeated requests for downside scenarios "
    "before committing. Communication preference is email at monthly cadence. "
    "Overall profile is disciplined with moderate loss aversion observable."
)


def _e4_inputs(
    investor_id: str = "inv_001",
    case_history: list[dict] | None = None,
    window_id: str | None = "e4_w_2024_01",
) -> AgentInputs:
    payload: dict[str, Any] = {
        "investor_id": investor_id,
        "investor_name": "Test Investor",
    }
    if case_history is not None:
        payload["case_history"] = case_history
    if window_id is not None:
        payload["window_id"] = window_id
    return AgentInputs(
        case_id="test_case",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload=payload,
    )


def _e4_payload(
    *,
    investor_id: str = "inv_001",
    behavioural_verdict: str = "disciplined",
    panic_indicators: list[dict] | None = None,
    bias_signals: list[dict] | None = None,
    reasoning_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "investor_id": investor_id,
        "behavioural_verdict": behavioural_verdict,
        "trading_pattern_signal": {
            "frequency": "low",
            "consistency_with_mandate": "consistent",
            "deviation_patterns": [],
        },
        "panic_indicators": panic_indicators if panic_indicators is not None else [],
        "decision_style": {
            "typical_decision_speed": "moderate",
            "modification_frequency": "rare",
            "escalation_tendency": "questions_then_accepts",
        },
        "communication_preferences": {
            "preferred_channel": "email",
            "preferred_detail_level": "summary",
            "preferred_cadence": "monthly",
        },
        "bias_signals": bias_signals
        if bias_signals is not None
        else [
            {
                "bias_type": "loss_aversion",
                "evidence": (
                    "Repeatedly requests downside scenario before committing."
                ),
                "advisory_implication": (
                    "Always provide downside scenario in recommendations."
                ),
            }
        ],
        "advisory_implications": [
            "Lead with downside protection framing.",
        ],
        "confidence": 0.82,
        "reasoning_summary": reasoning_summary or _E4_REASONING_GOOD,
    }


class TestE4BehaviouralShim:
    shim = E4BehaviouralShim()

    def test_valid_pass(self) -> None:
        inputs = _e4_inputs()
        res = _parse_and_validate(self.shim, inputs, _e4_payload())
        assert res.success is True
        assert res.error_type is None

    # ------------------------------------------------------------------
    # Rule 1 — investor_id mismatch
    # ------------------------------------------------------------------

    def test_rule_1_investor_id_mismatch_raises_in_parse(self) -> None:
        inputs = _e4_inputs(investor_id="inv_001")
        payload = _e4_payload(investor_id="inv_999")
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(payload)), inputs
            )

    def test_rule_1_investor_id_pass_when_input_omitted(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"investor_name": "Someone"},
        )
        payload = _e4_payload(investor_id="ANYONE")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 2 — panic_indicators consistency with verdict
    # ------------------------------------------------------------------

    def test_rule_2_reactive_verdict_requires_panic_indicators(self) -> None:
        inputs = _e4_inputs()
        payload = _e4_payload(
            behavioural_verdict="reactive",
            panic_indicators=[],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_panic_indicators_required_for_verdict"

    def test_rule_2_panic_prone_verdict_requires_panic_indicators(self) -> None:
        inputs = _e4_inputs()
        payload = _e4_payload(
            behavioural_verdict="panic_prone",
            panic_indicators=[],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_panic_indicators_required_for_verdict"

    def test_rule_2_reactive_verdict_with_indicator_passes(self) -> None:
        panic_indicator = {
            "trigger_type": "market_drop",
            "historical_reaction": "Requested immediate exit from equities.",
            "severity": "high",
        }
        inputs = _e4_inputs()
        payload = _e4_payload(
            behavioural_verdict="reactive",
            panic_indicators=[panic_indicator],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_2_untested_verdict_must_have_empty_panic_indicators(
        self,
    ) -> None:
        panic_indicator = {
            "trigger_type": "market_drop",
            "historical_reaction": "Requested immediate exit from equities.",
            "severity": "high",
        }
        inputs = _e4_inputs()
        payload = _e4_payload(
            behavioural_verdict="untested",
            panic_indicators=[panic_indicator],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_panic_indicators_present_for_untested"

    def test_rule_2_untested_verdict_no_indicators_passes(self) -> None:
        inputs = _e4_inputs(case_history=[])
        payload = _e4_payload(
            behavioural_verdict="untested",
            panic_indicators=[],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 3 — bias evidence not grounded
    # ------------------------------------------------------------------

    def test_rule_3_short_evidence_fails(self) -> None:
        # Evidence is only 12 chars — below the 20-char minimum.
        short_evidence = {
            "bias_type": "loss_aversion",
            "evidence": "Too short evd",
            "advisory_implication": "Provide downside scenarios.",
        }
        inputs = _e4_inputs()
        payload = _e4_payload(bias_signals=[short_evidence])
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_bias_evidence_not_grounded"

    def test_rule_3_exactly_20_chars_passes(self) -> None:
        # Exactly 20 chars — at threshold boundary.
        evidence_20 = "Sold at 10% loss x2."  # 21 chars — safe
        enough = {
            "bias_type": "loss_aversion",
            "evidence": evidence_20,
            "advisory_implication": "Provide downside scenarios always.",
        }
        inputs = _e4_inputs()
        payload = _e4_payload(bias_signals=[enough])
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_3_empty_bias_signals_passes(self) -> None:
        inputs = _e4_inputs()
        payload = _e4_payload(bias_signals=[])
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 4 — verdict inconsistent with history
    # ------------------------------------------------------------------

    def test_rule_4_disciplined_verdict_with_two_panic_proxies(self) -> None:
        case_history = [
            {"case_id": "case_1", "investor_decision": "accepted_with_modification"},
            {"case_id": "case_2", "investor_decision": "rejected"},
            {"case_id": "case_3", "investor_decision": "accepted"},
        ]
        inputs = _e4_inputs(case_history=case_history)
        payload = _e4_payload(behavioural_verdict="disciplined")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_verdict_inconsistent_with_history"

    def test_rule_4_disciplined_with_one_panic_proxy_passes(self) -> None:
        # Only 1 panic proxy — threshold requires >=2.
        case_history = [
            {"case_id": "case_1", "investor_decision": "rejected"},
            {"case_id": "case_2", "investor_decision": "accepted"},
            {"case_id": "case_3", "investor_decision": "accepted"},
        ]
        inputs = _e4_inputs(case_history=case_history)
        payload = _e4_payload(behavioural_verdict="disciplined")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_4_panic_prone_with_five_entries_zero_proxies(self) -> None:
        # 5 entries, 0 panic proxies, yet verdict=panic_prone → violation.
        case_history = [
            {"case_id": f"case_{i}", "investor_decision": "accepted"}
            for i in range(5)
        ]
        inputs = _e4_inputs(case_history=case_history)
        panic_indicator = {
            "trigger_type": "volatility",
            "historical_reaction": "Called RM multiple times during drawdown.",
            "severity": "high",
        }
        payload = _e4_payload(
            behavioural_verdict="panic_prone",
            panic_indicators=[panic_indicator],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_verdict_inconsistent_with_history"

    def test_rule_4_panic_prone_with_four_entries_skips_check(self) -> None:
        # Only 4 entries (below >=5 threshold) — check not triggered.
        case_history = [
            {"case_id": f"case_{i}", "investor_decision": "accepted"}
            for i in range(4)
        ]
        inputs = _e4_inputs(case_history=case_history)
        panic_indicator = {
            "trigger_type": "volatility",
            "historical_reaction": "Called RM multiple times during drawdown.",
            "severity": "high",
        }
        payload = _e4_payload(
            behavioural_verdict="panic_prone",
            panic_indicators=[panic_indicator],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_4_panic_prone_with_panic_proxies_passes(self) -> None:
        # 5 entries with 2 panic proxies + panic_prone verdict → consistent.
        case_history = [
            {"case_id": "case_1", "investor_decision": "rejected"},
            {"case_id": "case_2", "investor_decision": "accepted_with_modification"},
            {"case_id": "case_3", "investor_decision": "accepted"},
            {"case_id": "case_4", "investor_decision": "accepted"},
            {"case_id": "case_5", "investor_decision": "accepted"},
        ]
        inputs = _e4_inputs(case_history=case_history)
        panic_indicator = {
            "trigger_type": "volatility",
            "historical_reaction": "Called RM multiple times during drawdown.",
            "severity": "high",
        }
        payload = _e4_payload(
            behavioural_verdict="panic_prone",
            panic_indicators=[panic_indicator],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 5 — communication_preferences missing
    # ------------------------------------------------------------------

    def test_rule_5_communication_preferences_none_not_possible_via_schema(
        self,
    ) -> None:
        # Pydantic schema requires communication_preferences; omitting it
        # in the JSON causes a parse error rather than a rule-5 violation.
        inputs = _e4_inputs()
        bad = _e4_payload()
        del bad["communication_preferences"]
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(bad)), inputs
            )

    def test_rule_5_valid_communication_preferences_passes(self) -> None:
        inputs = _e4_inputs()
        res = _parse_and_validate(self.shim, inputs, _e4_payload())
        assert res.success is True

    # ------------------------------------------------------------------
    # Rule 6 — insufficient historical grounding
    # ------------------------------------------------------------------

    def test_rule_6_no_historical_refs_in_reasoning(self) -> None:
        # 200+ chars but no case_xxx IDs, dates, or trade/case counts.
        no_refs = (
            "The investor demonstrates a disciplined behavioural profile "
            "with low trading frequency and consistent mandate adherence. "
            "Decision speed is moderate with a tendency to ask clarifying "
            "questions before acceptance. Loss aversion bias is evident from "
            "frequent requests for downside scenario analysis. Communication "
            "is preferred via email on a monthly cadence. Overall profile "
            "supports a measured and deliberative investment approach."
        )
        inputs = _e4_inputs()
        payload = _e4_payload(reasoning_summary=no_refs)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_6_insufficient_historical_grounding"

    def test_rule_6_one_historical_ref_fails(self) -> None:
        one_ref = (
            "Investor shows disciplined behaviour. In case_alpha the investor "
            "accepted the recommendation without modification. No panic-proxy "
            "decisions recorded. Loss aversion bias is evident from repeated "
            "requests for downside scenario before committing to any action. "
            "Communication preference is email. Overall disciplined profile "
            "confirmed across review of all available interaction history."
        )
        inputs = _e4_inputs()
        payload = _e4_payload(reasoning_summary=one_ref)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_6_insufficient_historical_grounding"

    def test_rule_6_two_case_ids_passes(self) -> None:
        two_refs = (
            "Investor shows disciplined behaviour across case_alpha and "
            "case_beta. In both cases the recommendation was accepted. No "
            "panic-proxy decisions in available history. Loss aversion bias "
            "is evident from repeated requests for downside scenarios before "
            "committing. Communication preference is email at monthly cadence. "
            "Overall profile is disciplined with moderate loss aversion."
        )
        inputs = _e4_inputs()
        payload = _e4_payload(reasoning_summary=two_refs)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_6_trade_count_tokens_satisfy_pattern(self) -> None:
        # "8 cases" and "12 trades" each match the pattern.
        trade_refs = (
            "Investor has 8 cases in history over 24 months with 12 trades. "
            "All recommendations were accepted without modification. Loss "
            "aversion bias is evident from downside scenario requests. "
            "Communication is monthly via email. No panic-proxy decisions "
            "in the available case history. Decision speed is moderate "
            "with consistent alignment to mandate throughout the review period."
        )
        inputs = _e4_inputs()
        payload = _e4_payload(reasoning_summary=trade_refs)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    def test_rule_6_date_tokens_satisfy_pattern(self) -> None:
        # Two ISO dates match the pattern.
        date_refs = (
            "Investor history reviewed from 2024-01-15 to 2024-06-30. "
            "Disciplined behaviour observed throughout the period with no "
            "panic-proxy decisions. Loss aversion bias evident from repeated "
            "requests for downside scenarios before each commitment. "
            "Communication preference is email at monthly cadence. "
            "Overall profile supports a disciplined investor classification."
        )
        inputs = _e4_inputs()
        payload = _e4_payload(reasoning_summary=date_refs)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is True

    # ------------------------------------------------------------------
    # Infrastructure: cache key, validate_input, parse errors
    # ------------------------------------------------------------------

    def test_compute_cache_key_explicit_window_id(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={
                "investor_id": "inv_001",
                "window_id": "e4_w_2024_03",
                "behavioural_manual_flag_id": "flag_b1",
            },
        )
        key = self.shim.compute_cache_key(inputs)
        assert key == "e4:inv_001:e4_w_2024_03:flag_b1"

    def test_compute_cache_key_derived_from_case_opened_at(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={
                "investor_id": "inv_001",
                "case_opened_at": "2024-01-01T00:00:00",
            },
        )
        key = self.shim.compute_cache_key(inputs)
        assert key == "e4:inv_001:e4_w_2024_01:null"

    def test_compute_cache_key_no_window_falls_back(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"investor_id": "inv_001"},
        )
        key = self.shim.compute_cache_key(inputs)
        assert key == "e4:inv_001:no_window_seeded:null"

    def test_compute_cache_key_no_investor_id(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"investor_name": "Someone"},
        )
        assert self.shim.compute_cache_key(inputs) is None

    def test_validate_input_missing_investor_id(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"investor_name": "Someone"},
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_parse_error_on_garbage_json(self) -> None:
        inputs = _e4_inputs()
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text="<not json at all>"), inputs
            )

    def test_parse_error_on_schema_violation(self) -> None:
        inputs = _e4_inputs()
        bad_payload = _e4_payload()
        # confidence must be in [0, 1].
        bad_payload["confidence"] = 1.5
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(bad_payload)), inputs
            )


# ---------------------------------------------------------------------------
# derive_window_id — bucket arithmetic
# ---------------------------------------------------------------------------


class TestDeriveWindowId:
    def test_jan_1_is_bucket_1(self) -> None:
        # Day 1 → bucket ((1-1)//30)+1 = 1
        assert derive_window_id(datetime(2024, 1, 1)) == "e4_w_2024_01"

    def test_jan_31_is_bucket_2(self) -> None:
        # Day 31 → bucket ((31-1)//30)+1 = 2
        assert derive_window_id(datetime(2024, 1, 31)) == "e4_w_2024_02"

    def test_feb_1_is_bucket_2(self) -> None:
        # Day 32 → bucket ((32-1)//30)+1 = 2
        assert derive_window_id(datetime(2024, 2, 1)) == "e4_w_2024_02"

    def test_dec_31_leap_year_is_bucket_13(self) -> None:
        # 2024 is a leap year: 366 days.
        # Day 366 → bucket ((366-1)//30)+1 = 13
        assert derive_window_id(datetime(2024, 12, 31)) == "e4_w_2024_13"

    def test_non_leap_year_dec_31_is_bucket_13(self) -> None:
        # 2023 (non-leap): day 365 → bucket ((365-1)//30)+1 = 13
        assert derive_window_id(datetime(2023, 12, 31)) == "e4_w_2023_13"

    def test_bucket_zero_padding(self) -> None:
        # Bucket numbers 1–9 are zero-padded to two digits.
        result = derive_window_id(datetime(2024, 1, 1))
        assert result == "e4_w_2024_01"

    def test_year_component_correct(self) -> None:
        result = derive_window_id(datetime(2025, 3, 15))
        assert result.startswith("e4_w_2025_")


# ---------------------------------------------------------------------------
# Import sanity
# ---------------------------------------------------------------------------


class TestImportSanity:
    def test_e5_fund_view_shim_importable(self) -> None:
        assert E5FundViewShim is not None

    def test_e5_deal_view_shim_importable(self) -> None:
        assert E5DealViewShim is not None

    def test_e4_behavioural_shim_importable(self) -> None:
        assert E4BehaviouralShim is not None

    def test_derive_window_id_importable(self) -> None:
        assert derive_window_id is not None

    def test_e5_fund_view_output_importable(self) -> None:
        assert E5FundViewOutput is not None

    def test_fund_view_verdict_enum_values(self) -> None:
        assert FundViewVerdict.POSITIVE.value == "positive"
        assert FundViewVerdict.AVOID.value == "avoid"

    def test_e5_deal_view_output_importable(self) -> None:
        assert E5DealViewOutput is not None

    def test_deal_view_verdict_enum_values(self) -> None:
        assert DealViewVerdict.HIGH_CONVICTION.value == "high_conviction"
        assert DealViewVerdict.AVOID.value == "avoid"

    def test_deal_stage_enum_values(self) -> None:
        assert DealStage.SERIES_B.value == "series_b"
        assert DealStage.PRE_IPO.value == "pre_ipo"

    def test_e4_behavioural_output_importable(self) -> None:
        assert E4BehaviouralOutput is not None

    def test_behavioural_verdict_enum_values(self) -> None:
        assert BehaviouralVerdict.DISCIPLINED.value == "disciplined"
        assert BehaviouralVerdict.PANIC_PRONE.value == "panic_prone"
        assert BehaviouralVerdict.UNTESTED.value == "untested"
