"""Cluster 2 chunk 2.1 — M1 hard-rule + soft-warning test suite.

Pins FR Entry 12.1 §2.3 hard rules (within-class max>=min, sum-of-mins,
sum-of-maxes) and §3.3 / §4.3 / §5.3 soft-warning thresholds.
"""

from __future__ import annotations

import pytest

from artha.api_v2.m1.validation import (
    LIQUIDITY_FLOOR_DIVERGENCE_THRESHOLD,
    MandateValidationError,
    generate_soft_warnings,
    validate_hard_rules,
)


def _valid_constraints(**overrides):
    """Cluster 3 four-band fixture (moderate-tier defaults).

    Sums: mins = 45+15+5+5 = 70 ≤ 100 ✓; maxes = 65+35+15+15 = 130 ≥ 100 ✓.
    """
    base = {
        "equity_min_pct": 45,
        "equity_max_pct": 65,
        "debt_min_pct": 15,
        "debt_max_pct": 35,
        "cash_min_pct": 5,
        "cash_max_pct": 15,
        "alternatives_min_pct": 5,
        "alternatives_max_pct": 15,
        "single_position_max_pct": 5,
        "liquidity_floor_pct": 20,
        "sector_max_pct": 25,
        "prohibited_instruments": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Hard rules
# ---------------------------------------------------------------------------


class TestHardRules:
    def test_valid_constraints_pass(self):
        validate_hard_rules(_valid_constraints())  # no raise

    def test_equity_max_below_min_raises(self):
        with pytest.raises(MandateValidationError) as exc:
            validate_hard_rules(
                _valid_constraints(equity_min_pct=70, equity_max_pct=50)
            )
        codes = [f["code"] for f in exc.value.failures]
        assert "max_less_than_min" in codes

    def test_debt_max_below_min_raises(self):
        with pytest.raises(MandateValidationError) as exc:
            validate_hard_rules(
                _valid_constraints(debt_min_pct=40, debt_max_pct=20)
            )
        assert "max_less_than_min" in [f["code"] for f in exc.value.failures]

    def test_alternatives_max_below_min_raises(self):
        with pytest.raises(MandateValidationError) as exc:
            validate_hard_rules(
                _valid_constraints(
                    alternatives_min_pct=15, alternatives_max_pct=5
                )
            )
        assert "max_less_than_min" in [f["code"] for f in exc.value.failures]

    def test_sum_of_mins_over_100_raises(self):
        # Four-band: 60 + 30 + 20 + 5 = 115 → exceeds 100.
        with pytest.raises(MandateValidationError) as exc:
            validate_hard_rules(
                _valid_constraints(
                    equity_min_pct=60, equity_max_pct=70,
                    debt_min_pct=30, debt_max_pct=40,
                    cash_min_pct=20, cash_max_pct=30,
                    alternatives_min_pct=5, alternatives_max_pct=15,
                )
            )
        codes = [f["code"] for f in exc.value.failures]
        assert "sum_min_exceeds_100" in codes

    def test_sum_of_maxes_below_100_raises(self):
        # Four-band: 25 + 25 + 25 + 20 = 95 → below 100.
        with pytest.raises(MandateValidationError) as exc:
            validate_hard_rules(
                _valid_constraints(
                    equity_min_pct=10, equity_max_pct=25,
                    debt_min_pct=10, debt_max_pct=25,
                    cash_min_pct=5, cash_max_pct=25,
                    alternatives_min_pct=5, alternatives_max_pct=20,
                )
            )
        codes = [f["code"] for f in exc.value.failures]
        assert "sum_max_below_100" in codes

    def test_cash_band_max_less_than_min_raises(self):
        """Cluster 3 chunk 3.1 — cash band gets the same max>=min check."""
        with pytest.raises(MandateValidationError) as exc:
            validate_hard_rules(
                _valid_constraints(cash_min_pct=15, cash_max_pct=5)
            )
        assert "max_less_than_min" in [f["code"] for f in exc.value.failures]

    def test_multiple_failures_collected_in_one_raise(self):
        with pytest.raises(MandateValidationError) as exc:
            validate_hard_rules(
                _valid_constraints(
                    equity_min_pct=80, equity_max_pct=20,  # max < min
                    debt_min_pct=80, debt_max_pct=80,      # plus sum>100
                    cash_min_pct=5, cash_max_pct=15,
                    alternatives_min_pct=10, alternatives_max_pct=10,
                )
            )
        codes = [f["code"] for f in exc.value.failures]
        assert "max_less_than_min" in codes
        assert "sum_min_exceeds_100" in codes


# ---------------------------------------------------------------------------
# Soft warnings
# ---------------------------------------------------------------------------


class TestSoftWarnings:
    def test_typical_values_produce_no_warnings(self):
        warnings = generate_soft_warnings(
            _valid_constraints(),
            risk_appetite="moderate",
            liquidity_tier="secondary",
        )
        assert warnings == []

    def test_single_position_below_3_warns(self):
        warnings = generate_soft_warnings(
            _valid_constraints(single_position_max_pct=2),
            risk_appetite="moderate",
            liquidity_tier="secondary",
        )
        codes = [w.code for w in warnings]
        assert "single_position_outside_typical" in codes

    def test_single_position_above_10_warns(self):
        warnings = generate_soft_warnings(
            _valid_constraints(single_position_max_pct=15),
            risk_appetite="moderate",
            liquidity_tier="secondary",
        )
        codes = [w.code for w in warnings]
        assert "single_position_outside_typical" in codes

    def test_sector_cap_below_15_warns(self):
        warnings = generate_soft_warnings(
            _valid_constraints(sector_max_pct=10),
            risk_appetite="moderate",
            liquidity_tier="secondary",
        )
        codes = [w.code for w in warnings]
        assert "sector_cap_outside_typical" in codes

    def test_sector_cap_above_40_warns(self):
        warnings = generate_soft_warnings(
            _valid_constraints(sector_max_pct=50),
            risk_appetite="moderate",
            liquidity_tier="secondary",
        )
        codes = [w.code for w in warnings]
        assert "sector_cap_outside_typical" in codes

    def test_liquidity_floor_diverges_from_i0_warns(self):
        # Deep tier suggests 30; setting 5 diverges by 25 > 10 threshold.
        warnings = generate_soft_warnings(
            _valid_constraints(liquidity_floor_pct=5),
            risk_appetite="moderate",
            liquidity_tier="deep",
        )
        codes = [w.code for w in warnings]
        assert "liquidity_floor_diverges_from_i0" in codes

    def test_liquidity_floor_within_threshold_no_warn(self):
        # Secondary suggests 20; setting 25 (5-pt difference) within
        # threshold of 10.
        warnings = generate_soft_warnings(
            _valid_constraints(liquidity_floor_pct=25),
            risk_appetite="moderate",
            liquidity_tier="secondary",
        )
        codes = [w.code for w in warnings]
        assert "liquidity_floor_diverges_from_i0" not in codes

    def test_threshold_constant_is_10(self):
        assert LIQUIDITY_FLOOR_DIVERGENCE_THRESHOLD == 10

    def test_warning_message_includes_actual_and_suggested(self):
        warnings = generate_soft_warnings(
            _valid_constraints(liquidity_floor_pct=5),
            risk_appetite="moderate",
            liquidity_tier="deep",
        )
        msg = next(
            w.message for w in warnings
            if w.code == "liquidity_floor_diverges_from_i0"
        )
        assert "5%" in msg
        assert "30%" in msg
