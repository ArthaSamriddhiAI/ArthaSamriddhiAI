"""Structural eval harness — cluster 7 chunk 7.4 §1.

Walks every cluster-7 shim through a battery of canned LLM outputs
and checks the rule machinery does what the chunk-7.1/7.3 spec
prescribes. The harness is deterministic + offline (no Anthropic
calls); it's the safety net under the per-rule unit tests so that an
accidental rule regression surfaces in CI as a single failed harness
run rather than a diffuse cluster of unit-test failures.

Each entry in :data:`STRUCTURAL_CASES` declares:

- ``case_id`` — short slug for reporting.
- ``shim`` — :class:`AgentShim` instance under test.
- ``input`` — :class:`AgentInputs` to feed.
- ``llm_output`` — canned JSON string the mock client returns.
- ``expected`` — :class:`HarnessExpectation`: pass / fail-with-error-type /
  warning-with-error-type.

Run the harness:

>>> report = run_structural_eval()
>>> report.all_passed
True
>>> report.failures
()
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from artha.api_v2.agents.e1.shim import E1Shim
from artha.api_v2.agents.e2_sector_view.shim import E2SectorViewShim
from artha.api_v2.agents.e2_stock_in_sector.shim import E2StockInSectorShim
from artha.api_v2.agents.e3_macro_view.shim import E3MacroViewShim
from artha.api_v2.agents.e3_news_scanner.shim import E3NewsScannerShim
from artha.api_v2.agents.e7_mutual_fund.shim import E7MutualFundShim
from artha.api_v2.agents.llm_client import LLMResponse
from artha.api_v2.agents.m0_pra.shim import M0PortfolioRiskAnalyticsShim
from artha.api_v2.agents.shim import AgentInputs, AgentShim

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HarnessExpectation:
    """What the harness expects to observe for one canned input.

    Three flavours:

    - ``outcome="pass"`` — schema valid, semantic validation passes.
    - ``outcome="fail"`` — schema valid, semantic validation fails with
      ``expected_error_type``.
    - ``outcome="warn"`` — schema valid, semantic validation succeeds
      but emits a warning with ``expected_error_type``.
    - ``outcome="parse_error"`` — schema validation fails (malformed
      JSON or wrong shape).
    """

    outcome: str
    expected_error_type: str | None = None


@dataclass(frozen=True)
class StructuralCase:
    """One harness case."""

    case_id: str
    description: str
    shim: AgentShim
    inputs: AgentInputs
    llm_output: str
    expected: HarnessExpectation


@dataclass(frozen=True)
class HarnessOutcome:
    """Result of running one :class:`StructuralCase`."""

    case_id: str
    description: str
    expected_outcome: str
    expected_error_type: str | None
    actual_outcome: str
    actual_error_type: str | None
    passed: bool


@dataclass(frozen=True)
class HarnessReport:
    """Aggregate result of running all cases."""

    cases: tuple[HarnessOutcome, ...] = ()

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.cases)

    @property
    def failures(self) -> tuple[HarnessOutcome, ...]:
        return tuple(c for c in self.cases if not c.passed)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.cases if c.passed)


# ---------------------------------------------------------------------------
# Shared payload builders
# ---------------------------------------------------------------------------


def _e1_inputs(ticker: str = "RELIANCE") -> AgentInputs:
    return AgentInputs(
        case_id="harness_case",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "ticker": ticker,
            "snapshot_excerpt": "snapshot",
            "mandate_excerpt": "mandate",
            "macro_context": "macro",
            "latest_earnings_id": "no_earnings_seeded",
            "manual_flag_id": "null",
        },
    )


def _e1_payload(
    *,
    ticker: str = "RELIANCE",
    verdict: str = "positive",
    confidence: float = 0.7,
    risk_signals: list[str] | None = None,
    reasoning_words: int = 240,
    axis_value: str = "consumer/IT large-cap value-quality blend",
) -> dict[str, Any]:
    reasoning = f"{ticker} " + " ".join(
        [f"word{i}" for i in range(reasoning_words)],
    )
    return {
        "ticker": ticker,
        "verdict": verdict,
        "confidence": confidence,
        "metric_evaluations": {
            "roce": {"reading": "in-range"},
            "leverage": {"reading": "low"},
            "earnings_quality": {"reading": "high"},
            "valuation": {"reading": "fair"},
            "growth": {"reading": "moderate"},
            "margins": {"reading": "stable"},
        },
        "per_stock_framework": {
            "framework_axis": "quality_maturity_best_in_class",
            "axis_value": axis_value,
        },
        "risk_signals": risk_signals or [],
        "reasoning_summary": reasoning,
        "key_drivers": [{"driver": "x", "weight": "high"}],
    }


def _m0_pra_inputs(case_mode: str = "proposed_action") -> AgentInputs:
    return AgentInputs(
        case_id="harness_case",
        case_mode=case_mode,
        case_intent="invest_top_up",
        payload={
            "mandate": {
                "concentration_ceiling": {"hhi_at_holding": 0.25},
                "leverage_ceiling": 1.5,
                "liquidity_floor": {"T+0_to_T+30": 0.05},
                "fee_drag_ceiling_bps": 100,
            },
            "portfolio_analytics_pre_action": {
                "metrics": {
                    "concentration": {"hhi_at_holding": 0.18},
                    "leverage": {"leverage_ratio": 1.1},
                    "liquidity": {
                        "buckets": {
                            "T+0_to_T+3": 0.04,
                            "T+3_to_T+30": 0.08,
                        },
                    },
                    "fee_drag": {"aggregate_bps": 65},
                },
            },
            "portfolio_analytics_post_action": {
                "metrics": {
                    "concentration": {"hhi_at_holding": 0.17},
                    "leverage": {"leverage_ratio": 1.05},
                    "liquidity": {
                        "buckets": {
                            "T+0_to_T+3": 0.04,
                            "T+3_to_T+30": 0.10,
                        },
                    },
                    "fee_drag": {"aggregate_bps": 57},
                },
            },
            "evidence_summaries": [],
        },
    )


def _m0_pra_payload(
    *,
    overall: str = "moderate",
    confidence: float = 0.7,
    include_delta: bool = True,
    concentration_tag: str = "clean",
) -> dict[str, Any]:
    delta = "improves -8% post-action" if include_delta else None

    def _dim(reading: str, tag: str = "clean") -> dict[str, Any]:
        d: dict[str, Any] = {"reading": reading, "verdict_tag": tag}
        if delta is not None:
            d["delta_post_action"] = delta
        return d

    return {
        "overall_risk_level": overall,
        "confidence": confidence,
        "per_dimension_assessment": {
            "concentration": _dim("HHI 0.18 within band", concentration_tag),
            "leverage": _dim("leverage 1.1x"),
            "liquidity": _dim("T+0..30 = 12%"),
            "return_quality": _dim("Sharpe 1.4"),
            "fee_drag": _dim("aggregate 65 bps"),
            "deployment": _dim("82% deployed"),
        },
        "cascade_implications": [
            {
                "implication": "capital call timing T+45",
                "horizon": "near_term",
                "severity": "low",
            },
        ],
        "flagged_proximity": [],
        "reasoning_summary": (
            "HHI 0.18 (below ceiling 0.25), leverage 1.1x (below 1.5x), "
            "fee drag 65 bps (below 100). Post-action delta tightens "
            "liquidity by 4 percentage points and trims fee drag 8 bps "
            "across all six dimensions; overall stable verdict."
        ),
        "key_risk_drivers": [{"driver": "x", "weight": "high"}],
    }


# ---------------------------------------------------------------------------
# Canonical case set
# ---------------------------------------------------------------------------


def _build_structural_cases() -> tuple[StructuralCase, ...]:
    e1 = E1Shim()
    m0 = M0PortfolioRiskAnalyticsShim()

    cases: list[StructuralCase] = []

    # ------------------------------------------------------------------
    # E1 — Rule 1 (verdict-risk consistency)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_rule1_clean_positive",
            description="positive verdict with no high-severity signals passes",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(_e1_payload()),
            expected=HarnessExpectation(outcome="pass"),
        ),
    )
    cases.append(
        StructuralCase(
            case_id="e1_rule1_positive_with_promoter_pledge",
            description="positive + promoter pledge fails rule 1",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(
                _e1_payload(
                    risk_signals=["promoter pledge near covenant"],
                ),
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_1_verdict_risk_mismatch",
            ),
        ),
    )

    # ------------------------------------------------------------------
    # E1 — Rule 2 (confidence calibration)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_rule2_high_conf_short_reasoning",
            description="confidence>=0.85 with short reasoning fails rule 2",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(
                _e1_payload(confidence=0.92, reasoning_words=210),
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_2_confidence_underjustified",
            ),
        ),
    )
    cases.append(
        StructuralCase(
            case_id="e1_rule2_high_conf_long_reasoning_ok",
            description="confidence>=0.85 with >=300 words passes",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(
                _e1_payload(confidence=0.9, reasoning_words=320),
            ),
            expected=HarnessExpectation(outcome="pass"),
        ),
    )

    # ------------------------------------------------------------------
    # E1 — Rule 4 (framework axis presence on positive)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_rule4_positive_missing_axis_value",
            description="positive verdict with empty axis_value fails rule 4",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(_e1_payload(axis_value="")),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_4_missing_framework_axis_value",
            ),
        ),
    )

    # ------------------------------------------------------------------
    # E1 — Rule 5 (ticker mention warning)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_rule5_ticker_missing_warning",
            description="reasoning omits ticker — warning, not failure",
            shim=e1,
            inputs=_e1_inputs("INFY"),
            llm_output=json.dumps(
                {
                    **_e1_payload(),
                    "ticker": "INFY",  # honest ticker
                    "reasoning_summary": " ".join(
                        ["word" for _ in range(220)],
                    ),  # no ticker mention
                },
            ),
            expected=HarnessExpectation(
                outcome="warn",
                expected_error_type="rule_5_ticker_not_in_reasoning_warn",
            ),
        ),
    )

    # ------------------------------------------------------------------
    # M0.PRA — Rule 1 (mandate breach flagging)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="m0_rule1_clean",
            description="metrics in-band, verdict tags clean → pass",
            shim=m0,
            inputs=_m0_pra_inputs(),
            llm_output=json.dumps(_m0_pra_payload()),
            expected=HarnessExpectation(outcome="pass"),
        ),
    )

    # ------------------------------------------------------------------
    # M0.PRA — Rule 3 (PA delta requirement)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="m0_rule3_pa_missing_delta",
            description="proposed_action mode + missing deltas → fail rule 3",
            shim=m0,
            inputs=_m0_pra_inputs(case_mode="proposed_action"),
            llm_output=json.dumps(
                _m0_pra_payload(include_delta=False),
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_3_missing_delta_on_pa",
            ),
        ),
    )
    cases.append(
        StructuralCase(
            case_id="m0_rule3_diagnostic_no_delta_ok",
            description="diagnostic mode → no delta requirement → pass",
            shim=m0,
            inputs=_m0_pra_inputs(case_mode="diagnostic"),
            llm_output=json.dumps(
                _m0_pra_payload(include_delta=False),
            ),
            expected=HarnessExpectation(outcome="pass"),
        ),
    )

    # ------------------------------------------------------------------
    # M0.PRA — Rule 5 (critical confidence calibration)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="m0_rule5_critical_underconfident",
            description="critical verdict with confidence<0.75 fails rule 5",
            shim=m0,
            inputs=_m0_pra_inputs(),
            llm_output=json.dumps(
                _m0_pra_payload(overall="critical", confidence=0.6),
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_5_critical_underconfident",
            ),
        ),
    )

    # ------------------------------------------------------------------
    # Schema — malformed JSON
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_schema_garbage",
            description="non-JSON output → schema parse error",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output="totally not json output",
            expected=HarnessExpectation(outcome="parse_error"),
        ),
    )

    return tuple(cases)


#: Canonical case set the harness exercises. Tests in
#: :mod:`tests.test_unit.test_api_v2_agents_cluster7_eval` pin this.
STRUCTURAL_CASES: tuple[StructuralCase, ...] = _build_structural_cases()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_structural_eval(
    cases: tuple[StructuralCase, ...] | None = None,
) -> HarnessReport:
    """Run every structural case and return a :class:`HarnessReport`.

    Pure / sync; no LLM calls — the canned ``llm_output`` strings are
    handed straight to each shim's :meth:`AgentShim.parse_output` +
    :meth:`AgentShim.validate_output` hooks.
    """
    target = cases if cases is not None else STRUCTURAL_CASES
    outcomes: list[HarnessOutcome] = []
    for c in target:
        outcomes.append(_run_one(c))
    return HarnessReport(cases=tuple(outcomes))


def _run_one(case: StructuralCase) -> HarnessOutcome:
    shim = case.shim

    # Pre-flight input validation — if it fails, record as parse_error
    # (it bubbles up the same place the dispatcher would).
    pre = shim.validate_input(case.inputs)
    if not pre.success:
        actual_outcome = "parse_error"
        actual_error: str | None = pre.error_type
    else:
        try:
            verdict = shim.parse_output(
                LLMResponse(text=case.llm_output),
                case.inputs,
            )
        except Exception:  # noqa: BLE001 — schema / parse failure
            actual_outcome = "parse_error"
            actual_error = None
        else:
            sem = shim.validate_output(verdict, case.inputs)
            if sem.success and sem.error_type is None:
                actual_outcome = "pass"
                actual_error = None
            elif sem.success and sem.error_type is not None:
                actual_outcome = "warn"
                actual_error = sem.error_type
            else:
                actual_outcome = "fail"
                actual_error = sem.error_type

    passed = actual_outcome == case.expected.outcome and (
        case.expected.expected_error_type is None
        or actual_error == case.expected.expected_error_type
    )
    return HarnessOutcome(
        case_id=case.case_id,
        description=case.description,
        expected_outcome=case.expected.outcome,
        expected_error_type=case.expected.expected_error_type,
        actual_outcome=actual_outcome,
        actual_error_type=actual_error,
        passed=passed,
    )


def format_report(report: HarnessReport) -> str:
    """Render a :class:`HarnessReport` as a multi-line string for CLI."""
    lines: list[str] = []
    lines.append(
        f"Cluster 7 structural eval — {report.passed_count}/{report.total} "
        f"passed",
    )
    lines.append("=" * 60)
    for o in report.cases:
        marker = "PASS" if o.passed else "FAIL"
        line = (
            f"{marker:4s}  {o.case_id:42s}  "
            f"expected={o.expected_outcome:10s} "
            f"actual={o.actual_outcome}"
        )
        if o.expected_error_type:
            line += f"  expected_err={o.expected_error_type}"
        if o.actual_error_type and o.actual_error_type != o.expected_error_type:
            line += f"  actual_err={o.actual_error_type}"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cluster-8 payload builders
# ---------------------------------------------------------------------------

_C8_SECTOR_IMPLICATIONS = [
    {
        "sector_code": "banking_financial_services",
        "implication": "Credit growth 14% YoY; NIM compression 20 bps expected.",
        "directional_signal": "favourable",
    },
    {
        "sector_code": "information_technology",
        "implication": "USD tailwind 3% from INR at 84; deal wins accelerating.",
        "directional_signal": "favourable",
    },
    {
        "sector_code": "fast_moving_consumer_goods",
        "implication": "Rural demand up 8% on lower EMI burden.",
        "directional_signal": "favourable",
    },
    {
        "sector_code": "pharma_healthcare",
        "implication": "API exports 12%; US FDA approvals improving.",
        "directional_signal": "favourable",
    },
    {
        "sector_code": "energy",
        "implication": "Capex cycle 9% volume growth on infrastructure spend.",
        "directional_signal": "favourable",
    },
]

_C8_E3MV_REASONING = (
    "RBI repo rate cut 25 bps to 6.25%. Real rate now 1.75%. "
    "INR at 84 vs USD. Inflation 4.1%. Fiscal deficit 5.1% of GDP. "
    "Growth trajectory improving with 6-month transmission lag. "
    "Forward expectations broadly accommodative across all horizons. "
    "Sector implications positive as cost of capital declines."
)

_C8_E2SV_REASONING = (
    "Banking sector in Accommodative 2024 regime: credit growth 14% YoY. "
    "NIM expected to compress 20 bps as rates fall. NPA ratio declining. "
    "Regulatory pressure moderate — SEBI NBFC norms tightening. "
    "Recovery cycle underway; capacity utilisation 78%. "
    "Sector verdict favourable given accommodative macro backdrop."
)

_C8_E2SIS_REASONING = (
    "HDFCBANK in banking_financial_services sector: top quartile by loan quality. "
    "mid_cycle stage with 14% credit growth. CASA ratio 42% vs median 38%. "
    "Net NPA 0.3% vs sector median 1.2%. Strong digital franchise. "
    "Market share gains in home loans. Competitive positioning superior."
)

_C8_E7_REASONING = (
    "Mirae Asset Large Cap Fund managed by Neelesh Surana since 2008. "
    "Alpha 5Y: 180 bps above Nifty 100. TER 1.62%. "
    "AUM 32000 Cr — ample capacity for largecap_equity category. "
    "Peer quartile top. Style consistency maintained over 8 years. "
    "Key signals all positive. Verdict: positive."
)

_C8_NS_REASONING = (
    "Scanned 90 days of news for RELIANCE. "
    "1 high-materiality event: CFO management change. "
    "Cache invalidation warranted for E1 and E2SIS. "
    "Overall confidence high."
)


def _c8_e3mv_inputs(regime_category: str = "accommodative") -> AgentInputs:
    return AgentInputs(
        case_id="harness_c8",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "macro_regime_id": "regime_001",
            "macro_regime_name": "Accommodative 2024",
            "regime_category": regime_category,
            "latest_material_event_id": "evt_001",
        },
    )


def _c8_e3mv_payload(
    *,
    regime_characterisation: str = "Accommodative 2024 regime with rate cuts",
    cycle_positioning: str = "early_cutting",
    next_3m: str = "Rate cut 25 bps probable in next quarter.",
    reasoning: str | None = None,
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
            "next_6m": "Cumulative 50 bps likely over 6 months.",
            "next_12m": "Pause expected by year end at 6%.",
        },
        "fx_view": {
            "inr_outlook": inr_outlook,
            "key_pressures": ["oil imports", "FII outflows"],
        },
        "sector_macro_implications": _C8_SECTOR_IMPLICATIONS,
        "confidence": 0.8,
        "reasoning_summary": reasoning or _C8_E3MV_REASONING,
    }


def _c8_e2sv_inputs() -> AgentInputs:
    return AgentInputs(
        case_id="harness_c8",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "sector_code": "banking_financial_services",
            "macro_regime_id": "regime_001",
            "macro_regime_name": "Accommodative 2024",
            "sector_manual_flag_id": "null",
        },
    )


def _c8_e2sv_payload(
    *,
    verdict: str = "favourable",
    cycle_stage: str = "recovery",
    reasoning: str | None = None,
) -> dict[str, Any]:
    return {
        "sector_code": "banking_financial_services",
        "sector_view_verdict": verdict,
        "cycle_stage": cycle_stage,
        "dominant_themes": [
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
            "intensity": "moderate",
            "key_considerations": ["SEBI tightening NBFC lending norms"],
        },
        "confidence": 0.75,
        "reasoning_summary": reasoning or _C8_E2SV_REASONING,
    }


def _c8_e2sis_inputs() -> AgentInputs:
    return AgentInputs(
        case_id="harness_c8",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "ticker": "HDFCBANK",
            "sector_code": "banking_financial_services",
            "sector_view_output": {
                "cycle_stage": "mid_cycle",
                "sector_view_verdict": "favourable",
            },
        },
    )


def _c8_e2sis_payload(
    *,
    verdict: str = "above_median",
    sector_quartile: str = "second",
    ranking_framework: str = "CASA ratio, NPA quality, digital franchise reach",
    reasoning: str | None = None,
) -> dict[str, Any]:
    return {
        "ticker": "HDFCBANK",
        "sector_code": "banking_financial_services",
        "stock_in_sector_verdict": verdict,
        "positioning_within_sector": {
            "sector_quartile": sector_quartile,
            "ranking_framework": ranking_framework,
            "key_competitive_attributes": [
                "CASA 42% vs median 38%",
                "Digital acquisition 60% of new accounts",
            ],
        },
        "sector_relative_signals": [
            {
                "signal": "market share gain in home loans",
                "direction": "positive",
                "severity": "medium",
            },
            {
                "signal": "deposit franchise vs peers",
                "direction": "positive",
                "severity": "medium",
            },
        ],
        "confidence": 0.75,
        "reasoning_summary": reasoning or _C8_E2SIS_REASONING,
    }


def _c8_e7_inputs() -> AgentInputs:
    return AgentInputs(
        case_id="harness_c8",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "fund_id": "mirae_large_cap",
            "fund_name": "Mirae Asset Large Cap Fund",
            "fund_category": "largecap_equity",
            "current_manager_name": "Neelesh Surana",
        },
    )


def _c8_e7_payload(
    *,
    verdict: str = "positive",
    alpha_5y_bps: int = 180,
    ter_pct: float = 1.62,
    capacity_signal: str = "ample",
    key_signals: list[dict] | None = None,
    reasoning: str | None = None,
) -> dict[str, Any]:
    return {
        "fund_id": "mirae_large_cap",
        "fund_verdict": verdict,
        "manager_continuity_assessment": {
            "manager_name": "Neelesh Surana",
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
            "current_aum_inr_cr": 32000.0,
            "capacity_signal": capacity_signal,
        },
        "style_consistency": "consistent_with_stated_mandate",
        "category_positioning": {
            "category": "largecap_equity",
            "peer_quartile": "top",
            "peer_set_summary": "Top 5 of 30 largecap funds.",
        },
        "key_signals": key_signals or [
            {
                "signal": "alpha generation",
                "direction": "positive",
                "severity": "high",
            },
            {
                "signal": "manager continuity 8+ years",
                "direction": "positive",
                "severity": "medium",
            },
            {
                "signal": "TER competitive vs peers",
                "direction": "positive",
                "severity": "low",
            },
            {
                "signal": "AUM manageable",
                "direction": "positive",
                "severity": "low",
            },
        ],
        "confidence": 0.8,
        "reasoning_summary": reasoning or _C8_E7_REASONING,
    }


def _c8_ns_inputs() -> AgentInputs:
    return AgentInputs(
        case_id="case_ns_h01",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "case_id": "case_ns_h01",
            "tickers": ["RELIANCE"],
        },
    )


def _c8_ns_payload(
    *,
    case_id: str = "case_ns_h01",
    reasoning: str | None = None,
    per_ticker_signals: list[dict] | None = None,
    cache_invalidation_pushes: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "scan_period": {"from": "2024-01-01", "to": "2024-03-31"},
        "per_ticker_signals": per_ticker_signals or [
            {
                "ticker": "RELIANCE",
                "has_material_events": True,
                "events": [
                    {
                        "news_id": "news_h01",
                        "headline": "Reliance appoints new CFO",
                        "category": "management_change",
                        "materiality_level": "high",
                        "warrants_cache_invalidation": True,
                        "rationale": (
                            "CFO appointment warrants E1/E2SIS re-assessment."
                        ),
                    }
                ],
            }
        ],
        "case_level_signals": [],
        "cache_invalidation_pushes": cache_invalidation_pushes or [
            {
                "ticker": "RELIANCE",
                "news_id": "news_h01",
                "invalidates_e1": True,
                "invalidates_e2sis": True,
                "reason": "Management change warrants full cache invalidation.",
            }
        ],
        "confidence": 0.85,
        "reasoning_summary": reasoning or _C8_NS_REASONING,
    }


# ---------------------------------------------------------------------------
# Cluster-8 canonical case set
# ---------------------------------------------------------------------------


def _build_structural_cases_cluster8() -> tuple[StructuralCase, ...]:  # noqa: C901
    e3mv = E3MacroViewShim()
    e2sv = E2SectorViewShim()
    e2sis = E2StockInSectorShim()
    e7 = E7MutualFundShim()
    ns = E3NewsScannerShim()

    cases: list[StructuralCase] = []

    # ------------------------------------------------------------------
    # E3.MacroView — clean pass
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_e3mv_clean",
            description="E3.MacroView clean pass — all 6 rules satisfied",
            shim=e3mv,
            inputs=_c8_e3mv_inputs(),
            llm_output=json.dumps(_c8_e3mv_payload()),
            expected=HarnessExpectation(outcome="pass"),
        )
    )

    # ------------------------------------------------------------------
    # E3.MacroView — rule 1 (regime name missing from characterisation)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_e3mv_rule1_fail",
            description="E3.MacroView rule 1: regime_name absent from characterisation",
            shim=e3mv,
            inputs=_c8_e3mv_inputs(),
            llm_output=json.dumps(
                _c8_e3mv_payload(
                    regime_characterisation="Some other unrelated description"
                )
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_1_regime_name_missing_from_characterisation",
            ),
        )
    )

    # ------------------------------------------------------------------
    # E3.MacroView — rule 5 (no quant tokens in reasoning)
    # ------------------------------------------------------------------
    no_quant_reasoning = (
        "The macro environment remains broadly accommodative. Credit "
        "conditions are improving and the outlook for growth is constructive. "
        "Sectoral implications are broadly supportive for risk assets. "
        "Forward expectations reflect continued policy easing over coming "
        "quarters. FX conditions remain benign and no significant pressures "
        "are observed. Monetary policy is on an easing trajectory overall."
    )
    cases.append(
        StructuralCase(
            case_id="c8_e3mv_rule5_fail",
            description="E3.MacroView rule 5: reasoning_summary has no quant tokens",
            shim=e3mv,
            inputs=_c8_e3mv_inputs(),
            llm_output=json.dumps(
                _c8_e3mv_payload(reasoning=no_quant_reasoning)
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_5_insufficient_quantitative_grounding",
            ),
        )
    )

    # ------------------------------------------------------------------
    # E2.SectorView — clean pass
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_e2sv_clean",
            description="E2.SectorView clean pass — all 6 rules satisfied",
            shim=e2sv,
            inputs=_c8_e2sv_inputs(),
            llm_output=json.dumps(_c8_e2sv_payload()),
            expected=HarnessExpectation(outcome="pass"),
        )
    )

    # ------------------------------------------------------------------
    # E2.SectorView — rule 6 (verdict/cycle_stage inconsistency)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_e2sv_rule6_fail",
            description=(
                "E2.SectorView rule 6: challenging verdict with recovery cycle"
            ),
            shim=e2sv,
            inputs=_c8_e2sv_inputs(),
            llm_output=json.dumps(
                _c8_e2sv_payload(verdict="challenging", cycle_stage="recovery")
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_6_verdict_cycle_stage_inconsistency",
            ),
        )
    )

    # ------------------------------------------------------------------
    # E2.SectorView — rule 2 (macro regime not in reasoning)
    # ------------------------------------------------------------------
    sv_no_regime = (
        "Banking sector: credit growth 14% YoY. NIM down 20 bps. "
        "Recovery underway. Regulatory pressure moderate with SEBI NBFC norms. "
        "Capacity utilisation 78%. Retail loan expansion continuing. "
        "Verdict favourable given improving credit metrics."
    )
    cases.append(
        StructuralCase(
            case_id="c8_e2sv_rule2_fail",
            description="E2.SectorView rule 2: macro_regime_name absent from reasoning",
            shim=e2sv,
            inputs=_c8_e2sv_inputs(),
            llm_output=json.dumps(
                _c8_e2sv_payload(reasoning=sv_no_regime)
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_2_macro_regime_not_in_reasoning",
            ),
        )
    )

    # ------------------------------------------------------------------
    # E2.StockInSector — clean pass
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_e2sis_clean",
            description="E2.StockInSector clean pass — all 5 rules satisfied",
            shim=e2sis,
            inputs=_c8_e2sis_inputs(),
            llm_output=json.dumps(_c8_e2sis_payload()),
            expected=HarnessExpectation(outcome="pass"),
        )
    )

    # ------------------------------------------------------------------
    # E2.StockInSector — rule 3 (generic ranking framework)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_e2sis_rule3_fail",
            description="E2.StockInSector rule 3: generic ranking_framework",
            shim=e2sis,
            inputs=_c8_e2sis_inputs(),
            llm_output=json.dumps(
                _c8_e2sis_payload(ranking_framework="fundamental analysis")
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_3_generic_ranking_framework",
            ),
        )
    )

    # ------------------------------------------------------------------
    # E2.StockInSector — rule 2 (best_in_class needs top quartile)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_e2sis_rule2_fail",
            description=(
                "E2.StockInSector rule 2: best_in_class with upper quartile"
            ),
            shim=e2sis,
            inputs=_c8_e2sis_inputs(),
            llm_output=json.dumps(
                _c8_e2sis_payload(verdict="best_in_class", sector_quartile="second")
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_2_verdict_quartile_mismatch",
            ),
        )
    )

    # ------------------------------------------------------------------
    # E7.MutualFund — clean pass
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_e7_clean",
            description="E7.MutualFund clean pass — all 7 rules satisfied",
            shim=e7,
            inputs=_c8_e7_inputs(),
            llm_output=json.dumps(_c8_e7_payload()),
            expected=HarnessExpectation(outcome="pass"),
        )
    )

    # ------------------------------------------------------------------
    # E7.MutualFund — rule 5 (capacity_signal=ample with AUM>=80000)
    # ------------------------------------------------------------------
    e7_high_aum_inputs = AgentInputs(
        case_id="harness_c8",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "fund_id": "mirae_large_cap",
            "fund_name": "Mirae Asset Large Cap Fund",
            "fund_category": "largecap_equity",
            "current_manager_name": "Neelesh Surana",
            "current_aum_inr_cr": 90000.0,
        },
    )
    cases.append(
        StructuralCase(
            case_id="c8_e7_rule5_fail",
            description="E7 rule 5: capacity_signal=ample but AUM>=80000 Cr",
            shim=e7,
            inputs=e7_high_aum_inputs,
            llm_output=json.dumps(
                _c8_e7_payload(capacity_signal="ample")
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_5_capacity_signal_inconsistent",
            ),
        )
    )

    # ------------------------------------------------------------------
    # E7.MutualFund — rule 6 (positive verdict with <60% positive signals)
    # ------------------------------------------------------------------
    e7_low_positive_signals = [
        {"signal": "alpha", "direction": "positive", "severity": "high"},
        {"signal": "manager", "direction": "positive", "severity": "medium"},
        {"signal": "TER", "direction": "negative", "severity": "low"},
        {"signal": "AUM", "direction": "negative", "severity": "low"},
        {"signal": "style", "direction": "negative", "severity": "medium"},
    ]
    cases.append(
        StructuralCase(
            case_id="c8_e7_rule6_fail",
            description="E7 rule 6: positive verdict with only 40% positive signals",
            shim=e7,
            inputs=_c8_e7_inputs(),
            llm_output=json.dumps(
                _c8_e7_payload(
                    verdict="positive",
                    key_signals=e7_low_positive_signals,
                )
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_6_verdict_signals_inconsistency",
            ),
        )
    )

    # ------------------------------------------------------------------
    # E3.NewsScanner — clean pass
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="c8_ns_clean",
            description="E3.NewsScanner clean pass — all 7 rules satisfied",
            shim=ns,
            inputs=_c8_ns_inputs(),
            llm_output=json.dumps(_c8_ns_payload()),
            expected=HarnessExpectation(outcome="pass"),
        )
    )

    # ------------------------------------------------------------------
    # E3.NewsScanner — rule 5 (high materiality not invalidating)
    # ------------------------------------------------------------------
    ns_rule5_pts = [
        {
            "ticker": "RELIANCE",
            "has_material_events": True,
            "events": [
                {
                    "news_id": "news_h02",
                    "headline": "Reliance major regulatory action",
                    "category": "regulatory_action",
                    "materiality_level": "high",
                    "warrants_cache_invalidation": False,  # violates rule 5
                    "rationale": "Should have been True for high materiality.",
                }
            ],
        }
    ]
    cases.append(
        StructuralCase(
            case_id="c8_ns_rule5_fail",
            description=(
                "E3.NewsScanner rule 5: high materiality without invalidation"
            ),
            shim=ns,
            inputs=_c8_ns_inputs(),
            llm_output=json.dumps(
                {
                    "case_id": "case_ns_h01",
                    "scan_period": {"from": "2024-01-01", "to": "2024-03-31"},
                    "per_ticker_signals": ns_rule5_pts,
                    "case_level_signals": [],
                    "cache_invalidation_pushes": [],  # no pushes → rule 4 won't fire
                    "confidence": 0.85,
                    "reasoning_summary": _C8_NS_REASONING,
                }
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_5_high_materiality_not_invalidating",
            ),
        )
    )

    return tuple(cases)


#: Canonical cluster-8 structural cases.
STRUCTURAL_CASES_CLUSTER8: tuple[StructuralCase, ...] = (
    _build_structural_cases_cluster8()
)


def run_cluster8_structural_eval(
    cases: tuple[StructuralCase, ...] | None = None,
) -> HarnessReport:
    """Run cluster-8 structural eval cases."""
    target = cases if cases is not None else STRUCTURAL_CASES_CLUSTER8
    return HarnessReport(cases=tuple(_run_one(c) for c in target))


__all__ = [
    "STRUCTURAL_CASES",
    "STRUCTURAL_CASES_CLUSTER8",
    "HarnessExpectation",
    "HarnessOutcome",
    "HarnessReport",
    "StructuralCase",
    "format_report",
    "run_cluster8_structural_eval",
    "run_structural_eval",
]
