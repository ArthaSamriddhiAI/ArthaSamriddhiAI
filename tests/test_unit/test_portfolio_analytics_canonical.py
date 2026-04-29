"""Pass 5 — M0.PortfolioAnalytics tests against Section 8.9.9 acceptance.

  * Determinism (Test 1)
  * Formula correctness for HHI, top-N, fee aggregation, tax split, deployment (Test 2)
  * Look-through aggregation: 20% MF × 5% HDFC + 3% direct = 4% (Test 3)
  * Liquidity bucket assignment for mixed lock-ins (Test 5)
  * `tax_basis_stale_days` flag propagation (Test 6)
  * Cache behaviour (Test 7) — same context cache hit, new context cache miss
  * Edge cases: single-holding, zero-AUM, negative-cost-basis (Test 8)

Test 4 (net-of-tax return) and the look-through depth flag depend on input
substrate (cash flow history + fundamental data) that Pass 6+ wires; we test
the schema and structure here and the end-to-end formula in a later pass.
"""

from __future__ import annotations

from datetime import date

import pytest

from artha.canonical.holding import Holding, LookThroughEntry
from artha.canonical.l4_manifest import FeeSchedule
from artha.canonical.portfolio_analytics import (
    AnalyticsQueryInput,
    LiquidityBucket,
    MetricCategory,
)
from artha.common.types import AssetClass, VehicleType
from artha.portfolio_analysis.canonical_metrics import (
    HoldingCommitment,
    PortfolioAnalyticsContext,
    compute_concentration,
    compute_deployment,
    compute_fees,
    compute_liquidity,
    compute_tax,
    compute_vintage,
    compute_xirr,
)
from artha.portfolio_analysis.canonical_service import PortfolioAnalyticsService

_AS_OF = date(2026, 4, 25)


# ===========================================================================
# Helpers
# ===========================================================================


def _holding(
    instrument_id: str,
    market_value: float,
    *,
    cost_basis: float | None = None,
    asset_class: AssetClass = AssetClass.EQUITY,
    vehicle: VehicleType = VehicleType.MUTUAL_FUND,
    sub_asset_class: str = "multi_cap",
    amc: str = "Test AMC",
    acquisition_date: date = date(2024, 1, 15),
    lock_in_expiry: date | None = None,
    units: float = 1000.0,
    tax_basis_stale: bool = False,
) -> Holding:
    """Quick holding builder for tests."""
    cb = cost_basis if cost_basis is not None else market_value * 0.9
    return Holding(
        instrument_id=instrument_id,
        instrument_name=f"{instrument_id}_name",
        units=units,
        cost_basis=cb,
        market_value=market_value,
        unrealised_gain_loss=market_value - cb,
        amc_or_issuer=amc,
        vehicle_type=vehicle,
        asset_class=asset_class,
        sub_asset_class=sub_asset_class,
        acquisition_date=acquisition_date,
        as_of_date=_AS_OF,
        lock_in_expiry=lock_in_expiry,
        tax_basis_stale=tax_basis_stale,
    )


# ===========================================================================
# Section 8.9.9 Test 1 — Determinism
# ===========================================================================


class TestDeterminism:
    def test_identical_contexts_produce_identical_outputs(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c1",
            as_of_date=_AS_OF,
            holdings=[
                _holding("H1", 5_000_000.0),
                _holding("H2", 3_000_000.0, amc="Other AMC"),
                _holding("H3", 2_000_000.0),
            ],
        )
        c1 = compute_concentration(ctx)
        c2 = compute_concentration(ctx)
        assert c1 == c2
        d1 = compute_deployment(ctx)
        d2 = compute_deployment(ctx)
        assert d1 == d2


# ===========================================================================
# Section 8.9.9 Test 2 — Formula correctness
# ===========================================================================


class TestHhiFormula:
    def test_single_holding_hhi_one(self):
        # HHI of a single 100% holding is 1.0
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("ONLY", 1_000_000.0)]
        )
        c = compute_concentration(ctx)
        assert c.hhi_holding_level == pytest.approx(1.0)

    def test_three_equal_holdings_hhi_one_third(self):
        # HHI of three equal holdings = 3 × (1/3)^2 = 1/3
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 1_000_000.0),
                _holding("B", 1_000_000.0, amc="AMC2"),
                _holding("C", 1_000_000.0, amc="AMC3"),
            ],
        )
        c = compute_concentration(ctx)
        assert c.hhi_holding_level == pytest.approx(1.0 / 3.0, abs=1e-9)

    def test_known_two_position_hhi(self):
        # 60/40 split: HHI = 0.6^2 + 0.4^2 = 0.36 + 0.16 = 0.52
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 600_000.0),
                _holding("B", 400_000.0, amc="AMC2"),
            ],
        )
        c = compute_concentration(ctx)
        assert c.hhi_holding_level == pytest.approx(0.52, abs=1e-9)

    def test_top_n_concentration(self):
        # Weights: 0.5, 0.3, 0.2 (descending). top_1=0.5, top_3=1.0
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 5_000_000.0),
                _holding("B", 3_000_000.0, amc="AMC2"),
                _holding("C", 2_000_000.0, amc="AMC3"),
            ],
        )
        c = compute_concentration(ctx)
        top_by_n = {t.n: t.weight for t in c.top_n_holding_level}
        assert top_by_n[1] == pytest.approx(0.5)
        assert top_by_n[5] == pytest.approx(1.0)  # only 3 holdings, all top-5

    def test_manager_hhi_aggregates_by_amc(self):
        # Two holdings under same AMC at 0.4 + 0.4 = 0.8, plus one under different AMC at 0.2
        # Manager-level HHI = 0.8^2 + 0.2^2 = 0.64 + 0.04 = 0.68
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 4_000_000.0, amc="HDFC AMC"),
                _holding("B", 4_000_000.0, amc="HDFC AMC"),
                _holding("C", 2_000_000.0, amc="Kotak AMC"),
            ],
        )
        c = compute_concentration(ctx)
        assert c.hhi_manager_level == pytest.approx(0.68, abs=1e-9)


class TestSectorHhi:
    def test_sector_hhi_when_provided(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 5_000_000.0),
                _holding("B", 5_000_000.0, amc="AMC2"),
            ],
            instrument_sectors={"A": "Banking", "B": "Banking"},
        )
        c = compute_concentration(ctx)
        # All in Banking: sector HHI = 1.0
        assert c.hhi_sector_level == pytest.approx(1.0)

    def test_sector_hhi_none_when_unavailable(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[_holding("A", 5_000_000.0)],
        )
        c = compute_concentration(ctx)
        assert c.hhi_sector_level is None


class TestDeploymentFormulas:
    def test_total_aum_sums_market_values(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 1_000_000.0),
                _holding("B", 2_000_000.0),
                _holding("C", 3_000_000.0),
            ],
        )
        d = compute_deployment(ctx)
        assert d.total_aum_inr == 6_000_000.0

    def test_cash_buffer_split(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("CASH", 1_000_000.0, vehicle=VehicleType.CASH),
            ],
            cash_buffer_threshold_inr=400_000.0,
        )
        d = compute_deployment(ctx)
        assert d.cash_buffer_inr == 400_000.0
        assert d.undeployed_investable_assets_inr == 600_000.0

    def test_commitment_deployment_ratio(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[_holding("AIF1", 5_000_000.0, vehicle=VehicleType.AIF_CAT_2)],
            holding_commitments={
                "AIF1": HoldingCommitment(committed_inr=10_000_000.0, called_inr=6_000_000.0),
            },
        )
        d = compute_deployment(ctx)
        assert d.committed_capital_inr == 10_000_000.0
        assert d.called_capital_inr == 6_000_000.0
        assert d.uncalled_capital_inr == 4_000_000.0
        assert d.deployment_ratio == pytest.approx(0.6)


# ===========================================================================
# Section 8.9.9 Test 3 — Look-through aggregation
# ===========================================================================


class TestLookThroughAggregation:
    def test_section_8_9_9_test_3_combined_lookthrough(self):
        # Spec scenario: 20% in a multi-cap MF that holds 5% HDFC Bank →
        # 1% look-through HDFC contribution. Plus a direct 3% HDFC holding →
        # combined look-through HDFC = 4%.
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("MF_001", 2_000_000.0),  # 20% of 10M portfolio
                _holding("HDFC_BANK", 300_000.0, vehicle=VehicleType.DIRECT_EQUITY),  # 3%
                _holding("FILLER", 7_700_000.0, vehicle=VehicleType.MUTUAL_FUND, amc="X"),  # 77%
            ],
            look_through={
                "MF_001": [
                    LookThroughEntry(
                        underlying_holding_id="HDFC_BANK",
                        underlying_name="HDFC Bank Ltd",
                        weight_in_portfolio=0.01,  # 20% × 5%
                        weight_in_parent=0.05,
                    ),
                ],
                # FILLER has no look-through; will contribute itself
            },
        )
        c = compute_concentration(ctx)
        # HHI must include HDFC at 0.04, FILLER at 0.77
        # Underlying weights: HDFC=0.04 (0.01 lookthrough + 0.03 direct),
        # FILLER=0.77 (no lookthrough → contributes itself)
        # HHI = 0.04^2 + 0.77^2 = 0.0016 + 0.5929 = 0.5945
        assert c.hhi_lookthrough_stock_level == pytest.approx(0.0016 + 0.5929, abs=1e-9)

    def test_lookthrough_falls_back_to_direct_when_no_entries(self):
        # When no look-through is provided anywhere, look-through HHI = direct HHI
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 5_000_000.0, vehicle=VehicleType.DIRECT_EQUITY),
                _holding("B", 5_000_000.0, vehicle=VehicleType.DIRECT_EQUITY, amc="X"),
            ],
        )
        c = compute_concentration(ctx)
        assert c.hhi_lookthrough_stock_level == pytest.approx(c.hhi_holding_level)

    def test_lookthrough_unavailable_pct_propagates(self):
        # Holding flagged as look_through_unavailable but no entries → unavailable pct fires
        h = _holding("OPAQUE_MF", 5_000_000.0, vehicle=VehicleType.MUTUAL_FUND)
        h_with_flag = h.model_copy(update={"look_through_unavailable": True})
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                h_with_flag,
                _holding("CLEAR", 5_000_000.0, vehicle=VehicleType.DIRECT_EQUITY, amc="X"),
            ],
        )
        c = compute_concentration(ctx)
        # The OPAQUE_MF is 50% of the portfolio and flagged unavailable
        assert c.flags.look_through_unavailable_pct == pytest.approx(0.5)


# ===========================================================================
# Section 8.9.9 Test 5 — Liquidity bucket assignment
# ===========================================================================


class TestLiquidityBuckets:
    def test_section_8_9_9_test_5_mixed_lockins(self):
        # Mixed lock-ins: open-ended MF, 90-day NCD, AIF Cat II in commitment, FD 18m
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                # Open-ended MF: lock_in_expiry=None → 0_7 days bucket
                _holding("MF1", 2_000_000.0, vehicle=VehicleType.MUTUAL_FUND, lock_in_expiry=None),
                # 60-day NCD: 30_90 days bucket
                _holding(
                    "NCD1",
                    1_000_000.0,
                    vehicle=VehicleType.DEBT_DIRECT,
                    lock_in_expiry=date(2026, 6, 24),
                ),  # 60 days from 2026-04-25
                # AIF Cat II in commitment period: 5y lock-in → 3_7 years bucket
                _holding(
                    "AIF1",
                    5_000_000.0,
                    vehicle=VehicleType.AIF_CAT_2,
                    lock_in_expiry=date(2031, 4, 25),
                ),
                # FD maturing in 18 months: 1_3 years bucket
                _holding(
                    "FD1",
                    2_000_000.0,
                    vehicle=VehicleType.FD,
                    lock_in_expiry=date(2027, 10, 25),
                ),
            ],
        )
        liq = compute_liquidity(ctx)
        # MF1 is 20%, NCD1 is 10%, AIF1 is 50%, FD1 is 20%
        assert liq.liquidity_buckets[LiquidityBucket.DAYS_0_7] == pytest.approx(0.2)
        assert liq.liquidity_buckets[LiquidityBucket.DAYS_30_90] == pytest.approx(0.1)
        assert liq.liquidity_buckets[LiquidityBucket.YEARS_1_3] == pytest.approx(0.2)
        assert liq.liquidity_buckets[LiquidityBucket.YEARS_3_7] == pytest.approx(0.5)

    def test_liquidity_floor_compliance_pass(self):
        # 20% liquid (open-ended) > 10% mandate floor
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("MF1", 200_000.0),  # 20%
                _holding(
                    "FD1",
                    800_000.0,
                    vehicle=VehicleType.FD,
                    lock_in_expiry=date(2027, 10, 25),
                ),
            ],
            liquidity_floor=0.10,
        )
        liq = compute_liquidity(ctx)
        assert liq.liquidity_floor_compliance is True

    def test_liquidity_floor_compliance_fail(self):
        # 5% liquid < 10% floor
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("MF1", 50_000.0),  # 5%
                _holding(
                    "FD1",
                    950_000.0,
                    vehicle=VehicleType.FD,
                    lock_in_expiry=date(2027, 10, 25),
                ),
            ],
            liquidity_floor=0.10,
        )
        liq = compute_liquidity(ctx)
        assert liq.liquidity_floor_compliance is False


# ===========================================================================
# Section 8.9.9 Test 6 — Tax basis stale flag
# ===========================================================================


class TestTaxBasisStaleFlag:
    def test_section_8_9_9_test_6_stale_basis_flag(self):
        # tax_basis_as_of older than as_of_date by 35 days → flag set
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[_holding("A", 1_000_000.0)],
            tax_basis_as_of=date(2026, 3, 21),  # 35 days before as_of
        )
        t = compute_tax(ctx)
        assert t.flags.tax_basis_stale_days == 35

    def test_basis_fresh_no_flag(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[_holding("A", 1_000_000.0)],
            tax_basis_as_of=_AS_OF,
        )
        t = compute_tax(ctx)
        assert t.flags.tax_basis_stale_days is None

    def test_holding_level_stale_flag_propagates(self):
        h = _holding("A", 1_000_000.0, tax_basis_stale=True)
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[h]
        )
        t = compute_tax(ctx)
        assert "holding_level_tax_basis_stale" in t.flags.other_flags

    def test_holding_period_split(self):
        # Holding A acquired 400 days ago = long-term; B acquired 100 days ago = short-term
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding(
                    "A_LONG",
                    1_500_000.0,
                    cost_basis=1_000_000.0,
                    acquisition_date=date(2025, 3, 21),  # ~400 days before as_of
                ),
                _holding(
                    "B_SHORT",
                    1_200_000.0,
                    cost_basis=1_000_000.0,
                    acquisition_date=date(2026, 1, 15),  # ~100 days before as_of
                ),
            ],
        )
        t = compute_tax(ctx)
        # Long-term gain: 500K, Short-term gain: 200K
        assert t.unrealised_long_term_inr == pytest.approx(500_000.0)
        assert t.unrealised_short_term_inr == pytest.approx(200_000.0)
        assert t.unrealised_gain_loss_total_inr == pytest.approx(700_000.0)

    def test_harvestable_losses(self):
        # Holding A: long-term loss of 200K. Holding B: short-term loss of 100K.
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding(
                    "A_LONG_LOSS",
                    800_000.0,
                    cost_basis=1_000_000.0,
                    acquisition_date=date(2025, 3, 21),
                ),
                _holding(
                    "B_SHORT_LOSS",
                    900_000.0,
                    cost_basis=1_000_000.0,
                    acquisition_date=date(2026, 1, 15),
                ),
            ],
        )
        t = compute_tax(ctx)
        assert t.harvestable_long_term_loss_inr == pytest.approx(200_000.0)
        assert t.harvestable_short_term_loss_inr == pytest.approx(100_000.0)


# ===========================================================================
# Fee aggregation
# ===========================================================================


class TestFeeAggregation:
    def test_aggregate_fee_bps_weighted_average(self):
        # Two holdings, equal weight, fees 100 + 50 bps → weighted avg = 75
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 5_000_000.0),
                _holding("B", 5_000_000.0, amc="X"),
            ],
            fee_schedules={
                "A": FeeSchedule(management_fee_bps=100),
                "B": FeeSchedule(management_fee_bps=50),
            },
        )
        f = compute_fees(ctx)
        assert f.aggregate_fee_bps == 75
        assert f.flags.fee_data_incomplete is False

    def test_fee_data_incomplete_flag(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding("A", 5_000_000.0),
                _holding("B", 5_000_000.0, amc="X"),
            ],
            fee_schedules={"A": FeeSchedule(management_fee_bps=100)},  # B missing
        )
        f = compute_fees(ctx)
        assert f.flags.fee_data_incomplete is True

    def test_fee_breakdown_includes_performance_and_structure(self):
        # 100 mgmt + 200 perf + 50 struct = 350 bps total
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[_holding("A", 1_000_000.0)],
            fee_schedules={
                "A": FeeSchedule(
                    management_fee_bps=100, performance_fee_bps=200, structure_costs_bps=50
                ),
            },
        )
        f = compute_fees(ctx)
        assert f.aggregate_fee_bps == 350


# ===========================================================================
# Vintage
# ===========================================================================


class TestVintage:
    def test_aif_vintage_entries(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding(
                    "AIF_2024",
                    5_000_000.0,
                    vehicle=VehicleType.AIF_CAT_2,
                    acquisition_date=date(2024, 6, 15),
                ),
                _holding(
                    "AIF_2025",
                    3_000_000.0,
                    vehicle=VehicleType.AIF_CAT_3,
                    acquisition_date=date(2025, 1, 10),
                    amc="X",
                ),
                _holding("MF", 2_000_000.0),  # Not AIF
            ],
            holding_vintage_year={"AIF_2024": 2024, "AIF_2025": 2025},
        )
        v = compute_vintage(ctx)
        # Only AIFs are in the vintage list
        assert {e.holding_id for e in v.aif_vintages} == {"AIF_2024", "AIF_2025"}
        # Distribution sums to 1.0 across vintage years
        assert sum(v.vintage_distribution.values()) == pytest.approx(1.0)

    def test_pms_inception_dates(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[
                _holding(
                    "PMS_A",
                    5_000_000.0,
                    vehicle=VehicleType.PMS,
                    acquisition_date=date(2023, 5, 1),
                ),
            ],
        )
        v = compute_vintage(ctx)
        assert v.pms_inception_dates == {"PMS_A": date(2023, 5, 1)}


# ===========================================================================
# XIRR formula
# ===========================================================================


class TestXirr:
    def test_simple_two_flow_xirr(self):
        # Invest 1000 on day 0, get back 1100 one year later → ~10% IRR
        flows = [(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1100.0)]
        rate = compute_xirr(flows)
        assert rate is not None
        assert rate == pytest.approx(0.10, abs=1e-3)

    def test_zero_return_xirr(self):
        flows = [(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1000.0)]
        rate = compute_xirr(flows)
        assert rate is not None
        assert rate == pytest.approx(0.0, abs=1e-3)

    def test_xirr_returns_none_with_no_signs(self):
        # All positive (no purchases) → no rate
        flows = [(date(2025, 1, 1), 1000.0), (date(2026, 1, 1), 1100.0)]
        assert compute_xirr(flows) is None

    def test_xirr_returns_none_single_flow(self):
        flows = [(date(2025, 1, 1), 1000.0)]
        assert compute_xirr(flows) is None


# ===========================================================================
# Section 8.9.9 Test 7 — Cache behaviour
# ===========================================================================


class TestCacheBehaviour:
    def test_first_query_is_cache_miss(self):
        svc = PortfolioAnalyticsService()
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 1_000_000.0)]
        )
        q = AnalyticsQueryInput(
            client_id="c",
            as_of_date=_AS_OF,
            metric_categories=[MetricCategory.CONCENTRATION, MetricCategory.DEPLOYMENT],
        )
        result = svc.query(q, ctx)
        assert result.cache_hit is False

    def test_second_query_same_context_is_cache_hit(self):
        svc = PortfolioAnalyticsService()
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 1_000_000.0)]
        )
        q = AnalyticsQueryInput(
            client_id="c", as_of_date=_AS_OF, metric_categories=[MetricCategory.CONCENTRATION]
        )
        first = svc.query(q, ctx)
        second = svc.query(q, ctx)
        assert second.cache_hit is True
        assert first.snapshot_id == second.snapshot_id

    def test_modified_context_produces_new_snapshot(self):
        svc = PortfolioAnalyticsService()
        ctx_a = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 1_000_000.0)]
        )
        ctx_b = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 2_000_000.0)]
        )
        q = AnalyticsQueryInput(
            client_id="c", as_of_date=_AS_OF, metric_categories=[MetricCategory.CONCENTRATION]
        )
        r1 = svc.query(q, ctx_a)
        r2 = svc.query(q, ctx_b)
        assert r1.snapshot_id != r2.snapshot_id
        assert r2.cache_hit is False

    def test_snapshot_id_deterministic(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 1_000_000.0)]
        )
        from artha.portfolio_analysis.canonical_service import _compute_snapshot_id

        s1 = _compute_snapshot_id(ctx)
        s2 = _compute_snapshot_id(ctx)
        assert s1 == s2

    def test_clear_invalidates_cache(self):
        svc = PortfolioAnalyticsService()
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 1_000_000.0)]
        )
        q = AnalyticsQueryInput(
            client_id="c", as_of_date=_AS_OF, metric_categories=[MetricCategory.CONCENTRATION]
        )
        svc.query(q, ctx)
        svc.clear()
        result = svc.query(q, ctx)
        assert result.cache_hit is False  # cache cleared, fresh compute

    def test_partial_overlap_is_cache_miss(self):
        # First query covers concentration only; second adds deployment → not all hit
        svc = PortfolioAnalyticsService()
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 1_000_000.0)]
        )
        q1 = AnalyticsQueryInput(
            client_id="c", as_of_date=_AS_OF, metric_categories=[MetricCategory.CONCENTRATION]
        )
        q2 = AnalyticsQueryInput(
            client_id="c",
            as_of_date=_AS_OF,
            metric_categories=[MetricCategory.CONCENTRATION, MetricCategory.DEPLOYMENT],
        )
        svc.query(q1, ctx)
        result = svc.query(q2, ctx)
        # Concentration was cached, deployment is fresh → not all-hit
        assert result.cache_hit is False


# ===========================================================================
# Section 8.9.9 Test 8 — Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_single_holding_portfolio(self):
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("ONLY", 1_000_000.0)]
        )
        c = compute_concentration(ctx)
        d = compute_deployment(ctx)
        assert c.hhi_holding_level == pytest.approx(1.0)
        assert d.total_aum_inr == 1_000_000.0

    def test_zero_aum_portfolio(self):
        # No holdings → all metrics return defined defaults
        ctx = PortfolioAnalyticsContext(client_id="c", as_of_date=_AS_OF, holdings=[])
        c = compute_concentration(ctx)
        d = compute_deployment(ctx)
        liq = compute_liquidity(ctx)
        t = compute_tax(ctx)
        assert d.total_aum_inr == 0.0
        assert c.hhi_holding_level == 0.0
        assert liq.liquidity_buckets[LiquidityBucket.DAYS_0_7] == 0.0
        assert t.unrealised_gain_loss_total_inr == 0.0

    def test_negative_cost_basis_holding(self):
        # Negative cost basis (e.g. stock acquired via bonus issue or merger) should not crash
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[_holding("BONUS", 1_000_000.0, cost_basis=-50_000.0)],
        )
        # Compute every metric; none should raise
        compute_concentration(ctx)
        compute_deployment(ctx)
        compute_liquidity(ctx)
        t = compute_tax(ctx)
        # Gain = market - cost_basis = 1_000_000 - (-50_000) = 1_050_000
        assert t.unrealised_gain_loss_total_inr == pytest.approx(1_050_000.0)

    def test_single_holding_in_zero_aum_world(self):
        # Holding with zero market value → no division-by-zero
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[_holding("DEAD", 0.0, cost_basis=0.0)],
        )
        c = compute_concentration(ctx)
        # All weights = 0; HHI is 0 (degenerate but defined)
        assert c.hhi_holding_level == 0.0


# ===========================================================================
# Service end-to-end
# ===========================================================================


class TestServiceEndToEnd:
    def test_query_populates_only_requested_categories(self):
        svc = PortfolioAnalyticsService()
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 1_000_000.0)]
        )
        q = AnalyticsQueryInput(
            client_id="c",
            as_of_date=_AS_OF,
            metric_categories=[MetricCategory.DEPLOYMENT, MetricCategory.LIQUIDITY],
        )
        result = svc.query(q, ctx)
        assert result.deployment is not None
        assert result.liquidity is not None
        assert result.concentration is None
        assert result.tax is None

    def test_inputs_used_manifest_populated(self):
        svc = PortfolioAnalyticsService()
        ctx = PortfolioAnalyticsContext(
            client_id="c",
            as_of_date=_AS_OF,
            holdings=[_holding("A", 1_000_000.0), _holding("B", 2_000_000.0, amc="X")],
            fee_schedules={"A": FeeSchedule(management_fee_bps=100)},
        )
        q = AnalyticsQueryInput(
            client_id="c", as_of_date=_AS_OF, metric_categories=[MetricCategory.FEES]
        )
        result = svc.query(q, ctx)
        manifest = result.inputs_used_manifest.inputs
        assert manifest["holdings"]["count"] == "2"
        assert manifest["fee_schedules"]["count"] == "1"

    def test_query_round_trip_via_json(self):
        svc = PortfolioAnalyticsService()
        ctx = PortfolioAnalyticsContext(
            client_id="c", as_of_date=_AS_OF, holdings=[_holding("A", 1_000_000.0)]
        )
        q = AnalyticsQueryInput(
            client_id="c", as_of_date=_AS_OF, metric_categories=[MetricCategory.DEPLOYMENT]
        )
        result = svc.query(q, ctx)
        from artha.canonical.portfolio_analytics import AnalyticsQueryResult

        round_tripped = AnalyticsQueryResult.model_validate_json(result.model_dump_json())
        assert round_tripped == result
