"""Cluster 2 chunk 2.1 — I0 defaults pure-function test suite.

Pins the FR Entry 12.1 §2.4 + §4.4 mappings: every (risk_appetite,
liquidity_tier) combination produces the documented defaults.
"""

from __future__ import annotations

import pytest

from artha.api_v2.m1.i0_defaults import compute_defaults


class TestAssetAllocationDefaults:
    def test_aggressive_yields_70_90_5_25_5_15(self):
        d = compute_defaults(risk_appetite="aggressive", liquidity_tier="essential")
        assert (d.equity_min_pct, d.equity_max_pct) == (70, 90)
        assert (d.debt_min_pct, d.debt_max_pct) == (5, 25)
        assert (d.alternatives_min_pct, d.alternatives_max_pct) == (5, 15)

    def test_moderate_yields_50_70_20_40_5_15(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert (d.equity_min_pct, d.equity_max_pct) == (50, 70)
        assert (d.debt_min_pct, d.debt_max_pct) == (20, 40)
        assert (d.alternatives_min_pct, d.alternatives_max_pct) == (5, 15)

    def test_conservative_yields_30_50_40_60_5_15(self):
        d = compute_defaults(risk_appetite="conservative", liquidity_tier="deep")
        assert (d.equity_min_pct, d.equity_max_pct) == (30, 50)
        assert (d.debt_min_pct, d.debt_max_pct) == (40, 60)
        assert (d.alternatives_min_pct, d.alternatives_max_pct) == (5, 15)

    def test_unknown_risk_appetite_falls_back_to_moderate(self):
        d = compute_defaults(risk_appetite="balanced", liquidity_tier="secondary")
        assert (d.equity_min_pct, d.equity_max_pct) == (50, 70)


class TestLiquidityFloorDefaults:
    @pytest.mark.parametrize(
        "tier,expected",
        [("essential", 10), ("secondary", 20), ("deep", 30)],
    )
    def test_tier_to_floor(self, tier, expected):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier=tier)
        assert d.liquidity_floor_pct == expected

    def test_unknown_tier_falls_back_to_secondary(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="unknown")
        assert d.liquidity_floor_pct == 20

    def test_none_inputs_fall_back_to_moderate_secondary(self):
        d = compute_defaults(risk_appetite=None, liquidity_tier=None)
        assert (d.equity_min_pct, d.equity_max_pct) == (50, 70)
        assert d.liquidity_floor_pct == 20


class TestIndustryStandardDefaults:
    def test_single_position_default_5(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.single_position_max_pct == 5

    def test_sector_cap_default_25(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.sector_max_pct == 25

    def test_prohibited_default_empty(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.prohibited_instruments == ()


class TestSourceLabels:
    def test_asset_allocation_sourced_from_risk_appetite(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        for key in (
            "equity_min_pct", "equity_max_pct", "debt_min_pct", "debt_max_pct",
            "alternatives_min_pct", "alternatives_max_pct",
        ):
            assert d.sources[key] == "i0_risk_appetite"

    def test_liquidity_sourced_from_tier(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.sources["liquidity_floor_pct"] == "i0_liquidity_tier"

    def test_single_position_and_sector_sourced_from_industry_standard(self):
        d = compute_defaults(risk_appetite="moderate", liquidity_tier="secondary")
        assert d.sources["single_position_max_pct"] == "industry_standard"
        assert d.sources["sector_max_pct"] == "industry_standard"
