"""Cluster 5 chunk 5.4 — lookup-based stub layer.

Each stub function produces a deterministic canned payload for one
agent's stage output. The dispatcher (:mod:`.dispatch`) wires them up
to the case pipeline; the pipeline orchestrator (:mod:`.pipeline`)
runs them in the FR 20.1 §1.4 mode-specific order.

Determinism: every stub keys off ``case.case_id`` (and optionally a
``seed_archetype_id`` lookup) so replaying the same case yields the
same output. Cluster 7+ swaps these for real LLM calls; the surface —
``(case, seed_payload) -> dict`` — stays identical so the swap is
limited to the dispatcher.

Sixteen stubs, mapping 1:1 to stage-row inserters:

- 1 portfolio_risk_analytics
- 7 evidence verdicts (one per evidence agent)
- 3 synthesis (one per output mode)
- 1 IC1 deliberation (chair aggregates members)
- 3 governance gates (G1 / G2 / G3)
- 1 A1 challenge

Briefing + health stage rows aren't *agent-driven* in the same way —
they're stitcher templates filled by the chunk 5.4 pipeline using the
synthesis output. We provide a ``stub_briefing_note`` and
``stub_health_report`` here for symmetry but they aren't part of the
canonical 16.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from artha.api_v2.cases.materiality import MaterialityResult
from artha.api_v2.cases.models import Case
from artha.api_v2.cases.state_machine import (
    CaseMode,
    GovernanceGate,
    GovernanceOutcome,
    HealthOverall,
    IC1Recommendation,
    ProducedVia,
    RiskLevel,
)

# ---------------------------------------------------------------------------
# Stub context: what every stub function receives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StubContext:
    """Bag of inputs passed into every stub function.

    The dispatcher fills ``case`` from the DB row, ``seed_payload`` from
    the seed fixture (if the case has ``is_seed_data=True``), and
    ``produced_via`` from the case's seed flag. ``upstream`` is a
    typed view onto upstream stage outputs the pipeline has already
    written (e.g. synthesis stub reads evidence stub outputs from
    ``upstream.evidence_verdicts``).
    """

    case: Case
    produced_via: ProducedVia
    seed_payload: dict[str, Any] = field(default_factory=dict)
    upstream: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_to_int(case_id: str, salt: str = "") -> int:
    """Deterministic int derived from ``case_id`` + ``salt``.

    Used to seed pseudo-random-looking but reproducible placeholder
    numbers (e.g. confidence scores). Pure-Python hash so SQLite
    doesn't need extension support.
    """
    h = 0
    for ch in case_id + salt:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


def _confidence_from_case(case_id: str, salt: str) -> int:
    """Pseudo-random 65..95 confidence score for placeholder verdicts."""
    return 65 + (_hash_to_int(case_id, salt) % 31)


# ---------------------------------------------------------------------------
# 1. portfolio_risk_analytics (M0-tier deterministic)
# ---------------------------------------------------------------------------


def stub_portfolio_risk_analytics(ctx: StubContext) -> dict[str, Any]:
    """Return the canned ``PortfolioRiskAnalyticsOutput`` payload.

    Cluster 5.2's deterministic ``portfolio_analytics`` sub-agent
    handles the *real* concentration math given a portfolio state;
    this stub fills the higher-level "assessment" fields the schema
    asks for (FR 20.1 §2.4) — they're qualitative and so are stubbed
    here until cluster 7 wires real metric computation.
    """
    if "portfolio_risk_analytics" in ctx.seed_payload:
        return ctx.seed_payload["portfolio_risk_analytics"]

    cid = ctx.case.case_id
    return {
        "concentration_assessment": {
            "summary": "Top-5 holdings within firm prudence cap.",
            "hhi_score": _hash_to_int(cid, "hhi") % 1000 + 200,
            "max_single_position_pct": 6.5,
            "max_sector_share_pct": 18.2,
        },
        "leverage_assessment": {
            "summary": "Long-only book; no derivative leverage detected.",
        },
        "liquidity_assessment": {
            "summary": "Liquidity floor met (cash + liquid funds > 5%).",
            "days_to_liquidate_p95": 7,
        },
        "return_quality_assessment": {
            "summary": "Returns trail benchmark by 80 bps over trailing 12m.",
        },
        "deployment_assessment": {
            "summary": "Allocation within mandate bands; no idle cash drag.",
        },
        "cascade_assessment": {
            "summary": "No cascading-risk markers detected.",
        },
        "overall_risk_level": RiskLevel.MEDIUM.value,
        "overall_confidence": 0.75,
        "drivers": {"primary": ["concentration", "liquidity"]},
        "flags": {},
        "reasoning_summary": (
            "Stub portfolio risk analytics; cluster 7 swaps for real metric "
            "computation."
        ),
        "portfolio_analytics_input_hash": f"stub_{cid[:8]}",
    }


# ---------------------------------------------------------------------------
# 2-8. Evidence verdicts (7 agents)
# ---------------------------------------------------------------------------


def _evidence_verdict_template(
    *,
    ctx: StubContext,
    agent_id: str,
    verdict_summary: str,
    drivers: list[str],
    risk: RiskLevel = RiskLevel.MEDIUM,
) -> dict[str, Any]:
    """Common shape used by all 7 evidence verdict stubs."""
    seed_key = f"evidence.{agent_id}"
    if seed_key in ctx.seed_payload:
        return ctx.seed_payload[seed_key]

    cid = ctx.case.case_id
    return {
        "agent_id": agent_id,
        "risk_level": risk.value,
        "confidence": float(_confidence_from_case(cid, agent_id)) / 100,
        "drivers": {"top_drivers": drivers},
        "flags": {},
        "structured_output": {
            "verdict_summary": verdict_summary,
            "key_findings": [
                {"finding": d, "severity": "medium"} for d in drivers
            ],
        },
        "reasoning_summary": (
            f"Stub {agent_id} verdict; cluster 7 will swap in real LLM call."
        ),
    }


def stub_evidence_equity(ctx: StubContext) -> dict[str, Any]:
    return _evidence_verdict_template(
        ctx=ctx,
        agent_id="e1_equity_evidence",
        verdict_summary=(
            "Equity sleeve broadly supports the proposed action; valuations "
            "above 10y mean for large-cap, neutral for mid-cap."
        ),
        drivers=[
            "valuation_premium_large_cap",
            "earnings_quality_consumer",
            "mid_cap_breadth",
        ],
    )


def stub_evidence_debt(ctx: StubContext) -> dict[str, Any]:
    return _evidence_verdict_template(
        ctx=ctx,
        agent_id="e1_debt_evidence",
        verdict_summary=(
            "Duration risk neutral; credit-quality mix biased to AAA. RBI "
            "repo-cycle posture suggests modest tactical shift."
        ),
        drivers=["duration_neutral", "aaa_dominant", "rbi_pause_priced_in"],
        risk=RiskLevel.LOW,
    )


def stub_evidence_alternatives(ctx: StubContext) -> dict[str, Any]:
    return _evidence_verdict_template(
        ctx=ctx,
        agent_id="e1_alternatives_evidence",
        verdict_summary=(
            "PMS minimum-ticket compliance verified. AIF Cat-II exposure "
            "well within firm prudence cap."
        ),
        drivers=["pms_min_ticket_ok", "aif_cat_ii_below_cap"],
        risk=RiskLevel.LOW,
    )


def stub_evidence_macro(ctx: StubContext) -> dict[str, Any]:
    return _evidence_verdict_template(
        ctx=ctx,
        agent_id="e1_macro_evidence",
        verdict_summary=(
            "Macro backdrop neutral-to-supportive: CPI in target band, INR "
            "stable, FII flows positive QTD."
        ),
        drivers=["cpi_in_band", "inr_stable", "fii_positive_qtd"],
    )


def stub_evidence_sentiment(ctx: StubContext) -> dict[str, Any]:
    return _evidence_verdict_template(
        ctx=ctx,
        agent_id="e1_sentiment_evidence",
        verdict_summary=(
            "Market sentiment mildly positive; news-flow on relevant sectors "
            "balanced."
        ),
        drivers=["news_balanced", "fii_dii_neutral"],
    )


def stub_evidence_behavioural(ctx: StubContext) -> dict[str, Any]:
    return _evidence_verdict_template(
        ctx=ctx,
        agent_id="e1_behavioural_evidence",
        verdict_summary=(
            "No recent panic-selling or performance-chasing patterns. "
            "Mandate amendment cadence is normal."
        ),
        drivers=["no_panic_pattern", "mandate_cadence_normal"],
        risk=RiskLevel.LOW,
    )


def stub_evidence_tax(ctx: StubContext) -> dict[str, Any]:
    return _evidence_verdict_template(
        ctx=ctx,
        agent_id="e1_tax_evidence",
        verdict_summary=(
            "Action is broadly tax-efficient: STCG impact minimal; LTCG "
            "exemption headroom ~₹50K remaining FY."
        ),
        drivers=["stcg_minimal", "ltcg_headroom_50k"],
    )


# ---------------------------------------------------------------------------
# 9-11. Synthesis (3 modes)
# ---------------------------------------------------------------------------


def _synthesis_template(
    *,
    ctx: StubContext,
    output_mode: str,
    narrative: str,
    recommendation: str,
    amplification: bool = False,
) -> dict[str, Any]:
    seed_key = f"synthesis.{output_mode}"
    if seed_key in ctx.seed_payload:
        return ctx.seed_payload[seed_key]

    return {
        "output_mode": output_mode,
        "consensus": {"summary": "Consensus across evidence agents."},
        "agreement_areas": {
            "areas": ["valuation_neutral", "macro_supportive"],
        },
        "conflict_areas": {"areas": []},
        "uncertainty_flag": False,
        "uncertainty_reasons": None,
        "amplification": (
            {"flag": True, "drivers": ["concentration", "valuation_premium"]}
            if amplification
            else None
        ),
        "mode_dominance": "balanced",
        "escalation_recommended": amplification,
        "escalation_reason": (
            "S1 amplification flag: 3+ medium-risk evidence findings combine."
            if amplification
            else None
        ),
        "counterfactual_framing": {
            "frames": ["base_case", "downside_10pct", "upside_5pct"],
        },
        "synthesis_narrative": narrative,
        "recommendation": recommendation,
        "flags": {},
        "reasoning_summary": (
            f"Stub {output_mode} synthesis; cluster 7 will swap for real LLM."
        ),
    }


def stub_synthesis_case_mode(ctx: StubContext) -> dict[str, Any]:
    return _synthesis_template(
        ctx=ctx,
        output_mode="case_mode",
        narrative=(
            "Evidence converges on supportive-with-conditions verdict. "
            "Equity + debt + macro slices align; behavioural + tax checks "
            "clean. No amplification flag."
        ),
        recommendation="proceed_with_conditions",
    )


def stub_synthesis_diagnostic_mode(ctx: StubContext) -> dict[str, Any]:
    return _synthesis_template(
        ctx=ctx,
        output_mode="diagnostic",
        narrative=(
            "Portfolio is in healthy operating range. Concentration within "
            "firm prudence; mandate compliance clean; performance trailing "
            "benchmark by ~80 bps over trailing 12m."
        ),
        recommendation="no_action_required",
    )


def stub_synthesis_briefing_mode(ctx: StubContext) -> dict[str, Any]:
    return _synthesis_template(
        ctx=ctx,
        output_mode="briefing",
        narrative=(
            "Investor portfolio recently outperformed peers by 120 bps. "
            "Recent macro: RBI status quo, INR stable. Suggested talking "
            "points: reaffirm mandate fit, preview FY-end tax planning."
        ),
        recommendation="discuss_with_client",
    )


# ---------------------------------------------------------------------------
# 12. IC1 deliberation (chair aggregates members)
# ---------------------------------------------------------------------------


def stub_ic1_deliberation(ctx: StubContext) -> dict[str, Any]:
    if "ic1_deliberation" in ctx.seed_payload:
        return ctx.seed_payload["ic1_deliberation"]

    return {
        "chair_summary": (
            "Committee supports the action with conditions. Quant member "
            "flags concentration as the primary residual risk; "
            "recommendation proceeds with size cap."
        ),
        "devils_advocate_position": (
            "Counter-argument: timing risk in concentrating equity now "
            "given valuation premium."
        ),
        "risk_assessment": {
            "primary": ["concentration"],
            "residual": "medium",
        },
        "counterfactual_engine_output": {
            "scenarios": ["downside_10pct", "upside_5pct"],
        },
        "minutes": {
            "members_present": ["chair", "quant"],
            "votes": {"chair": "support_with_conditions", "quant": "support_with_conditions"},
            "key_discussion_points": [
                "Concentration vs target",
                "Timing relative to mandate band",
            ],
        },
        "dissent": {"members": []},
        "recommendation": IC1Recommendation.SUPPORT_WITH_CONDITIONS.value,
        "conditions": {
            "items": ["cap_position_size_at_8pct", "review_in_30_days"],
        },
        "reasoning_summary": (
            "Stub IC1 deliberation; cluster 7 swaps for real chair + member "
            "personas + reasoning."
        ),
    }


# ---------------------------------------------------------------------------
# 13-15. Governance gates (G1 / G2 / G3)
# ---------------------------------------------------------------------------


def _governance_template(
    *,
    ctx: StubContext,
    gate: GovernanceGate,
    summary: str,
) -> dict[str, Any]:
    seed_key = f"governance.{gate.value}"
    if seed_key in ctx.seed_payload:
        return ctx.seed_payload[seed_key]

    return {
        "gate": gate.value,
        "outcome": GovernanceOutcome.APPROVED.value,
        "blocking_rule_id": None,
        "blocking_rule_text": None,
        "reasoning": summary,
        "override_requirements": None,
        "conditions_to_attach": None,
        "rule_corpus_version": "v0.1-stub",
    }


def stub_governance_g1_mandate(ctx: StubContext) -> dict[str, Any]:
    return _governance_template(
        ctx=ctx,
        gate=GovernanceGate.G1_MANDATE,
        summary=(
            "Asset-allocation bands respected; single-position cap honoured; "
            "no prohibited instruments touched."
        ),
    )


def stub_governance_g2_sebi(ctx: StubContext) -> dict[str, Any]:
    return _governance_template(
        ctx=ctx,
        gate=GovernanceGate.G2_SEBI_REGULATORY,
        summary=(
            "SEBI single-issuer cap respected; PMS / AIF minimum-ticket "
            "compliant; no FEMA cross-border flag."
        ),
    )


def stub_governance_g3_action_filter(ctx: StubContext) -> dict[str, Any]:
    return _governance_template(
        ctx=ctx,
        gate=GovernanceGate.G3_ACTION_FILTER,
        summary=(
            "Tax-efficient timing (LTCG horizon respected); settlement "
            "window OK (T+1); no demat-tagging issues; STT / exit-load "
            "within tolerable range."
        ),
    )


# ---------------------------------------------------------------------------
# 16. A1 challenge
# ---------------------------------------------------------------------------


def stub_a1_challenge(ctx: StubContext) -> dict[str, Any]:
    if "a1_challenge" in ctx.seed_payload:
        return ctx.seed_payload["a1_challenge"]

    return {
        "counter_arguments": {
            "items": [
                {
                    "argument": "Concentration risk under-weighted",
                    "evidence": "Top-1 position at 6.5% post-action",
                    "severity": "medium",
                },
                {
                    "argument": "Timing premium",
                    "evidence": "Large-cap equity above 10y valuation mean",
                    "severity": "medium",
                },
            ],
        },
        "alternative_proposals": {
            "items": [
                {
                    "description": "Phase the action over 3 tranches",
                    "rationale": "Smooth timing risk while preserving thesis",
                },
            ],
        },
        "stress_test_scenarios": {
            "scenarios": [
                {"name": "downside_10pct", "impact_pct": -3.2},
                {"name": "rate_hike_50bps", "impact_pct": -1.8},
            ],
        },
        "edge_cases": {
            "items": [
                "Mandate-band-edge proximity if equity rallies further",
            ],
        },
        "accountability_flags": {"flags": []},
        "reasoning_summary": (
            "Stub A1 challenge; cluster 7 will swap for adversarial LLM."
        ),
    }


# ---------------------------------------------------------------------------
# Briefing + health (driven by stitcher in pipeline, included here for
# completeness of the ProducedVia tagging)
# ---------------------------------------------------------------------------


def stub_briefing_note(ctx: StubContext) -> dict[str, Any]:
    if "briefing_note" in ctx.seed_payload:
        return ctx.seed_payload["briefing_note"]

    return {
        "meeting_context": "Quarterly review with the client.",
        "recent_activity_summary": (
            "Two transactions this quarter; portfolio drift within mandate."
        ),
        "current_state_summary": (
            "Total value tracking firm benchmark; equity tilt 60/30/10."
        ),
        "market_context": "Macro neutral; RBI on hold; FII positive QTD.",
        "prep_questions": {
            "questions": [
                "Any change in time horizon or risk appetite?",
                "Liquidity needs over the next 12 months?",
                "Tax planning priorities for FY-end?",
            ],
        },
    }


def stub_health_report(
    ctx: StubContext, *, materiality: MaterialityResult | None = None,
) -> dict[str, Any]:
    if "health_report" in ctx.seed_payload:
        return ctx.seed_payload["health_report"]

    overall = HealthOverall.HEALTHY.value
    if materiality and materiality.is_material:
        overall = HealthOverall.ATTENTION_NEEDED.value

    return {
        "overall_health": overall,
        "asset_allocation_status": {
            "status": "within_band",
            "drift_pct": 1.8,
        },
        "performance_summary": {
            "trailing_12m_pct": 14.2,
            "vs_benchmark_bps": -80,
        },
        "drift_indicators": {
            "max_drift_pct": 1.8,
            "drifted_classes": [],
        },
        "recommendations": {
            "items": [
                "Continue current allocation",
                "Schedule annual mandate review",
            ],
        },
    }


__all__ = [
    "StubContext",
    "stub_a1_challenge",
    "stub_briefing_note",
    "stub_evidence_alternatives",
    "stub_evidence_behavioural",
    "stub_evidence_debt",
    "stub_evidence_equity",
    "stub_evidence_macro",
    "stub_evidence_sentiment",
    "stub_evidence_tax",
    "stub_governance_g1_mandate",
    "stub_governance_g2_sebi",
    "stub_governance_g3_action_filter",
    "stub_health_report",
    "stub_ic1_deliberation",
    "stub_portfolio_risk_analytics",
    "stub_synthesis_briefing_mode",
    "stub_synthesis_case_mode",
    "stub_synthesis_diagnostic_mode",
]


# Legibility helper — kept at module bottom so pylint doesn't complain.
_ = CaseMode  # re-exported via state_machine
