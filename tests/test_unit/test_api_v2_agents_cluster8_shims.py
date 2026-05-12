"""Cluster 8 chunks 8.1-8.4 — per-shim semantic validation rule tests.

Pins all semantic validation rules for the five new cluster-8 shims:

- E3.MacroView: 6 rules (chunk 8.1 §7)
- E2.SectorView: 6 rules (chunk 8.2 §3.5)
- E2.StockInSector: 5 rules (chunk 8.2 §4.5)
- E7 MutualFund: 7 rules (chunk 8.3 §9)
- E3.NewsScanner: 7 rules (chunk 8.4 §8)

All tests are purely structural (no Anthropic calls); canned JSON strings
are passed directly to shim.parse_output + shim.validate_output.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from artha.api_v2.agents.e2_sector_view.shim import E2SectorViewShim
from artha.api_v2.agents.e2_stock_in_sector.shim import E2StockInSectorShim
from artha.api_v2.agents.e3_macro_view.shim import E3MacroViewShim
from artha.api_v2.agents.e3_news_scanner.shim import E3NewsScannerShim
from artha.api_v2.agents.e7_mutual_fund.shim import E7MutualFundShim
from artha.api_v2.agents.llm_client import LLMResponse
from artha.api_v2.agents.shim import AgentInputs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG_TEXT = "Alpha " * 50  # 300 chars, zero numeric tokens


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
# E3.MacroView
# ---------------------------------------------------------------------------

_E3MV_SECTOR_IMPLICATIONS = [
    {
        "sector_code": "banking_financial_services",
        "implication": "Credit growth 14% YoY remains robust.",
        "directional_signal": "favourable",
    },
    {
        "sector_code": "information_technology",
        "implication": "USD-INR at 84 boosts exports 3%.",
        "directional_signal": "favourable",
    },
    {
        "sector_code": "fast_moving_consumer_goods",
        "implication": "Rural demand up 8% on lower rates.",
        "directional_signal": "favourable",
    },
    {
        "sector_code": "pharma_healthcare",
        "implication": "API exports 12% growth expected.",
        "directional_signal": "favourable",
    },
    {
        "sector_code": "energy",
        "implication": "Capex cycle supports 9% volume growth.",
        "directional_signal": "favourable",
    },
]

_E3MV_REASONING_GOOD = (
    "RBI repo rate cut 25 bps to 6.25%. Real rate is now 1.75%, "
    "supporting early_cutting cycle. INR at 84 vs USD. "
    "Inflation at 4.1%. Fiscal deficit 5.1% of GDP. "
    "Growth trajectory improving with rate transmission lag of 6 months. "
    "Sector implications broadly positive as cost of capital declines. "
    "Forward expectations are accommodative across all three horizons."
)


def _e3mv_inputs(
    macro_regime_name: str = "Accommodative 2024",
    regime_category: str = "accommodative",
) -> AgentInputs:
    return AgentInputs(
        case_id="test_case",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "macro_regime_id": "regime_001",
            "macro_regime_name": macro_regime_name,
            "regime_category": regime_category,
            "latest_material_event_id": "evt_001",
        },
    )


def _e3mv_payload(
    *,
    regime_characterisation: str = "Accommodative 2024 regime with rate cuts",
    next_3m: str = "Rate cut expected in next 3 months; 25 bps probable.",
    next_6m: str = "Continued accommodation; cumulative 50 bps likely.",
    next_12m: str = "Pause likely by year end; rates stable at 6%.",
    sector_implications: list[dict] | None = None,
    cycle_positioning: str = "early_cutting",
    reasoning_summary: str | None = None,
    inr_outlook: str = "Mildly depreciating to 85 vs USD.",
) -> dict[str, Any]:
    return {
        "rate_environment": {
            "current_repo_bps": 625,
            "regime_characterisation": regime_characterisation,
            "real_rate_assessment": "Positive real rates at 1.75%.",
        },
        "cycle_positioning": cycle_positioning,
        "forward_expectations": {
            "next_3m": next_3m,
            "next_6m": next_6m,
            "next_12m": next_12m,
        },
        "fx_view": {
            "inr_outlook": inr_outlook,
            "key_pressures": ["oil imports", "FII outflows"],
        },
        "sector_macro_implications": (
            sector_implications
            if sector_implications is not None
            else _E3MV_SECTOR_IMPLICATIONS
        ),
        "confidence": 0.8,
        "reasoning_summary": reasoning_summary or _E3MV_REASONING_GOOD,
    }


class TestE3MacroViewShim:
    shim = E3MacroViewShim()

    def test_valid_pass(self) -> None:
        inputs = _e3mv_inputs()
        res = _parse_and_validate(self.shim, inputs, _e3mv_payload())
        assert res.success is True
        assert res.error_type is None

    def test_rule_1_regime_name_not_in_characterisation(self) -> None:
        inputs = _e3mv_inputs(macro_regime_name="Accommodative 2024")
        payload = _e3mv_payload(
            regime_characterisation="Completely different description here"
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_1_regime_name_missing_from_characterisation"

    def test_rule_2_forward_expectation_whitespace_only(self) -> None:
        # " " has length 1 (passes Pydantic min_length) but fails .strip()
        inputs = _e3mv_inputs()
        payload = _e3mv_payload(next_3m=" ")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_forward_expectations_incomplete"

    def test_rule_3_insufficient_sector_coverage_count(self) -> None:
        inputs = _e3mv_inputs()
        # Only 4 sectors — below the minimum of 5
        payload = _e3mv_payload(
            sector_implications=_E3MV_SECTOR_IMPLICATIONS[:4]
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_insufficient_sector_coverage"

    def test_rule_3_missing_required_sector(self) -> None:
        inputs = _e3mv_inputs()
        # 5 entries but "energy" replaced with non-required sector
        implications = _E3MV_SECTOR_IMPLICATIONS[:4] + [
            {
                "sector_code": "automobile",
                "implication": "EV transition accelerating.",
                "directional_signal": "neutral",
            }
        ]
        payload = _e3mv_payload(sector_implications=implications)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_missing_required_sectors"

    def test_rule_4_cycle_regime_mismatch(self) -> None:
        # accommodative + active_tightening → mismatch
        inputs = _e3mv_inputs(regime_category="accommodative")
        payload = _e3mv_payload(cycle_positioning="active_tightening")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_cycle_regime_mismatch"

    def test_rule_5_no_quantitative_tokens(self) -> None:
        inputs = _e3mv_inputs()
        # 200+ chars but zero numeric tokens
        no_numbers = (
            "The macro environment remains broadly accommodative. "
            "Credit conditions are improving and the outlook for "
            "growth is constructive. Sectoral implications are broadly "
            "supportive. Forward expectations reflect continued policy "
            "easing by the central bank over the coming quarters and "
            "FX conditions are benign. Overall conditions support "
            "continued accumulation of risk assets within mandate limits."
        )
        payload = _e3mv_payload(reasoning_summary=no_numbers)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_5_insufficient_quantitative_grounding"

    def test_rule_6_inr_outlook_whitespace(self) -> None:
        inputs = _e3mv_inputs()
        payload = _e3mv_payload(inr_outlook=" ")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_6_inr_outlook_missing"

    def test_parse_error_on_garbage_json(self) -> None:
        inputs = _e3mv_inputs()
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text="not json at all!!!"), inputs
            )

    def test_validate_input_missing_required_field(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"macro_regime_name": "X", "regime_category": "accommodative"},
            # macro_regime_id is missing
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_compute_cache_key(self) -> None:
        inputs = _e3mv_inputs()
        key = self.shim.compute_cache_key(inputs)
        assert key == "e3mv:regime_001:evt_001"

    def test_compute_cache_key_no_event(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={
                "macro_regime_id": "r1",
                "macro_regime_name": "X",
                "regime_category": "accommodative",
            },
        )
        key = self.shim.compute_cache_key(inputs)
        assert key == "e3mv:r1:no_material_event_seeded"


# ---------------------------------------------------------------------------
# E2.SectorView
# ---------------------------------------------------------------------------

_E2SV_REASONING_GOOD = (
    "Banking sector in Accommodative 2024 regime: credit growth 14% YoY. "
    "Net interest margins expected to compress 20 bps as rates fall. "
    "Loan book quality improving with NPA ratio declining. "
    "Regulatory pressure moderate — SEBI tightening NBFC norms. "
    "Recovery cycle underway with capacity utilisation at 78%. "
    "Dominant themes: credit growth, NIM compression, NBFC consolidation, "
    "retail loan expansion. Overall sector verdict is favourable given "
    "accommodative macro and improving credit metrics."
)


def _e2sv_inputs(
    sector_code: str = "banking_financial_services",
    macro_regime_name: str = "Accommodative 2024",
) -> AgentInputs:
    return AgentInputs(
        case_id="test_case",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "sector_code": sector_code,
            "macro_regime_id": "regime_001",
            "macro_regime_name": macro_regime_name,
            "sector_manual_flag_id": "flag_abc",
        },
    )


def _e2sv_payload(
    *,
    sector_code: str = "banking_financial_services",
    verdict: str = "favourable",
    cycle_stage: str = "recovery",
    dominant_themes: list[str] | None = None,
    regulatory_intensity: str = "moderate",
    key_considerations: list[str] | None = None,
    reasoning_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "sector_code": sector_code,
        "sector_view_verdict": verdict,
        "cycle_stage": cycle_stage,
        "dominant_themes": dominant_themes or [
            "credit growth acceleration",
            "NIM compression on rate cuts",
            "NBFC consolidation pressure",
            "retail loan book expansion",
        ],
        "competitive_structure": {
            "structure_type": "consolidated",
            "concentration_trend": "stable",
        },
        "regulatory_environment": {
            "intensity": regulatory_intensity,
            "key_considerations": (
                key_considerations
                if key_considerations is not None
                else ["SEBI tightening NBFC lending norms"]
            ),
        },
        "confidence": 0.75,
        "reasoning_summary": reasoning_summary or _E2SV_REASONING_GOOD,
    }


class TestE2SectorViewShim:
    shim = E2SectorViewShim()

    def test_valid_pass(self) -> None:
        inputs = _e2sv_inputs()
        res = _parse_and_validate(self.shim, inputs, _e2sv_payload())
        assert res.success is True
        assert res.error_type is None

    def test_rule_1_sector_code_mismatch(self) -> None:
        inputs = _e2sv_inputs(sector_code="banking_financial_services")
        payload = _e2sv_payload(sector_code="information_technology")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_1_sector_code_mismatch"

    def test_rule_2_macro_regime_not_in_reasoning(self) -> None:
        inputs = _e2sv_inputs(macro_regime_name="Accommodative 2024")
        payload = _e2sv_payload(
            reasoning_summary=(
                "Credit growth 14% YoY. NIM down 20 bps. "
                "Recovery cycle underway. Sector verdict favourable. "
                "Regulatory pressure moderate. Capacity utilisation 78%. "
                "Retail loan book expanding strongly. Overall positive "
                "trajectory confirmed by leading indicators."
                # Deliberately omits "Accommodative 2024"
            )
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_macro_regime_not_in_reasoning"

    def test_rule_3_generic_theme(self) -> None:
        inputs = _e2sv_inputs()
        payload = _e2sv_payload(
            dominant_themes=["growth opportunity", "NIM compression"]
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_generic_theme"

    def test_rule_3_parse_error_too_few_themes(self) -> None:
        # dominant_themes min_length=2 is a Pydantic constraint — it fires
        # at the schema layer (parse_output), not as a semantic rule.
        inputs = _e2sv_inputs()
        payload = _e2sv_payload(dominant_themes=["credit growth acceleration"])
        with pytest.raises(ValueError):
            _parse_and_validate(self.shim, inputs, payload)

    def test_rule_4_moderate_intensity_no_considerations(self) -> None:
        inputs = _e2sv_inputs()
        payload = _e2sv_payload(
            regulatory_intensity="moderate",
            key_considerations=[],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_missing_regulatory_considerations"

    def test_rule_5_no_quant_tokens(self) -> None:
        inputs = _e2sv_inputs()
        no_numbers = (
            "In the Accommodative 2024 regime, banking sector shows "
            "improving credit conditions. Regulatory environment is "
            "moderate. Recovery cycle is underway. Dominant themes are "
            "credit growth and retail expansion. Sector verdict is "
            "favourable given the macro context and improving fundamentals. "
            "Key considerations include NBFC norms and policy direction."
        )
        payload = _e2sv_payload(reasoning_summary=no_numbers)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_5_insufficient_quantitative_grounding"

    def test_rule_6_challenging_with_recovery(self) -> None:
        inputs = _e2sv_inputs()
        payload = _e2sv_payload(verdict="challenging", cycle_stage="recovery")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_6_verdict_cycle_stage_inconsistency"

    def test_rule_6_favourable_with_contraction(self) -> None:
        inputs = _e2sv_inputs()
        payload = _e2sv_payload(verdict="favourable", cycle_stage="contraction")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_6_verdict_cycle_stage_inconsistency"

    def test_parse_error_on_garbage_json(self) -> None:
        inputs = _e2sv_inputs()
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text="{bad json["), inputs
            )

    def test_validate_input_missing_required_field(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"sector_code": "banking_financial_services"},
            # macro_regime_id + macro_regime_name missing
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_compute_cache_key(self) -> None:
        inputs = _e2sv_inputs()
        key = self.shim.compute_cache_key(inputs)
        assert key == "e2sv:banking_financial_services:regime_001:flag_abc"


# ---------------------------------------------------------------------------
# E2.StockInSector
# ---------------------------------------------------------------------------

_E2SIS_REASONING_GOOD = (
    "HDFCBANK in banking_financial_services sector: top quartile by "
    "return on equity and loan book quality metrics. "
    "Mid_cycle stage with 14% credit growth. "
    "CASA ratio 42% vs sector median 38%. "
    "Net NPA ratio 0.3% vs sector median 1.2%. "
    "Strong competitive positioning via retail franchise and "
    "digital acquisition channels. Sector context supports positive "
    "positioning relative to peers."
)


def _e2sis_inputs(
    ticker: str = "HDFCBANK",
    sector_code: str = "banking_financial_services",
) -> AgentInputs:
    return AgentInputs(
        case_id="test_case",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "ticker": ticker,
            "sector_code": sector_code,
            "sector_view_output": {
                "cycle_stage": "mid_cycle",
                "sector_view_verdict": "favourable",
            },
        },
    )


def _e2sis_payload(
    *,
    ticker: str = "HDFCBANK",
    sector_code: str = "banking_financial_services",
    verdict: str = "above_median",
    sector_quartile: str = "second",
    ranking_framework: str = "CASA ratio, NPA quality, digital franchise reach",
    sector_relative_signals: list[dict] | None = None,
    reasoning_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "sector_code": sector_code,
        "stock_in_sector_verdict": verdict,
        "positioning_within_sector": {
            "sector_quartile": sector_quartile,
            "ranking_framework": ranking_framework,
            "key_competitive_attributes": [
                "CASA ratio 42%",
                "Digital acquisition 60% of new accounts",
            ],
        },
        "sector_relative_signals": sector_relative_signals or [
            {
                "signal": "market share gain in home loans",
                "direction": "positive",
                "severity": "medium",
            },
            {
                "signal": "deposit franchise strength vs peers",
                "direction": "positive",
                "severity": "medium",
            },
        ],
        "confidence": 0.75,
        "reasoning_summary": reasoning_summary or _E2SIS_REASONING_GOOD,
    }


class TestE2StockInSectorShim:
    shim = E2StockInSectorShim()

    def test_valid_pass(self) -> None:
        inputs = _e2sis_inputs()
        res = _parse_and_validate(self.shim, inputs, _e2sis_payload())
        assert res.success is True

    def test_rule_1_ticker_mismatch_raises_in_parse(self) -> None:
        # parse_output raises ValueError on ticker mismatch
        inputs = _e2sis_inputs(ticker="HDFCBANK")
        payload = _e2sis_payload(ticker="ICICIBANK")
        with pytest.raises(ValueError, match="ticker mismatch"):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(payload)), inputs
            )

    def test_rule_1_sector_mismatch_raises_in_parse(self) -> None:
        inputs = _e2sis_inputs(sector_code="banking_financial_services")
        payload = _e2sis_payload(sector_code="information_technology")
        with pytest.raises(ValueError, match="sector_code mismatch"):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(payload)), inputs
            )

    def test_rule_2_best_in_class_requires_top_quartile(self) -> None:
        inputs = _e2sis_inputs()
        payload = _e2sis_payload(
            verdict="best_in_class",
            sector_quartile="second",  # not "top"
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_verdict_quartile_mismatch"

    def test_rule_2_challenged_requires_bottom_quartile(self) -> None:
        inputs = _e2sis_inputs()
        payload = _e2sis_payload(
            verdict="challenged_position",
            sector_quartile="third",  # not "bottom"
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_verdict_quartile_mismatch"

    def test_rule_3_generic_ranking_framework(self) -> None:
        inputs = _e2sis_inputs()
        payload = _e2sis_payload(ranking_framework="fundamental analysis")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_generic_ranking_framework"

    def test_rule_4_sector_context_warning(self) -> None:
        # cycle_stage provided in sector_view_output but not in reasoning
        inputs = _e2sis_inputs()
        # Reasoning that omits "mid_cycle"
        reasoning = (
            "HDFCBANK in banking_financial_services sector: top quartile "
            "by loan quality. CASA 42%, NPA 0.3%. Strong digital franchise. "
            "Competitive positioning superior to peers. Retail growth "
            "continuing at high pace. Market share gains in home loans. "
            "Deposit franchise robust. Overall strong position maintained."
        )
        payload = _e2sis_payload(reasoning_summary=reasoning)
        res = _parse_and_validate(self.shim, inputs, payload)
        # Rule 4 is a WARNING — success=True but error_type is set
        assert res.success is True
        assert res.error_type == "rule_4_sector_context_not_in_reasoning_warn"

    def test_rule_5_signals_fundamentals_only(self) -> None:
        inputs = _e2sis_inputs()
        # All signals are pure E1 fundamentals terms
        payload = _e2sis_payload(
            sector_relative_signals=[
                {"signal": "roce", "direction": "positive", "severity": "medium"},
                {"signal": "debt equity", "direction": "positive", "severity": "low"},
                {
                    "signal": "pe ratio",
                    "direction": "positive",
                    "severity": "low",
                },
            ]
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_5_signals_are_fundamentals_only"

    def test_parse_error_on_garbage_json(self) -> None:
        inputs = _e2sis_inputs()
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text="garbage input"), inputs
            )

    def test_validate_input_missing_required_field(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"ticker": "HDFCBANK"},
            # sector_code missing
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_compute_cache_key(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={
                "ticker": "HDFCBANK",
                "sector_code": "banking_financial_services",
                "latest_earnings_id": "earn_001",
                "stock_manual_flag_id": "flag_001",
            },
        )
        key = self.shim.compute_cache_key(inputs)
        assert key == (
            "e2sis:HDFCBANK:banking_financial_services:earn_001:flag_001"
        )


# ---------------------------------------------------------------------------
# E7 MutualFund
# ---------------------------------------------------------------------------

_E7_REASONING_GOOD = (
    "Mirae Asset Large Cap Fund managed by Neelesh Surana since 2008. "
    "Alpha 5Y: 180 bps above Nifty 100. TER 1.61%. "
    "AUM 32000 Cr — ample capacity for largecap_equity. "
    "Alpha consistency above median peer quartile. "
    "Fee structure below category norm of 1.75%. "
    "Key signals: alpha generation positive, manager continuity positive, "
    "TER competitive, AUM manageable. Verdict: positive."
)


def _e7_inputs(
    fund_id: str = "mirae_large_cap",
    fund_name: str = "Mirae Asset Large Cap Fund",
    fund_category: str = "largecap_equity",
    current_manager_name: str = "Neelesh Surana",
    ter_pct_current: float | None = 1.61,
    alpha_5y_bps_input: int | None = 185,
    current_aum_inr_cr: float | None = 32000.0,
) -> AgentInputs:
    payload: dict[str, Any] = {
        "fund_id": fund_id,
        "fund_name": fund_name,
        "fund_category": fund_category,
        "current_manager_name": current_manager_name,
    }
    if ter_pct_current is not None:
        payload["ter_pct_current"] = ter_pct_current
    if alpha_5y_bps_input is not None:
        payload["alpha_5y_bps_input"] = alpha_5y_bps_input
    if current_aum_inr_cr is not None:
        payload["current_aum_inr_cr"] = current_aum_inr_cr
    return AgentInputs(
        case_id="test_case",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload=payload,
    )


def _e7_payload(
    *,
    fund_id: str = "mirae_large_cap",
    fund_verdict: str = "positive",
    manager_name: str = "Neelesh Surana",
    alpha_5y_bps: int = 180,
    ter_pct: float = 1.62,
    capacity_signal: str = "ample",
    current_aum_inr_cr: float = 32000.0,
    key_signals: list[dict] | None = None,
    reasoning_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "fund_id": fund_id,
        "fund_verdict": fund_verdict,
        "manager_continuity_assessment": {
            "manager_name": manager_name,
            "tenure_years": 16,
            "continuity_signal": "stable_long_tenure",
        },
        "alpha_assessment": {
            "alpha_5y_bps": alpha_5y_bps,
            "benchmark": "Nifty 100 TRI",
            "alpha_consistency": "consistent_positive",
        },
        "fee_structure_assessment": {
            "ter_pct": ter_pct,
            "category_norm_pct": 1.75,
            "fee_verdict": "below_norm",
        },
        "capacity_assessment": {
            "current_aum_inr_cr": current_aum_inr_cr,
            "capacity_signal": capacity_signal,
        },
        "style_consistency": "consistent_with_stated_mandate",
        "category_positioning": {
            "category": "largecap_equity",
            "peer_quartile": "top",
            "peer_set_summary": "Top 5 of 30 largecap funds.",
        },
        "key_signals": key_signals or [
            {"signal": "alpha generation", "direction": "positive", "severity": "high"},
            {"signal": "manager continuity", "direction": "positive", "severity": "medium"},
            {"signal": "TER competitive", "direction": "positive", "severity": "low"},
            {"signal": "AUM manageable", "direction": "positive", "severity": "low"},
        ],
        "confidence": 0.8,
        "reasoning_summary": reasoning_summary or _E7_REASONING_GOOD,
    }


class TestE7MutualFundShim:
    shim = E7MutualFundShim()

    def test_valid_pass(self) -> None:
        inputs = _e7_inputs()
        res = _parse_and_validate(self.shim, inputs, _e7_payload())
        assert res.success is True

    def test_rule_1_fund_id_mismatch_raises_in_parse(self) -> None:
        inputs = _e7_inputs(fund_id="mirae_large_cap")
        payload = _e7_payload(fund_id="axis_bluechip")
        with pytest.raises(ValueError, match="fund_id mismatch"):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(payload)), inputs
            )

    def test_rule_2_manager_name_mismatch(self) -> None:
        inputs = _e7_inputs(current_manager_name="Neelesh Surana")
        payload = _e7_payload(manager_name="Completely Different Person")
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_manager_name_mismatch"

    def test_rule_3_alpha_outside_plausibility(self) -> None:
        inputs = _e7_inputs(alpha_5y_bps_input=None)
        payload = _e7_payload(alpha_5y_bps=2000)  # above 1500 ceiling
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_alpha_outside_plausibility"

    def test_rule_3_alpha_not_grounded(self) -> None:
        inputs = _e7_inputs(alpha_5y_bps_input=185)
        payload = _e7_payload(alpha_5y_bps=300)  # >20 bps from 185
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_alpha_not_grounded"

    def test_rule_4_ter_not_grounded(self) -> None:
        inputs = _e7_inputs(ter_pct_current=1.61)
        payload = _e7_payload(ter_pct=1.80)  # > 0.05 from 1.61
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_ter_not_grounded"

    def test_rule_5_capacity_signal_inconsistent(self) -> None:
        # largecap_equity: ample fails if AUM >= 80000
        inputs = _e7_inputs(
            fund_category="largecap_equity",
            current_aum_inr_cr=90000.0,
            ter_pct_current=None,
            alpha_5y_bps_input=None,
        )
        payload = _e7_payload(
            capacity_signal="ample",
            current_aum_inr_cr=90000.0,
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_5_capacity_signal_inconsistent"

    def test_rule_6_positive_verdict_needs_60pct_positive(self) -> None:
        inputs = _e7_inputs()
        # Only 2 of 5 signals positive → below 60%
        signals = [
            {"signal": "alpha", "direction": "positive", "severity": "high"},
            {"signal": "manager", "direction": "positive", "severity": "medium"},
            {"signal": "TER", "direction": "negative", "severity": "low"},
            {"signal": "AUM", "direction": "negative", "severity": "low"},
            {"signal": "style", "direction": "negative", "severity": "medium"},
        ]
        payload = _e7_payload(fund_verdict="positive", key_signals=signals)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_6_verdict_signals_inconsistency"

    def test_rule_7_no_quant_tokens(self) -> None:
        inputs = _e7_inputs(
            ter_pct_current=None, alpha_5y_bps_input=None
        )
        no_numbers = (
            "Mirae Asset Large Cap Fund managed by Neelesh Surana. "
            "Alpha generation is strong relative to benchmark peers. "
            "TER is competitive within category. AUM is at ample levels. "
            "Manager has a long and stable tenure at the fund. "
            "Style consistency is strong with no meaningful drift observed. "
            "Overall verdict is positive based on multiple positive signals."
        )
        payload = _e7_payload(reasoning_summary=no_numbers)
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_7_insufficient_quantitative_grounding"

    def test_parse_error_on_garbage_json(self) -> None:
        inputs = _e7_inputs()
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text="<not json>"), inputs
            )

    def test_validate_input_missing_required_field(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"fund_id": "x", "fund_name": "y"},
            # fund_category missing
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_compute_cache_key(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={
                "fund_id": "mirae_large_cap",
                "fund_name": "Mirae Asset Large Cap Fund",
                "fund_category": "largecap_equity",
                "latest_quarterly_disclosure_id": "disc_2024q3",
                "fund_manual_flag_id": "flagX",
            },
        )
        key = self.shim.compute_cache_key(inputs)
        assert key == "e7:mirae_large_cap:disc_2024q3:flagX"


# ---------------------------------------------------------------------------
# E3.NewsScanner
# ---------------------------------------------------------------------------

_NS_REASONING = (
    "Scanned 90 days of news for RELIANCE and INFY. "
    "RELIANCE: 1 high-materiality event (management change) warrants "
    "cache invalidation. INFY: 2 medium-materiality events, no "
    "cache invalidation triggered. Overall confidence high."
)


def _ns_inputs(
    case_id: str = "case_ns_001",
    tickers: list[str] | None = None,
    available_news_ids: list[str] | None = None,
) -> AgentInputs:
    payload: dict[str, Any] = {
        "case_id": case_id,
        "tickers": tickers or ["RELIANCE", "INFY"],
    }
    if available_news_ids is not None:
        payload["available_news_ids"] = available_news_ids
    return AgentInputs(
        case_id=case_id,
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload=payload,
    )


def _ns_payload(
    *,
    case_id: str = "case_ns_001",
    per_ticker_signals: list[dict] | None = None,
    cache_invalidation_pushes: list[dict] | None = None,
    reasoning_summary: str | None = None,
) -> dict[str, Any]:
    default_pts = [
        {
            "ticker": "RELIANCE",
            "has_material_events": True,
            "events": [
                {
                    "news_id": "news_001",
                    "headline": "Reliance appoints new CFO",
                    "category": "management_change",
                    "materiality_level": "high",
                    "warrants_cache_invalidation": True,
                    "rationale": (
                        "CFO change warrants review of financial strategy."
                    ),
                }
            ],
        },
        {
            "ticker": "INFY",
            "has_material_events": False,
            "events": [
                {
                    "news_id": "news_002",
                    "headline": "Infosys Q2 revenue guidance maintained",
                    "category": "earnings_guidance",
                    "materiality_level": "low",
                    "warrants_cache_invalidation": False,
                    "rationale": "Guidance unchanged; no re-assessment needed.",
                }
            ],
        },
    ]
    return {
        "case_id": case_id,
        "scan_period": {"from": "2024-01-01", "to": "2024-03-31"},
        "per_ticker_signals": (
            per_ticker_signals if per_ticker_signals is not None else default_pts
        ),
        "case_level_signals": [],
        "cache_invalidation_pushes": (
            cache_invalidation_pushes
            if cache_invalidation_pushes is not None
            else [
                {
                    "ticker": "RELIANCE",
                    "news_id": "news_001",
                    "invalidates_e1": True,
                    "invalidates_e2sis": True,
                    "reason": "Management change warrants E1/E2SIS re-run.",
                }
            ]
        ),
        "confidence": 0.85,
        "reasoning_summary": reasoning_summary or _NS_REASONING,
    }


class TestE3NewsScannerShim:
    shim = E3NewsScannerShim()

    def test_valid_pass(self) -> None:
        inputs = _ns_inputs()
        res = _parse_and_validate(self.shim, inputs, _ns_payload())
        assert res.success is True

    def test_rule_1_case_id_mismatch_raises_in_parse(self) -> None:
        inputs = _ns_inputs(case_id="case_ns_001")
        payload = _ns_payload(case_id="case_ns_999")
        with pytest.raises(ValueError, match="case_id mismatch"):
            self.shim.parse_output(
                LLMResponse(text=json.dumps(payload)), inputs
            )

    def test_rule_2_missing_ticker_coverage(self) -> None:
        inputs = _ns_inputs(tickers=["RELIANCE", "INFY", "TCS"])
        # Payload only covers RELIANCE + INFY, misses TCS
        res = _parse_and_validate(self.shim, inputs, _ns_payload())
        assert res.success is False
        assert res.error_type == "rule_2_missing_ticker_coverage"

    def test_rule_2_extra_ticker_in_signals(self) -> None:
        # Payload has TCS which is not in input tickers
        inputs = _ns_inputs(tickers=["RELIANCE"])
        payload = _ns_payload()  # has both RELIANCE + INFY
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_2_extra_ticker_in_signals"

    def test_rule_3_hallucinated_news_id(self) -> None:
        inputs = _ns_inputs(
            available_news_ids=["news_001", "news_002"]
        )
        # news_003 not in available_news_ids
        pts = [
            {
                "ticker": "RELIANCE",
                "has_material_events": True,
                "events": [
                    {
                        "news_id": "news_003",
                        "headline": "Fake news item",
                        "category": "other_material",
                        "materiality_level": "high",
                        "warrants_cache_invalidation": True,
                        "rationale": "Hallucinated event.",
                    }
                ],
            },
            {
                "ticker": "INFY",
                "has_material_events": False,
                "events": [],
            },
        ]
        payload = _ns_payload(
            per_ticker_signals=pts,
            cache_invalidation_pushes=[
                {
                    "ticker": "RELIANCE",
                    "news_id": "news_003",
                    "invalidates_e1": True,
                    "invalidates_e2sis": False,
                    "reason": "Hallucinated.",
                }
            ],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_3_hallucinated_news_id"

    def test_rule_4_push_without_warrant(self) -> None:
        inputs = _ns_inputs()
        # Push references news_002 which has warrants_cache_invalidation=False
        payload = _ns_payload(
            cache_invalidation_pushes=[
                {
                    "ticker": "INFY",
                    "news_id": "news_002",
                    "invalidates_e1": True,
                    "invalidates_e2sis": False,
                    "reason": "Should not push for low materiality.",
                }
            ]
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_4_push_without_warrant"

    def test_rule_5_high_materiality_not_invalidating(self) -> None:
        inputs = _ns_inputs()
        pts = [
            {
                "ticker": "RELIANCE",
                "has_material_events": True,
                "events": [
                    {
                        "news_id": "news_001",
                        "headline": "Reliance major regulatory action",
                        "category": "regulatory_action",
                        "materiality_level": "high",
                        "warrants_cache_invalidation": False,  # violates rule 5
                        "rationale": "Should have invalidated.",
                    }
                ],
            },
            {"ticker": "INFY", "has_material_events": False, "events": []},
        ]
        payload = _ns_payload(
            per_ticker_signals=pts, cache_invalidation_pushes=[]
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_5_high_materiality_not_invalidating"

    def test_rule_6_low_materiality_invalidating(self) -> None:
        inputs = _ns_inputs()
        pts = [
            {
                "ticker": "RELIANCE",
                "has_material_events": False,
                "events": [
                    {
                        "news_id": "news_001",
                        "headline": "Routine AGM notice",
                        "category": "corporate_action_routine",
                        "materiality_level": "low",
                        "warrants_cache_invalidation": True,  # violates rule 6
                        "rationale": "Routine event over-flagged.",
                    }
                ],
            },
            {"ticker": "INFY", "has_material_events": False, "events": []},
        ]
        payload = _ns_payload(
            per_ticker_signals=pts,
            cache_invalidation_pushes=[
                {
                    "ticker": "RELIANCE",
                    "news_id": "news_001",
                    "invalidates_e1": True,
                    "invalidates_e2sis": False,
                    "reason": "Wrongly flagged.",
                }
            ],
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_6_low_materiality_invalidating"

    def test_rule_7_empty_rationale(self) -> None:
        inputs = _ns_inputs()
        pts = [
            {
                "ticker": "RELIANCE",
                "has_material_events": False,
                "events": [
                    {
                        "news_id": "news_001",
                        "headline": "Reliance routine disclosure",
                        "category": "other_routine",
                        "materiality_level": "medium",
                        "warrants_cache_invalidation": False,
                        "rationale": " ",  # only whitespace — fails .strip()
                    }
                ],
            },
            {"ticker": "INFY", "has_material_events": False, "events": []},
        ]
        payload = _ns_payload(
            per_ticker_signals=pts, cache_invalidation_pushes=[]
        )
        res = _parse_and_validate(self.shim, inputs, payload)
        assert res.success is False
        assert res.error_type == "rule_7_empty_rationale"

    def test_parse_error_on_garbage_json(self) -> None:
        inputs = _ns_inputs()
        with pytest.raises(ValueError):
            self.shim.parse_output(
                LLMResponse(text="{{totally broken"), inputs
            )

    def test_validate_input_missing_case_id(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"tickers": ["RELIANCE"]},
            # case_id missing from payload
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "missing_field"

    def test_validate_input_tickers_not_list(self) -> None:
        inputs = AgentInputs(
            case_id="x",
            case_mode="proposed_action",
            case_intent="invest_top_up",
            payload={"case_id": "case_x", "tickers": "RELIANCE"},
        )
        res = self.shim.validate_input(inputs)
        assert res.success is False
        assert res.error_type == "invalid_field"

    def test_compute_cache_key_is_none(self) -> None:
        # E3.NewsScanner is not cached
        inputs = _ns_inputs()
        assert self.shim.compute_cache_key(inputs) is None
