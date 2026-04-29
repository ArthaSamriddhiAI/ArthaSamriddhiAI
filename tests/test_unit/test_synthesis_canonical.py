"""Pass 11 — S1 + IC1 + M0.Stitcher acceptance tests.

§12.2.8 (S1):
  Test 1 — determinism within version
  Test 2 — conflict surfacing on E1=HIGH vs E2=LOW
  Test 3 — counterfactual framing in mode-1 case
  Test 4 — mode_dominance flag honours dominant_lens
  Test 5 — escalation_recommended on high-materiality + uncertainty
  Test 6 — citation discipline (≥3 agent verdicts)

§12.3.9 (IC1):
  Test 1 — MaterialityGate fires on Cat II AIF above threshold; skips on routine MF
  Test 2 — Devil's Advocate produces dissent in fired cases
  Test 3 — Minutes capture all sub-role contributions
  Test 4 — Recommendation enum is one of (proceed, modify, do_not_proceed, defer)
  Test 5 — escalation_to_human always True
  Test 6 — Determinism within version

§8.6.8 (M0.Stitcher):
  Test 1 — Faithful composition: every claim maps to structured component
  Test 2 — Length compliance under budget
  Test 3 — Lens-aware framing (portfolio vs proposal)
  Test 4 — All concerns surfaced when IC1 dissent + A1 + governance present
  Test 5 — Replay correctness from structured components
"""

from __future__ import annotations

from datetime import UTC, datetime

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
from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.investor import DataSource, InvestorContextProfile
from artha.canonical.synthesis import (
    AmplificationAssessment,
    CommitteePosition,
    ConflictArea,
    ConsensusBlock,
    CounterfactualFraming,
    IC1SubRole,
    RenderedArtifact,
    S1Synthesis,
)
from artha.common.types import (
    Bucket,
    CapacityTrajectory,
    CaseIntent,
    Driver,
    DriverDirection,
    DriverSeverity,
    InputsUsedManifest,
    MaterialityGateResult,
    Recommendation,
    RiskLevel,
    RiskProfile,
    RunMode,
    TimeHorizon,
    VehicleType,
    WealthTier,
)
from artha.llm.providers.mock import MockProvider
from artha.m0.stitcher import M0Stitcher
from artha.synthesis import (
    IC1Agent,
    IC1MaterialityGate,
    MaterialityInputs,
    S1SynthesisAgent,
)
from artha.synthesis.canonical_ic1 import (
    DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _profile() -> InvestorContextProfile:
    now = datetime(2026, 4, 25, tzinfo=UTC)
    return InvestorContextProfile(
        client_id="c1",
        firm_id="firm_test",
        created_at=now,
        updated_at=now,
        risk_profile=RiskProfile.MODERATE,
        time_horizon=TimeHorizon.LONG_TERM,
        wealth_tier=WealthTier.AUM_5CR_TO_10CR,
        assigned_bucket=Bucket.MOD_LT,
        capacity_trajectory=CapacityTrajectory.STABLE_OR_GROWING,
        intermediary_present=False,
        beneficiary_can_operate_current_structure=True,
        data_source=DataSource.FORM,
    )


def _envelope(
    *,
    dominant_lens: DominantLens = DominantLens.PROPOSAL,
    proposed_structure: VehicleType | None = None,
    ticket_size_inr: float | None = None,
    run_mode: RunMode = RunMode.CASE,
) -> AgentActivationEnvelope:
    proposed: ProposedAction | None = None
    if proposed_structure is not None:
        proposed = ProposedAction(
            target_product=f"{proposed_structure.value}_test",
            ticket_size_inr=ticket_size_inr,
            structure=proposed_structure.value,
        )
    case = CaseObject(
        case_id="case_p11_001",
        client_id="c1",
        firm_id="firm_test",
        advisor_id="advisor_jane",
        created_at=datetime(2026, 4, 25, tzinfo=UTC),
        intent=CaseIntent.CASE,
        intent_confidence=0.9,
        dominant_lens=dominant_lens,
        lens_metadata=LensMetadata(lenses_fired=[dominant_lens]),
        current_status=CaseStatus.IN_PROGRESS,
        channel=CaseChannel.C0,
        proposed_action=proposed,
    )
    return AgentActivationEnvelope(
        case=case,
        target_agent="s1",
        run_mode=run_mode,
        investor_profile=_profile(),
    )


def _verdict(
    agent_id: str,
    risk: RiskLevel,
    *,
    confidence: float = 0.8,
    flags: list[str] | None = None,
    drivers: list[Driver] | None = None,
) -> StandardEvidenceVerdict:
    return StandardEvidenceVerdict(
        agent_id=agent_id,
        case_id="case_p11_001",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        risk_level=risk,
        confidence=confidence,
        drivers=drivers
        or [
            Driver(
                factor="placeholder",
                direction=DriverDirection.NEUTRAL,
                severity=DriverSeverity.LOW,
                detail="placeholder driver",
            )
        ],
        flags=flags or [],
        reasoning_trace=f"{agent_id} canned trace.",
        inputs_used_manifest=InputsUsedManifest(),
        input_hash=f"hash_{agent_id}",
    )


def _s1_mock(
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    confidence: float = 0.7,
    conflict_areas: list[ConflictArea] | None = None,
    uncertainty_flag: bool = False,
    uncertainty_reasons: list[str] | None = None,
    amplification: AmplificationAssessment | None = None,
    counterfactual: CounterfactualFraming | None = None,
    escalation_recommended: bool = False,
    escalation_reason: str | None = None,
    citations: list[str] | None = None,
    narrative: str = (
        "S1 narrative cites financial_risk, industry_analyst, and macro_policy."
    ),
) -> MockProvider:
    mock = MockProvider()
    mock.set_structured_response(
        "Signals:",
        {
            "risk_level_value": risk_level.value,
            "confidence": confidence,
            "agreement_areas": ["risk_band_alignment"],
            "conflict_areas": [c.model_dump(mode="json") for c in (conflict_areas or [])],
            "uncertainty_flag": uncertainty_flag,
            "uncertainty_reasons": uncertainty_reasons or [],
            "amplification": (
                amplification.model_dump(mode="json") if amplification else None
            ),
            "counterfactual_framing": (
                counterfactual.model_dump(mode="json") if counterfactual else None
            ),
            "escalation_recommended": escalation_recommended,
            "escalation_reason": escalation_reason,
            "synthesis_narrative": narrative,
            "reasoning_trace": "Reviewed E1, E2, E3 and concluded.",
            "citations": citations or ["financial_risk", "industry_analyst", "macro_policy"],
        },
    )
    return mock


def _ic1_mock(
    *,
    chair_recommendation: str = "proceed",
    devils_advocate_dissent: str = "Concentration risk understated; IC could revisit.",
    devils_advocate_recommendation: str = "modify",
    risk_assessor_recommendation: str = "proceed",
    minutes_recommendation: str = "proceed",
    minutes_conditions: list[str] | None = None,
) -> MockProvider:
    mock = MockProvider()
    # IC1 sub-roles each have a distinct system prompt; Mock matches on
    # "Sub-role: <role_value>" string.
    mock.set_structured_response(
        "Sub-role: chair",
        {
            "contribution": "Chair frames the deliberation around bucket-relative concentration.",
            "citations": ["financial_risk"],
            "dissent_point": None,
            "proposed_recommendation": chair_recommendation,
            "proposed_conditions": [],
        },
    )
    mock.set_structured_response(
        "Sub-role: devils_advocate",
        {
            "contribution": "Devil's advocate argues dissent.",
            "citations": ["financial_risk"],
            "dissent_point": devils_advocate_dissent,
            "proposed_recommendation": devils_advocate_recommendation,
            "proposed_conditions": [],
        },
    )
    mock.set_structured_response(
        "Sub-role: risk_assessor",
        {
            "contribution": "Risk assessor aggregates risk perspectives.",
            "citations": ["financial_risk", "macro_policy"],
            "dissent_point": None,
            "proposed_recommendation": risk_assessor_recommendation,
            "proposed_conditions": [],
        },
    )
    mock.set_structured_response(
        "Sub-role: minutes_recorder",
        {
            "contribution": "Minutes capture the converged committee position.",
            "citations": ["financial_risk", "industry_analyst", "macro_policy"],
            "dissent_point": None,
            "proposed_recommendation": minutes_recommendation,
            "proposed_conditions": minutes_conditions or [],
        },
    )
    return mock


def _stitcher_mock(narrative: str = None) -> MockProvider:
    mock = MockProvider()
    text = narrative or (
        "Case header. Recommendation: proceed. Supporting evidence cites financial_risk, "
        "industry_analyst, macro_policy. No major concerns. Decision options follow. "
        "Audit trail link present."
    )
    mock.set_structured_response(
        "Structured components keys:",
        {
            "natural_language_text": text,
            "section_lengths": {
                "case_header": 12,
                "recommendation": 18,
                "supporting_evidence": 24,
                "concerns": 8,
                "decision_options": 12,
                "audit_trail": 10,
            },
        },
    )
    return mock


def _build_s1(
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    consensus_confidence: float = 0.75,
    escalation_recommended: bool = False,
    uncertainty_flag: bool = False,
    counterfactual: CounterfactualFraming | None = None,
    conflict_areas: list[ConflictArea] | None = None,
    amplification: AmplificationAssessment | None = None,
    citations: list[str] | None = None,
) -> S1Synthesis:
    return S1Synthesis(
        case_id="case_p11_001",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        consensus=ConsensusBlock(risk_level=risk_level, confidence=consensus_confidence),
        agreement_areas=["risk_band_alignment"],
        conflict_areas=conflict_areas or [],
        uncertainty_flag=uncertainty_flag,
        uncertainty_reasons=[],
        amplification=amplification,
        mode_dominance=DominantLens.PROPOSAL,
        counterfactual_framing=counterfactual,
        escalation_recommended=escalation_recommended,
        escalation_reason=None,
        synthesis_narrative="Canned S1 narrative.",
        reasoning_trace="Reviewed agents.",
        citations=citations or ["financial_risk", "industry_analyst", "macro_policy"],
        input_hash="canned_s1_hash",
    )


# ===========================================================================
# §12.2.8 — S1 acceptance tests
# ===========================================================================


class TestS1Acceptance:
    @pytest.mark.asyncio
    async def test_test_1_determinism(self):
        """§12.2.8 Test 1 — same input bundle → same input_hash."""
        agent = S1SynthesisAgent(_s1_mock())
        verdicts = [
            _verdict("financial_risk", RiskLevel.MEDIUM),
            _verdict("industry_analyst", RiskLevel.MEDIUM),
            _verdict("macro_policy", RiskLevel.MEDIUM),
        ]
        v1 = await agent.evaluate(_envelope(), verdicts=verdicts)
        v2 = await agent.evaluate(_envelope(), verdicts=verdicts)
        assert v1.input_hash == v2.input_hash
        assert v1.consensus.risk_level == v2.consensus.risk_level

    @pytest.mark.asyncio
    async def test_test_2_conflict_surfacing(self):
        """§12.2.8 Test 2 — E1=HIGH vs E2=LOW produces conflict_areas."""
        agent = S1SynthesisAgent(_s1_mock())
        verdicts = [
            _verdict("financial_risk", RiskLevel.HIGH),
            _verdict("industry_analyst", RiskLevel.LOW),
            _verdict("macro_policy", RiskLevel.MEDIUM),
        ]
        synthesis = await agent.evaluate(_envelope(), verdicts=verdicts)
        # Deterministic conflict_areas surfaces the disagreement
        assert len(synthesis.conflict_areas) >= 1
        names = {c.dimension for c in synthesis.conflict_areas}
        assert "overall_risk" in names

    @pytest.mark.asyncio
    async def test_test_3_counterfactual_framing(self):
        """§12.2.8 Test 3 — model-default cited when supplied."""
        cf = CounterfactualFraming(
            model_default_recommendation="Equity 60 / Debt 30 / Gold 10",
            proposal_relative_to_default="degrades",
            bucket="MOD_LT",
        )
        agent = S1SynthesisAgent(_s1_mock(counterfactual=cf))
        verdicts = [_verdict("financial_risk", RiskLevel.MEDIUM)]
        synthesis = await agent.evaluate(
            _envelope(),
            verdicts=verdicts,
            model_default_recommendation="Equity 60 / Debt 30 / Gold 10",
        )
        assert synthesis.counterfactual_framing is not None
        assert (
            "Equity 60"
            in synthesis.counterfactual_framing.model_default_recommendation
        )

    @pytest.mark.asyncio
    async def test_test_4_mode_dominance(self):
        """§12.2.8 Test 4 — mode_dominance honours dominant_lens."""
        agent = S1SynthesisAgent(_s1_mock())
        verdicts = [_verdict("financial_risk", RiskLevel.MEDIUM)]
        synth_portfolio = await agent.evaluate(
            _envelope(dominant_lens=DominantLens.PORTFOLIO), verdicts=verdicts
        )
        synth_proposal = await agent.evaluate(
            _envelope(dominant_lens=DominantLens.PROPOSAL), verdicts=verdicts
        )
        assert synth_portfolio.mode_dominance is DominantLens.PORTFOLIO
        assert synth_proposal.mode_dominance is DominantLens.PROPOSAL

    @pytest.mark.asyncio
    async def test_test_5_escalation_when_high_uncertain(self):
        """§12.2.8 Test 5 — high-risk verdict + uncertainty_flag forces escalation."""
        # LLM omits escalation; deterministic layer adds it.
        agent = S1SynthesisAgent(
            _s1_mock(
                uncertainty_flag=True,
                uncertainty_reasons=["data_stale"],
                escalation_recommended=False,
            )
        )
        verdicts = [
            _verdict("financial_risk", RiskLevel.HIGH),
            _verdict("industry_analyst", RiskLevel.MEDIUM),
        ]
        synthesis = await agent.evaluate(_envelope(), verdicts=verdicts)
        assert synthesis.escalation_recommended is True
        assert synthesis.escalation_reason is not None

    @pytest.mark.asyncio
    async def test_test_6_citation_discipline(self):
        """§12.2.8 Test 6 — at least 3 agent verdicts cited."""
        agent = S1SynthesisAgent(
            _s1_mock(citations=["financial_risk"])  # LLM under-cites
        )
        verdicts = [
            _verdict("financial_risk", RiskLevel.MEDIUM),
            _verdict("industry_analyst", RiskLevel.MEDIUM),
            _verdict("macro_policy", RiskLevel.LOW),
        ]
        synthesis = await agent.evaluate(_envelope(), verdicts=verdicts)
        # Deterministic top-up forces ≥ MIN_CITATIONS_FOR_FULL_NARRATIVE
        assert len(synthesis.citations) >= 3

    @pytest.mark.asyncio
    async def test_round_trip_schema(self):
        agent = S1SynthesisAgent(_s1_mock())
        verdicts = [_verdict("financial_risk", RiskLevel.MEDIUM)]
        synthesis = await agent.evaluate(_envelope(), verdicts=verdicts)
        round_tripped = S1Synthesis.model_validate_json(synthesis.model_dump_json())
        assert round_tripped == synthesis


# ===========================================================================
# §12.3.9 — IC1 acceptance tests
# ===========================================================================


class TestIC1MaterialityGate:
    def test_test_1a_fires_on_aif_above_threshold(self):
        """§12.3.9 Test 1 — Cat II AIF above ticket threshold convenes IC1."""
        gate = IC1MaterialityGate()
        decision = gate.evaluate(
            run_mode=RunMode.CASE,
            inputs=MaterialityInputs(
                ticket_size_inr=DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR + 1,
                proposed_vehicle_type=VehicleType.AIF_CAT_2,
            ),
        )
        assert decision.fired is MaterialityGateResult.CONVENE
        assert "ticket_size_above_threshold" in decision.signals
        assert "complex_vehicle_proposal" in decision.signals

    def test_test_1b_skips_routine_mf(self):
        """§12.3.9 Test 1 — routine MF rebalance below threshold skips IC1."""
        gate = IC1MaterialityGate()
        decision = gate.evaluate(
            run_mode=RunMode.CASE,
            inputs=MaterialityInputs(
                ticket_size_inr=100_000.0,
                proposed_vehicle_type=VehicleType.MUTUAL_FUND,
            ),
        )
        assert decision.fired is MaterialityGateResult.SKIP
        assert decision.signals == []

    def test_construction_pipeline_force_convene(self):
        gate = IC1MaterialityGate()
        decision = gate.evaluate(
            run_mode=RunMode.CONSTRUCTION,
            inputs=MaterialityInputs(),
        )
        assert decision.fired is MaterialityGateResult.CONVENE
        assert "construction_pipeline" in decision.signals

    def test_advisor_request_fires_gate(self):
        gate = IC1MaterialityGate()
        decision = gate.evaluate(
            run_mode=RunMode.CASE,
            inputs=MaterialityInputs(advisor_requested=True),
        )
        assert decision.fired is MaterialityGateResult.CONVENE
        assert "advisor_requested" in decision.signals

    def test_s1_amplification_fires_gate(self):
        gate = IC1MaterialityGate()
        decision = gate.evaluate(
            run_mode=RunMode.CASE,
            inputs=MaterialityInputs(s1_amplification_present=True),
        )
        assert decision.fired is MaterialityGateResult.CONVENE
        assert "s1_amplification_present" in decision.signals


class TestIC1Acceptance:
    @pytest.mark.asyncio
    async def test_test_2_devils_advocate_dissent(self):
        """§12.3.9 Test 2 — devil's advocate produces dissent in fired cases."""
        provider = _ic1_mock()
        ic1 = IC1Agent(provider)
        s1 = _build_s1()
        env = _envelope(
            proposed_structure=VehicleType.AIF_CAT_2,
            ticket_size_inr=DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR * 2,
        )
        deliberation = await ic1.evaluate(
            env,
            s1_synthesis=s1,
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
        )
        assert deliberation.materiality_gate_result.fired is MaterialityGateResult.CONVENE
        # Devil's advocate dissent surfaced
        assert any(
            d.source_role is IC1SubRole.DEVILS_ADVOCATE
            for d in deliberation.dissent_recorded
        )

    @pytest.mark.asyncio
    async def test_test_3_minutes_capture_all_subroles(self):
        """§12.3.9 Test 3 — minutes capture all four sub-role contributions."""
        provider = _ic1_mock()
        ic1 = IC1Agent(provider)
        s1 = _build_s1()
        env = _envelope(
            proposed_structure=VehicleType.AIF_CAT_2,
            ticket_size_inr=DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR * 2,
        )
        deliberation = await ic1.evaluate(
            env, s1_synthesis=s1, verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)]
        )
        roles = {c.sub_role for c in deliberation.minutes}
        assert roles == {
            IC1SubRole.CHAIR,
            IC1SubRole.DEVILS_ADVOCATE,
            IC1SubRole.RISK_ASSESSOR,
            IC1SubRole.MINUTES_RECORDER,
        }

    @pytest.mark.asyncio
    async def test_test_4_recommendation_enum(self):
        """§12.3.9 Test 4 — recommendation is a canonical Recommendation value."""
        provider = _ic1_mock(
            minutes_recommendation="modify",
            minutes_conditions=["liquidity_buffer_increase"],
        )
        ic1 = IC1Agent(provider)
        s1 = _build_s1()
        env = _envelope(
            proposed_structure=VehicleType.AIF_CAT_2,
            ticket_size_inr=DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR * 2,
        )
        deliberation = await ic1.evaluate(
            env, s1_synthesis=s1, verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)]
        )
        assert deliberation.recommendation is Recommendation.MODIFY
        assert "liquidity_buffer_increase" in deliberation.conditions

    @pytest.mark.asyncio
    async def test_test_5_escalation_to_human_always_true(self):
        """§12.3.9 Test 5 — escalation_to_human=True always."""
        provider = _ic1_mock()
        ic1 = IC1Agent(provider)
        # Even in a SKIP case the field is True
        s1 = _build_s1()
        env_skip = _envelope(proposed_structure=VehicleType.MUTUAL_FUND)
        deliberation_skip = await ic1.evaluate(
            env_skip,
            s1_synthesis=s1,
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
        )
        assert deliberation_skip.escalation_to_human is True
        assert deliberation_skip.materiality_gate_result.fired is MaterialityGateResult.SKIP

        # And in a CONVENE case
        env_fire = _envelope(
            proposed_structure=VehicleType.AIF_CAT_2,
            ticket_size_inr=DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR * 2,
        )
        deliberation_fire = await ic1.evaluate(
            env_fire,
            s1_synthesis=s1,
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
        )
        assert deliberation_fire.escalation_to_human is True

    @pytest.mark.asyncio
    async def test_test_6_determinism(self):
        """§12.3.9 Test 6 — deterministic input_hash within version."""
        provider = _ic1_mock()
        ic1 = IC1Agent(provider)
        s1 = _build_s1()
        env = _envelope(
            proposed_structure=VehicleType.AIF_CAT_2,
            ticket_size_inr=DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR * 2,
        )
        d1 = await ic1.evaluate(
            env, s1_synthesis=s1, verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)]
        )
        d2 = await ic1.evaluate(
            env, s1_synthesis=s1, verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)]
        )
        assert d1.input_hash == d2.input_hash

    @pytest.mark.asyncio
    async def test_split_position_when_subroles_disagree(self):
        provider = _ic1_mock(
            chair_recommendation="proceed",
            devils_advocate_recommendation="do_not_proceed",
            risk_assessor_recommendation="proceed",
            minutes_recommendation="proceed",
        )
        ic1 = IC1Agent(provider)
        s1 = _build_s1()
        env = _envelope(
            proposed_structure=VehicleType.AIF_CAT_2,
            ticket_size_inr=DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR * 2,
        )
        deliberation = await ic1.evaluate(
            env,
            s1_synthesis=s1,
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
        )
        assert deliberation.committee_position is CommitteePosition.SPLIT


# ===========================================================================
# §8.6.8 — M0.Stitcher acceptance tests
# ===========================================================================


class TestStitcherAcceptance:
    @pytest.mark.asyncio
    async def test_test_1_faithful_composition(self):
        """§8.6.8 Test 1 — every claim in narrative maps to a structured component."""
        stitcher = M0Stitcher(_stitcher_mock())
        env = _envelope()
        s1 = _build_s1(citations=["financial_risk", "industry_analyst", "macro_policy"])
        verdicts = [
            _verdict("financial_risk", RiskLevel.MEDIUM),
            _verdict("industry_analyst", RiskLevel.MEDIUM),
            _verdict("macro_policy", RiskLevel.LOW),
        ]
        artifact = await stitcher.render(
            env.case, s1_synthesis=s1, verdicts=verdicts
        )

        # Six required sections present
        for section in (
            "case_header",
            "recommendation",
            "supporting_evidence",
            "concerns",
            "decision_options",
            "audit_trail",
        ):
            assert section in artifact.structured_components

        # Narrative mentions cited agents
        for citation in s1.citations[:3]:
            assert citation in artifact.natural_language_text

    @pytest.mark.asyncio
    async def test_test_2_length_compliance_under_budget(self):
        """§8.6.8 Test 2 — short narrative stays under budget; over-budget triggers compression."""
        # Short narrative — under budget
        short = "Short artifact narrative for compliance test, under budget."
        stitcher = M0Stitcher(_stitcher_mock(narrative=short), length_budget_tokens=1200)
        artifact = await stitcher.render(
            _envelope().case,
            s1_synthesis=_build_s1(),
            verdicts=[_verdict("financial_risk", RiskLevel.LOW)],
        )
        assert artifact.length_statistics["__total__"] <= 1200

        # Over budget — compression decision recorded
        long_narrative = "x " * 3000  # ~6000 chars → ≈1500 tokens
        stitcher_over = M0Stitcher(
            _stitcher_mock(narrative=long_narrative), length_budget_tokens=200
        )
        artifact_over = await stitcher_over.render(
            _envelope().case,
            s1_synthesis=_build_s1(),
            verdicts=[_verdict("financial_risk", RiskLevel.LOW)],
        )
        # Compression decision present; final under budget
        compressions = [
            d for d in artifact_over.rendering_decisions if d.decision == "condensed"
        ]
        assert compressions
        assert artifact_over.length_statistics["__total__"] <= 200

    @pytest.mark.asyncio
    async def test_test_3_lens_aware_framing(self):
        """§8.6.8 Test 3 — proposal-dominant vs portfolio-dominant produce different framing.

        We verify the deterministic prompt-instruction layer changes between
        the two lens cases, which is what drives the LLM's framing.
        """
        stitcher = M0Stitcher(_stitcher_mock())
        s1 = _build_s1()
        verdicts = [_verdict("financial_risk", RiskLevel.MEDIUM)]

        # Verify the deterministic structured component for dominant_lens differs
        artifact_portfolio = await stitcher.render(
            _envelope(dominant_lens=DominantLens.PORTFOLIO).case,
            s1_synthesis=s1,
            verdicts=verdicts,
        )
        artifact_proposal = await stitcher.render(
            _envelope(dominant_lens=DominantLens.PROPOSAL).case,
            s1_synthesis=s1,
            verdicts=verdicts,
        )
        assert (
            artifact_portfolio.structured_components["case_header"]["dominant_lens"]
            == "portfolio"
        )
        assert (
            artifact_proposal.structured_components["case_header"]["dominant_lens"]
            == "proposal"
        )

    @pytest.mark.asyncio
    async def test_test_4_all_concerns_surfaced(self):
        """§8.6.8 Test 4 — IC1 dissent + A1 + governance escalations all appear."""
        stitcher = M0Stitcher(_stitcher_mock())
        env = _envelope(
            proposed_structure=VehicleType.AIF_CAT_2,
            ticket_size_inr=DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR * 2,
        )
        ic1_provider = _ic1_mock()
        ic1 = IC1Agent(ic1_provider)
        s1 = _build_s1()
        verdicts = [_verdict("financial_risk", RiskLevel.MEDIUM)]
        ic1_deliberation = await ic1.evaluate(
            env, s1_synthesis=s1, verdicts=verdicts
        )

        artifact = await stitcher.render(
            env.case,
            s1_synthesis=s1,
            ic1_deliberation=ic1_deliberation,
            verdicts=verdicts,
            a1_challenges=["challenge_factor_concentration"],
            governance_escalations=["g2_escalation_high_severity"],
        )

        concerns = artifact.structured_components["concerns"]
        assert "ic1_dissent" in concerns
        assert concerns["a1_challenges"] == ["challenge_factor_concentration"]
        assert concerns["governance_escalations"] == ["g2_escalation_high_severity"]

    @pytest.mark.asyncio
    async def test_test_5_replay_correctness(self):
        """§8.6.8 Test 5 — structured components let an external reviewer reconstruct the case."""
        stitcher = M0Stitcher(_stitcher_mock())
        s1 = _build_s1()
        verdicts = [
            _verdict("financial_risk", RiskLevel.MEDIUM),
            _verdict("industry_analyst", RiskLevel.LOW),
        ]
        artifact = await stitcher.render(
            _envelope().case, s1_synthesis=s1, verdicts=verdicts
        )

        # Audit trail captures every input_hash needed to replay
        audit = artifact.structured_components["audit_trail"]
        assert audit["s1_input_hash"] == s1.input_hash
        assert sorted(audit["verdict_input_hashes"]) == sorted(
            v.input_hash for v in verdicts
        )

        # Verdicts appear in supporting_evidence with their flags + drivers
        evidence = artifact.structured_components["supporting_evidence"]
        verdict_ids = {v["agent_id"] for v in evidence["verdicts"]}
        assert verdict_ids == {"financial_risk", "industry_analyst"}

    @pytest.mark.asyncio
    async def test_round_trip_schema(self):
        stitcher = M0Stitcher(_stitcher_mock())
        artifact = await stitcher.render(
            _envelope().case,
            s1_synthesis=_build_s1(),
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
        )
        round_tripped = RenderedArtifact.model_validate_json(artifact.model_dump_json())
        assert round_tripped == artifact
