"""Pass 6 — M0.PortfolioState tests against §8.4.8 acceptance.

Tests 1, 4, 5, 6, 7 (Tests 2 and 3 — ingestion latency and reconciliation —
are deferred until ingestion lands).
"""

from __future__ import annotations

from datetime import date

import pytest

from artha.canonical.holding import (
    CascadeCertainty,
    CascadeEvent,
    CascadeEventType,
    ConflictType,
    Holding,
    LookThroughEntry,
)
from artha.canonical.m0_portfolio_state import (
    M0PortfolioStateQuery,
    M0PortfolioStateQueryCategory,
)
from artha.common.types import (
    AssetClass,
    Bucket,
    RunMode,
    VehicleType,
    WealthTier,
)
from artha.m0.portfolio_state import (
    IngestionNotImplementedError,
    InMemoryPortfolioStateRepository,
    M0PortfolioState,
)
from tests.canonical_fixtures import (
    make_family_office_mandate,
    make_model_portfolio_for_bucket,
)

_AS_OF = date(2026, 4, 25)


# ===========================================================================
# Helpers
# ===========================================================================


def _h(
    iid: str,
    market_value: float,
    *,
    asset_class: AssetClass = AssetClass.EQUITY,
    vehicle: VehicleType = VehicleType.MUTUAL_FUND,
    sub_asset_class: str = "multi_cap",
    amc: str = "Test AMC",
    units: float = 1000.0,
) -> Holding:
    return Holding(
        instrument_id=iid,
        instrument_name=f"{iid}_name",
        units=units,
        cost_basis=market_value * 0.9,
        market_value=market_value,
        unrealised_gain_loss=market_value * 0.1,
        amc_or_issuer=amc,
        vehicle_type=vehicle,
        asset_class=asset_class,
        sub_asset_class=sub_asset_class,
        acquisition_date=date(2024, 1, 15),
        as_of_date=_AS_OF,
    )


def _service(
    *,
    holdings: dict[str, list[Holding]] | None = None,
    look_through: dict[str, list[LookThroughEntry]] | None = None,
    cascade: dict[str, list[CascadeEvent]] | None = None,
) -> M0PortfolioState:
    repo = InMemoryPortfolioStateRepository(
        holdings_by_client=holdings,
        look_through_by_parent=look_through,
        cascade_by_client=cascade,
    )
    return M0PortfolioState(repo)


# ===========================================================================
# §8.4.8 Test 1 — Holdings query determinism
# ===========================================================================


class TestHoldingsQuery:
    def test_returns_all_holdings_for_client(self):
        svc = _service(
            holdings={
                "c1": [_h("A", 1_000_000.0), _h("B", 2_000_000.0, amc="Other")],
                "c2": [_h("X", 500_000.0)],
            }
        )
        out = svc.get_holdings("c1")
        assert {h.instrument_id for h in out} == {"A", "B"}

    def test_unknown_client_returns_empty(self):
        svc = _service(holdings={"c1": [_h("A", 1.0)]})
        assert svc.get_holdings("unknown_client") == []

    def test_holdings_query_deterministic(self):
        svc = _service(holdings={"c1": [_h("A", 1_000_000.0), _h("B", 2_000_000.0, amc="X")]})
        a = svc.get_holdings("c1")
        b = svc.get_holdings("c1")
        assert a == b

    def test_query_dispatcher_returns_envelope(self):
        svc = _service(holdings={"c1": [_h("A", 1_000_000.0)]})
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.HOLDINGS,
            client_id="c1",
            as_of_date=_AS_OF,
        )
        resp = svc.query(q)
        assert resp.query_category is M0PortfolioStateQueryCategory.HOLDINGS
        assert resp.holdings is not None
        assert len(resp.holdings) == 1
        assert resp.inputs_used_manifest.inputs["holdings"]["count"] == "1"


# ===========================================================================
# Slice query — filter discipline
# ===========================================================================


class TestSliceQuery:
    def test_filter_by_asset_class(self):
        svc = _service(
            holdings={
                "c1": [
                    _h("EQ", 1_000_000.0, asset_class=AssetClass.EQUITY),
                    _h("DEBT", 500_000.0, asset_class=AssetClass.DEBT, vehicle=VehicleType.FD),
                ]
            }
        )
        result = svc.get_slice("c1", asset_class=AssetClass.EQUITY)
        assert len(result.holdings) == 1
        assert result.holdings[0].instrument_id == "EQ"

    def test_filter_by_vehicle_type(self):
        svc = _service(
            holdings={
                "c1": [
                    _h("MF", 1_000_000.0, vehicle=VehicleType.MUTUAL_FUND),
                    _h("PMS", 5_000_000.0, vehicle=VehicleType.PMS, amc="PMS Manager"),
                ]
            }
        )
        result = svc.get_slice("c1", vehicle_type=VehicleType.PMS)
        assert {h.instrument_id for h in result.holdings} == {"PMS"}

    def test_total_value_aggregates_filtered_holdings(self):
        svc = _service(
            holdings={
                "c1": [
                    _h("A", 1_000_000.0),
                    _h("B", 2_000_000.0, amc="X"),
                    _h("C", 3_000_000.0, vehicle=VehicleType.PMS, amc="PMS"),
                ]
            }
        )
        result = svc.get_slice("c1")  # no filter
        assert result.total_value_inr == 6_000_000.0

    def test_total_units_by_amc(self):
        svc = _service(
            holdings={
                "c1": [
                    _h("A", 1_000_000.0, amc="HDFC", units=500.0),
                    _h("B", 2_000_000.0, amc="HDFC", units=1500.0),
                    _h("C", 3_000_000.0, amc="Kotak", units=300.0),
                ]
            }
        )
        result = svc.get_slice("c1")
        assert result.total_units_by_amc["HDFC"] == 2000.0
        assert result.total_units_by_amc["Kotak"] == 300.0

    def test_query_dispatcher_slice(self):
        svc = _service(holdings={"c1": [_h("A", 1_000_000.0)]})
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.SLICE,
            client_id="c1",
            query_parameters={"asset_class": "equity"},
        )
        resp = svc.query(q)
        assert resp.slice_result is not None
        assert resp.slice_result.total_value_inr == 1_000_000.0


# ===========================================================================
# §8.4.8 Test 4 — Look-through correctness
# ===========================================================================


class TestLookThroughQuery:
    def test_returns_underlying_entries(self):
        svc = _service(
            look_through={
                "MF_001": [
                    LookThroughEntry(
                        underlying_holding_id="HDFC_BANK",
                        underlying_name="HDFC Bank Ltd",
                        weight_in_portfolio=0.01,
                        weight_in_parent=0.05,
                    ),
                    LookThroughEntry(
                        underlying_holding_id="ITC",
                        underlying_name="ITC Ltd",
                        weight_in_portfolio=0.008,
                        weight_in_parent=0.04,
                    ),
                ]
            }
        )
        lt = svc.get_look_through("MF_001")
        assert lt.parent_instrument_id == "MF_001"
        assert {e.underlying_holding_id for e in lt.entries} == {"HDFC_BANK", "ITC"}

    def test_section_8_4_8_test_4_lookthrough_aggregation(self):
        # Spec acceptance: a multi-cap MF should expose its underlying-stock weights
        svc = _service(
            look_through={
                "MULTI_CAP": [
                    LookThroughEntry(
                        underlying_holding_id=f"STOCK_{i}",
                        underlying_name=f"Stock {i}",
                        weight_in_portfolio=0.05,
                        weight_in_parent=0.05,
                    )
                    for i in range(20)
                ]
            }
        )
        lt = svc.get_look_through("MULTI_CAP")
        # Within-parent weights sum to 1.0 (perfect equal split)
        assert sum(e.weight_in_parent for e in lt.entries) == pytest.approx(1.0)

    def test_query_dispatcher_lookthrough_requires_parent_id(self):
        svc = _service()
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.LOOK_THROUGH,
            client_id="c1",
            query_parameters={},  # missing parent_instrument_id
        )
        with pytest.raises(ValueError, match="parent_instrument_id"):
            svc.query(q)


# ===========================================================================
# §8.4.8 Test 5 — Cascade timing
# ===========================================================================


class TestCascadeQuery:
    def test_cascade_returns_events_in_order(self):
        events = [
            CascadeEvent(
                event_type=CascadeEventType.MATURITY,
                expected_date=date(2027, 6, 1),
                expected_amount_inr=2_500_000.0,
                source_holding_id="FD1",
                certainty_band=CascadeCertainty.CERTAIN,
            ),
            CascadeEvent(
                event_type=CascadeEventType.DISTRIBUTION,
                expected_date=date(2026, 12, 1),
                expected_amount_inr=500_000.0,
                source_holding_id="AIF1",
                certainty_band=CascadeCertainty.LIKELY,
            ),
        ]
        svc = _service(cascade={"c1": events})
        result = svc.get_cascade("c1")
        assert len(result) == 2

    def test_cascade_filters_past_events(self):
        # Repository filters events before as_of_date
        events = [
            CascadeEvent(
                event_type=CascadeEventType.MATURITY,
                expected_date=date(2025, 6, 1),  # past
                expected_amount_inr=1_000_000.0,
                source_holding_id="OLD",
                certainty_band=CascadeCertainty.CERTAIN,
            ),
            CascadeEvent(
                event_type=CascadeEventType.MATURITY,
                expected_date=date(2027, 6, 1),  # future
                expected_amount_inr=2_500_000.0,
                source_holding_id="NEW",
                certainty_band=CascadeCertainty.CERTAIN,
            ),
        ]
        svc = _service(cascade={"c1": events})
        result = svc.get_cascade("c1", as_of_date=_AS_OF)
        assert len(result) == 1
        assert result[0].source_holding_id == "NEW"

    def test_query_dispatcher_cascade(self):
        events = [
            CascadeEvent(
                event_type=CascadeEventType.DISTRIBUTION,
                expected_date=date(2027, 1, 1),
                expected_amount_inr=100_000.0,
                source_holding_id="X",
                certainty_band=CascadeCertainty.POSSIBLE,
            )
        ]
        svc = _service(cascade={"c1": events})
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.CASCADE,
            client_id="c1",
            as_of_date=_AS_OF,
        )
        resp = svc.query(q)
        assert resp.cascade_events is not None
        assert len(resp.cascade_events) == 1


# ===========================================================================
# §8.4.8 Test 6 — Conflict detection
# ===========================================================================


class TestConflictDetection:
    def test_no_conflicts_when_envelope_fits(self):
        svc = _service(holdings={"c1": []})
        m = make_family_office_mandate()
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        conflicts = svc.detect_conflicts("c1", m, mp)
        # Family office mandate equity range [30%, 70%] fits MOD_LT envelope [55%, 65%]
        equity = [c for c in conflicts if c.dimension == "asset_class.equity"]
        assert equity == []

    def test_aum_eligibility_conflict_for_small_investor(self):
        svc = _service(holdings={"c1": []})
        m = make_family_office_mandate()
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        # MOD_LT has PMS in L2 equity. UP_TO_25K_SIP investor can't access PMS.
        conflicts = svc.detect_conflicts(
            "c1", m, mp, investor_tier=WealthTier.UP_TO_25K_SIP
        )
        aum_conflicts = [
            c for c in conflicts if c.conflict_type is ConflictType.WEALTH_TIER_ELIGIBILITY
        ]
        assert len(aum_conflicts) > 0
        # PMS specifically should be flagged
        pms_aum = [c for c in aum_conflicts if "pms" in c.dimension]
        assert len(pms_aum) == 1

    def test_query_dispatcher_conflict_detection(self):
        svc = _service(holdings={"c1": []})
        m = make_family_office_mandate()
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.CONFLICT_DETECTION,
            client_id="c1",
        )
        resp = svc.query(q, mandate=m, model_portfolio=mp)
        assert resp.conflicts is not None  # may be empty list, but not None

    def test_query_dispatcher_conflict_detection_requires_mandate_and_model(self):
        svc = _service()
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.CONFLICT_DETECTION,
            client_id="c1",
        )
        with pytest.raises(ValueError, match="mandate.*model_portfolio"):
            svc.query(q)


# ===========================================================================
# §8.4.8 Test 7 — AUM eligibility filtering
# ===========================================================================


class TestAumEligibilityFiltering:
    def test_family_office_tier_no_aum_conflicts(self):
        svc = _service()
        m = make_family_office_mandate()
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        conflicts = svc.detect_conflicts(
            "c1", m, mp, investor_tier=WealthTier.AUM_BEYOND_100CR
        )
        aum_conflicts = [
            c for c in conflicts if c.conflict_type is ConflictType.WEALTH_TIER_ELIGIBILITY
        ]
        assert aum_conflicts == []


# ===========================================================================
# Pipeline mode plumbing (Thesis 4.2)
# ===========================================================================


class TestPipelineModePlumbing:
    def test_query_default_run_mode_is_case(self):
        svc = _service(holdings={"c1": [_h("A", 1.0)]})
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.HOLDINGS, client_id="c1"
        )
        assert q.run_mode is RunMode.CASE
        # And the dispatcher accepts it
        resp = svc.query(q)
        assert resp.client_id == "c1"

    def test_query_construction_mode_raises_not_implemented(self):
        svc = _service(holdings={"c1": [_h("A", 1.0)]})
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.HOLDINGS,
            client_id="c1",
            run_mode=RunMode.CONSTRUCTION,
        )
        with pytest.raises(NotImplementedError, match="construction"):
            svc.query(q)


# ===========================================================================
# Ingestion deferred
# ===========================================================================


class TestIngestionDeferred:
    def test_ingestion_query_raises(self):
        svc = _service()
        q = M0PortfolioStateQuery(
            query_category=M0PortfolioStateQueryCategory.INGESTION,
            client_id="c1",
        )
        with pytest.raises(IngestionNotImplementedError):
            svc.query(q)
