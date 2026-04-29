"""Pass 2 canonical schema tests — Section 15 Pydantic models.

Covers:
  * model_portfolio.buckets       — derive_bucket round-trip + 9-bucket coverage
  * canonical.investor            — InvestorContextProfile validators
  * canonical.case                — CaseObject schema discipline
  * canonical.mandate             — MandateObject min<=target<=max, family overrides
  * canonical.model_portfolio     — ModelPortfolioObject L1/L2/L3 sum invariants
  * canonical.l4_manifest         — L4 entry + manifest version round-trip
  * canonical.holding             — Holding + slice/look_through/cascade/conflict
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from artha.canonical import (
    AssetClassLimits,
    BeneficiaryMetadata,
    CascadeCertainty,
    CascadeEvent,
    CascadeEventType,
    CaseChannel,
    CaseObject,
    CaseStatus,
    ConcentrationLimits,
    ConflictReport,
    ConflictType,
    ConstructionContext,
    DataSource,
    DominantLens,
    FeeSchedule,
    FundUniverseL4Entry,
    Holding,
    IngestionReport,
    IntermediaryMetadata,
    InvestorContextProfile,
    L4ManifestChange,
    L4ManifestVersion,
    L4Operation,
    L4Status,
    LensMetadata,
    LiquidityWindow,
    LookThroughEntry,
    LookThroughResponse,
    MandateAmendmentRequest,
    MandateAmendmentStatus,
    MandateAmendmentType,
    MandateObject,
    ModelPortfolioObject,
    ProposedAction,
    SignoffEvidence,
    SignoffMethod,
    SliceResponse,
    SubAssetClassLimits,
    TargetWithTolerance,
    VehicleLimits,
)
from artha.common.types import (
    AssetClass,
    Bucket,
    CapacityTrajectory,
    CaseIntent,
    MandateType,
    RiskProfile,
    TimeHorizon,
    VehicleType,
    WealthTier,
)
from artha.model_portfolio.buckets import (
    BUCKET_RISK_PROFILE,
    BUCKET_TIME_HORIZON,
    bucket_components,
    derive_bucket,
)
from tests.canonical_fixtures import (
    make_all_bucket_portfolios,
    make_family_office_mandate,
    make_model_portfolio_for_bucket,
)

# ===========================================================================
# Bucket helper (Section 5.4)
# ===========================================================================


class TestBuckets:
    def test_derive_bucket_for_each_combination(self):
        cases = [
            (RiskProfile.CONSERVATIVE, TimeHorizon.SHORT_TERM, Bucket.CON_ST),
            (RiskProfile.CONSERVATIVE, TimeHorizon.MEDIUM_TERM, Bucket.CON_MT),
            (RiskProfile.CONSERVATIVE, TimeHorizon.LONG_TERM, Bucket.CON_LT),
            (RiskProfile.MODERATE, TimeHorizon.SHORT_TERM, Bucket.MOD_ST),
            (RiskProfile.MODERATE, TimeHorizon.MEDIUM_TERM, Bucket.MOD_MT),
            (RiskProfile.MODERATE, TimeHorizon.LONG_TERM, Bucket.MOD_LT),
            (RiskProfile.AGGRESSIVE, TimeHorizon.SHORT_TERM, Bucket.AGG_ST),
            (RiskProfile.AGGRESSIVE, TimeHorizon.MEDIUM_TERM, Bucket.AGG_MT),
            (RiskProfile.AGGRESSIVE, TimeHorizon.LONG_TERM, Bucket.AGG_LT),
        ]
        for rp, th, expected in cases:
            assert derive_bucket(rp, th) is expected

    def test_bucket_components_round_trip(self):
        # Every bucket must round-trip cleanly via components
        for bucket in Bucket:
            rp, th = bucket_components(bucket)
            assert derive_bucket(rp, th) is bucket

    def test_bucket_lookup_tables_complete(self):
        assert len(BUCKET_RISK_PROFILE) == 9
        assert len(BUCKET_TIME_HORIZON) == 9
        assert set(BUCKET_RISK_PROFILE.keys()) == set(Bucket)


# ===========================================================================
# InvestorContextProfile (Section 15.3.1)
# ===========================================================================


def _baseline_investor(**overrides) -> InvestorContextProfile:
    """Construct a minimal valid InvestorContextProfile, allowing per-field overrides."""
    base = dict(
        client_id="client_001",
        firm_id="firm_test",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        risk_profile=RiskProfile.MODERATE,
        time_horizon=TimeHorizon.LONG_TERM,
        wealth_tier=WealthTier.AUM_5CR_TO_10CR,
        assigned_bucket=Bucket.MOD_LT,
        data_source=DataSource.FORM,
    )
    base.update(overrides)
    return InvestorContextProfile(**base)


class TestInvestorContextProfile:
    def test_minimal_valid(self):
        inv = _baseline_investor()
        assert inv.assigned_bucket is Bucket.MOD_LT
        assert inv.dormant_layer.active is False
        # MVP contract: every dormant collection is empty
        assert inv.dormant_layer.matched_l1_patterns == []
        assert inv.dormant_layer.matched_l2_patterns == []
        assert inv.dormant_layer.matched_l3_patterns == []

    def test_assigned_bucket_must_match_derive(self):
        with pytest.raises(ValidationError, match="assigned_bucket"):
            _baseline_investor(
                risk_profile=RiskProfile.AGGRESSIVE,
                # mismatched: bucket says MOD_LT but risk says AGGRESSIVE
                assigned_bucket=Bucket.MOD_LT,
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            _baseline_investor(unknown_field="x")

    def test_intermediary_metadata_requires_flag(self):
        # Metadata populated but flag False — should fail
        with pytest.raises(ValidationError, match="intermediary"):
            _baseline_investor(
                intermediary_present=False,
                intermediary_metadata=IntermediaryMetadata(relationship_type="ca"),
            )

    def test_intermediary_metadata_with_flag_passes(self):
        inv = _baseline_investor(
            intermediary_present=True,
            intermediary_metadata=IntermediaryMetadata(
                relationship_type="distributor",
                authority_scope="advises",
            ),
        )
        assert inv.intermediary_metadata is not None

    def test_beneficiary_metadata_requires_inability(self):
        # Beneficiary CAN operate but metadata is populated — should fail
        with pytest.raises(ValidationError, match="beneficiary"):
            _baseline_investor(
                beneficiary_can_operate_current_structure=True,
                beneficiary_metadata=BeneficiaryMetadata(capacity_basis="cognitive_decline"),
            )

    def test_beneficiary_metadata_when_unable_passes(self):
        inv = _baseline_investor(
            beneficiary_can_operate_current_structure=False,
            beneficiary_metadata=BeneficiaryMetadata(
                capacity_basis="cognitive_decline",
                support_structure="adult_son_acts_as_advisor",
            ),
        )
        assert inv.beneficiary_metadata is not None

    def test_dormant_layer_default_inactive(self):
        inv = _baseline_investor()
        assert inv.dormant_layer.active is False

    def test_capacity_trajectory_enum(self):
        inv = _baseline_investor(capacity_trajectory=CapacityTrajectory.DECLINING_MODERATE)
        assert inv.capacity_trajectory is CapacityTrajectory.DECLINING_MODERATE


# ===========================================================================
# CaseObject (Section 15.3.2)
# ===========================================================================


def _baseline_case(**overrides) -> CaseObject:
    base = dict(
        case_id="case_001",
        client_id="client_001",
        firm_id="firm_test",
        advisor_id="advisor_jane",
        created_at=datetime(2026, 4, 25, tzinfo=UTC),
        intent=CaseIntent.CASE,
        intent_confidence=0.92,
        dominant_lens=DominantLens.PROPOSAL,
        lens_metadata=LensMetadata(lenses_fired=[DominantLens.PROPOSAL, DominantLens.PORTFOLIO]),
        current_status=CaseStatus.IN_PROGRESS,
        channel=CaseChannel.C0,
    )
    base.update(overrides)
    return CaseObject(**base)


class TestCaseObject:
    def test_minimal_valid(self):
        case = _baseline_case()
        assert case.intent is CaseIntent.CASE

    def test_intent_confidence_must_be_in_range(self):
        with pytest.raises(ValidationError):
            _baseline_case(intent_confidence=1.5)

    def test_proposal_dominant_can_carry_proposed_action(self):
        case = _baseline_case(
            dominant_lens=DominantLens.PROPOSAL,
            proposed_action=ProposedAction(
                target_product="HDFC AMC Cat II AIF",
                ticket_size_inr=10_000_000.0,
                structure="Cat II",
                source_of_funds="redemption_from_mf_passive",
            ),
        )
        assert case.proposed_action is not None
        assert case.proposed_action.ticket_size_inr == 10_000_000.0

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            _baseline_case(unknown_field="x")


# ===========================================================================
# MandateObject (Section 15.4.1)
# ===========================================================================


class TestAssetClassLimits:
    def test_valid_ordering(self):
        AssetClassLimits(min_pct=0.0, target_pct=0.5, max_pct=0.7)

    def test_target_below_min_rejected(self):
        with pytest.raises(ValidationError, match="min_pct"):
            AssetClassLimits(min_pct=0.5, target_pct=0.3, max_pct=0.7)

    def test_max_below_target_rejected(self):
        with pytest.raises(ValidationError, match="max_pct"):
            AssetClassLimits(min_pct=0.0, target_pct=0.7, max_pct=0.5)

    def test_min_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            AssetClassLimits(min_pct=-0.1, target_pct=0.5, max_pct=0.7)


class TestVehicleLimits:
    def test_valid_with_bounds(self):
        VehicleLimits(allowed=True, min_pct=0.05, max_pct=0.30)

    def test_min_above_max_rejected(self):
        with pytest.raises(ValidationError, match="min_pct"):
            VehicleLimits(allowed=True, min_pct=0.50, max_pct=0.30)

    def test_disallowed_vehicle(self):
        v = VehicleLimits(allowed=False)
        assert v.allowed is False


class TestMandateObject:
    def test_family_office_fixture_validates(self):
        m = make_family_office_mandate()
        assert m.mandate_type is MandateType.FAMILY_OFFICE
        assert len(m.family_overrides) == 3
        assert m.signoff_method is SignoffMethod.IN_PERSON
        assert m.liquidity_floor == 0.10

    def test_family_overrides_have_distinct_member_ids(self):
        m = make_family_office_mandate()
        member_ids = {fo.member_id for fo in m.family_overrides}
        assert len(member_ids) == len(m.family_overrides)

    def test_sector_blocks_separate_from_exclusions(self):
        m = make_family_office_mandate()
        assert "tobacco" in m.sector_exclusions
        assert "firearms" in m.sector_hard_blocks
        assert "tobacco" not in m.sector_hard_blocks

    def test_supersedence_must_be_after_effective(self):
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValidationError, match="superseded_at"):
            MandateObject(
                mandate_id="m1",
                client_id="c1",
                firm_id="f1",
                created_at=eff,
                effective_at=eff,
                superseded_at=datetime(2025, 12, 1, tzinfo=UTC),
                mandate_type=MandateType.INDIVIDUAL,
                asset_class_limits={
                    AssetClass.EQUITY: AssetClassLimits(
                        min_pct=0.0, target_pct=0.6, max_pct=1.0
                    ),
                    AssetClass.DEBT: AssetClassLimits(
                        min_pct=0.0, target_pct=0.4, max_pct=1.0
                    ),
                },
                liquidity_floor=0.05,
                signoff_method=SignoffMethod.E_SIGNATURE,
                signoff_evidence=SignoffEvidence(
                    evidence_id="sig1", captured_at=eff, storage_uri=None
                ),
                signed_by="client_001",
            )

    def test_liquidity_window_and_concentration_limits(self):
        m = make_family_office_mandate()
        assert len(m.liquidity_windows) == 1
        assert m.liquidity_windows[0].amount_inr == 50_000_000.0
        assert m.concentration_limits is not None
        assert m.concentration_limits.per_holding_max == 0.10

    def test_round_trip_json(self):
        m = make_family_office_mandate()
        round_tripped = MandateObject.model_validate_json(m.model_dump_json())
        assert round_tripped == m


class TestMandateAmendmentRequest:
    def test_minimal_pending_amendment(self):
        req = MandateAmendmentRequest(
            amendment_id="amd_001",
            client_id="c1",
            proposed_at=datetime(2026, 4, 25, tzinfo=UTC),
            proposed_by="advisor_jane",
            amendment_type=MandateAmendmentType.LIQUIDITY_CHANGE,
            diff={"old": {"liquidity_floor": 0.05}, "new": {"liquidity_floor": 0.10}},
            justification="Client expects family business sale proceeds in 18m.",
        )
        assert req.activation_status is MandateAmendmentStatus.PENDING_SIGNOFF


# ===========================================================================
# ModelPortfolioObject (Section 15.5.1)
# ===========================================================================


class TestModelPortfolioObject:
    def test_nine_bucket_sweep_all_validate(self):
        portfolios = make_all_bucket_portfolios()
        assert len(portfolios) == 9
        for bucket, mp in portfolios.items():
            assert mp.bucket is bucket
            # L1 sums to 1.0 implicitly via model validator — if construction succeeded, sum is OK
            l1_sum = sum(t.target for t in mp.l1_targets.values())
            assert abs(l1_sum - 1.0) < 1e-6

    def test_mod_lt_has_l2_and_l3(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        assert AssetClass.EQUITY in mp.l2_targets
        assert "equity.mutual_fund" in mp.l3_targets

    def test_l1_must_sum_to_one(self):
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValidationError, match="L1 targets must sum to 1.0"):
            ModelPortfolioObject(
                model_id="MP_BAD_001",
                bucket=Bucket.MOD_LT,
                version="0.1.0",
                firm_id="firm_test",
                created_at=eff,
                effective_at=eff,
                approved_by="cio",
                approval_rationale="bad sum test",
                l1_targets={
                    AssetClass.EQUITY: TargetWithTolerance(target=0.6, tolerance_band=0.05),
                    AssetClass.DEBT: TargetWithTolerance(target=0.5, tolerance_band=0.05),
                    # 0.6 + 0.5 = 1.1
                },
                construction=ConstructionContext(construction_pipeline_run_id="r"),
            )

    def test_l2_must_sum_per_asset_class(self):
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValidationError, match="L2 targets"):
            ModelPortfolioObject(
                model_id="MP_BAD_002",
                bucket=Bucket.MOD_LT,
                version="0.1.0",
                firm_id="firm_test",
                created_at=eff,
                effective_at=eff,
                approved_by="cio",
                approval_rationale="bad L2 sum test",
                l1_targets={
                    AssetClass.EQUITY: TargetWithTolerance(target=0.6, tolerance_band=0.05),
                    AssetClass.DEBT: TargetWithTolerance(target=0.4, tolerance_band=0.05),
                },
                l2_targets={
                    AssetClass.EQUITY: {
                        # 0.3 + 0.4 = 0.7, not 1.0 — should fail validation
                        VehicleType.DIRECT_EQUITY: TargetWithTolerance(
                            target=0.3, tolerance_band=0.1
                        ),
                        VehicleType.MUTUAL_FUND: TargetWithTolerance(
                            target=0.4, tolerance_band=0.1
                        ),
                    },
                },
                construction=ConstructionContext(construction_pipeline_run_id="r"),
            )

    def test_l3_must_sum_per_cell(self):
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValidationError, match="L3 targets"):
            ModelPortfolioObject(
                model_id="MP_BAD_003",
                bucket=Bucket.MOD_LT,
                version="0.1.0",
                firm_id="firm_test",
                created_at=eff,
                effective_at=eff,
                approved_by="cio",
                approval_rationale="bad L3 sum test",
                l1_targets={
                    AssetClass.EQUITY: TargetWithTolerance(target=0.6, tolerance_band=0.05),
                    AssetClass.DEBT: TargetWithTolerance(target=0.4, tolerance_band=0.05),
                },
                l3_targets={
                    "equity.mutual_fund": {
                        "large_cap": TargetWithTolerance(target=0.3, tolerance_band=0.15),
                        "mid_cap": TargetWithTolerance(target=0.3, tolerance_band=0.15),
                        # 0.6 != 1.0
                    },
                },
                construction=ConstructionContext(construction_pipeline_run_id="r"),
            )

    def test_target_with_tolerance_accepts_zero_target_with_band(self):
        # Section 5.3.2 example: SIF target=0, band=0.05 must validate.
        TargetWithTolerance(target=0.0, tolerance_band=0.05)

    def test_target_with_tolerance_accepts_full_target(self):
        # Defensive: target=1.0 with band > 0 should still validate (band is trigger threshold).
        TargetWithTolerance(target=1.0, tolerance_band=0.05)

    def test_default_tolerances_match_spec(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_MT)
        assert mp.l1_action_tolerance == 0.05
        assert mp.l2_informational_tolerance == 0.10
        assert mp.l3_informational_tolerance == 0.15

    def test_round_trip_json(self):
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        round_tripped = ModelPortfolioObject.model_validate_json(mp.model_dump_json())
        assert round_tripped == mp

    def test_construction_context_required(self):
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValidationError):
            ModelPortfolioObject(
                model_id="m",
                bucket=Bucket.MOD_LT,
                version="0.1.0",
                firm_id="f",
                created_at=eff,
                effective_at=eff,
                approved_by="cio",
                approval_rationale="r",
                l1_targets={
                    AssetClass.EQUITY: TargetWithTolerance(target=1.0, tolerance_band=0.05),
                },
                # construction is required
            )


# ===========================================================================
# L4 manifest (Section 15.5.2/3)
# ===========================================================================


class TestL4Manifest:
    def _entry(self, **overrides) -> FundUniverseL4Entry:
        base = dict(
            instrument_id="INF_001",
            instrument_name="Test Multi-Cap Fund",
            vehicle_type=VehicleType.MUTUAL_FUND,
            asset_class=AssetClass.EQUITY,
            sub_asset_class="multi_cap",
            amc_or_issuer="Test AMC",
            minimum_aum_tier=WealthTier.UP_TO_25K_SIP,
            fee_schedule=FeeSchedule(management_fee_bps=80, exit_load_pct=0.01),
            fee_effective_at=date(2026, 1, 1),
        )
        base.update(overrides)
        return FundUniverseL4Entry(**base)

    def test_minimal_entry_validates(self):
        e = self._entry()
        assert e.status is L4Status.ACTIVE

    def test_substitute_relation(self):
        e = self._entry(
            substitute_for="INF_OLD_001",
            substituted_at=date(2026, 4, 1),
            status=L4Status.ACTIVE,
        )
        assert e.substitute_for == "INF_OLD_001"

    def test_manifest_version_with_changes(self):
        eff = datetime(2026, 4, 1, tzinfo=UTC)
        version = L4ManifestVersion(
            manifest_version="2026Q2_v1",
            firm_id="firm_test",
            created_at=eff,
            effective_at=eff,
            approved_by="fund_research_lead",
            changes_from_prior=[
                L4ManifestChange(
                    operation=L4Operation.ADD,
                    instrument_id="INF_NEW_001",
                    rationale="New flexi-cap fund vetted by fund research.",
                ),
                L4ManifestChange(
                    operation=L4Operation.SUBSTITUTE,
                    instrument_id="INF_REP_001",
                    rationale="Manager departed; substituting with peer.",
                ),
            ],
            entries=[self._entry()],
        )
        assert len(version.changes_from_prior) == 2
        assert version.entries[0].instrument_id == "INF_001"

    def test_round_trip_json(self):
        e = self._entry()
        round_tripped = FundUniverseL4Entry.model_validate_json(e.model_dump_json())
        assert round_tripped == e


# ===========================================================================
# Holding + slice/look_through/cascade/conflict (Section 15.3.3/4)
# ===========================================================================


class TestHolding:
    def _holding(self, **overrides) -> Holding:
        base = dict(
            instrument_id="INF_001",
            instrument_name="Test Fund",
            units=1000.0,
            cost_basis=1_000_000.0,
            market_value=1_200_000.0,
            unrealised_gain_loss=200_000.0,
            amc_or_issuer="Test AMC",
            vehicle_type=VehicleType.MUTUAL_FUND,
            asset_class=AssetClass.EQUITY,
            sub_asset_class="multi_cap",
            acquisition_date=date(2024, 1, 15),
            as_of_date=date(2026, 4, 25),
        )
        base.update(overrides)
        return Holding(**base)

    def test_minimal_valid(self):
        h = self._holding()
        assert h.market_value == 1_200_000.0

    def test_unrealised_loss(self):
        # Negative gain_loss is permitted (drawdowns happen)
        h = self._holding(market_value=900_000.0, unrealised_gain_loss=-100_000.0)
        assert h.unrealised_gain_loss == -100_000.0

    def test_lock_in_expiry(self):
        h = self._holding(lock_in_expiry=date(2027, 1, 15))
        assert h.lock_in_expiry == date(2027, 1, 15)

    def test_flags_default_false(self):
        h = self._holding()
        assert h.tax_basis_stale is False
        assert h.look_through_unavailable is False


class TestSliceResponse:
    def test_minimal_slice(self):
        s = SliceResponse(
            holdings=[],
            total_value_inr=0.0,
        )
        assert s.holdings == []

    def test_with_total_units_by_amc(self):
        s = SliceResponse(
            holdings=[],
            total_value_inr=10_000_000.0,
            total_units_by_amc={"HDFC AMC": 5000.0, "Kotak AMC": 3000.0},
        )
        assert s.total_units_by_amc["HDFC AMC"] == 5000.0


class TestLookThroughResponse:
    def test_round_trip(self):
        lt = LookThroughResponse(
            parent_instrument_id="INF_MULTI_CAP",
            entries=[
                LookThroughEntry(
                    underlying_holding_id="HDFC_BANK",
                    underlying_name="HDFC Bank Ltd",
                    weight_in_portfolio=0.05,
                    weight_in_parent=0.10,
                ),
            ],
        )
        round_tripped = LookThroughResponse.model_validate_json(lt.model_dump_json())
        assert round_tripped == lt


class TestCascadeEvent:
    def test_minimal_cascade(self):
        c = CascadeEvent(
            event_type=CascadeEventType.MATURITY,
            expected_date=date(2027, 6, 1),
            expected_amount_inr=2_500_000.0,
            source_holding_id="FD_001",
            certainty_band=CascadeCertainty.CERTAIN,
        )
        assert c.event_type is CascadeEventType.MATURITY


class TestIngestionAndConflict:
    def test_ingestion_report_default_empty(self):
        r = IngestionReport()
        assert r.mapped_count == 0
        assert r.unmappable_list == []

    def test_conflict_report_with_resolution_paths(self):
        c = ConflictReport(
            conflict_type=ConflictType.MANDATE_VS_MODEL,
            dimension="asset_class.equity",
            mandate_value={"max_pct": 0.55},
            model_value={"target": 0.60, "tolerance_band": 0.05},
            resolution_paths=["amend_mandate", "clip_model", "out_of_bucket"],
        )
        assert c.conflict_type is ConflictType.MANDATE_VS_MODEL
        assert len(c.resolution_paths) == 3


# ===========================================================================
# SubAssetClassLimits (round-trip and ordering)
# ===========================================================================


class TestSubAssetClassLimits:
    def test_valid_ordering(self):
        SubAssetClassLimits(min_pct=0.05, target_pct=0.20, max_pct=0.40)

    def test_target_below_min_rejected(self):
        with pytest.raises(ValidationError):
            SubAssetClassLimits(min_pct=0.20, target_pct=0.10, max_pct=0.30)


# ===========================================================================
# ConcentrationLimits
# ===========================================================================


class TestConcentrationLimits:
    def test_valid(self):
        c = ConcentrationLimits(per_holding_max=0.10, per_manager_max=0.20, per_sector_max=0.30)
        assert c.per_sector_max == 0.30

    def test_above_one_rejected(self):
        with pytest.raises(ValidationError):
            ConcentrationLimits(per_holding_max=1.5, per_manager_max=0.2, per_sector_max=0.3)


# ===========================================================================
# LiquidityWindow
# ===========================================================================


class TestLiquidityWindow:
    def test_valid(self):
        w = LiquidityWindow(by_date=date(2030, 6, 1), amount_inr=20_000_000.0)
        assert w.amount_inr == 20_000_000.0
