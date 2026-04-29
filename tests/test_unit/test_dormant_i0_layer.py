"""Pass 7 — dormant I0 layer schema scaffolding (§6.5, §6.9-6.12, §16.2).

The dormant layer ships typed but inactive. Tests verify:
  * The 9-pattern enums (L1/L2/L3) cover the spec list
  * A profile defaults to `active=False` with empty pattern collections
  * All sub-types validate (interaction flags, worldview, resistance, blind
    spots, advisory framing)
  * The MVP guard `assert_field_is_active` (Pass 1) still rejects dormant
    field references
"""

from __future__ import annotations

from datetime import UTC, datetime

from artha.canonical import (
    DataSource,
    DormantAdvisoryFraming,
    DormantBlindSpot,
    DormantI0Layer,
    DormantLifeSituationPattern,
    DormantPatternInteractionFlag,
    DormantResistanceFlag,
    DormantStructuralComplicationPattern,
    DormantWealthOriginPattern,
    DormantWorldviewIndicator,
    InvestorContextProfile,
)
from artha.common.standards import assert_field_is_active
from artha.common.types import (
    RiskProfile,
    TimeHorizon,
    WealthTier,
)
from artha.model_portfolio.buckets import derive_bucket


def _profile_with_dormant_active(active: bool = False) -> InvestorContextProfile:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    return InvestorContextProfile(
        client_id="c1",
        firm_id="firm_test",
        created_at=ts,
        updated_at=ts,
        risk_profile=RiskProfile.MODERATE,
        time_horizon=TimeHorizon.LONG_TERM,
        wealth_tier=WealthTier.AUM_5CR_TO_10CR,
        assigned_bucket=derive_bucket(RiskProfile.MODERATE, TimeHorizon.LONG_TERM),
        data_source=DataSource.FORM,
        dormant_layer=DormantI0Layer(active=active),
    )


# ===========================================================================
# Pattern enums cover spec
# ===========================================================================


class TestDormantPatternEnums:
    def test_nine_l1_wealth_origin_patterns(self):
        assert len(DormantWealthOriginPattern) == 9
        assert DormantWealthOriginPattern.L1_01_FIRST_GEN_BUSINESS_BUILDER.value.startswith("L1-01")

    def test_nine_l2_life_situation_patterns(self):
        assert len(DormantLifeSituationPattern) == 9
        assert DormantLifeSituationPattern.L2_07_RECENT_WIDOWHOOD.value == "L2-07_recent_widowhood"

    def test_nine_l3_structural_complication_patterns(self):
        assert len(DormantStructuralComplicationPattern) == 9
        assert (
            DormantStructuralComplicationPattern.L3_03_PERSONAL_GUARANTEE_BURDEN.value
            == "L3-03_personal_guarantee_burden"
        )


# ===========================================================================
# Profile default state — all empty, active=False
# ===========================================================================


class TestProfileDefaults:
    def test_default_dormant_layer_inactive(self):
        profile = _profile_with_dormant_active()
        assert profile.dormant_layer.active is False

    def test_default_pattern_collections_empty(self):
        profile = _profile_with_dormant_active()
        assert profile.dormant_layer.matched_l1_patterns == []
        assert profile.dormant_layer.matched_l2_patterns == []
        assert profile.dormant_layer.matched_l3_patterns == []
        assert profile.dormant_layer.pattern_interactions == []
        assert profile.dormant_layer.worldview_indicators == []
        assert profile.dormant_layer.resistance_flags == []
        assert profile.dormant_layer.blind_spots == []
        assert profile.dormant_layer.advisory_framings == []

    def test_default_metadata_dicts_empty(self):
        profile = _profile_with_dormant_active()
        assert profile.dormant_layer.capacity_trajectory_detail == {}
        assert profile.dormant_layer.intermediary_metadata_detail == {}
        assert profile.dormant_layer.beneficiary_metadata_detail == {}


# ===========================================================================
# Sub-type validation
# ===========================================================================


class TestDormantSubtypes:
    def test_pattern_interaction_validates(self):
        flag = DormantPatternInteractionFlag(
            interaction_id="L1-01+L3-01+L3-05",
            triggering_patterns=[
                "L1-01_first_gen_business_builder",
                "L3-01_material_debt",
                "L3-05_cross_border_complexity",
            ],
            interaction_effect="HIGH cascade risk; AIF illiquidity contraindicated.",
            downstream_consumers=["e6_gate", "s1"],
        )
        assert flag.interaction_id == "L1-01+L3-01+L3-05"

    def test_worldview_indicator_validates(self):
        ind = DormantWorldviewIndicator(
            pattern_key="L1-01",
            indicators=["earned through effort and sacrifice", "tangible assets are safe"],
        )
        assert "earned through effort and sacrifice" in ind.indicators

    def test_resistance_flag_validates(self):
        rf = DormantResistanceFlag(
            pattern_key="L1-01",
            will_resist=["discretionary_pms", "structured_credit"],
        )
        assert "discretionary_pms" in rf.will_resist

    def test_blind_spot_validates(self):
        bs = DormantBlindSpot(
            pattern_key="L1-01",
            blind_spots=["underestimates_business_concentration_risk"],
        )
        assert len(bs.blind_spots) == 1

    def test_advisory_framing_validates(self):
        af = DormantAdvisoryFraming(
            pattern_key="L1-01",
            lead_with="protection",
            never_lead_with="alpha-and-returns",
            growth_edges=["frame_as_protecting_what_you_built"],
        )
        assert af.lead_with == "protection"


# ===========================================================================
# Pattern matches can be populated when activated
# ===========================================================================


class TestActivationPathway:
    def test_dormant_layer_can_carry_l1_patterns_when_active(self):
        layer = DormantI0Layer(
            active=True,
            matched_l1_patterns=[
                DormantWealthOriginPattern.L1_01_FIRST_GEN_BUSINESS_BUILDER,
            ],
            matched_l3_patterns=[
                DormantStructuralComplicationPattern.L3_01_MATERIAL_DEBT,
                DormantStructuralComplicationPattern.L3_03_PERSONAL_GUARANTEE_BURDEN,
            ],
        )
        assert layer.active is True
        assert len(layer.matched_l1_patterns) == 1
        assert len(layer.matched_l3_patterns) == 2

    def test_dormant_layer_round_trips_via_json(self):
        layer = DormantI0Layer(
            active=True,
            matched_l1_patterns=[DormantWealthOriginPattern.L1_02_SALARIED_CORPORATE_EXECUTIVE],
            worldview_indicators=[
                DormantWorldviewIndicator(
                    pattern_key="L1-02", indicators=["disciplined_saver"]
                ),
            ],
        )
        round_tripped = DormantI0Layer.model_validate_json(layer.model_dump_json())
        assert round_tripped == layer


# ===========================================================================
# MVP active-field guard still works (Pass 1)
# ===========================================================================


class TestActiveFieldGuard:
    def test_dormant_field_reference_raises(self):
        # Per Section 3.9, agent prompts must NOT read dormant fields in MVP.
        # The Pass 1 guard catches this.
        import pytest

        with pytest.raises(ValueError, match="dormant"):
            assert_field_is_active("matched_l1_patterns")

        with pytest.raises(ValueError, match="dormant"):
            assert_field_is_active("worldview_indicators")

    def test_active_field_passes_guard(self):
        # Active layer fields don't raise
        assert_field_is_active("risk_profile")
        assert_field_is_active("capacity_trajectory")
        assert_field_is_active("intermediary_present")
