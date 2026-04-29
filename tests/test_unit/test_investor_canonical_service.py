"""Pass 4 — investor canonical service + migration + registry + re-mapping.

Acceptance: Section 6.7 tests 1, 2, 4, 5 (test 3 is Pass 5+ when E6.Gate's
intermediary-conflict surface lands).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from artha.accountability.t1 import T1Repository
from artha.canonical.investor import (
    BeneficiaryMetadata,
    DataSource,
    InvestorContextProfile,
)
from artha.canonical.mandate import AssetClassLimits, MandateObject, SignoffEvidence, SignoffMethod
from artha.common.standards import T1EventType
from artha.common.types import (
    AssetClass,
    Bucket,
    CapacityTrajectory,
    MandateType,
    RiskProfile,
    TimeHorizon,
    VersionPins,
    WealthTier,
)
from artha.investor.canonical_service import (
    StructuralFlagSummary,
    assigned_bucket_for,
    cat_ii_aif_structurally_appropriate,
    check_conflicts_at_activation,
    detect_remapping,
    emit_remapping_event,
    structural_flag_summary,
)
from artha.investor.migration import (
    DEFAULTED_FROM_LEGACY,
    LEGACY_HORIZON_STRING_MAP,
    LEGACY_RISK_CATEGORY_MAP,
    map_legacy_horizon,
    map_legacy_risk_category,
    migrate_legacy_investor,
)
from artha.investor.schemas import RiskCategory
from artha.model_portfolio import ModelPortfolioRegistry
from tests.canonical_fixtures import (
    make_family_office_mandate,
    make_model_portfolio_for_bucket,
)

# ===========================================================================
# Fixtures and builders
# ===========================================================================


def _profile(
    *,
    risk_profile: RiskProfile = RiskProfile.MODERATE,
    time_horizon: TimeHorizon = TimeHorizon.LONG_TERM,
    capacity_trajectory: CapacityTrajectory = CapacityTrajectory.STABLE_OR_GROWING,
    intermediary_present: bool = False,
    beneficiary_can_operate: bool = True,
    beneficiary_metadata: BeneficiaryMetadata | None = None,
    client_id: str = "client_001",
    firm_id: str = "firm_test",
    updated_at: datetime | None = None,
    version: int = 1,
) -> InvestorContextProfile:
    """Construct a profile for testing. The `assigned_bucket` is computed automatically."""
    from artha.model_portfolio.buckets import derive_bucket

    ts = updated_at or datetime(2026, 1, 1, tzinfo=UTC)
    bucket = derive_bucket(risk_profile, time_horizon)
    return InvestorContextProfile(
        client_id=client_id,
        firm_id=firm_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=ts,
        version=version,
        risk_profile=risk_profile,
        time_horizon=time_horizon,
        wealth_tier=WealthTier.AUM_5CR_TO_10CR,
        assigned_bucket=bucket,
        capacity_trajectory=capacity_trajectory,
        intermediary_present=intermediary_present,
        beneficiary_can_operate_current_structure=beneficiary_can_operate,
        beneficiary_metadata=beneficiary_metadata,
        data_source=DataSource.FORM,
    )


# ===========================================================================
# Section 6.7 Test 1 — deterministic bucket mapping
# ===========================================================================


class TestDeterministicBucketMapping:
    def test_same_active_fields_same_bucket(self):
        # Section 6.7 Test 1: same active fields produce the same bucket id across runs
        p1 = _profile(risk_profile=RiskProfile.MODERATE, time_horizon=TimeHorizon.LONG_TERM)
        p2 = _profile(risk_profile=RiskProfile.MODERATE, time_horizon=TimeHorizon.LONG_TERM)
        assert assigned_bucket_for(p1) == assigned_bucket_for(p2) == Bucket.MOD_LT

    def test_assigned_bucket_for_returns_validator_pinned_value(self):
        p = _profile(risk_profile=RiskProfile.AGGRESSIVE, time_horizon=TimeHorizon.SHORT_TERM)
        assert assigned_bucket_for(p) is Bucket.AGG_ST

    def test_all_nine_combinations_produce_distinct_buckets(self):
        seen = set()
        for rp in RiskProfile:
            for th in TimeHorizon:
                p = _profile(risk_profile=rp, time_horizon=th)
                seen.add(assigned_bucket_for(p))
        assert len(seen) == 9


# ===========================================================================
# Section 6.7 Test 2 — capacity trajectory propagates as flag
# ===========================================================================


class TestCapacityTrajectoryFlag:
    def test_section_6_7_test_2_declining_moderate_blocks_cat_ii_aif(self):
        # Spec scenario: capacity_trajectory=declining_moderate triggers SOFT_BLOCK on Cat II AIF
        # Pass 4 contract: cat_ii_aif_structurally_appropriate returns False with the right reason
        p = _profile(capacity_trajectory=CapacityTrajectory.DECLINING_MODERATE)
        appropriate, reasons = cat_ii_aif_structurally_appropriate(p)
        assert appropriate is False
        assert "capacity_trajectory_declining" in reasons

    def test_declining_severe_also_blocks(self):
        p = _profile(capacity_trajectory=CapacityTrajectory.DECLINING_SEVERE)
        appropriate, reasons = cat_ii_aif_structurally_appropriate(p)
        assert appropriate is False
        assert "capacity_trajectory_declining" in reasons

    def test_stable_or_growing_does_not_block(self):
        p = _profile(capacity_trajectory=CapacityTrajectory.STABLE_OR_GROWING)
        appropriate, reasons = cat_ii_aif_structurally_appropriate(p)
        assert appropriate is True
        assert reasons == []

    def test_stable_with_known_decline_does_not_block_yet(self):
        # The "stable_with_known_decline_dates" tier is informational; the decline is
        # not yet active so Cat II AIF isn't blocked on this alone.
        p = _profile(capacity_trajectory=CapacityTrajectory.STABLE_WITH_KNOWN_DECLINE_DATES)
        appropriate, _reasons = cat_ii_aif_structurally_appropriate(p)
        assert appropriate is True

    def test_structural_flag_summary_marks_capacity_constrained(self):
        p = _profile(capacity_trajectory=CapacityTrajectory.DECLINING_MODERATE)
        summary = structural_flag_summary(p)
        assert isinstance(summary, StructuralFlagSummary)
        assert summary.capacity_constrained is True

    def test_structural_flag_summary_unconstrained_for_stable(self):
        p = _profile(capacity_trajectory=CapacityTrajectory.STABLE_OR_GROWING)
        summary = structural_flag_summary(p)
        assert summary.capacity_constrained is False


# ===========================================================================
# Section 6.7 Test 4 — beneficiary agency gap propagates
# ===========================================================================


class TestBeneficiaryAgencyGap:
    def test_section_6_7_test_4_beneficiary_gap_blocks_cat_ii_aif(self):
        # Spec: investor with beneficiary_can_operate=False triggers SOFT_BLOCK on Cat II AIF.
        # Pass 4 contract: structural appropriateness returns False with the right reason.
        p = _profile(
            beneficiary_can_operate=False,
            beneficiary_metadata=BeneficiaryMetadata(capacity_basis="cognitive_decline"),
        )
        appropriate, reasons = cat_ii_aif_structurally_appropriate(p)
        assert appropriate is False
        assert "beneficiary_agency_gap" in reasons

    def test_can_operate_does_not_block(self):
        # The other half of Section 6.7 Test 4: index MF is not blocked by this flag.
        # cat_ii_aif_structurally_appropriate returns True when the gap is absent.
        p = _profile(beneficiary_can_operate=True)
        appropriate, _ = cat_ii_aif_structurally_appropriate(p)
        assert appropriate is True

    def test_structural_flag_summary_marks_agency_gap(self):
        p = _profile(
            beneficiary_can_operate=False,
            beneficiary_metadata=BeneficiaryMetadata(capacity_basis="health"),
        )
        summary = structural_flag_summary(p)
        assert summary.beneficiary_agency_gap is True

    def test_combined_flags_aggregate_reasons(self):
        # Both capacity and beneficiary blocks present — both reasons surface
        p = _profile(
            capacity_trajectory=CapacityTrajectory.DECLINING_SEVERE,
            beneficiary_can_operate=False,
            beneficiary_metadata=BeneficiaryMetadata(capacity_basis="cognitive_decline"),
        )
        appropriate, reasons = cat_ii_aif_structurally_appropriate(p)
        assert appropriate is False
        assert set(reasons) == {"capacity_trajectory_declining", "beneficiary_agency_gap"}


class TestIntermediaryFlag:
    def test_intermediary_present_propagates_to_summary(self):
        from artha.canonical.investor import IntermediaryMetadata

        p = _profile(intermediary_present=True)
        # Need to also pass metadata to satisfy validator
        # Re-build with intermediary metadata
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        from artha.model_portfolio.buckets import derive_bucket

        p = InvestorContextProfile(
            client_id="c",
            firm_id="f",
            created_at=ts,
            updated_at=ts,
            risk_profile=RiskProfile.MODERATE,
            time_horizon=TimeHorizon.LONG_TERM,
            wealth_tier=WealthTier.AUM_5CR_TO_10CR,
            assigned_bucket=derive_bucket(RiskProfile.MODERATE, TimeHorizon.LONG_TERM),
            intermediary_present=True,
            intermediary_metadata=IntermediaryMetadata(
                relationship_type="ca", authority_scope="advises"
            ),
            data_source=DataSource.FORM,
        )
        summary = structural_flag_summary(p)
        assert summary.intermediary_conflict_present is True

    def test_intermediary_does_not_block_cat_ii_aif_in_pass_4(self):
        # Per Section 6.7, intermediary_present surfaces a "conflict indicator" on every E6
        # verdict — it doesn't itself block Cat II AIF (that's E6.Gate's call). Our Pass 4
        # contract surfaces the flag without blocking.
        from artha.canonical.investor import IntermediaryMetadata
        from artha.model_portfolio.buckets import derive_bucket

        ts = datetime(2026, 1, 1, tzinfo=UTC)
        p = InvestorContextProfile(
            client_id="c",
            firm_id="f",
            created_at=ts,
            updated_at=ts,
            risk_profile=RiskProfile.MODERATE,
            time_horizon=TimeHorizon.LONG_TERM,
            wealth_tier=WealthTier.AUM_5CR_TO_10CR,
            assigned_bucket=derive_bucket(RiskProfile.MODERATE, TimeHorizon.LONG_TERM),
            intermediary_present=True,
            intermediary_metadata=IntermediaryMetadata(
                relationship_type="distributor", authority_scope="co-decides"
            ),
            data_source=DataSource.FORM,
        )
        appropriate, _ = cat_ii_aif_structurally_appropriate(p)
        assert appropriate is True


# ===========================================================================
# Section 6.7 Test 5 — re-mapping detection + T1 emission
# ===========================================================================


class TestBucketRemapping:
    def test_no_remapping_when_active_fields_unchanged(self):
        old = _profile(
            risk_profile=RiskProfile.MODERATE,
            time_horizon=TimeHorizon.LONG_TERM,
            version=1,
        )
        new = _profile(
            risk_profile=RiskProfile.MODERATE,
            time_horizon=TimeHorizon.LONG_TERM,
            version=2,
            updated_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        assert detect_remapping(old, new) is None

    def test_no_remapping_when_only_capacity_trajectory_changes(self):
        # capacity_trajectory change is a profile update, not a re-mapping.
        old = _profile(capacity_trajectory=CapacityTrajectory.STABLE_OR_GROWING)
        new = _profile(
            capacity_trajectory=CapacityTrajectory.DECLINING_MODERATE,
            updated_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        assert detect_remapping(old, new) is None

    def test_remapping_when_risk_profile_changes(self):
        # Section 6.7 Test 5 scenario
        old = _profile(risk_profile=RiskProfile.MODERATE, time_horizon=TimeHorizon.LONG_TERM)
        new = _profile(
            risk_profile=RiskProfile.AGGRESSIVE,
            time_horizon=TimeHorizon.LONG_TERM,
            updated_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        remap = detect_remapping(old, new)
        assert remap is not None
        assert remap.from_bucket is Bucket.MOD_LT
        assert remap.to_bucket is Bucket.AGG_LT
        assert remap.from_risk_profile is RiskProfile.MODERATE
        assert remap.to_risk_profile is RiskProfile.AGGRESSIVE

    def test_remapping_when_time_horizon_changes(self):
        old = _profile(time_horizon=TimeHorizon.SHORT_TERM)
        new = _profile(
            time_horizon=TimeHorizon.LONG_TERM, updated_at=datetime(2026, 4, 1, tzinfo=UTC)
        )
        remap = detect_remapping(old, new)
        assert remap is not None
        assert remap.from_bucket is Bucket.MOD_ST
        assert remap.to_bucket is Bucket.MOD_LT

    def test_detect_remapping_rejects_different_clients(self):
        old = _profile(client_id="a")
        new = _profile(client_id="b")
        with pytest.raises(ValueError, match="same client"):
            detect_remapping(old, new)

    def test_remapping_triggered_by_default_is_system(self):
        old = _profile(risk_profile=RiskProfile.MODERATE)
        new = _profile(
            risk_profile=RiskProfile.AGGRESSIVE,
            updated_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        remap = detect_remapping(old, new)
        assert remap is not None
        assert remap.triggered_by == "system"

    def test_remapping_triggered_by_advisor(self):
        old = _profile(risk_profile=RiskProfile.MODERATE)
        new = _profile(
            risk_profile=RiskProfile.AGGRESSIVE,
            updated_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        remap = detect_remapping(old, new, triggered_by="advisor_jane")
        assert remap is not None
        assert remap.triggered_by == "advisor_jane"


@pytest.mark.asyncio
async def test_section_6_7_test_5_emit_remapping_event_to_t1(db_session):
    """Section 6.7 Test 5: profile update changes risk_profile → T1 BUCKET_REMAPPING event.

    The N0 alert that the spec text mentions is wired in Pass 6+; here we
    verify the structured T1 event lands with the right type, scope, and payload.
    """
    repo = T1Repository(db_session)
    old = _profile(risk_profile=RiskProfile.MODERATE, time_horizon=TimeHorizon.LONG_TERM)
    new = _profile(
        risk_profile=RiskProfile.AGGRESSIVE,
        time_horizon=TimeHorizon.LONG_TERM,
        updated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    remap = detect_remapping(old, new)
    assert remap is not None

    event = await emit_remapping_event(
        remap, repo, version_pins=VersionPins(model_portfolio_version="3.4.0")
    )

    assert event.event_type is T1EventType.BUCKET_REMAPPING
    assert event.client_id == "client_001"
    assert event.firm_id == "firm_test"
    assert event.payload["from_bucket"] == Bucket.MOD_LT.value
    assert event.payload["to_bucket"] == Bucket.AGG_LT.value
    assert event.version_pins.model_portfolio_version == "3.4.0"

    # Round-trip via T1: the event is queryable for the client
    events = await repo.list_for_client("client_001")
    assert len(events) == 1
    assert events[0].event_id == event.event_id


# ===========================================================================
# Mandate-vs-model conflict at activation (Section 5.10 / 6.6)
# ===========================================================================


class TestConflictsAtActivation:
    def test_no_conflict_when_envelope_fits(self):
        # Family office mandate equity range [30%, 70%]; MOD_LT model envelope [55%, 65%]
        p = _profile()
        m = make_family_office_mandate()
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        conflicts = check_conflicts_at_activation(p, m, mp)
        equity_conflicts = [c for c in conflicts if c.dimension == "asset_class.equity"]
        assert equity_conflicts == []

    def test_conflict_surfaces_with_three_paths(self):
        p = _profile()
        eff = datetime(2026, 1, 1, tzinfo=UTC)
        # Mandate caps equity at 55%; MOD_LT model envelope upper is 65%
        m = MandateObject(
            mandate_id="m_eq_55",
            client_id="client_001",
            firm_id="firm_test",
            created_at=eff,
            effective_at=eff,
            mandate_type=MandateType.INDIVIDUAL,
            asset_class_limits={
                AssetClass.EQUITY: AssetClassLimits(
                    min_pct=0.0, target_pct=0.5, max_pct=0.55
                ),
                AssetClass.DEBT: AssetClassLimits(
                    min_pct=0.0, target_pct=0.4, max_pct=1.0
                ),
            },
            liquidity_floor=0.05,
            signoff_method=SignoffMethod.E_SIGNATURE,
            signoff_evidence=SignoffEvidence(evidence_id="sig", captured_at=eff),
            signed_by="client_001",
        )
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        conflicts = check_conflicts_at_activation(p, m, mp)
        equity_conflicts = [c for c in conflicts if c.dimension == "asset_class.equity"]
        assert len(equity_conflicts) == 1
        assert set(equity_conflicts[0].resolution_paths) == {
            "amend_mandate", "clip_model", "out_of_bucket"
        }


# ===========================================================================
# ModelPortfolioRegistry (Pass 4 in-memory catalog)
# ===========================================================================


class TestModelPortfolioRegistry:
    def test_empty_registry_returns_none(self):
        reg = ModelPortfolioRegistry()
        assert reg.active_for("firm_test", Bucket.MOD_LT) is None

    def test_register_and_active_for_returns_only_match(self):
        reg = ModelPortfolioRegistry()
        mp = make_model_portfolio_for_bucket(Bucket.MOD_LT)
        reg.register(mp)
        assert reg.active_for("firm_test", Bucket.MOD_LT) == mp

    def test_active_for_returns_most_recent_when_multiple(self):
        reg = ModelPortfolioRegistry()
        v1 = make_model_portfolio_for_bucket(
            Bucket.MOD_LT, version="1.0.0", effective_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        v2 = make_model_portfolio_for_bucket(
            Bucket.MOD_LT, version="2.0.0", effective_at=datetime(2026, 4, 1, tzinfo=UTC)
        )
        reg.register(v1)
        reg.register(v2)
        active = reg.active_for("firm_test", Bucket.MOD_LT, as_of=datetime(2026, 6, 1, tzinfo=UTC))
        assert active is not None
        assert active.version == "2.0.0"

    def test_active_for_respects_as_of(self):
        reg = ModelPortfolioRegistry()
        v1 = make_model_portfolio_for_bucket(
            Bucket.MOD_LT, version="1.0.0", effective_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        v2 = make_model_portfolio_for_bucket(
            Bucket.MOD_LT, version="2.0.0", effective_at=datetime(2026, 4, 1, tzinfo=UTC)
        )
        reg.register(v1)
        reg.register(v2)
        # Looking up at 2026-02-15 should pick v1 (effective Jan 1) not v2 (effective Apr 1)
        active = reg.active_for("firm_test", Bucket.MOD_LT, as_of=datetime(2026, 2, 15, tzinfo=UTC))
        assert active is not None
        assert active.version == "1.0.0"

    def test_active_for_skips_superseded(self):
        # A version with superseded_at <= as_of is not active
        reg = ModelPortfolioRegistry()
        v1 = make_model_portfolio_for_bucket(
            Bucket.MOD_LT, version="1.0.0", effective_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        # Mark v1 superseded
        v1_superseded = v1.model_copy(update={"superseded_at": datetime(2026, 4, 1, tzinfo=UTC)})
        reg.register(v1_superseded)
        active = reg.active_for("firm_test", Bucket.MOD_LT, as_of=datetime(2026, 4, 15, tzinfo=UTC))
        assert active is None

    def test_active_for_isolates_by_firm_and_bucket(self):
        reg = ModelPortfolioRegistry()
        mp_mod_lt = make_model_portfolio_for_bucket(Bucket.MOD_LT, firm_id="firm_a")
        mp_agg_lt = make_model_portfolio_for_bucket(Bucket.AGG_LT, firm_id="firm_a")
        reg.register(mp_mod_lt)
        reg.register(mp_agg_lt)
        # Different firm
        assert reg.active_for("firm_b", Bucket.MOD_LT) is None
        # Different bucket
        active_agg = reg.active_for("firm_a", Bucket.AGG_LT)
        assert active_agg is not None
        assert active_agg.bucket is Bucket.AGG_LT

    def test_all_versions_returns_insertion_order(self):
        reg = ModelPortfolioRegistry()
        v1 = make_model_portfolio_for_bucket(Bucket.MOD_LT, version="1.0.0")
        v2 = make_model_portfolio_for_bucket(Bucket.MOD_LT, version="2.0.0")
        reg.register(v1)
        reg.register(v2)
        versions = reg.all_versions("firm_test", Bucket.MOD_LT)
        assert [v.version for v in versions] == ["1.0.0", "2.0.0"]


# ===========================================================================
# Migration (legacy → canonical)
# ===========================================================================


class TestLegacyMigration:
    def test_risk_category_mapping_covers_five_legacy_values(self):
        # Every legacy RiskCategory must map to a canonical RiskProfile
        for legacy in RiskCategory:
            assert legacy in LEGACY_RISK_CATEGORY_MAP
            assert isinstance(LEGACY_RISK_CATEGORY_MAP[legacy], RiskProfile)

    def test_horizon_string_mapping(self):
        assert map_legacy_horizon("short") is TimeHorizon.SHORT_TERM
        assert map_legacy_horizon("medium") is TimeHorizon.MEDIUM_TERM
        assert map_legacy_horizon("long") is TimeHorizon.LONG_TERM
        assert map_legacy_horizon("LONG") is TimeHorizon.LONG_TERM  # case-insensitive

    def test_horizon_string_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown legacy horizon"):
            map_legacy_horizon("very_long_term")

    def test_moderately_aggressive_maps_to_aggressive(self):
        assert (
            map_legacy_risk_category(RiskCategory.MODERATELY_AGGRESSIVE) is RiskProfile.AGGRESSIVE
        )

    def test_moderately_conservative_maps_to_conservative(self):
        assert (
            map_legacy_risk_category(RiskCategory.MODERATELY_CONSERVATIVE)
            is RiskProfile.CONSERVATIVE
        )

    def test_migrate_full_round_trip(self):
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        canonical = migrate_legacy_investor(
            client_id="client_legacy_001",
            firm_id="firm_legacy",
            legacy_risk_category=RiskCategory.MODERATE,
            legacy_horizon="long",
            created_at=ts,
            updated_at=ts,
        )
        assert canonical.risk_profile is RiskProfile.MODERATE
        assert canonical.time_horizon is TimeHorizon.LONG_TERM
        assert canonical.assigned_bucket is Bucket.MOD_LT
        # Defaulted fields
        assert canonical.wealth_tier is WealthTier.UP_TO_25K_SIP
        assert canonical.capacity_trajectory is CapacityTrajectory.STABLE_OR_GROWING
        assert canonical.intermediary_present is False
        assert canonical.beneficiary_can_operate_current_structure is True
        # All defaulted fields appear in data_gaps_flagged
        assert set(canonical.data_gaps_flagged) == set(DEFAULTED_FROM_LEGACY)
        # Confidence is moderate (not 1.0) reflecting the unconfirmed defaults
        assert canonical.confidence < 1.0
        # Dormant layer inactive per Section 6.5
        assert canonical.dormant_layer.active is False

    def test_migrate_with_explicit_overrides(self):
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        canonical = migrate_legacy_investor(
            client_id="client_002",
            firm_id="firm_test",
            legacy_risk_category=RiskCategory.AGGRESSIVE,
            legacy_horizon="long",
            created_at=ts,
            updated_at=ts,
            wealth_tier=WealthTier.AUM_BEYOND_100CR,
            capacity_trajectory=CapacityTrajectory.STABLE_WITH_KNOWN_DECLINE_DATES,
        )
        assert canonical.wealth_tier is WealthTier.AUM_BEYOND_100CR
        assert canonical.capacity_trajectory is CapacityTrajectory.STABLE_WITH_KNOWN_DECLINE_DATES
        assert canonical.assigned_bucket is Bucket.AGG_LT

    def test_horizon_strings_map_table_complete(self):
        # Exactly the three canonical horizons covered
        assert set(LEGACY_HORIZON_STRING_MAP.values()) == set(TimeHorizon)
