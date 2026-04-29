"""Pass 10 — E6 PMS / AIF / SIF / MF acceptance tests.

§11.7.9 acceptance:
  Test 1 — sub-agent routing fires the correct sub-agent per vehicle.
  Test 2 — E6 verdict schema round-trips.
  Test 3 — fee normalisation produces net-of-costs and net-of-all returns.
  Test 4 — liquidity manager surfaces unfunded commitment + floor compliance.
  Test 5 — synthesis aggregates gate + sub-agents + shared sub-agents.
  Test 6 — counterfactual delta computed when proposed gross + model return are present.
  Test 8 — gate HARD_BLOCK on capacity_severely_declining + AIF (override path).
  Test 9 — gate SOFT_BLOCK on beneficiary_agency_gap + AIF.
  Test 10 — gate EVALUATE_WITH_COUNTERFACTUAL on intermediary_present + complex.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.case import (
    CaseChannel,
    CaseObject,
    CaseStatus,
    DominantLens,
    LensMetadata,
    ProposedAction,
)
from artha.canonical.evidence_verdict import (
    E6Verdict,
    FundRiskScore,
    FundRiskScores,
)
from artha.canonical.holding import (
    CascadeCertainty,
    CascadeEvent,
    CascadeEventType,
    Holding,
)
from artha.canonical.investor import DataSource, InvestorContextProfile
from artha.canonical.l4_manifest import FeeSchedule
from artha.common.types import (
    AssetClass,
    Bucket,
    CapacityTrajectory,
    CaseIntent,
    Driver,
    DriverDirection,
    DriverSeverity,
    GateResult,
    RiskLevel,
    RiskProfile,
    RunMode,
    TimeHorizon,
    VehicleType,
    WealthTier,
)
from artha.evidence.canonical_e6 import (
    PRODUCT_SUBAGENT_REGISTRY,
    AifCat2SubAgent,
    E6Gate,
    E6Orchestrator,
    E6OrchestratorInputs,
    MutualFundSubAgent,
    PmsSubAgent,
    compute_cascade_assessment,
    compute_liquidity_manager_output,
    compute_normalised_returns,
)
from artha.llm.providers.mock import MockProvider
from artha.portfolio_analysis.canonical_metrics import HoldingCommitment

# ===========================================================================
# Helpers
# ===========================================================================


def _profile(
    *,
    bucket: Bucket = Bucket.MOD_LT,
    capacity_trajectory: CapacityTrajectory = CapacityTrajectory.STABLE_OR_GROWING,
    intermediary_present: bool = False,
    beneficiary_can_operate: bool = True,
    wealth_tier: WealthTier = WealthTier.AUM_5CR_TO_10CR,
    risk_profile: RiskProfile = RiskProfile.MODERATE,
    time_horizon: TimeHorizon = TimeHorizon.LONG_TERM,
) -> InvestorContextProfile:
    now = datetime(2026, 4, 25, tzinfo=UTC)
    return InvestorContextProfile(
        client_id="c1",
        firm_id="firm_test",
        created_at=now,
        updated_at=now,
        risk_profile=risk_profile,
        time_horizon=time_horizon,
        wealth_tier=wealth_tier,
        assigned_bucket=bucket,
        capacity_trajectory=capacity_trajectory,
        intermediary_present=intermediary_present,
        beneficiary_can_operate_current_structure=beneficiary_can_operate,
        data_source=DataSource.FORM,
    )


def _envelope(
    *,
    target_agent: str = "e6",
    run_mode: RunMode = RunMode.CASE,
    proposed_structure: VehicleType | None = None,
    profile: InvestorContextProfile | None = None,
) -> AgentActivationEnvelope:
    proposed: ProposedAction | None = None
    if proposed_structure is not None:
        proposed = ProposedAction(
            target_product=f"{proposed_structure.value}_test",
            ticket_size_inr=10_000_000.0,
            structure=proposed_structure.value,
        )
    case = CaseObject(
        case_id="case_e6_001",
        client_id="c1",
        firm_id="firm_test",
        advisor_id="advisor_jane",
        created_at=datetime(2026, 4, 25, tzinfo=UTC),
        intent=CaseIntent.CASE,
        intent_confidence=0.9,
        dominant_lens=DominantLens.PROPOSAL,
        lens_metadata=LensMetadata(lenses_fired=[DominantLens.PROPOSAL]),
        current_status=CaseStatus.IN_PROGRESS,
        channel=CaseChannel.C0,
        proposed_action=proposed,
    )
    return AgentActivationEnvelope(
        case=case,
        target_agent=target_agent,
        run_mode=run_mode,
        investor_profile=profile or _profile(),
    )


def _holding(
    iid: str,
    *,
    vehicle: VehicleType = VehicleType.MUTUAL_FUND,
    market_value: float = 1_000_000.0,
    asset_class: AssetClass = AssetClass.EQUITY,
) -> Holding:
    return Holding(
        instrument_id=iid,
        instrument_name=f"{iid}_name",
        units=100.0,
        cost_basis=market_value * 0.9,
        market_value=market_value,
        unrealised_gain_loss=market_value * 0.1,
        amc_or_issuer="Test",
        vehicle_type=vehicle,
        asset_class=asset_class,
        sub_asset_class="multi_cap",
        acquisition_date=date(2024, 1, 15),
        as_of_date=date(2026, 4, 25),
    )


def _sub_agent_mock(
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    confidence: float = 0.8,
    flags: list[str] | None = None,
) -> MockProvider:
    """Mock LLM that returns canned output for product sub-agents."""
    mock = MockProvider()
    mock.set_structured_response(
        "Signals:",
        {
            "risk_level_value": risk_level.value,
            "confidence": confidence,
            "drivers": [
                Driver(
                    factor="manager_quality",
                    direction=DriverDirection.NEGATIVE,
                    severity=DriverSeverity.MEDIUM,
                    detail="Manager tenure short.",
                ).model_dump(mode="json"),
            ],
            "flags": flags or [],
            "reasoning_trace": "Canned product-lane evaluation.",
        },
    )
    return mock


def _orchestrator_mock(
    *,
    sub_risk: RiskLevel = RiskLevel.MEDIUM,
    synth_risk: RiskLevel = RiskLevel.MEDIUM,
    synth_confidence: float = 0.8,
    synth_flags: list[str] | None = None,
    fund_risk_scores: dict | None = None,
) -> MockProvider:
    """Single MockProvider used by both sub-agents and synthesis."""
    mock = MockProvider()

    sub_agent_payload = {
        "risk_level_value": sub_risk.value,
        "confidence": 0.78,
        "drivers": [
            Driver(
                factor="manager_quality",
                direction=DriverDirection.NEGATIVE,
                severity=DriverSeverity.MEDIUM,
                detail="Manager tenure short.",
            ).model_dump(mode="json"),
        ],
        "flags": [],
        "reasoning_trace": "Sub-agent canned evaluation.",
    }

    synthesis_payload = {
        "risk_level_value": synth_risk.value,
        "confidence": synth_confidence,
        "drivers": [
            Driver(
                factor="aggregate_lane_risk",
                direction=DriverDirection.NEGATIVE,
                severity=DriverSeverity.MEDIUM,
                detail="Synthesis-level aggregate.",
            ).model_dump(mode="json"),
        ],
        "flags": synth_flags or [],
        "reasoning_trace": "Synthesis canned aggregation.",
        "fund_risk_scores": fund_risk_scores
        or FundRiskScores(
            manager_quality=FundRiskScore.SOUND,
            strategy_consistency=FundRiskScore.SOUND,
            fee_reasonableness=FundRiskScore.SOUND,
            operational_risk=FundRiskScore.SOUND,
            liquidity_risk=FundRiskScore.SOUND,
        ).model_dump(mode="json"),
        "suitability_conditions": [],
        "tax_year_projection": [],
    }

    # Both prompts include "Signals:"; the synthesis prompt also includes
    # "RecommendationSynthesis" in its system prompt while sub-agents include
    # the product name. Use a more specific token to distinguish.
    mock.set_structured_response("RecommendationSynthesis", synthesis_payload)
    mock.set_structured_response("Signals:", sub_agent_payload)
    return mock


# ===========================================================================
# §11.7.1 Gate tests — Tests 8, 9, 10
# ===========================================================================


class TestE6Gate:
    def test_test_8_severe_decline_aif_hard_block(self):
        """§11.7.9 Test 8 — capacity_severely_declining + AIF → HARD_BLOCK."""
        gate = E6Gate()
        profile = _profile(capacity_trajectory=CapacityTrajectory.DECLINING_SEVERE)
        decision = gate.evaluate(profile, VehicleType.AIF_CAT_2)
        assert decision.result is GateResult.HARD_BLOCK
        assert "capacity_trajectory_severely_declining" in decision.reasons
        assert decision.override_path == "senior_escalation"

    def test_test_9_beneficiary_gap_aif_soft_block(self):
        """§11.7.9 Test 9 — beneficiary cannot operate + AIF → SOFT_BLOCK."""
        gate = E6Gate()
        profile = _profile(beneficiary_can_operate=False)
        decision = gate.evaluate(profile, VehicleType.AIF_CAT_2)
        assert decision.result is GateResult.SOFT_BLOCK
        assert "beneficiary_agency_gap" in decision.reasons
        assert decision.override_path == "documented_advisor_rationale"

    def test_test_10_intermediary_complex_evaluate_with_counterfactual(self):
        """§11.7.9 Test 10 — intermediary_present + complex → EVALUATE_WITH_COUNTERFACTUAL."""
        gate = E6Gate()
        profile = _profile(intermediary_present=True)
        decision = gate.evaluate(profile, VehicleType.AIF_CAT_2)
        assert decision.result is GateResult.EVALUATE_WITH_COUNTERFACTUAL
        assert "intermediary_present" in decision.reasons

    def test_moderate_decline_complex_soft_block(self):
        gate = E6Gate()
        profile = _profile(capacity_trajectory=CapacityTrajectory.DECLINING_MODERATE)
        decision = gate.evaluate(profile, VehicleType.SIF)
        assert decision.result is GateResult.SOFT_BLOCK
        assert "capacity_trajectory_declining" in decision.reasons

    def test_clean_proceeds(self):
        gate = E6Gate()
        decision = gate.evaluate(_profile(), VehicleType.MUTUAL_FUND)
        assert decision.result is GateResult.PROCEED
        assert decision.reasons == []

    def test_severe_decline_mf_does_not_hard_block(self):
        # Hard-block rule only applies to AIF vehicles
        gate = E6Gate()
        profile = _profile(capacity_trajectory=CapacityTrajectory.DECLINING_SEVERE)
        decision = gate.evaluate(profile, VehicleType.MUTUAL_FUND)
        # MF is not in _COMPLEX_VEHICLES so no soft-block either
        assert decision.result is GateResult.PROCEED


# ===========================================================================
# Shared sub-agents (deterministic)
# ===========================================================================


class TestE6Shared:
    def test_test_3_fee_normalisation_basic(self):
        """§11.7.9 Test 3 — net-of-costs and net-of-all returns."""
        result = compute_normalised_returns(
            gross_return=0.15,
            fee_schedule=FeeSchedule(
                management_fee_bps=200,
                performance_fee_bps=2000,  # 20%
                structure_costs_bps=50,
            ),
            tax_rate=0.20,
            counterfactual_model_portfolio_return=0.10,
        )
        # Fee drag = (200 + 2000 + 50) / 10_000 = 0.225
        assert result.gross_return == pytest.approx(0.15)
        assert result.net_of_costs_return == pytest.approx(0.15 - 0.225)
        assert result.net_of_costs_and_taxes_return == pytest.approx(
            (0.15 - 0.225) * (1 - 0.20)
        )
        assert result.counterfactual_delta == pytest.approx(
            result.net_of_costs_and_taxes_return - 0.10
        )

    def test_test_6_counterfactual_delta_present(self):
        """§11.7.9 Test 6 — counterfactual delta computed when both inputs present."""
        result = compute_normalised_returns(
            gross_return=0.18,
            fee_schedule=FeeSchedule(
                management_fee_bps=150, performance_fee_bps=0, structure_costs_bps=25
            ),
            tax_rate=0.0,
            counterfactual_model_portfolio_return=0.12,
        )
        assert result.counterfactual_delta is not None
        assert result.counterfactual_delta == pytest.approx(
            result.net_of_costs_and_taxes_return - 0.12
        )

    def test_no_fee_schedule_returns_only_gross(self):
        result = compute_normalised_returns(gross_return=0.10)
        assert result.gross_return == pytest.approx(0.10)
        assert result.net_of_costs_return is None
        assert result.net_of_costs_and_taxes_return is None
        assert result.counterfactual_delta is None

    def test_cascade_engine_aggregates_events(self):
        events = [
            CascadeEvent(
                event_type=CascadeEventType.DISTRIBUTION,
                expected_date=date(2026, 9, 1),
                expected_amount_inr=500_000.0,
                source_holding_id="AIF1",
                certainty_band=CascadeCertainty.LIKELY,
            ),
            CascadeEvent(
                event_type=CascadeEventType.CAPITAL_CALL,
                expected_date=date(2026, 12, 1),
                expected_amount_inr=2_000_000.0,
                source_holding_id="AIF2",
                certainty_band=CascadeCertainty.CERTAIN,
            ),
            CascadeEvent(
                event_type=CascadeEventType.MATURITY,
                expected_date=date(2027, 3, 1),
                expected_amount_inr=1_500_000.0,
                source_holding_id="DEBT1",
                certainty_band=CascadeCertainty.CERTAIN,
            ),
        ]
        assessment = compute_cascade_assessment(events)
        # Distribution + maturity fold into expected_distribution
        assert assessment.expected_distribution_inr == pytest.approx(2_000_000.0)
        assert assessment.expected_capital_calls_inr == pytest.approx(2_000_000.0)
        assert len(assessment.cash_flow_schedule) == 3

    def test_test_4_liquidity_manager_surfaces_unfunded(self):
        """§11.7.9 Test 4 — unfunded commitments + floor compliance."""
        commitments = {
            "AIF1": HoldingCommitment(committed_inr=10_000_000.0, called_inr=4_000_000.0),
            "AIF2": HoldingCommitment(committed_inr=5_000_000.0, called_inr=5_000_000.0),
        }
        result = compute_liquidity_manager_output(
            holding_commitments=commitments,
            most_liquid_bucket_share=0.15,
            mandate_liquidity_floor=0.10,
            proposed_uncalled_inr=8_000_000.0,
        )
        # AIF1 uncalled = 6M, AIF2 uncalled = 0, proposed = 8M → 14M
        assert result.cumulative_unfunded_commitment_inr == pytest.approx(14_000_000.0)
        assert result.liquidity_floor_check_result is True
        assert result.most_liquid_bucket_share == pytest.approx(0.15)

    def test_liquidity_manager_floor_breach(self):
        result = compute_liquidity_manager_output(
            most_liquid_bucket_share=0.05,
            mandate_liquidity_floor=0.10,
        )
        assert result.liquidity_floor_check_result is False


# ===========================================================================
# Product sub-agents — Test 1 (routing)
# ===========================================================================


class TestProductSubAgentsRouting:
    @pytest.mark.asyncio
    async def test_test_1_pms_subagent_fires_on_pms_holding(self):
        agent = PmsSubAgent(_sub_agent_mock())
        holdings = [_holding("PMS1", vehicle=VehicleType.PMS)]
        verdict = await agent.evaluate(_envelope(), holdings=holdings)
        assert verdict.agent_id == "e6.pms_subagent"
        assert verdict.risk_level is RiskLevel.MEDIUM

    @pytest.mark.asyncio
    async def test_pms_subagent_not_applicable_without_pms(self):
        # Should not call LLM
        class _Strict:
            name = "strict"

            async def complete(self, request):
                raise AssertionError("LLM should not be called")

            async def complete_structured(self, request, output_type):
                raise AssertionError("LLM should not be called")

        agent = PmsSubAgent(_Strict())
        holdings = [_holding("MF1", vehicle=VehicleType.MUTUAL_FUND)]
        verdict = await agent.evaluate(_envelope(), holdings=holdings)
        assert verdict.risk_level is RiskLevel.NOT_APPLICABLE

    @pytest.mark.asyncio
    async def test_aif_cat2_subagent_fires_on_proposal(self):
        agent = AifCat2SubAgent(_sub_agent_mock())
        env = _envelope(proposed_structure=VehicleType.AIF_CAT_2)
        verdict = await agent.evaluate(env, holdings=[])
        assert verdict.agent_id == "e6.aif_cat2_subagent"
        assert verdict.risk_level is RiskLevel.MEDIUM

    @pytest.mark.asyncio
    async def test_mf_subagent_routing(self):
        agent = MutualFundSubAgent(_sub_agent_mock())
        holdings = [_holding("MF1", vehicle=VehicleType.MUTUAL_FUND)]
        verdict = await agent.evaluate(_envelope(), holdings=holdings)
        assert verdict.agent_id == "e6.mf_subagent"

    def test_registry_covers_all_product_vehicles(self):
        expected = {
            VehicleType.PMS,
            VehicleType.AIF_CAT_1,
            VehicleType.AIF_CAT_2,
            VehicleType.AIF_CAT_3,
            VehicleType.SIF,
            VehicleType.MUTUAL_FUND,
        }
        assert set(PRODUCT_SUBAGENT_REGISTRY.keys()) == expected


# ===========================================================================
# Orchestrator — Tests 2 + 5
# ===========================================================================


class TestE6Orchestrator:
    @pytest.mark.asyncio
    async def test_test_2_verdict_schema_round_trips(self):
        """§11.7.9 Test 2 — E6Verdict round-trips via JSON."""
        provider = _orchestrator_mock()
        orch = E6Orchestrator(provider)
        env = _envelope(proposed_structure=VehicleType.AIF_CAT_2)
        inputs = E6OrchestratorInputs(
            holdings=[],
            proposed_gross_return=0.18,
            proposed_fee_schedule=FeeSchedule(
                management_fee_bps=200, performance_fee_bps=2000, structure_costs_bps=50
            ),
            proposed_tax_rate=0.20,
            counterfactual_model_portfolio_return=0.12,
        )
        verdict = await orch.evaluate(env, inputs=inputs)
        # Round-trip
        round_tripped = E6Verdict.model_validate_json(verdict.model_dump_json())
        assert round_tripped == verdict

    @pytest.mark.asyncio
    async def test_test_5_synthesis_aggregates(self):
        """§11.7.9 Test 5 — synthesis combines gate + sub-agents + shared sub-agents."""
        provider = _orchestrator_mock(synth_risk=RiskLevel.MEDIUM)
        orch = E6Orchestrator(provider)
        env = _envelope(proposed_structure=VehicleType.AIF_CAT_2)
        inputs = E6OrchestratorInputs(
            holdings=[_holding("PMS1", vehicle=VehicleType.PMS)],
            holding_commitments={
                "AIF_OLD": HoldingCommitment(
                    committed_inr=5_000_000.0, called_inr=2_000_000.0
                ),
            },
            proposed_gross_return=0.15,
            proposed_fee_schedule=FeeSchedule(
                management_fee_bps=200, performance_fee_bps=2000
            ),
            counterfactual_model_portfolio_return=0.10,
            cash_flow_schedule=[
                CascadeEvent(
                    event_type=CascadeEventType.CAPITAL_CALL,
                    expected_date=date(2026, 9, 1),
                    expected_amount_inr=2_000_000.0,
                    source_holding_id="AIF1",
                    certainty_band=CascadeCertainty.LIKELY,
                )
            ],
            most_liquid_bucket_share=0.15,
            mandate_liquidity_floor=0.10,
            proposed_uncalled_inr=8_000_000.0,
        )

        verdict = await orch.evaluate(env, inputs=inputs)

        assert verdict.gate_result is GateResult.PROCEED
        # Two product sub-agents (PMS holding + AIF_2 proposal)
        sub_ids = [v.agent_id for v in verdict.sub_agent_verdicts]
        assert "e6.pms_subagent" in sub_ids
        assert "e6.aif_cat2_subagent" in sub_ids
        # Normalised returns populated
        assert verdict.normalised_returns is not None
        assert verdict.normalised_returns.counterfactual_delta is not None
        # Cascade aggregated
        assert verdict.cascade_assessment is not None
        assert verdict.cascade_assessment.expected_capital_calls_inr == pytest.approx(
            2_000_000.0
        )
        # Liquidity computed
        assert verdict.liquidity_manager_output is not None
        assert verdict.liquidity_manager_output.cumulative_unfunded_commitment_inr == (
            pytest.approx(11_000_000.0)
        )
        # Default fund-risk scores filled
        assert verdict.fund_risk_scores is not None
        assert verdict.fund_risk_scores.manager_quality is FundRiskScore.SOUND

    @pytest.mark.asyncio
    async def test_hard_block_short_circuits_subagents(self):
        """§11.7.1 — HARD_BLOCK skips product sub-agents."""
        provider = _orchestrator_mock(synth_flags=["gate_risk"])
        orch = E6Orchestrator(provider)
        profile = _profile(capacity_trajectory=CapacityTrajectory.DECLINING_SEVERE)
        env = _envelope(profile=profile, proposed_structure=VehicleType.AIF_CAT_2)
        inputs = E6OrchestratorInputs(
            holdings=[_holding("PMS1", vehicle=VehicleType.PMS)],
        )

        verdict = await orch.evaluate(env, inputs=inputs)
        assert verdict.gate_result is GateResult.HARD_BLOCK
        assert "gate_risk" in verdict.flags
        # Sub-agents skipped
        assert verdict.sub_agent_verdicts == []

    @pytest.mark.asyncio
    async def test_soft_block_runs_subagents_but_flags(self):
        provider = _orchestrator_mock()
        orch = E6Orchestrator(provider)
        profile = _profile(beneficiary_can_operate=False)
        env = _envelope(profile=profile, proposed_structure=VehicleType.AIF_CAT_2)

        verdict = await orch.evaluate(env, inputs=E6OrchestratorInputs())
        assert verdict.gate_result is GateResult.SOFT_BLOCK
        assert "gate_risk" in verdict.flags

    @pytest.mark.asyncio
    async def test_liquidity_breach_surfaces_flag(self):
        provider = _orchestrator_mock()
        orch = E6Orchestrator(provider)
        env = _envelope(proposed_structure=VehicleType.AIF_CAT_2)
        inputs = E6OrchestratorInputs(
            most_liquid_bucket_share=0.05,
            mandate_liquidity_floor=0.10,
        )
        verdict = await orch.evaluate(env, inputs=inputs)
        assert "liquidity_floor_proximity" in verdict.flags

    @pytest.mark.asyncio
    async def test_synthesis_failure_produces_fallback(self):
        """Synthesis LLM failure → HIGH-risk fallback per §11.7.7."""

        class _FailingSynth:
            name = "failing_synth"

            async def complete(self, request):
                raise RuntimeError("not used")

            async def complete_structured(self, request, output_type):
                raise RuntimeError("synthesis unavailable")

        # Use sub-agent-only mock (works) plus override synthesis to fail
        provider = _orchestrator_mock()

        # Replace the synthesis with a failing provider
        from artha.evidence.canonical_e6.orchestrator import RecommendationSynthesis

        failing_synth = RecommendationSynthesis(_FailingSynth())
        orch = E6Orchestrator(provider, synthesis=failing_synth)

        env = _envelope(proposed_structure=VehicleType.AIF_CAT_2)
        verdict = await orch.evaluate(env, inputs=E6OrchestratorInputs())

        assert verdict.risk_level is RiskLevel.HIGH
        assert verdict.confidence == 0.0
        assert "sub_agent_unavailable" in verdict.flags

    @pytest.mark.asyncio
    async def test_run_mode_propagates_to_verdict(self):
        provider = _orchestrator_mock()
        orch = E6Orchestrator(provider)
        env = _envelope(
            proposed_structure=VehicleType.AIF_CAT_2,
            run_mode=RunMode.CONSTRUCTION,
        )
        verdict = await orch.evaluate(env, inputs=E6OrchestratorInputs())
        assert verdict.run_mode is RunMode.CONSTRUCTION

    @pytest.mark.asyncio
    async def test_routing_picks_only_in_scope_subagents(self):
        """Only PMS + MF run when only those products are present."""
        provider = _orchestrator_mock()
        orch = E6Orchestrator(provider)
        env = _envelope()  # no proposed_action
        inputs = E6OrchestratorInputs(
            holdings=[
                _holding("PMS1", vehicle=VehicleType.PMS),
                _holding("MF1", vehicle=VehicleType.MUTUAL_FUND),
                _holding("DE1", vehicle=VehicleType.DIRECT_EQUITY),
            ],
        )
        verdict = await orch.evaluate(env, inputs=inputs)
        sub_ids = sorted(v.agent_id for v in verdict.sub_agent_verdicts)
        assert sub_ids == ["e6.mf_subagent", "e6.pms_subagent"]

    @pytest.mark.asyncio
    async def test_no_profile_raises(self):
        provider = _orchestrator_mock()
        orch = E6Orchestrator(provider)
        # Build envelope without investor_profile
        case = CaseObject(
            case_id="case_002",
            client_id="c1",
            firm_id="firm_test",
            advisor_id="advisor_jane",
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
            intent=CaseIntent.CASE,
            intent_confidence=0.9,
            dominant_lens=DominantLens.PROPOSAL,
            lens_metadata=LensMetadata(lenses_fired=[DominantLens.PROPOSAL]),
            current_status=CaseStatus.IN_PROGRESS,
            channel=CaseChannel.C0,
        )
        env = AgentActivationEnvelope(
            case=case, target_agent="e6", investor_profile=None
        )
        with pytest.raises(ValueError):
            await orch.evaluate(env)

    @pytest.mark.asyncio
    async def test_determinism_within_version(self):
        """Identical inputs → identical input_hash + sub-verdicts."""
        provider = _orchestrator_mock()
        orch = E6Orchestrator(provider)
        env = _envelope(proposed_structure=VehicleType.AIF_CAT_2)
        inputs = E6OrchestratorInputs(
            holdings=[_holding("PMS1", vehicle=VehicleType.PMS)],
        )
        v1 = await orch.evaluate(env, inputs=inputs)
        v2 = await orch.evaluate(env, inputs=inputs)
        assert v1.input_hash == v2.input_hash
        # sub-agent verdicts also stable
        ids1 = [v.input_hash for v in v1.sub_agent_verdicts]
        ids2 = [v.input_hash for v in v2.sub_agent_verdicts]
        assert ids1 == ids2
