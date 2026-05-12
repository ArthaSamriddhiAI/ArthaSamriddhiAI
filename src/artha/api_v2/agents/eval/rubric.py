"""Manual review rubric — cluster 7 chunk 7.4 §2.

Eight hand-curated cases that exercise the corner cases an analyst
should sanity-check by reading a real LLM verdict. Half exercise E1
(per-stock fundamental analysis); half exercise M0.PortfolioRiskAnalytics
(portfolio-risk rollup). Each case carries:

- ``case_id`` — short slug.
- ``agent_id`` — which shim to invoke.
- ``description`` — what the analyst is checking for.
- ``inputs`` — the :class:`AgentInputs` to feed the shim.
- ``review_criteria`` — bullet list the analyst rates the LLM verdict
  against (4 criteria, 1-5 score each, 20 points total per case).
- ``expected_verdict_summary`` — the expected directional answer (so
  the analyst can detect off-axis hallucinations quickly).

Workflow (chunk 7.4 §2.3):

1. Run the rubric against a real Anthropic model.
2. For each case, score every criterion 1-5.
3. Aggregate to a per-case score / 20 + a total / 160.
4. Total <= 120 → block prompt rollout; investigate failures.

The rubric defines data only — driving real Anthropic calls is the
analyst's responsibility (cluster 7 ideation §6.4 keeps tooling
out of the runtime to avoid scope creep).
"""

from __future__ import annotations

from dataclasses import dataclass

from artha.api_v2.agents.shim import AgentInputs

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewCriterion:
    """One scoring axis on a rubric case (1-5 scale)."""

    label: str
    description: str


@dataclass(frozen=True)
class RubricCase:
    """One manual-review case."""

    case_id: str
    agent_id: str
    description: str
    inputs: AgentInputs
    review_criteria: tuple[ReviewCriterion, ...]
    expected_verdict_summary: str


# ---------------------------------------------------------------------------
# Shared criterion definitions
# ---------------------------------------------------------------------------


_E1_CRITERIA: tuple[ReviewCriterion, ...] = (
    ReviewCriterion(
        label="metric_grounding",
        description=(
            "Does each metric_evaluations entry cite specific numerical "
            "values (e.g. ROCE %, leverage ratio, P/E)?"
        ),
    ),
    ReviewCriterion(
        label="risk_signal_specificity",
        description=(
            "Are listed risk_signals concrete and ticker-specific (not "
            "boilerplate)?"
        ),
    ),
    ReviewCriterion(
        label="framework_axis_fit",
        description=(
            "Does per_stock_framework.framework_axis match the stock's "
            "lifecycle/style profile?"
        ),
    ),
    ReviewCriterion(
        label="reasoning_coherence",
        description=(
            "Does reasoning_summary tie metrics → verdict → confidence "
            "without contradictions?"
        ),
    ),
)


_M0_PRA_CRITERIA: tuple[ReviewCriterion, ...] = (
    ReviewCriterion(
        label="mandate_consistency",
        description=(
            "Are per-dimension verdict_tags consistent with the mandate "
            "ceilings/floors fed in?"
        ),
    ),
    ReviewCriterion(
        label="quantitative_grounding",
        description=(
            "Does reasoning_summary cite multiple numerical values from "
            "the deterministic metrics?"
        ),
    ),
    ReviewCriterion(
        label="cascade_specificity",
        description=(
            "Are cascade_implications concrete (capital call, reserved "
            "liquidity) rather than generic?"
        ),
    ),
    ReviewCriterion(
        label="delta_commentary",
        description=(
            "For PA/SCENARIO modes: does each dimension delta_post_action "
            "describe direction + magnitude?"
        ),
    ),
)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _e1_inputs(
    *,
    ticker: str,
    snapshot_excerpt: str,
    mandate_excerpt: str,
    macro_context: str = "Not dispatched in this case",
) -> AgentInputs:
    return AgentInputs(
        case_id=f"rubric_{ticker.lower()}",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "ticker": ticker,
            "snapshot_excerpt": snapshot_excerpt,
            "mandate_excerpt": mandate_excerpt,
            "macro_context": macro_context,
            "latest_earnings_id": "no_earnings_seeded",
            "manual_flag_id": "null",
        },
    )


def _m0_pra_inputs(
    *,
    case_id: str,
    case_mode: str,
    mandate: dict,
    pre: dict,
    post: dict | None,
    proposed_action_summary: str,
    dominant_lens: str,
) -> AgentInputs:
    payload: dict = {
        "mandate": mandate,
        "portfolio_analytics_pre_action": pre,
        "proposed_action_summary": proposed_action_summary,
        "dominant_lens": dominant_lens,
        "evidence_summaries": [],
    }
    if post is not None:
        payload["portfolio_analytics_post_action"] = post
    return AgentInputs(
        case_id=case_id,
        case_mode=case_mode,
        case_intent="invest_top_up",
        payload=payload,
    )


def _build_rubric_cases() -> tuple[RubricCase, ...]:
    cases: list[RubricCase] = []

    # ------------------------------------------------------------------
    # E1 cases
    # ------------------------------------------------------------------

    cases.append(
        RubricCase(
            case_id="rubric_e1_quality_compounder",
            agent_id="e1_listed_fundamental_equity",
            description=(
                "Quality compounder (consumer staples large-cap). Stable "
                "30%+ ROCE, low leverage, premium valuation."
            ),
            inputs=_e1_inputs(
                ticker="HINDUNILVR",
                snapshot_excerpt=(
                    "Holding 4.5% portfolio. ROCE 110%, EBITDA margin 24%, "
                    "leverage 0.0x. P/E 62 vs 5y mean 58. Cashflow positive "
                    "every quarter for 7 years."
                ),
                mandate_excerpt=(
                    "Conservative mandate: 8% per-holding cap, equity sleeve "
                    "30-50%, value-at-fair-quality lens dominant."
                ),
            ),
            review_criteria=_E1_CRITERIA,
            expected_verdict_summary=(
                "positive_with_valuation_caution; quality_maturity_best_in_class"
            ),
        ),
    )

    cases.append(
        RubricCase(
            case_id="rubric_e1_distressed_special_situation",
            agent_id="e1_listed_fundamental_equity",
            description=(
                "Special situation: sector cyclical at trough, leverage "
                "above sector but improving."
            ),
            inputs=_e1_inputs(
                ticker="VEDL",
                snapshot_excerpt=(
                    "Holding 1.8% portfolio. Net debt/EBITDA 2.4x (down "
                    "from 3.1x), commodity-linked revenues, dividend yield "
                    "9%. Promoter holding stable; pledge ratio 11% (down "
                    "from 26% 2y ago)."
                ),
                mandate_excerpt=(
                    "Balanced mandate: 5% per-holding cap; cyclical "
                    "exposure capped 15%."
                ),
            ),
            review_criteria=_E1_CRITERIA,
            expected_verdict_summary=(
                "special_situation; cyclical_position; explicit "
                "deleveraging-trajectory call"
            ),
        ),
    )

    cases.append(
        RubricCase(
            case_id="rubric_e1_audit_qualification_red_flag",
            agent_id="e1_listed_fundamental_equity",
            description=(
                "Auditor adds 'going concern' / qualification language "
                "between earnings."
            ),
            inputs=_e1_inputs(
                ticker="DUMMYBANK",
                snapshot_excerpt=(
                    "Holding 2.1%. Auditor flagged loan-loss provision "
                    "adequacy as a key audit matter; 'going concern' "
                    "language in subsequent-events note. Deposit growth "
                    "still positive."
                ),
                mandate_excerpt=(
                    "Conservative mandate: financial-sector cap 25%; "
                    "audit-flagged holdings restricted."
                ),
            ),
            review_criteria=_E1_CRITERIA,
            expected_verdict_summary=(
                "negative; risk_signals must list 'going concern' "
                "verbatim; verdict cannot be positive (rule 1 trip)"
            ),
        ),
    )

    cases.append(
        RubricCase(
            case_id="rubric_e1_high_growth_optical_caution",
            agent_id="e1_listed_fundamental_equity",
            description=(
                "Growth darling at premium multiple — does the model "
                "apply valuation_caution or hallucinate confidence?"
            ),
            inputs=_e1_inputs(
                ticker="ZOMATO",
                snapshot_excerpt=(
                    "Holding 1.2%. Revenue +47% YoY, EBITDA loss narrowing, "
                    "first FCF-positive quarter just announced. P/S 22 vs "
                    "global peer median 8."
                ),
                mandate_excerpt=(
                    "Aggressive mandate: 4% per-holding cap; growth-tilt "
                    "lens dominant."
                ),
            ),
            review_criteria=_E1_CRITERIA,
            expected_verdict_summary=(
                "positive_with_valuation_caution OR hold_with_attention; "
                "framework_axis quality_growth_emerging"
            ),
        ),
    )

    # ------------------------------------------------------------------
    # M0.PRA cases
    # ------------------------------------------------------------------

    liquidity_buckets = ("T+0_to_T+3", "T+3_to_T+30")

    cases.append(
        RubricCase(
            case_id="rubric_m0_clean_in_band",
            agent_id="m0_portfolio_risk_analytics",
            description=(
                "Portfolio inside every mandate band; model should "
                "synthesise to ``low`` overall, no breach flags."
            ),
            inputs=_m0_pra_inputs(
                case_id="rubric_m0_clean",
                case_mode="proposed_action",
                mandate={
                    "concentration_ceiling": {"hhi_at_holding": 0.25},
                    "leverage_ceiling": 1.5,
                    "liquidity_floor": {"T+0_to_T+30": 0.05},
                    "fee_drag_ceiling_bps": 100,
                },
                pre={
                    "metrics": {
                        "concentration": {"hhi_at_holding": 0.18},
                        "leverage": {"leverage_ratio": 1.0},
                        "liquidity": {
                            "buckets": dict.fromkeys(liquidity_buckets, 0.06),
                        },
                        "fee_drag": {"aggregate_bps": 60},
                    },
                },
                post={
                    "metrics": {
                        "concentration": {"hhi_at_holding": 0.17},
                        "leverage": {"leverage_ratio": 1.0},
                        "liquidity": {
                            "buckets": dict.fromkeys(liquidity_buckets, 0.07),
                        },
                        "fee_drag": {"aggregate_bps": 55},
                    },
                },
                proposed_action_summary=(
                    "Add 5L of large-cap blend index fund."
                ),
                dominant_lens="growth",
            ),
            review_criteria=_M0_PRA_CRITERIA,
            expected_verdict_summary=(
                "overall_risk_level=low; every dimension verdict_tag=clean"
            ),
        ),
    )

    cases.append(
        RubricCase(
            case_id="rubric_m0_concentration_breach",
            agent_id="m0_portfolio_risk_analytics",
            description=(
                "HHI above mandate ceiling; model must flag breach + "
                "escalate overall to at least ``moderate``."
            ),
            inputs=_m0_pra_inputs(
                case_id="rubric_m0_conc_breach",
                case_mode="proposed_action",
                mandate={
                    "concentration_ceiling": {"hhi_at_holding": 0.20},
                    "leverage_ceiling": 1.5,
                    "liquidity_floor": {"T+0_to_T+30": 0.05},
                    "fee_drag_ceiling_bps": 100,
                },
                pre={
                    "metrics": {
                        "concentration": {"hhi_at_holding": 0.27},
                        "leverage": {"leverage_ratio": 1.1},
                        "liquidity": {
                            "buckets": dict.fromkeys(liquidity_buckets, 0.06),
                        },
                        "fee_drag": {"aggregate_bps": 70},
                    },
                },
                post=None,
                proposed_action_summary="Top up the largest holding.",
                dominant_lens="growth",
            ),
            review_criteria=_M0_PRA_CRITERIA,
            expected_verdict_summary=(
                "concentration verdict_tag=breach; overall_risk_level "
                ">= moderate; reasoning cites the 0.27 vs 0.20 gap"
            ),
        ),
    )

    cases.append(
        RubricCase(
            case_id="rubric_m0_liquidity_floor_breach",
            agent_id="m0_portfolio_risk_analytics",
            description=(
                "Near-term liquidity below mandate floor; model must "
                "flag breach + cite cascade impact on capital calls."
            ),
            inputs=_m0_pra_inputs(
                case_id="rubric_m0_liquidity_breach",
                case_mode="proposed_action",
                mandate={
                    "concentration_ceiling": {"hhi_at_holding": 0.25},
                    "leverage_ceiling": 1.5,
                    "liquidity_floor": {"T+0_to_T+30": 0.10},
                    "fee_drag_ceiling_bps": 100,
                },
                pre={
                    "metrics": {
                        "concentration": {"hhi_at_holding": 0.18},
                        "leverage": {"leverage_ratio": 1.1},
                        "liquidity": {
                            "buckets": {
                                "T+0_to_T+3": 0.02,
                                "T+3_to_T+30": 0.05,
                            },
                        },
                        "fee_drag": {"aggregate_bps": 70},
                    },
                },
                post={
                    "metrics": {
                        "concentration": {"hhi_at_holding": 0.18},
                        "leverage": {"leverage_ratio": 1.1},
                        "liquidity": {
                            "buckets": {
                                "T+0_to_T+3": 0.01,
                                "T+3_to_T+30": 0.04,
                            },
                        },
                        "fee_drag": {"aggregate_bps": 70},
                    },
                },
                proposed_action_summary=(
                    "Subscribe 10L to AIF Cat-II with 6m drawdown schedule."
                ),
                dominant_lens="alternatives",
            ),
            review_criteria=_M0_PRA_CRITERIA,
            expected_verdict_summary=(
                "liquidity verdict_tag=breach; cascade_implications cite "
                "AIF capital call timing; deltas show worsening trend"
            ),
        ),
    )

    cases.append(
        RubricCase(
            case_id="rubric_m0_scenario_improves_position",
            agent_id="m0_portfolio_risk_analytics",
            description=(
                "Scenario where the proposed exit IMPROVES every dimension; "
                "model should describe direction in delta_post_action."
            ),
            inputs=_m0_pra_inputs(
                case_id="rubric_m0_scenario_improve",
                case_mode="scenario",
                mandate={
                    "concentration_ceiling": {"hhi_at_holding": 0.20},
                    "leverage_ceiling": 1.5,
                    "liquidity_floor": {"T+0_to_T+30": 0.05},
                    "fee_drag_ceiling_bps": 100,
                },
                pre={
                    "metrics": {
                        "concentration": {"hhi_at_holding": 0.22},
                        "leverage": {"leverage_ratio": 1.3},
                        "liquidity": {
                            "buckets": {
                                "T+0_to_T+3": 0.03,
                                "T+3_to_T+30": 0.04,
                            },
                        },
                        "fee_drag": {"aggregate_bps": 110},
                    },
                },
                post={
                    "metrics": {
                        "concentration": {"hhi_at_holding": 0.16},
                        "leverage": {"leverage_ratio": 1.0},
                        "liquidity": {
                            "buckets": {
                                "T+0_to_T+3": 0.05,
                                "T+3_to_T+30": 0.07,
                            },
                        },
                        "fee_drag": {"aggregate_bps": 75},
                    },
                },
                proposed_action_summary=(
                    "Trim 8L from over-concentrated mid-cap; redeploy to "
                    "liquid debt fund."
                ),
                dominant_lens="risk_reduction",
            ),
            review_criteria=_M0_PRA_CRITERIA,
            expected_verdict_summary=(
                "every dimension delta_post_action says 'improves' / "
                "'tightens' with magnitudes; verdict moderate→low"
            ),
        ),
    )

    return tuple(cases)


#: Canonical rubric cases. Keep at exactly 8 — chunk 7.4 §2.1.
RUBRIC_CASES: tuple[RubricCase, ...] = _build_rubric_cases()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_rubric_markdown() -> str:
    """Render the rubric as a markdown document analysts fill out.

    Output format (chunk 7.4 §2.4): one section per case with the
    description, inputs summary, expected verdict, and a checklist
    table of criteria the reviewer scores 1-5.
    """
    lines: list[str] = []
    lines.append("# Cluster 7 manual review rubric")
    lines.append("")
    lines.append(
        f"{len(RUBRIC_CASES)} hand-curated cases. For each: run the "
        "agent against a real model, then score every criterion 1-5. "
        "Total /160 — block prompt rollout if total <= 120.",
    )
    lines.append("")

    for idx, case in enumerate(RUBRIC_CASES, start=1):
        lines.append(f"## {idx}. {case.case_id}")
        lines.append("")
        lines.append(f"**Agent**: `{case.agent_id}`")
        lines.append("")
        lines.append(f"**Description**: {case.description}")
        lines.append("")
        lines.append(f"**Expected verdict**: {case.expected_verdict_summary}")
        lines.append("")
        lines.append("### Review criteria (1=poor, 5=excellent)")
        lines.append("")
        lines.append("| # | Label | Description | Score (1-5) | Notes |")
        lines.append("|---|---|---|---|---|")
        for cidx, crit in enumerate(case.review_criteria, start=1):
            lines.append(
                f"| {cidx} | `{crit.label}` | {crit.description} |  |  |",
            )
        lines.append("")
        lines.append("**Subtotal /20**:")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Grand total /160**:")
    lines.append("")
    lines.append("Reviewer name + date:")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cluster-8 criterion definitions
# ---------------------------------------------------------------------------


_E3MV_CRITERIA: tuple[ReviewCriterion, ...] = (
    ReviewCriterion(
        label="macro_data_grounding",
        description=(
            "Does reasoning_summary cite specific numerical values (repo rate "
            "bps, real rate %, inflation %, fiscal deficit %) from input data?"
        ),
    ),
    ReviewCriterion(
        label="forward_projection_specificity",
        description=(
            "Do all three forward_expectations horizons (3m/6m/12m) give "
            "concrete directional calls rather than generic placeholders?"
        ),
    ),
    ReviewCriterion(
        label="sector_implication_depth",
        description=(
            "Does each required sector entry have a sector-specific "
            "implication (not boilerplate) with a directional signal?"
        ),
    ),
    ReviewCriterion(
        label="fx_view_completeness",
        description=(
            "Is inr_outlook non-empty and does it cite at least one "
            "driver from key_pressures in reasoning?"
        ),
    ),
)


_E2SV_CRITERIA: tuple[ReviewCriterion, ...] = (
    ReviewCriterion(
        label="macro_citation",
        description=(
            "Does reasoning_summary reference the macro regime name and "
            "at least one quantitative macro indicator?"
        ),
    ),
    ReviewCriterion(
        label="theme_specificity",
        description=(
            "Are dominant_themes sector-specific (not generic patterns) "
            "and supported by concrete evidence in reasoning?"
        ),
    ),
    ReviewCriterion(
        label="regulatory_awareness",
        description=(
            "If intensity is moderate/intensive, are key_considerations "
            "specific regulatory items (not boilerplate)?"
        ),
    ),
    ReviewCriterion(
        label="cycle_coherence",
        description=(
            "Is sector_view_verdict logically consistent with cycle_stage "
            "and with the macro regime backdrop?"
        ),
    ),
)


_E2SIS_CRITERIA: tuple[ReviewCriterion, ...] = (
    ReviewCriterion(
        label="sector_context_reference",
        description=(
            "Does reasoning_summary reference the sector cycle_stage and "
            "sector_view_verdict from the upstream E2.SectorView output?"
        ),
    ),
    ReviewCriterion(
        label="ranking_specificity",
        description=(
            "Is ranking_framework a concrete multi-dimensional description "
            "(not a generic label like 'fundamental analysis')?"
        ),
    ),
    ReviewCriterion(
        label="competitive_attribute_quality",
        description=(
            "Are key_competitive_attributes quantified where possible "
            "(e.g. CASA 42% vs median 38%) rather than qualitative phrases?"
        ),
    ),
    ReviewCriterion(
        label="relative_signal_depth",
        description=(
            "Are sector_relative_signals genuinely sector-relative (market "
            "share, deposit franchise) rather than per-stock fundamentals "
            "terms (ROCE, P/E) that belong in E1?"
        ),
    ),
)


_E7_CRITERIA: tuple[ReviewCriterion, ...] = (
    ReviewCriterion(
        label="manager_grounding",
        description=(
            "Does manager_continuity_assessment.manager_name match input "
            "current_manager_name and is tenure_years plausible?"
        ),
    ),
    ReviewCriterion(
        label="alpha_quantification",
        description=(
            "Is alpha_5y_bps within 20 bps of input and within the "
            "[-1000, 1500] plausibility range?"
        ),
    ),
    ReviewCriterion(
        label="fee_benchmarking",
        description=(
            "Is ter_pct grounded in input disclosure (within 0.05), and "
            "is category_norm_pct a reasonable peer benchmark?"
        ),
    ),
    ReviewCriterion(
        label="capacity_awareness",
        description=(
            "Is capacity_signal consistent with AUM vs category-specific "
            "thresholds (e.g. largecap ample < 50000 Cr)?"
        ),
    ),
)


_E3NS_CRITERIA: tuple[ReviewCriterion, ...] = (
    ReviewCriterion(
        label="ticker_coverage",
        description=(
            "Does per_ticker_signals cover exactly the input tickers — "
            "no missing, no extra — with meaningful event lists?"
        ),
    ),
    ReviewCriterion(
        label="materiality_calibration",
        description=(
            "Are materiality_level assignments calibrated to event type "
            "(management change = high; routine = low) and consistent "
            "with warrants_cache_invalidation flags?"
        ),
    ),
    ReviewCriterion(
        label="rationale_specificity",
        description=(
            "Is each event.rationale specific to the event (not boilerplate) "
            "and does it explain why the materiality was assigned?"
        ),
    ),
    ReviewCriterion(
        label="push_proportionality",
        description=(
            "Are cache_invalidation_pushes proportionate — only high-"
            "materiality events generate pushes, and invalidates_e1 / "
            "invalidates_e2sis flags match the nature of the event?"
        ),
    ),
)


# ---------------------------------------------------------------------------
# Cluster-8 inputs builders
# ---------------------------------------------------------------------------


def _e3mv_rubric_inputs(macro_regime_name: str) -> AgentInputs:
    return AgentInputs(
        case_id=f"rubric_e3mv_{macro_regime_name.lower().replace(' ', '_')}",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "macro_regime_id": "rubric_regime_001",
            "macro_regime_name": macro_regime_name,
            "regime_category": "accommodative",
            "latest_material_event_id": "rubric_evt_001",
        },
    )


def _e2sv_rubric_inputs(sector_code: str, macro_regime_name: str) -> AgentInputs:
    return AgentInputs(
        case_id=f"rubric_e2sv_{sector_code}",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "sector_code": sector_code,
            "macro_regime_id": "rubric_regime_001",
            "macro_regime_name": macro_regime_name,
            "sector_manual_flag_id": "null",
        },
    )


def _e2sis_rubric_inputs(ticker: str, sector_code: str) -> AgentInputs:
    return AgentInputs(
        case_id=f"rubric_e2sis_{ticker.lower()}",
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


def _e7_rubric_inputs(fund_id: str, fund_name: str) -> AgentInputs:
    return AgentInputs(
        case_id=f"rubric_e7_{fund_id}",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "fund_id": fund_id,
            "fund_name": fund_name,
            "fund_category": "largecap_equity",
            "current_manager_name": "Neelesh Surana",
            "ter_pct_current": 1.61,
            "alpha_5y_bps_input": 185,
            "current_aum_inr_cr": 32000.0,
        },
    )


def _e3ns_rubric_inputs(case_id: str, tickers: list[str]) -> AgentInputs:
    return AgentInputs(
        case_id=case_id,
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={"case_id": case_id, "tickers": tickers},
    )


def _build_rubric_cases_cluster8() -> tuple[RubricCase, ...]:
    cases: list[RubricCase] = []

    # ------------------------------------------------------------------
    # E3.MacroView — 2 cases
    # ------------------------------------------------------------------

    cases.append(
        RubricCase(
            case_id="rubric_c8_e3mv_accommodative",
            agent_id="e3_macro_view",
            description=(
                "Accommodative regime (RBI rate cut cycle): verify macro "
                "data grounding, forward specificity, all 5 required sector "
                "codes present, INR outlook populated."
            ),
            inputs=_e3mv_rubric_inputs("Accommodative 2024"),
            review_criteria=_E3MV_CRITERIA,
            expected_verdict_summary=(
                "cycle_positioning=early_cutting or active_cutting; "
                "all 5 required sector codes; reasoning cites repo bps + "
                "real rate % + inflation %; inr_outlook non-empty."
            ),
        )
    )

    cases.append(
        RubricCase(
            case_id="rubric_c8_e3mv_tightening",
            agent_id="e3_macro_view",
            description=(
                "Tightening regime: verify cycle_positioning is "
                "early_tightening or active_tightening and sector "
                "implications reflect tighter cost of capital."
            ),
            inputs=AgentInputs(
                case_id="rubric_c8_e3mv_tightening",
                case_mode="proposed_action",
                case_intent="invest_top_up",
                payload={
                    "macro_regime_id": "rubric_regime_002",
                    "macro_regime_name": "Tightening 2022",
                    "regime_category": "tightening",
                    "latest_material_event_id": "rubric_evt_002",
                },
            ),
            review_criteria=_E3MV_CRITERIA,
            expected_verdict_summary=(
                "cycle_positioning=early_tightening or active_tightening; "
                "sector implications show negative signal for rate-sensitive "
                "sectors; reasoning cites bps + CPI % + policy rate."
            ),
        )
    )

    # ------------------------------------------------------------------
    # E2.SectorView — 2 cases
    # ------------------------------------------------------------------

    cases.append(
        RubricCase(
            case_id="rubric_c8_e2sv_banking_recovery",
            agent_id="e2_sector_view",
            description=(
                "Banking sector in recovery cycle: check macro regime "
                "citation, 2-4 specific themes, moderate regulatory "
                "considerations, favourable verdict consistency."
            ),
            inputs=_e2sv_rubric_inputs(
                "banking_financial_services", "Accommodative 2024"
            ),
            review_criteria=_E2SV_CRITERIA,
            expected_verdict_summary=(
                "sector_view_verdict=favourable; cycle_stage=recovery; "
                "dominant_themes credit-growth-specific (not generic); "
                "reasoning mentions Accommodative 2024 + quant %."
            ),
        )
    )

    cases.append(
        RubricCase(
            case_id="rubric_c8_e2sv_it_contraction",
            agent_id="e2_sector_view",
            description=(
                "IT sector in contraction (demand slowdown): verify "
                "verdict=challenging or neutral, cycle_stage=contraction, "
                "regulatory=low, themes specific to IT demand dynamics."
            ),
            inputs=_e2sv_rubric_inputs(
                "information_technology", "Tightening 2022"
            ),
            review_criteria=_E2SV_CRITERIA,
            expected_verdict_summary=(
                "sector_view_verdict=challenging; cycle_stage=contraction; "
                "dominant_themes: global IT spend decline, visa headwinds, "
                "deal-size compression; reasoning cites Tightening 2022 + "
                "quant demand % indicators."
            ),
        )
    )

    # ------------------------------------------------------------------
    # E2.StockInSector — 2 cases
    # ------------------------------------------------------------------

    cases.append(
        RubricCase(
            case_id="rubric_c8_e2sis_hdfcbank_top",
            agent_id="e2_stock_in_sector",
            description=(
                "HDFCBANK in banking mid-cycle: check sector context "
                "reference, non-generic ranking, quantified competitive "
                "attributes, sector-relative signals."
            ),
            inputs=_e2sis_rubric_inputs("HDFCBANK", "banking_financial_services"),
            review_criteria=_E2SIS_CRITERIA,
            expected_verdict_summary=(
                "stock_in_sector_verdict=strong_position or best_in_class; "
                "sector_quartile=top or upper; ranking_framework cites "
                "CASA %, NPA ratio; signals are market-share / deposit-"
                "franchise (not ROCE/P/E); mid_cycle in reasoning."
            ),
        )
    )

    cases.append(
        RubricCase(
            case_id="rubric_c8_e2sis_smallit_bottom",
            agent_id="e2_stock_in_sector",
            description=(
                "Small IT stock in contraction: check challenged_position "
                "verdict with bottom quartile, signals are client-"
                "concentration and deal-win-rate (sector-relative)."
            ),
            inputs=_e2sis_rubric_inputs("MPHASIS", "information_technology"),
            review_criteria=_E2SIS_CRITERIA,
            expected_verdict_summary=(
                "stock_in_sector_verdict=challenged_position; "
                "sector_quartile=bottom; ranking_framework cites deal "
                "win-rate, client concentration, offshore-mix; contraction "
                "in reasoning."
            ),
        )
    )

    # ------------------------------------------------------------------
    # E7.MutualFund — 2 cases
    # ------------------------------------------------------------------

    cases.append(
        RubricCase(
            case_id="rubric_c8_e7_mirae_positive",
            agent_id="e7_mutual_fund",
            description=(
                "Mirae Asset Large Cap: verify alpha grounded in input "
                "(±20 bps), TER within tolerance, AUM ample for largecap, "
                "manager name matches, ≥3 quant tokens in reasoning."
            ),
            inputs=_e7_rubric_inputs("mirae_large_cap", "Mirae Asset Large Cap Fund"),
            review_criteria=_E7_CRITERIA,
            expected_verdict_summary=(
                "fund_verdict=positive; alpha_5y_bps≈185 bps; "
                "ter_pct≈1.61; capacity_signal=ample (AUM 32000 Cr); "
                "manager=Neelesh Surana; ≥60% positive key_signals."
            ),
        )
    )

    cases.append(
        RubricCase(
            case_id="rubric_c8_e7_smallcap_avoid",
            agent_id="e7_mutual_fund",
            description=(
                "Small-cap fund with manager change: verdict=avoid expected "
                "due to negative alpha + elevated TER + high AUM for "
                "smallcap category."
            ),
            inputs=AgentInputs(
                case_id="rubric_c8_e7_smallcap",
                case_mode="proposed_action",
                case_intent="invest_top_up",
                payload={
                    "fund_id": "nippon_smallcap",
                    "fund_name": "Nippon India Small Cap Fund",
                    "fund_category": "smallcap_equity",
                    "current_manager_name": "Samir Rachh",
                    "ter_pct_current": 1.85,
                    "alpha_5y_bps_input": -50,
                    "current_aum_inr_cr": 52000.0,
                },
            ),
            review_criteria=_E7_CRITERIA,
            expected_verdict_summary=(
                "fund_verdict=avoid or cautious; capacity_signal=constrained "
                "or approaching_limit (AUM 52000 Cr for smallcap); "
                "majority negative key_signals; reasoning cites bps + % + Cr."
            ),
        )
    )

    # ------------------------------------------------------------------
    # E3.NewsScanner — 2 cases
    # ------------------------------------------------------------------

    cases.append(
        RubricCase(
            case_id="rubric_c8_ns_management_change",
            agent_id="e3_news_scanner",
            description=(
                "RELIANCE CFO change: high-materiality event must trigger "
                "cache invalidation push; rationale must be event-specific; "
                "low-materiality routine items must not push."
            ),
            inputs=_e3ns_rubric_inputs("rubric_case_ns_01", ["RELIANCE", "INFY"]),
            review_criteria=_E3NS_CRITERIA,
            expected_verdict_summary=(
                "RELIANCE: CFO change=high, warrants_cache_invalidation=True, "
                "invalidates_e1+e2sis=True; INFY: low/medium routine, "
                "warrants_cache_invalidation=False; rationales event-specific."
            ),
        )
    )

    cases.append(
        RubricCase(
            case_id="rubric_c8_ns_regulatory_action",
            agent_id="e3_news_scanner",
            description=(
                "HDFC Bank RBI regulatory notice: verify materiality=high, "
                "full cache invalidation; TCS no material events with empty "
                "events list; case_level_signals include portfolio-wide note."
            ),
            inputs=_e3ns_rubric_inputs(
                "rubric_case_ns_02", ["HDFCBANK", "TCS"]
            ),
            review_criteria=_E3NS_CRITERIA,
            expected_verdict_summary=(
                "HDFCBANK: regulatory_action=high, warrants_invalidation=True; "
                "TCS: has_material_events=False, events=[]; "
                "cache_invalidation_pushes for HDFCBANK only; "
                "rationale explains regulatory scope + impact."
            ),
        )
    )

    return tuple(cases)


#: Canonical cluster-8 rubric. Exactly 10 cases (2 per agent).
RUBRIC_CASES_CLUSTER8: tuple[RubricCase, ...] = _build_rubric_cases_cluster8()


def render_rubric_cluster8_markdown() -> str:
    """Render the cluster-8 rubric as markdown.

    Format follows :func:`render_rubric_markdown` (chunk 7.4 §2.4).
    Grand total: 10 cases × 20 points = /200.
    """
    lines: list[str] = []
    lines.append("# Cluster 8 manual review rubric")
    lines.append("")
    lines.append(
        f"{len(RUBRIC_CASES_CLUSTER8)} hand-curated cases (2 per C8 agent). "
        "For each: run the agent against a real model, then score every "
        "criterion 1-5. Total /200 — block prompt rollout if total <= 150.",
    )
    lines.append("")

    for idx, case in enumerate(RUBRIC_CASES_CLUSTER8, start=1):
        lines.append(f"## {idx}. {case.case_id}")
        lines.append("")
        lines.append(f"**Agent**: `{case.agent_id}`")
        lines.append("")
        lines.append(f"**Description**: {case.description}")
        lines.append("")
        lines.append(f"**Expected verdict**: {case.expected_verdict_summary}")
        lines.append("")
        lines.append("### Review criteria (1=poor, 5=excellent)")
        lines.append("")
        lines.append("| # | Label | Description | Score (1-5) | Notes |")
        lines.append("|---|---|---|---|---|")
        for cidx, crit in enumerate(case.review_criteria, start=1):
            lines.append(
                f"| {cidx} | `{crit.label}` | {crit.description} |  |  |",
            )
        lines.append("")
        lines.append("**Subtotal /20**:")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Grand total /200**")
    lines.append("")
    lines.append("Reviewer name + date:")
    return "\n".join(lines)


__all__ = [
    "RUBRIC_CASES",
    "RUBRIC_CASES_CLUSTER8",
    "ReviewCriterion",
    "RubricCase",
    "render_rubric_cluster8_markdown",
    "render_rubric_markdown",
]
