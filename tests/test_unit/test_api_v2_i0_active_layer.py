"""I0 active layer test suite — chunk 1.1.

Verifies the rule-based heuristics in :mod:`artha.api_v2.i0.active_layer`
against the standard cases and edge cases from FR Entry 11.1 §9.
"""

from __future__ import annotations

import pytest

from artha.api_v2.i0.active_layer import (
    ENRICHMENT_VERSION,
    LIFE_STAGE_LABELS,
    LIQUIDITY_TIER_LABELS,
    enrich_investor,
)

# ---------------------------------------------------------------------------
# 1. Standard cases — FR 11.1 §9 acceptance test 1
# ---------------------------------------------------------------------------


class TestStandardCases:
    def test_30_moderate_over_5_years_is_accumulation_essential(self):
        result = enrich_investor(age=30, risk_appetite="moderate", time_horizon="over_5_years")
        assert result.life_stage == "accumulation"
        assert result.life_stage_confidence == "high"
        assert result.liquidity_tier == "essential"
        assert result.liquidity_tier_range == "5-15%"

    def test_50_moderate_3_to_5_years_is_transition_secondary(self):
        result = enrich_investor(age=50, risk_appetite="moderate", time_horizon="3_to_5_years")
        assert result.life_stage == "transition"
        assert result.life_stage_confidence == "high"
        assert result.liquidity_tier == "secondary"
        assert result.liquidity_tier_range == "15-30%"

    def test_60_conservative_under_3_years_is_distribution_deep(self):
        result = enrich_investor(age=60, risk_appetite="conservative", time_horizon="under_3_years")
        assert result.life_stage == "distribution"
        assert result.life_stage_confidence == "high"
        assert result.liquidity_tier == "deep"
        assert result.liquidity_tier_range == "30%+"

    @pytest.mark.parametrize("risk", ["aggressive", "moderate", "conservative"])
    @pytest.mark.parametrize(
        "horizon", ["under_3_years", "3_to_5_years", "over_5_years"]
    )
    def test_75_year_old_any_profile_is_legacy(self, risk, horizon):
        result = enrich_investor(age=75, risk_appetite=risk, time_horizon=horizon)
        assert result.life_stage == "legacy"


# ---------------------------------------------------------------------------
# 2. Edge cases — FR 11.1 §9 acceptance test 2
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_28_conservative_under_3_years_is_transition_low_confidence(self):
        result = enrich_investor(age=28, risk_appetite="conservative", time_horizon="under_3_years")
        assert result.life_stage == "transition"
        assert result.life_stage_confidence == "low"

    def test_72_aggressive_over_5_years_is_legacy_low_confidence(self):
        result = enrich_investor(age=72, risk_appetite="aggressive", time_horizon="over_5_years")
        assert result.life_stage == "legacy"
        assert result.life_stage_confidence == "low"


# ---------------------------------------------------------------------------
# 3. Borderline ages — FR 11.1 §2.2
# ---------------------------------------------------------------------------


class TestBorderlineAges:
    def test_age_45_is_transition_lower_bound(self):
        result = enrich_investor(age=45, risk_appetite="moderate", time_horizon="3_to_5_years")
        # Per FR §2.2: "age 45 maps to transition" when distribution-rule
        # range starts at 55.
        assert result.life_stage == "transition"

    def test_age_55_is_distribution_lower_bound_with_short_horizon(self):
        result = enrich_investor(age=55, risk_appetite="moderate", time_horizon="under_3_years")
        assert result.life_stage == "distribution"

    def test_age_70_is_distribution_upper_bound(self):
        result = enrich_investor(age=70, risk_appetite="moderate", time_horizon="3_to_5_years")
        # Per FR §2.2: "age 70 maps to distribution if horizons match".
        # Legacy is strictly > 70.
        assert result.life_stage == "distribution"

    def test_age_71_is_legacy(self):
        result = enrich_investor(age=71, risk_appetite="moderate", time_horizon="3_to_5_years")
        assert result.life_stage == "legacy"


# ---------------------------------------------------------------------------
# 4. Liquidity tier rules — FR 11.1 §3.1 (all combos covered)
# ---------------------------------------------------------------------------


class TestLiquidityTierRules:
    @pytest.mark.parametrize("risk", ["aggressive", "moderate", "conservative"])
    def test_under_3_years_is_always_deep(self, risk):
        result = enrich_investor(age=40, risk_appetite=risk, time_horizon="under_3_years")
        assert result.liquidity_tier == "deep"
        assert result.liquidity_tier_range == "30%+"

    @pytest.mark.parametrize("risk", ["aggressive", "moderate", "conservative"])
    def test_3_to_5_years_is_always_secondary(self, risk):
        result = enrich_investor(age=40, risk_appetite=risk, time_horizon="3_to_5_years")
        assert result.liquidity_tier == "secondary"
        assert result.liquidity_tier_range == "15-30%"

    def test_over_5_years_aggressive_is_essential(self):
        result = enrich_investor(age=30, risk_appetite="aggressive", time_horizon="over_5_years")
        assert result.liquidity_tier == "essential"
        assert result.liquidity_tier_range == "5-15%"

    def test_over_5_years_moderate_is_essential(self):
        result = enrich_investor(age=30, risk_appetite="moderate", time_horizon="over_5_years")
        assert result.liquidity_tier == "essential"

    def test_over_5_years_conservative_is_secondary(self):
        # Per FR §3.1: long horizon with conservative risk → secondary,
        # not essential. Conservative profile bumps liquidity up one tier.
        result = enrich_investor(age=30, risk_appetite="conservative", time_horizon="over_5_years")
        assert result.liquidity_tier == "secondary"


# ---------------------------------------------------------------------------
# 5. Determinism + idempotency — FR 11.1 §9 acceptance tests 7 + 8
# ---------------------------------------------------------------------------


class TestOperationalProperties:
    def test_deterministic_same_inputs_produce_same_outputs(self):
        a = enrich_investor(age=30, risk_appetite="moderate", time_horizon="over_5_years")
        b = enrich_investor(age=30, risk_appetite="moderate", time_horizon="over_5_years")
        assert a == b

    def test_enrichment_version_is_v1_0(self):
        result = enrich_investor(age=30, risk_appetite="moderate", time_horizon="over_5_years")
        assert result.enrichment_version == "i0_active_layer_v1.0"
        assert ENRICHMENT_VERSION == "i0_active_layer_v1.0"

    def test_display_labels_present_for_all_life_stages(self):
        for stage in ("accumulation", "transition", "distribution", "legacy"):
            assert LIFE_STAGE_LABELS[stage]

    def test_display_labels_present_for_all_liquidity_tiers(self):
        for tier in ("essential", "secondary", "deep"):
            assert LIQUIDITY_TIER_LABELS[tier]
