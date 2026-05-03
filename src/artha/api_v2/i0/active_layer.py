"""I0 Active Layer — rule-based investor enrichment.

Per FR Entry 11.1 §2 (life stage rules) and §3 (liquidity tier rules).

Pure Python, deterministic, sub-millisecond. No external calls, no LLM.
Same inputs always produce same outputs — replayable, auditable.

Implementation note on rule precedence: FR 11.1 §2.1 lists the rules with
some internal ambiguity around the "older conservative + short horizon"
cross-rule for legacy (would conflict with the distribution rule for
ages 55-70). We resolve by treating the FR §9 acceptance criteria as the
test contract: 60-year-old conservative under_3_years → distribution
(high), not legacy. The legacy cross-rule fires only for age > 70 cases
that need confidence dampening (e.g., aggressive + long horizon at 72+).

Documented for the cluster 1 chunk 1.1 retrospective.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Per FR 11.1 §5.3 — bumped when heuristics evolve. Records enriched at
# older versions retain their classifications; re-enrichment writes the
# new version.
ENRICHMENT_VERSION = "i0_active_layer_v1.0"


LifeStage = Literal["accumulation", "transition", "distribution", "legacy"]
Confidence = Literal["high", "medium", "low"]
LiquidityTier = Literal["essential", "secondary", "deep"]
RiskAppetite = Literal["aggressive", "moderate", "conservative"]
TimeHorizon = Literal["under_3_years", "3_to_5_years", "over_5_years"]


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    """Output of :func:`enrich_investor`. Per FR 11.1 §5.2."""

    life_stage: LifeStage
    life_stage_confidence: Confidence
    liquidity_tier: LiquidityTier
    liquidity_tier_range: str  # "5-15%" | "15-30%" | "30%+"
    enrichment_version: str = ENRICHMENT_VERSION


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def enrich_investor(
    *,
    age: int,
    risk_appetite: RiskAppetite,
    time_horizon: TimeHorizon,
) -> EnrichmentResult:
    """Enrich an investor's classification from their advisor-entered fields.

    Pure function over (age, risk_appetite, time_horizon). The investor's
    other fields (name, email, etc.) are not inputs to the active layer
    per FR 11.1 §4.1.
    """
    life_stage, confidence = _classify_life_stage(age, risk_appetite, time_horizon)
    liquidity_tier, tier_range = _classify_liquidity_tier(time_horizon, risk_appetite)
    return EnrichmentResult(
        life_stage=life_stage,
        life_stage_confidence=confidence,
        liquidity_tier=liquidity_tier,
        liquidity_tier_range=tier_range,
    )


# ---------------------------------------------------------------------------
# Life stage rules — FR 11.1 §2.1
# ---------------------------------------------------------------------------


def _classify_life_stage(
    age: int, risk_appetite: RiskAppetite, time_horizon: TimeHorizon
) -> tuple[LifeStage, Confidence]:
    """Apply life-stage rules in priority order.

    Order matters — earlier rules win to match the FR §9 acceptance test
    cases (60-year-old conservative under_3_years → distribution, not
    the legacy cross-rule).
    """
    # Rule 1: legacy — age > 70 (FR 11.1 §2.1 strictly greater than 70).
    # Confidence is dampened when profile signals are inconsistent with
    # typical legacy-stage behaviour (FR §9 acceptance test 2).
    if age > 70:
        if risk_appetite == "aggressive" and time_horizon == "over_5_years":
            # 72-year-old aggressive over_5_years per FR §9 → legacy, low.
            return "legacy", "low"
        return "legacy", "high"

    # Rule 2: distribution — age 55-70 inclusive + short/medium horizon.
    # Per FR §2.2 borderline rule: age 70 maps here when horizons match.
    if 55 <= age <= 70 and time_horizon in ("under_3_years", "3_to_5_years"):
        return "distribution", "high"

    # Rule 3: transition (primary) — age 45-54.
    # Per FR §2.2: age 45 maps to transition (lower-bound inclusive).
    if 45 <= age <= 54:
        return "transition", "high"

    # Rule 4: accumulation — age 25-44 + medium/long horizon (the
    # standard wealth-building profile). FR §9 acceptance test 1.
    if 25 <= age <= 44 and time_horizon in ("over_5_years", "3_to_5_years"):
        return "accumulation", "high"

    # Rule 5: transition (cross-rule) — age 25-44 + short horizon.
    # Unusual profile; confidence reflects how unusual it is. The
    # 28-year-old conservative under_3_years from FR §9 maps here at low
    # confidence; an aggressive/moderate variant gets medium.
    if 25 <= age <= 44 and time_horizon == "under_3_years":
        if risk_appetite == "conservative":
            return "transition", "low"
        return "transition", "medium"

    # Fallback — shouldn't fire for valid inputs (age 18-100 +
    # constrained enums) but FR §6.1 says missing/edge inputs return
    # low-confidence rather than failing.
    if age < 25:
        # Very young investors — accumulation is the right life-stage but
        # with low confidence because the heuristic boundary doesn't
        # claim to fit them.
        return "accumulation", "low"
    # Other unmatched cases (shouldn't be reachable) → most-restrictive
    # tier per FR §2.2 with low confidence.
    return "transition", "low"


# ---------------------------------------------------------------------------
# Liquidity tier rules — FR 11.1 §3.1
# ---------------------------------------------------------------------------


def _classify_liquidity_tier(
    time_horizon: TimeHorizon, risk_appetite: RiskAppetite
) -> tuple[LiquidityTier, str]:
    """Apply liquidity-tier rules. The three rules collectively cover all
    valid (time_horizon, risk_appetite) combinations per FR 11.1 §3.2."""
    # Rule: deep — short horizon dominates.
    if time_horizon == "under_3_years":
        return "deep", "30%+"

    # Rule: secondary — medium horizon, OR long horizon with conservative risk.
    if time_horizon == "3_to_5_years":
        return "secondary", "15-30%"
    if time_horizon == "over_5_years" and risk_appetite == "conservative":
        return "secondary", "15-30%"

    # Rule: essential — long horizon + non-conservative risk.
    return "essential", "5-15%"


# ---------------------------------------------------------------------------
# Display semantics — FR 11.1 §2.3 and §3.3
# ---------------------------------------------------------------------------

LIFE_STAGE_LABELS: dict[LifeStage, str] = {
    "accumulation": "Wealth Building",
    "transition": "Wealth Transition",
    "distribution": "Income Generation",
    "legacy": "Estate Planning",
}

LIQUIDITY_TIER_LABELS: dict[LiquidityTier, str] = {
    "essential": "Minimum Liquidity",
    "secondary": "Moderate Liquidity",
    "deep": "High Liquidity",
}
