"""Pass 3 model portfolio operations — tolerance, conflict, and AUM filter.

Acceptance: Section 5.13 tests 1–4 (the construction-pipeline tests 5–8 are
deferred to a later pass).

Covers:
  * tolerance — L1/L2/L3 drift detection, severity, exact-edge handling
  * conflict — mandate vs model L1 envelope, vehicle disallow + cap
  * service — AUM eligibility filter, vehicle accessibility, version pin
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from artha.canonical import (
    AssetClassLimits,
    ConflictType,
    ConstructionContext,
    MandateObject,
    ModelPortfolioObject,
    SignoffEvidence,
    SignoffMethod,
    TargetWithTolerance,
)
from artha.common.types import (
    AssetClass,
    Bucket,
    MandateType,
    VehicleType,
    WealthTier,
)
from artha.model_portfolio import (
    DEFAULT_VEHICLE_MIN_TIER,
    DriftDimension,
    DriftSeverity,
    PortfolioAllocationSnapshot,
    apply_aum_eligibility_filter,
    detect_drift_events,
    detect_l1_drift,
    detect_l2_drift,
    detect_l3_drift,
    detect_mandate_vs_model_conflicts,
    has_l1_breach,
    is_irreconcilable,
    model_portfolio_version_pin,
    vehicle_accessible,
)
from tests.canonical_fixtures import (
    make_family_office_mandate,
    make_model_portfolio_for_bucket,
)

_TODAY = date(2026, 4, 25)


def _l1_only_snapshot(weights: dict[AssetClass, float]) -> PortfolioAllocationSnapshot:
    return PortfolioAllocationSnapshot(as_of_date=_TODAY, l1_weights=weights)


# ===========================================================================
# Tolerance / drift detection (Section 5.5, 5.13 tests 2–3)
# ===========================================================================


class TestL1DriftDetection:
    def _mod_lt(self) -> ModelPortfolioObject:
        return make_model_portfolio_for_bucket(Bucket.MOD_LT)

    def test_section_5_13_test_2_l1_breach_triggers_action(self):
        # Spec scenario: equity 67%, target 60%, tolerance ±5% → action_required
        mp = self._mod_lt()
        snapshot = _l1_only_snapshot({
            AssetClass.EQUITY: 0.67,
            AssetClass.DEBT: 0.23,
            AssetClass.GOLD_COMMODITIES: 0.07,
            AssetClass.REAL_ASSETS: 0.03,
        })
        events = detect_l1_drift(mp, snapshot)

        equity_events = [e for e in events if e.cell_key == "equity"]
        assert len(equity_events) == 1
        ev = equity_events[0]
        assert ev.severity is DriftSeverity.ACTION_REQUIRED
        assert ev.dimension is DriftDimension.L1
        assert ev.target == pytest.approx(0.60)
        assert ev.actual == pytest.approx(0.67)
        assert ev.drift_magnitude == pytest.approx(0.07)

    def test_l1_in_tolerance_emits_no_event(self):
        # 64% equity, target 60% ± 5% → strictly within tolerance, no event
        mp = self._mod_lt()
        snapshot = _l1_only_snapshot({
            AssetClass.EQUITY: 0.64,
            AssetClass.DEBT: 0.26,
            AssetClass.GOLD_COMMODITIES: 0.07,
            AssetClass.REAL_ASSETS: 0.03,
        })
        events = detect_l1_drift(mp, snapshot)
        equity_events = [e for e in events if e.cell_key == "equity"]
        assert equity_events == []

    def test_l1_negative_drift_breach(self):
        # 53% equity, target 60% ± 5% → action_required with negative magnitude
        mp = self._mod_lt()
        snapshot = _l1_only_snapshot({
            AssetClass.EQUITY: 0.53,
            AssetClass.DEBT: 0.37,
            AssetClass.GOLD_COMMODITIES: 0.07,
            AssetClass.REAL_ASSETS: 0.03,
        })
        events = detect_l1_drift(mp, snapshot)
        equity_events = [e for e in events if e.cell_key == "equity"]
        assert len(equity_events) == 1
        assert equity_events[0].drift_magnitude == pytest.approx(-0.07)
        assert equity_events[0].severity is DriftSeverity.ACTION_REQUIRED

    def test_l1_missing_class_in_snapshot_treated_as_zero(self):
        # If a snapshot omits an asset class, it's treated as 0 weight, which is
        # almost certainly a breach for any non-zero target.
        mp = self._mod_lt()
        snapshot = _l1_only_snapshot({AssetClass.EQUITY: 1.0})  # only equity
        events = detect_l1_drift(mp, snapshot)
        debt_events = [e for e in events if e.cell_key == "debt"]
        assert len(debt_events) == 1
        assert debt_events[0].actual == 0.0
        # Magnitude is -0.30 (target 0.30, actual 0.0)
        assert debt_events[0].drift_magnitude == pytest.approx(-0.30)

    def test_l1_event_includes_band(self):
        mp = self._mod_lt()
        snapshot = _l1_only_snapshot({
            AssetClass.EQUITY: 0.67,
            AssetClass.DEBT: 0.23,
            AssetClass.GOLD_COMMODITIES: 0.07,
            AssetClass.REAL_ASSETS: 0.03,
        })
        events = detect_l1_drift(mp, snapshot)
        equity_event = next(e for e in events if e.cell_key == "equity")
        assert equity_event.tolerance_band == pytest.approx(0.05)

    def test_has_l1_breach_helper(self):
        mp = self._mod_lt()
        snapshot = _l1_only_snapshot({
            AssetClass.EQUITY: 0.67,
            AssetClass.DEBT: 0.23,
            AssetClass.GOLD_COMMODITIES: 0.07,
            AssetClass.REAL_ASSETS: 0.03,
        })
        assert has_l1_breach(detect_drift_events(mp, snapshot)) is True

    def test_has_l1_breach_false_when_only_l2_drift(self):
        # All L1 in tolerance; L2 drift only
        mp = self._mod_lt()
        snapshot = PortfolioAllocationSnapshot(
            as_of_date=_TODAY,
            l1_weights={
                AssetClass.EQUITY: 0.60,
                AssetClass.DEBT: 0.30,
                AssetClass.GOLD_COMMODITIES: 0.07,
                AssetClass.REAL_ASSETS: 0.03,
            },
            l2_weights={
                AssetClass.EQUITY: {
                    VehicleType.PMS: 0.25 + 0.10,  # 0.35, exactly at edge of band 0.10
                    VehicleType.MUTUAL_FUND: 0.50,
                    VehicleType.DIRECT_EQUITY: 0.10,
                    VehicleType.AIF_CAT_3: 0.05,
                },
            },
        )
        events = detect_drift_events(mp, snapshot)
        assert has_l1_breach(events) is False


class TestL2DriftDetection:
    def test_section_5_13_test_3_l2_drift_at_edge_is_informational(self):
        # Spec scenario: PMS at 35% of equity, target 25%, band ±10% → at edge,
        # informational, no action.
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        snapshot = PortfolioAllocationSnapshot(
            as_of_date=_TODAY,
            l1_weights={
                AssetClass.EQUITY: 0.60,
                AssetClass.DEBT: 0.30,
                AssetClass.GOLD_COMMODITIES: 0.07,
                AssetClass.REAL_ASSETS: 0.03,
            },
            l2_weights={
                AssetClass.EQUITY: {
                    VehicleType.PMS: 0.35,
                    VehicleType.MUTUAL_FUND: 0.50,
                    VehicleType.DIRECT_EQUITY: 0.10,
                    VehicleType.AIF_CAT_3: 0.05,
                },
            },
        )
        events = detect_l2_drift(mp, snapshot)
        pms_events = [e for e in events if e.cell_key == "equity.pms"]
        assert len(pms_events) == 1
        assert pms_events[0].severity is DriftSeverity.INFORMATIONAL
        assert pms_events[0].dimension is DriftDimension.L2

    def test_l2_strictly_within_band_emits_no_event(self):
        # PMS at 30% of equity, target 25%, band ±10% → 5pp away, well inside
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        snapshot = PortfolioAllocationSnapshot(
            as_of_date=_TODAY,
            l1_weights={AssetClass.EQUITY: 0.60, AssetClass.DEBT: 0.30,
                        AssetClass.GOLD_COMMODITIES: 0.07, AssetClass.REAL_ASSETS: 0.03},
            l2_weights={
                AssetClass.EQUITY: {
                    VehicleType.PMS: 0.30,
                    VehicleType.MUTUAL_FUND: 0.55,
                    VehicleType.DIRECT_EQUITY: 0.10,
                    VehicleType.AIF_CAT_3: 0.05,
                },
            },
        )
        events = detect_l2_drift(mp, snapshot)
        pms_events = [e for e in events if e.cell_key == "equity.pms"]
        assert pms_events == []


class TestL3DriftDetection:
    def test_l3_breach_is_informational(self):
        # MOD_LT has L3 fixture: large_cap target 0.30, band ±0.15
        # Set actual to 0.50 (20pp over target) → breach
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        snapshot = PortfolioAllocationSnapshot(
            as_of_date=_TODAY,
            l1_weights={AssetClass.EQUITY: 0.60, AssetClass.DEBT: 0.30,
                        AssetClass.GOLD_COMMODITIES: 0.07, AssetClass.REAL_ASSETS: 0.03},
            l3_weights={
                "equity.mutual_fund": {
                    "large_cap": 0.50,
                    "mid_cap": 0.20,
                    "small_cap": 0.15,
                    "multi_cap": 0.10,
                    "international": 0.05,
                },
            },
        )
        events = detect_l3_drift(mp, snapshot)
        large_events = [e for e in events if e.cell_key == "equity.mutual_fund.large_cap"]
        assert len(large_events) == 1
        assert large_events[0].severity is DriftSeverity.INFORMATIONAL


class TestDriftDetectionDeterminism:
    def test_same_inputs_same_outputs(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        snapshot = _l1_only_snapshot({
            AssetClass.EQUITY: 0.67,
            AssetClass.DEBT: 0.23,
            AssetClass.GOLD_COMMODITIES: 0.07,
            AssetClass.REAL_ASSETS: 0.03,
        })
        e1 = detect_drift_events(mp, snapshot)
        e2 = detect_drift_events(mp, snapshot)
        assert e1 == e2


# ===========================================================================
# Mandate-vs-model conflict detection (Section 5.10, 5.13 test 4)
# ===========================================================================


def _mandate_with_equity_max(equity_max: float) -> MandateObject:
    """Build a minimal mandate that caps equity at `equity_max` for conflict tests."""
    eff = datetime(2026, 1, 1, tzinfo=UTC)
    return MandateObject(
        mandate_id=f"m_eq_max_{int(equity_max * 100)}",
        client_id="c_test",
        firm_id="f_test",
        created_at=eff,
        effective_at=eff,
        mandate_type=MandateType.INDIVIDUAL,
        asset_class_limits={
            AssetClass.EQUITY: AssetClassLimits(
                min_pct=0.0, target_pct=min(0.5, equity_max), max_pct=equity_max
            ),
            AssetClass.DEBT: AssetClassLimits(min_pct=0.0, target_pct=0.4, max_pct=1.0),
        },
        liquidity_floor=0.05,
        signoff_method=SignoffMethod.E_SIGNATURE,
        signoff_evidence=SignoffEvidence(evidence_id="sig_t", captured_at=eff),
        signed_by="c_test",
    )


class TestMandateVsModelConflict:
    def test_section_5_13_test_4_l1_conflict_surfaces_three_paths(self):
        # Spec scenario: client mapped to MOD_LT (equity 60% ± 5% → envelope [55%, 65%])
        # but mandate caps equity at 55% — so envelope upper edge (65%) > mandate max (55%)
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        mandate = _mandate_with_equity_max(0.55)

        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        equity_conflicts = [c for c in conflicts if c.dimension == "asset_class.equity"]
        assert len(equity_conflicts) == 1

        c = equity_conflicts[0]
        assert c.conflict_type is ConflictType.MANDATE_VS_MODEL
        assert c.mandate_value is not None
        assert c.mandate_value["max_pct"] == 0.55
        assert c.model_value is not None
        assert c.model_value["target"] == pytest.approx(0.60)
        # Section 5.10: three resolution paths
        assert set(c.resolution_paths) == {"amend_mandate", "clip_model", "out_of_bucket"}

    def test_no_conflict_when_envelope_fits_inside_mandate(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        # Mandate allows up to 70% equity; model envelope is [55%, 65%] — fits
        mandate = _mandate_with_equity_max(0.70)
        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        equity_conflicts = [c for c in conflicts if c.dimension == "asset_class.equity"]
        assert equity_conflicts == []

    def test_mandate_min_above_envelope_lower_edge_conflicts(self):
        # MOD_LT equity envelope is [55%, 65%]. If mandate min is 60% (above 55%) → conflict
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        mandate = MandateObject(
            mandate_id="m_eq_min_60",
            client_id="c",
            firm_id="f",
            created_at=eff,
            effective_at=eff,
            mandate_type=MandateType.INDIVIDUAL,
            asset_class_limits={
                AssetClass.EQUITY: AssetClassLimits(
                    min_pct=0.60, target_pct=0.65, max_pct=0.80
                ),
                AssetClass.DEBT: AssetClassLimits(min_pct=0.0, target_pct=0.2, max_pct=0.40),
            },
            liquidity_floor=0.05,
            signoff_method=SignoffMethod.E_SIGNATURE,
            signoff_evidence=SignoffEvidence(evidence_id="sig", captured_at=eff),
            signed_by="c",
        )
        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        equity_conflicts = [c for c in conflicts if c.dimension == "asset_class.equity"]
        assert len(equity_conflicts) == 1

    def test_vehicle_disallowed_with_nonzero_target_conflicts(self):
        # Family office mandate disallows AIF_CAT_2; we need a model with AIF_CAT_2 in L2.
        # The MOD_LT fixture doesn't have AIF_CAT_2 in L2, so build one inline.
        mandate = make_family_office_mandate()
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        mp = ModelPortfolioObject(
            model_id="MP_TEST",
            bucket=Bucket.MOD_LT,
            version="0.1.0",
            firm_id="firm_test",
            created_at=eff,
            effective_at=eff,
            approved_by="cio",
            approval_rationale="test",
            l1_targets={
                AssetClass.EQUITY: TargetWithTolerance(target=0.60, tolerance_band=0.05),
                AssetClass.DEBT: TargetWithTolerance(target=0.30, tolerance_band=0.05),
                AssetClass.GOLD_COMMODITIES: TargetWithTolerance(target=0.07, tolerance_band=0.02),
                AssetClass.REAL_ASSETS: TargetWithTolerance(target=0.03, tolerance_band=0.02),
            },
            l2_targets={
                AssetClass.DEBT: {
                    VehicleType.MUTUAL_FUND: TargetWithTolerance(target=0.80, tolerance_band=0.10),
                    VehicleType.AIF_CAT_2: TargetWithTolerance(target=0.20, tolerance_band=0.05),
                },
            },
            construction=ConstructionContext(construction_pipeline_run_id="r"),
        )
        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        aif_conflicts = [c for c in conflicts if "aif_cat_2" in c.dimension]
        assert len(aif_conflicts) == 1
        assert aif_conflicts[0].mandate_value == {"allowed": False}

    def test_vehicle_max_breach_conflicts(self):
        # Family office mandate: PMS allowed with max 30%. Build a model with PMS at 35%.
        mandate = make_family_office_mandate()
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        mp = ModelPortfolioObject(
            model_id="MP_PMS_HIGH",
            bucket=Bucket.MOD_LT,
            version="0.1.0",
            firm_id="firm_test",
            created_at=eff,
            effective_at=eff,
            approved_by="cio",
            approval_rationale="test",
            l1_targets={
                AssetClass.EQUITY: TargetWithTolerance(target=0.60, tolerance_band=0.05),
                AssetClass.DEBT: TargetWithTolerance(target=0.30, tolerance_band=0.05),
                AssetClass.GOLD_COMMODITIES: TargetWithTolerance(target=0.07, tolerance_band=0.02),
                AssetClass.REAL_ASSETS: TargetWithTolerance(target=0.03, tolerance_band=0.02),
            },
            l2_targets={
                AssetClass.EQUITY: {
                    VehicleType.PMS: TargetWithTolerance(target=0.35, tolerance_band=0.05),
                    VehicleType.MUTUAL_FUND: TargetWithTolerance(target=0.65, tolerance_band=0.10),
                },
            },
            construction=ConstructionContext(construction_pipeline_run_id="r"),
        )
        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        pms_conflicts = [c for c in conflicts if c.dimension == "vehicle.equity.pms"]
        assert len(pms_conflicts) == 1
        assert pms_conflicts[0].mandate_value == {"allowed": True, "max_pct": 0.30}

    def test_conflict_detection_deterministic(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        mandate = _mandate_with_equity_max(0.55)
        c1 = detect_mandate_vs_model_conflicts(mandate, mp)
        c2 = detect_mandate_vs_model_conflicts(mandate, mp)
        assert c1 == c2

    def test_no_conflict_when_mandate_silent_on_class(self):
        # Build a model with REAL_ASSETS but a mandate that doesn't constrain that class.
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        mandate = MandateObject(
            mandate_id="m_no_real_assets_constraint",
            client_id="c",
            firm_id="f",
            created_at=eff,
            effective_at=eff,
            mandate_type=MandateType.INDIVIDUAL,
            asset_class_limits={
                AssetClass.EQUITY: AssetClassLimits(min_pct=0.0, target_pct=0.6, max_pct=1.0),
                AssetClass.DEBT: AssetClassLimits(min_pct=0.0, target_pct=0.4, max_pct=1.0),
                # no REAL_ASSETS constraint
            },
            liquidity_floor=0.05,
            signoff_method=SignoffMethod.E_SIGNATURE,
            signoff_evidence=SignoffEvidence(evidence_id="sig", captured_at=eff),
            signed_by="c",
        )
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        real_assets_conflicts = [c for c in conflicts if c.dimension == "asset_class.real_assets"]
        assert real_assets_conflicts == []


class TestIrreconcilableHeuristic:
    def test_partial_overlap_is_reconcilable(self):
        # Mandate equity max 55%, model envelope [55%, 65%] — they touch at 55%, so overlap exists
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        mandate = _mandate_with_equity_max(0.55)
        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        assert is_irreconcilable(conflicts) is False

    def test_zero_overlap_is_irreconcilable(self):
        # Mandate caps equity at 30%, model envelope is [55%, 65%] → zero overlap
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        mandate = _mandate_with_equity_max(0.30)
        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        assert is_irreconcilable(conflicts) is True

    def test_no_conflicts_is_not_irreconcilable(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        mandate = _mandate_with_equity_max(0.99)
        conflicts = detect_mandate_vs_model_conflicts(mandate, mp)
        assert conflicts == []
        assert is_irreconcilable(conflicts) is False


# ===========================================================================
# AUM eligibility filter + version pin (Section 3.7, 5.3.2)
# ===========================================================================


class TestAumEligibilityFilter:
    def test_small_investor_loses_pms_aif_unlisted(self):
        # UP_TO_25K_SIP investor cannot access PMS, AIF, SIF, or unlisted equity
        for vehicle in (
            VehicleType.PMS, VehicleType.AIF_CAT_1, VehicleType.AIF_CAT_2,
            VehicleType.AIF_CAT_3, VehicleType.SIF, VehicleType.UNLISTED_EQUITY,
        ):
            assert (
                vehicle_accessible(vehicle, WealthTier.UP_TO_25K_SIP) is False
            ), f"{vehicle.value} should not be accessible at UP_TO_25K_SIP"

    def test_family_office_accesses_everything(self):
        for vehicle in VehicleType:
            assert (
                vehicle_accessible(vehicle, WealthTier.AUM_BEYOND_100CR) is True
            ), f"{vehicle.value} should be accessible at AUM_BEYOND_100CR"

    def test_unrestricted_vehicles_accessible_at_all_tiers(self):
        # Mutual funds, FDs, gold etc. have no tier requirement
        for tier in WealthTier:
            assert vehicle_accessible(VehicleType.MUTUAL_FUND, tier) is True
            assert vehicle_accessible(VehicleType.FD, tier) is True
            assert vehicle_accessible(VehicleType.GOLD, tier) is True

    def test_pms_accessible_at_or_above_tier_2(self):
        assert vehicle_accessible(VehicleType.PMS, WealthTier.UP_TO_25K_SIP) is False
        assert vehicle_accessible(VehicleType.PMS, WealthTier.SIP_25K_TO_2CR_AUM) is True
        assert vehicle_accessible(VehicleType.PMS, WealthTier.AUM_BEYOND_100CR) is True

    def test_filter_redistributes_proportionally(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        # MOD_LT L2 equity: DIRECT 0.10, MUTUAL_FUND 0.60, PMS 0.25, AIF_CAT_3 0.05
        # Small investor: PMS + AIF_CAT_3 suppressed (sum 0.30)
        # Surviving: DIRECT 0.10, MUTUAL_FUND 0.60 (sum 0.70)
        # Scale: 1.0 / 0.70 ≈ 1.4286
        # New: DIRECT ≈ 0.1429, MUTUAL_FUND ≈ 0.8571
        filtered = apply_aum_eligibility_filter(mp, WealthTier.UP_TO_25K_SIP)
        equity_l2 = filtered.l2_targets[AssetClass.EQUITY]

        # PMS and AIF_CAT_3 should be gone
        assert VehicleType.PMS not in equity_l2
        assert VehicleType.AIF_CAT_3 not in equity_l2

        # The surviving vehicles should still sum to 1.0 within the asset class
        total = sum(t.target for t in equity_l2.values())
        assert total == pytest.approx(1.0, abs=1e-6)

        # Specifically: MUTUAL_FUND was 0.60 / 0.70 of survivors, now ~0.857
        assert equity_l2[VehicleType.MUTUAL_FUND].target == pytest.approx(0.60 / 0.70, abs=1e-6)

    def test_filter_preserves_l1(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        filtered = apply_aum_eligibility_filter(mp, WealthTier.UP_TO_25K_SIP)
        assert filtered.l1_targets == mp.l1_targets

    def test_family_office_filter_is_identity(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        filtered = apply_aum_eligibility_filter(mp, WealthTier.AUM_BEYOND_100CR)
        # No vehicles suppressed → l2 should be unchanged
        assert filtered.l2_targets == mp.l2_targets

    def test_filter_accepts_custom_min_tier_mapping(self):
        # Override default: make MUTUAL_FUND require AUM_5CR_TO_10CR (artificial)
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        custom = {VehicleType.MUTUAL_FUND: WealthTier.AUM_5CR_TO_10CR}
        # A SIP investor would lose MUTUAL_FUND under this custom policy
        filtered = apply_aum_eligibility_filter(
            mp, WealthTier.SIP_25K_TO_2CR_AUM, vehicle_min_tier=custom
        )
        equity_l2 = filtered.l2_targets[AssetClass.EQUITY]
        assert VehicleType.MUTUAL_FUND not in equity_l2

    def test_default_vehicle_min_tier_constants(self):
        # Spot check that the default mapping covers the spec's restricted vehicles
        assert DEFAULT_VEHICLE_MIN_TIER[VehicleType.PMS] is WealthTier.SIP_25K_TO_2CR_AUM
        assert DEFAULT_VEHICLE_MIN_TIER[VehicleType.AIF_CAT_2] is WealthTier.SIP_25K_TO_2CR_AUM
        assert DEFAULT_VEHICLE_MIN_TIER[VehicleType.UNLISTED_EQUITY] is WealthTier.AUM_2CR_TO_5CR


class TestVersionPin:
    def test_format_includes_model_id_and_version(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT, version="3.4.0")
        pin = model_portfolio_version_pin(mp)
        assert pin == f"{mp.model_id}@3.4.0"

    def test_pin_is_deterministic(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        assert model_portfolio_version_pin(mp) == model_portfolio_version_pin(mp)

    def test_section_5_13_test_1_pin_replay_matches(self):
        # Spec scenario: a case is processed against MOD_LT version 3.4.0; the pin
        # captures both bucket and version so replay can reconstruct deterministically.
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT, version="3.4.0")
        pin = model_portfolio_version_pin(mp)
        # The pin must contain the bucket identifier and the exact version string
        assert Bucket.MOD_LT.value in pin
        assert "3.4.0" in pin
