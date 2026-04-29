"""Pass 12 — G1 + G2 + G3 + A1 acceptance tests.

§7.10 (G1):
  Test 1 — determinism within version
  Test 2 — blocks mandate breach (equity cap)
  Test 3 — escalates near limit (within proximity threshold)
  Test 4 — lists all evaluated constraints
  Test 6 — family-member override applied correctly

§13.3.8 (G2):
  Test 1 — determinism
  Test 2 — citation: every BLOCK / ESCALATE cites rule by id + version
  Test 3 — time-aware: case before effective_date does not trigger rule
  Test 4 — aggregation rules
  Test 5 — schema validation
  Test 6 — rule corpus version captured

§13.4.8 (G3):
  Test 1 — aggregation correctness across (G1, G2, S1) outcomes
  Test 2 — determinism
  Test 3 — override requirements populated when block is overridable
  Test 4 — citation completeness

§13.5.8 (A1):
  Test 1 — non-empty challenges on material cases
  Test 2 — stress-test specificity
  Test 3 — alternative-proposal feasibility
  Test 4 — accountability flags surfaced
  Test 5 — A1 never gates (advisory only)
  Test 6 — determinism within version
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from artha.accountability.canonical_a1 import AccountabilitySurface
from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.case import (
    CaseChannel,
    CaseObject,
    CaseStatus,
    DominantLens,
    LensMetadata,
    ProposedAction,
)
from artha.canonical.curated_knowledge import (
    CuratedKnowledgeSnapshot,
    GiftCityRoutingRequirement,
    GiftCityRoutingRule,
    GiftCityRoutingRulesSet,
    ResidencyStatus,
    SebiProductRule,
    SebiProductRulesSet,
)
from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.governance import (
    A1Challenge,
    AccountabilityFlag,
    AccountabilityFlagType,
    AlternativeProposal,
    ChallengePoint,
    ChallengeSeverity,
    ChallengeType,
    ConstraintEvaluationStatus,
    ConstraintType,
    G1Evaluation,
    G2Evaluation,
    G3Evaluation,
    RegulatoryRuleSeverity,
    RegulatoryRuleStatus,
    StressTestScenario,
)
from artha.canonical.holding import Holding
from artha.canonical.mandate import (
    AssetClassLimits,
    ConcentrationLimits,
    FamilyMemberOverrideMandate,
    MandateObject,
    SignoffEvidence,
    SignoffMethod,
    VehicleLimits,
)
from artha.canonical.synthesis import (
    ConsensusBlock,
    IC1Deliberation,
    MaterialityGateBlock,
    S1Synthesis,
)
from artha.common.types import (
    AssetClass,
    CaseIntent,
    Driver,
    DriverDirection,
    DriverSeverity,
    InputsUsedManifest,
    MandateType,
    MaterialityGateResult,
    Permission,
    Recommendation,
    RiskLevel,
    RunMode,
    VehicleType,
)
from artha.governance.canonical_g1 import MandateComplianceGate
from artha.governance.canonical_g2 import RegulatoryEngine
from artha.governance.canonical_g3 import ActionPermissionFilter
from artha.llm.providers.mock import MockProvider

# ===========================================================================
# Helpers — fixtures shared across tests
# ===========================================================================


def _mandate(
    *,
    version: int = 1,
    equity_max: float = 0.60,
    equity_min: float = 0.30,
    equity_target: float = 0.50,
    aif_cat2_allowed: bool = True,
    aif_cat2_max: float = 0.20,
    family_override: FamilyMemberOverrideMandate | None = None,
    sector_hard_blocks: list[str] | None = None,
) -> MandateObject:
    fams: list[FamilyMemberOverrideMandate] = []
    if family_override is not None:
        fams = [family_override]
    return MandateObject(
        mandate_id="mandate_test",
        client_id="c1",
        firm_id="firm_test",
        version=version,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        mandate_type=MandateType.INDIVIDUAL,
        asset_class_limits={
            AssetClass.EQUITY: AssetClassLimits(
                min_pct=equity_min,
                target_pct=equity_target,
                max_pct=equity_max,
            ),
            AssetClass.DEBT: AssetClassLimits(
                min_pct=0.20,
                target_pct=0.40,
                max_pct=0.60,
            ),
        },
        vehicle_limits={
            VehicleType.AIF_CAT_2: VehicleLimits(
                allowed=aif_cat2_allowed,
                min_pct=0.0,
                max_pct=aif_cat2_max,
            ),
        },
        sector_hard_blocks=sector_hard_blocks or [],
        concentration_limits=ConcentrationLimits(
            per_holding_max=0.10, per_manager_max=0.20, per_sector_max=0.30
        ),
        liquidity_floor=0.10,
        signoff_method=SignoffMethod.E_SIGNATURE,
        signoff_evidence=SignoffEvidence(
            evidence_id="sign_evidence_test",
            captured_at=datetime(2026, 4, 1, tzinfo=UTC),
        ),
        signed_by="advisor_jane",
        family_overrides=fams,
    )


def _case(
    *,
    proposed_structure: VehicleType | None = None,
    ticket_size_inr: float | None = None,
    target_product: str = "test_product",
    routing_metadata: dict | None = None,
) -> CaseObject:
    proposed: ProposedAction | None = None
    if proposed_structure is not None:
        proposed = ProposedAction(
            target_product=target_product,
            ticket_size_inr=ticket_size_inr,
            structure=proposed_structure.value,
        )
    return CaseObject(
        case_id="case_p12_001",
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
        routing_metadata=routing_metadata or {},
    )


def _holding(
    iid: str,
    *,
    market_value: float = 1_000_000.0,
    asset_class: AssetClass = AssetClass.EQUITY,
    vehicle: VehicleType = VehicleType.MUTUAL_FUND,
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


def _curated_snapshot(
    *,
    sebi_rules: list[SebiProductRule] | None = None,
    gift_rules: list[GiftCityRoutingRule] | None = None,
    snapshot_version: str = "snap_test_v1",
) -> CuratedKnowledgeSnapshot:
    """Build a minimal snapshot suitable for G2 tests.

    Reuses `make_default_snapshot` for the tax/structure/demat/changelog
    sections so the schema validates, then overrides the SEBI / GIFT pieces
    we want to drive the test against.
    """
    from artha.m0.curated_knowledge import make_default_snapshot

    base = make_default_snapshot()
    return CuratedKnowledgeSnapshot(
        snapshot_version=snapshot_version,
        last_updated=date(2026, 4, 1),
        tax_table=base.tax_table,
        structure_compatibility=base.structure_compatibility,
        sebi_rules=SebiProductRulesSet(
            rules=sebi_rules if sebi_rules is not None else [],
            last_updated=date(2026, 4, 1),
        ),
        gift_city_rules=GiftCityRoutingRulesSet(
            rules=gift_rules if gift_rules is not None else [],
            last_updated=date(2026, 4, 1),
        ),
        demat_mechanics=base.demat_mechanics,
        regulatory_changelog=base.regulatory_changelog,
    )


def _build_g1(
    *,
    aggregated_status: Permission = Permission.APPROVED,
    breach_reasons: list[str] | None = None,
    escalation_reasons: list[str] | None = None,
    per_constraint_evaluations: list | None = None,
) -> G1Evaluation:
    return G1Evaluation(
        case_id="case_p12_001",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        aggregated_status=aggregated_status,
        per_constraint_evaluations=per_constraint_evaluations or [],
        breach_reasons=breach_reasons or [],
        escalation_reasons=escalation_reasons or [],
        mandate_version=1,
        input_hash="canned_g1_hash",
    )


def _build_g2(
    *,
    aggregated_permission: Permission = Permission.APPROVED,
    blocking_reasons: list[str] | None = None,
    escalation_reasons: list[str] | None = None,
) -> G2Evaluation:
    return G2Evaluation(
        case_id="case_p12_001",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        aggregated_permission=aggregated_permission,
        per_rule_evaluations=[],
        blocking_reasons=blocking_reasons or [],
        escalation_reasons=escalation_reasons or [],
        rule_corpus_version="snap_test_v1",
        decision_date=datetime(2026, 4, 25, tzinfo=UTC),
        input_hash="canned_g2_hash",
    )


def _build_s1() -> S1Synthesis:
    return S1Synthesis(
        case_id="case_p12_001",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        consensus=ConsensusBlock(risk_level=RiskLevel.MEDIUM, confidence=0.75),
        agreement_areas=["risk_band_alignment"],
        mode_dominance=DominantLens.PROPOSAL,
        synthesis_narrative="Canned narrative.",
        input_hash="canned_s1_hash",
        citations=["financial_risk", "industry_analyst", "macro_policy"],
    )


def _build_ic1() -> IC1Deliberation:
    return IC1Deliberation(
        case_id="case_p12_001",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        materiality_gate_result=MaterialityGateBlock(
            fired=MaterialityGateResult.CONVENE,
            signals=["s1_amplification_present"],
            rationale="canned",
        ),
        recommendation=Recommendation.PROCEED,
        input_hash="canned_ic1_hash",
    )


def _verdict(agent_id: str, risk: RiskLevel) -> StandardEvidenceVerdict:
    return StandardEvidenceVerdict(
        agent_id=agent_id,
        case_id="case_p12_001",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        risk_level=risk,
        confidence=0.8,
        drivers=[
            Driver(
                factor="placeholder",
                direction=DriverDirection.NEUTRAL,
                severity=DriverSeverity.LOW,
                detail="placeholder",
            )
        ],
        flags=[],
        reasoning_trace=f"{agent_id} canned trace.",
        inputs_used_manifest=InputsUsedManifest(),
        input_hash=f"hash_{agent_id}",
    )


def _envelope() -> AgentActivationEnvelope:
    return AgentActivationEnvelope(
        case=_case(),
        target_agent="a1",
        run_mode=RunMode.CASE,
    )


# ===========================================================================
# §7.10 — G1 acceptance
# ===========================================================================


class TestG1Acceptance:
    def test_test_1_determinism(self):
        gate = MandateComplianceGate()
        case = _case(
            proposed_structure=VehicleType.MUTUAL_FUND,
            ticket_size_inr=500_000.0,
        )
        mandate = _mandate()
        v1 = gate.evaluate(case, mandate, current_holdings=[_holding("MF1")])
        v2 = gate.evaluate(case, mandate, current_holdings=[_holding("MF1")])
        assert v1.input_hash == v2.input_hash

    def test_test_2_blocks_equity_cap_breach(self):
        # 95% already in equity, propose more equity → breach
        gate = MandateComplianceGate()
        # Mandate caps equity at 60%. Holding is 95L of 100L AUM = 95% equity.
        holdings = [
            _holding("EQ1", market_value=9_500_000.0, asset_class=AssetClass.EQUITY),
            _holding(
                "DEBT1", market_value=500_000.0, asset_class=AssetClass.DEBT,
                vehicle=VehicleType.DEBT_DIRECT,
            ),
        ]
        case = _case(
            proposed_structure=VehicleType.DIRECT_EQUITY,
            ticket_size_inr=1_000_000.0,
        )
        mandate = _mandate(equity_max=0.60)
        evaluation = gate.evaluate(case, mandate, current_holdings=holdings)
        assert evaluation.aggregated_status is Permission.BLOCKED
        # The breach must reference current/proposed/limit values
        eq_evals = [
            ev
            for ev in evaluation.per_constraint_evaluations
            if ev.constraint_id == "asset_class_limit:equity"
        ]
        assert eq_evals
        assert eq_evals[0].status is ConstraintEvaluationStatus.BREACH
        assert eq_evals[0].current_value is not None
        assert eq_evals[0].proposed_value is not None
        assert eq_evals[0].limit_value == pytest.approx(0.60)

    def test_test_3_escalates_near_limit(self):
        gate = MandateComplianceGate()
        # 56% in equity → within 10% proximity of 60% cap → WARN → ESCALATION
        holdings = [
            _holding("EQ1", market_value=5_600_000.0, asset_class=AssetClass.EQUITY),
            _holding(
                "DEBT1", market_value=4_400_000.0, asset_class=AssetClass.DEBT,
                vehicle=VehicleType.DEBT_DIRECT,
            ),
        ]
        case = _case()  # no proposal — just evaluate current state
        mandate = _mandate(equity_max=0.60)
        evaluation = gate.evaluate(case, mandate, current_holdings=holdings)
        assert evaluation.aggregated_status is Permission.ESCALATION_REQUIRED

    def test_test_4_lists_all_constraints(self):
        gate = MandateComplianceGate()
        case = _case()
        mandate = _mandate()
        evaluation = gate.evaluate(case, mandate, current_holdings=[])
        # Every asset-class limit appears in per_constraint_evaluations
        types = {ev.constraint_id for ev in evaluation.per_constraint_evaluations}
        assert "asset_class_limit:equity" in types
        assert "asset_class_limit:debt" in types

    def test_test_6_family_override_applied(self):
        # Family override raises equity max to 0.85
        override = FamilyMemberOverrideMandate(
            member_id="spouse",
            override_fields={
                "asset_class_limits.equity": {
                    "min_pct": 0.20,
                    "target_pct": 0.65,
                    "max_pct": 0.85,
                },
            },
        )
        gate = MandateComplianceGate()
        holdings = [
            _holding("EQ1", market_value=7_000_000.0, asset_class=AssetClass.EQUITY),
            _holding(
                "DEBT1", market_value=3_000_000.0, asset_class=AssetClass.DEBT,
                vehicle=VehicleType.DEBT_DIRECT,
            ),
        ]
        case = _case()
        mandate = _mandate(equity_max=0.60, family_override=override)

        # Without override → 70% equity breaches 60% cap
        no_override = gate.evaluate(case, mandate, current_holdings=holdings)
        assert no_override.aggregated_status is Permission.BLOCKED

        # With override → 70% equity is well under 85% cap
        with_override = gate.evaluate(
            case, mandate, current_holdings=holdings, family_member_id="spouse"
        )
        assert with_override.aggregated_status is Permission.APPROVED

    def test_sector_hard_block(self):
        gate = MandateComplianceGate()
        mandate = _mandate(sector_hard_blocks=["tobacco"])
        case = _case(
            proposed_structure=VehicleType.DIRECT_EQUITY,
            ticket_size_inr=500_000.0,
            target_product="ITC Tobacco Holdings",  # contains "tobacco"
        )
        evaluation = gate.evaluate(case, mandate, current_holdings=[])
        sector_breaches = [
            ev for ev in evaluation.per_constraint_evaluations
            if ev.constraint_type is ConstraintType.SECTOR_HARD_BLOCK
        ]
        assert sector_breaches
        assert evaluation.aggregated_status is Permission.BLOCKED

    def test_round_trip_g1_schema(self):
        gate = MandateComplianceGate()
        case = _case(proposed_structure=VehicleType.MUTUAL_FUND, ticket_size_inr=100_000.0)
        evaluation = gate.evaluate(case, _mandate(), current_holdings=[])
        round_tripped = G1Evaluation.model_validate_json(evaluation.model_dump_json())
        assert round_tripped == evaluation


# ===========================================================================
# §13.3.8 — G2 acceptance
# ===========================================================================


class TestG2Acceptance:
    def test_test_1_determinism(self):
        engine = RegulatoryEngine()
        case = _case(
            proposed_structure=VehicleType.AIF_CAT_2, ticket_size_inr=20_000_000.0
        )
        snapshot = _curated_snapshot(
            sebi_rules=[
                SebiProductRule(
                    rule_id="SEBI_AIF_CAT2_MINIMUM",
                    product_category=VehicleType.AIF_CAT_2.value,
                    rule_text="AIF Cat II minimum ticket 1 Cr",
                    minimum_ticket_size_inr=10_000_000.0,
                    effective_from=date(2024, 1, 1),
                ),
            ]
        )
        v1 = engine.evaluate(case, snapshot)
        v2 = engine.evaluate(case, snapshot)
        assert v1.input_hash == v2.input_hash

    def test_test_2_citation_present_on_block(self):
        engine = RegulatoryEngine()
        # Ticket below SEBI minimum → BLOCK with citation
        case = _case(
            proposed_structure=VehicleType.AIF_CAT_2, ticket_size_inr=500_000.0
        )
        snapshot = _curated_snapshot(
            sebi_rules=[
                SebiProductRule(
                    rule_id="SEBI_AIF_CAT2_MIN",
                    product_category=VehicleType.AIF_CAT_2.value,
                    rule_text="AIF Cat II minimum ticket 1 Cr",
                    minimum_ticket_size_inr=10_000_000.0,
                    effective_from=date(2024, 1, 1),
                ),
            ]
        )
        evaluation = engine.evaluate(case, snapshot)
        block_rules = [
            r for r in evaluation.per_rule_evaluations
            if r.status is RegulatoryRuleStatus.BLOCK
        ]
        assert block_rules
        assert all(r.citation is not None for r in block_rules)
        assert all(r.citation.source_id for r in block_rules)
        assert all(r.citation.source_version for r in block_rules)

    def test_test_3_time_aware_no_trigger_before_effective_date(self):
        engine = RegulatoryEngine()
        # Case before rule effective_date → rule does not trigger
        case = CaseObject(
            case_id="case_p12_002",
            client_id="c1",
            firm_id="firm_test",
            advisor_id="advisor_jane",
            created_at=datetime(2023, 6, 1, tzinfo=UTC),  # before 2024-01-01
            intent=CaseIntent.CASE,
            intent_confidence=0.9,
            dominant_lens=DominantLens.PROPOSAL,
            lens_metadata=LensMetadata(lenses_fired=[DominantLens.PROPOSAL]),
            current_status=CaseStatus.IN_PROGRESS,
            channel=CaseChannel.C0,
            proposed_action=ProposedAction(
                target_product="aif_test",
                ticket_size_inr=500_000.0,  # would breach if rule applied
                structure=VehicleType.AIF_CAT_2.value,
            ),
        )
        snapshot = _curated_snapshot(
            sebi_rules=[
                SebiProductRule(
                    rule_id="SEBI_AIF_CAT2_MIN",
                    product_category=VehicleType.AIF_CAT_2.value,
                    rule_text="AIF Cat II minimum ticket 1 Cr",
                    minimum_ticket_size_inr=10_000_000.0,
                    effective_from=date(2024, 1, 1),  # after the case date
                ),
            ]
        )
        evaluation = engine.evaluate(case, snapshot)
        # Rule did not trigger
        assert evaluation.per_rule_evaluations == []
        assert evaluation.aggregated_permission is Permission.APPROVED

    def test_test_4_aggregation(self):
        engine = RegulatoryEngine()
        # All PASS → APPROVED
        case_pass = _case(
            proposed_structure=VehicleType.AIF_CAT_2, ticket_size_inr=20_000_000.0
        )
        snap_pass = _curated_snapshot(
            sebi_rules=[
                SebiProductRule(
                    rule_id="SEBI_AIF_CAT2_MIN",
                    product_category=VehicleType.AIF_CAT_2.value,
                    rule_text="ok",
                    minimum_ticket_size_inr=10_000_000.0,
                    effective_from=date(2024, 1, 1),
                ),
            ]
        )
        ev_pass = engine.evaluate(case_pass, snap_pass)
        assert ev_pass.aggregated_permission is Permission.APPROVED

        # ESCALATE only → ESCALATION_REQUIRED
        snap_escalate = _curated_snapshot(
            sebi_rules=[
                SebiProductRule(
                    rule_id="SEBI_AIF_CAT2_MIN",
                    product_category=VehicleType.AIF_CAT_2.value,
                    rule_text="ok",
                    minimum_ticket_size_inr=10_000_000.0,
                    documentation_required=["aif_subscription_agreement"],
                    effective_from=date(2024, 1, 1),
                ),
            ]
        )
        ev_escalate = engine.evaluate(case_pass, snap_escalate)
        assert ev_escalate.aggregated_permission is Permission.ESCALATION_REQUIRED

        # BLOCK + ESCALATE → BLOCKED
        case_block = _case(
            proposed_structure=VehicleType.AIF_CAT_2, ticket_size_inr=100_000.0
        )
        ev_blocked = engine.evaluate(case_block, snap_escalate)
        assert ev_blocked.aggregated_permission is Permission.BLOCKED

    def test_test_5_schema_validation(self):
        engine = RegulatoryEngine()
        case = _case(
            proposed_structure=VehicleType.AIF_CAT_2, ticket_size_inr=20_000_000.0
        )
        evaluation = engine.evaluate(case, _curated_snapshot())
        round_tripped = G2Evaluation.model_validate_json(evaluation.model_dump_json())
        assert round_tripped == evaluation

    def test_test_6_corpus_version_captured(self):
        engine = RegulatoryEngine()
        case = _case()
        snapshot = _curated_snapshot()
        evaluation = engine.evaluate(case, snapshot)
        assert evaluation.rule_corpus_version == "snap_test_v1"

    def test_gift_routing_block_for_not_permitted(self):
        engine = RegulatoryEngine()
        case = _case(
            proposed_structure=VehicleType.AIF_CAT_2, ticket_size_inr=20_000_000.0
        )
        snapshot = _curated_snapshot(
            gift_rules=[
                GiftCityRoutingRule(
                    residency=ResidencyStatus.NRI,
                    product_domicile="indian",
                    route="direct",
                    requirement=GiftCityRoutingRequirement.UNAVAILABLE,
                ),
            ]
        )
        evaluation = engine.evaluate(case, snapshot, residency=ResidencyStatus.NRI)
        gift_rules = [
            r for r in evaluation.per_rule_evaluations
            if r.severity is RegulatoryRuleSeverity.HARD
            and r.status is RegulatoryRuleStatus.BLOCK
        ]
        assert gift_rules


# ===========================================================================
# §13.4.8 — G3 acceptance
# ===========================================================================


class TestG3Acceptance:
    def test_test_1a_g1_block_propagates(self):
        filt = ActionPermissionFilter()
        case = _case()
        g1 = _build_g1(
            aggregated_status=Permission.BLOCKED,
            breach_reasons=["asset_class_limit:equity: over cap"],
        )
        g2 = _build_g2()
        evaluation = filt.evaluate(case, g1=g1, g2=g2)
        assert evaluation.permission is Permission.BLOCKED
        assert any("g1:" in r for r in evaluation.blocking_reasons)

    def test_test_1b_g2_block_propagates(self):
        filt = ActionPermissionFilter()
        case = _case()
        g1 = _build_g1()
        g2 = _build_g2(
            aggregated_permission=Permission.BLOCKED,
            blocking_reasons=["SEBI_AIF_MIN: below ticket"],
        )
        evaluation = filt.evaluate(case, g1=g1, g2=g2)
        assert evaluation.permission is Permission.BLOCKED
        assert any("g2:" in r for r in evaluation.blocking_reasons)

    def test_test_1c_s1_escalation_lifts_to_escalation(self):
        filt = ActionPermissionFilter()
        case = _case()
        g1 = _build_g1()
        g2 = _build_g2()
        evaluation = filt.evaluate(
            case, g1=g1, g2=g2, s1_escalation_recommended=True
        )
        assert evaluation.permission is Permission.ESCALATION_REQUIRED
        assert "s1:escalation_recommended" in evaluation.escalation_reasons

    def test_test_1d_all_pass_approves(self):
        filt = ActionPermissionFilter()
        case = _case()
        evaluation = filt.evaluate(case, g1=_build_g1(), g2=_build_g2())
        assert evaluation.permission is Permission.APPROVED
        assert evaluation.blocking_reasons == []
        assert evaluation.escalation_reasons == []

    def test_test_1e_block_supersedes_escalation(self):
        filt = ActionPermissionFilter()
        case = _case()
        g1 = _build_g1(
            aggregated_status=Permission.BLOCKED,
            breach_reasons=["foo"],
        )
        g2 = _build_g2(
            aggregated_permission=Permission.ESCALATION_REQUIRED,
            escalation_reasons=["bar"],
        )
        evaluation = filt.evaluate(case, g1=g1, g2=g2, s1_escalation_recommended=True)
        assert evaluation.permission is Permission.BLOCKED

    def test_test_2_determinism(self):
        filt = ActionPermissionFilter()
        case = _case()
        v1 = filt.evaluate(case, g1=_build_g1(), g2=_build_g2())
        v2 = filt.evaluate(case, g1=_build_g1(), g2=_build_g2())
        assert v1.input_hash == v2.input_hash

    def test_test_3_override_requirements_when_overridable(self):
        from artha.canonical.governance import ConstraintEvaluation

        filt = ActionPermissionFilter()
        case = _case()
        g1 = _build_g1(
            aggregated_status=Permission.BLOCKED,
            breach_reasons=["asset_class_limit:equity"],
            per_constraint_evaluations=[
                ConstraintEvaluation(
                    constraint_id="asset_class_limit:equity",
                    constraint_type=ConstraintType.ASSET_CLASS_LIMIT,
                    status=ConstraintEvaluationStatus.BREACH,
                    evaluation_detail="over cap",
                ),
            ],
        )
        g2 = _build_g2()  # no regulatory block
        evaluation = filt.evaluate(case, g1=g1, g2=g2)
        assert evaluation.permission is Permission.BLOCKED
        assert evaluation.override_requirements is not None
        assert evaluation.override_requirements.override_permitted is True
        assert "documented_advisor_rationale" in evaluation.override_requirements.requires
        assert "supervisor_cosign" in evaluation.override_requirements.requires

    def test_g2_block_disables_override(self):
        from artha.canonical.governance import ConstraintEvaluation

        filt = ActionPermissionFilter()
        case = _case()
        g1 = _build_g1(
            aggregated_status=Permission.BLOCKED,
            breach_reasons=["asset_class_limit:equity"],
            per_constraint_evaluations=[
                ConstraintEvaluation(
                    constraint_id="asset_class_limit:equity",
                    constraint_type=ConstraintType.ASSET_CLASS_LIMIT,
                    status=ConstraintEvaluationStatus.BREACH,
                    evaluation_detail="over cap",
                ),
            ],
        )
        g2 = _build_g2(
            aggregated_permission=Permission.BLOCKED,
            blocking_reasons=["SEBI_AIF: below ticket"],
        )
        evaluation = filt.evaluate(case, g1=g1, g2=g2)
        assert evaluation.permission is Permission.BLOCKED
        assert evaluation.override_requirements is not None
        assert evaluation.override_requirements.override_permitted is False

    def test_test_4_citation_completeness(self):
        filt = ActionPermissionFilter()
        case = _case()
        g1 = _build_g1(
            aggregated_status=Permission.BLOCKED,
            breach_reasons=["asset_class_limit:equity: over cap by 5%"],
        )
        g2 = _build_g2(
            aggregated_permission=Permission.BLOCKED,
            blocking_reasons=["SEBI_AIF_CAT2_MIN: below ticket"],
        )
        evaluation = filt.evaluate(case, g1=g1, g2=g2)
        # Each blocking_reason traces back to its source (g1: or g2:)
        for r in evaluation.blocking_reasons:
            assert r.startswith("g1:") or r.startswith("g2:")

    def test_g3_round_trip(self):
        filt = ActionPermissionFilter()
        evaluation = filt.evaluate(_case(), g1=_build_g1(), g2=_build_g2())
        round_tripped = G3Evaluation.model_validate_json(evaluation.model_dump_json())
        assert round_tripped == evaluation


# ===========================================================================
# §13.5.8 — A1 acceptance
# ===========================================================================


def _a1_mock(
    *,
    challenge_count: int = 1,
    scenario_named_impacts: list[str] | None = None,
    proposal_l4_instruments: list[str] | None = None,
    flags: list[AccountabilityFlag] | None = None,
    confidence: float = 0.7,
) -> MockProvider:
    mock = MockProvider()
    challenges = [
        ChallengePoint(
            challenge_type=ChallengeType.COUNTER_ARGUMENT,
            content=f"Counter-argument {i}: synthesis may understate concentration.",
            severity=ChallengeSeverity.MEDIUM,
            cited_agent_ids=["financial_risk"],
        ).model_dump(mode="json")
        for i in range(challenge_count)
    ]
    scenarios = [
        StressTestScenario(
            scenario_name="Equity drawdown",
            conditions=["Nifty -25%", "Bond yields +200bps"],
            named_impacts=scenario_named_impacts or [],
            severity=ChallengeSeverity.HIGH,
        ).model_dump(mode="json")
    ]
    proposals = [
        AlternativeProposal(
            proposal_summary="Reduce AIF allocation, prefer liquid debt MFs",
            structure_changes=["replace AIF_CAT_2 with debt MF"],
            rationale="Smaller drawdown profile.",
            cited_l4_instruments=proposal_l4_instruments or [],
        ).model_dump(mode="json")
    ]
    mock.set_structured_response(
        "Signals:",
        {
            "challenge_points": challenges,
            "alternative_proposals": proposals,
            "stress_test_scenarios": scenarios,
            "accountability_flags": [f.model_dump(mode="json") for f in (flags or [])],
            "confidence": confidence,
            "reasoning_trace": "Reviewed S1 + governance.",
        },
    )
    return mock


class TestA1Acceptance:
    @pytest.mark.asyncio
    async def test_test_1_non_empty_challenges_on_material_case(self):
        a1 = AccountabilitySurface(
            _a1_mock(
                challenge_count=2,
                scenario_named_impacts=["concentration_drag", "liquidity_pressure"],
                proposal_l4_instruments=["mf_liquid_001"],
            )
        )
        challenge = await a1.evaluate(
            _envelope(),
            verdicts=[_verdict("financial_risk", RiskLevel.HIGH)],
            s1_synthesis=_build_s1(),
            ic1_deliberation=_build_ic1(),
            g1=_build_g1(),
            g2=_build_g2(),
        )
        assert len(challenge.challenge_points) >= 1

    @pytest.mark.asyncio
    async def test_test_2_specificity_enforced(self):
        # Mock returns a scenario with no named_impacts → A1 forces a placeholder
        a1 = AccountabilitySurface(_a1_mock(scenario_named_impacts=[]))
        challenge = await a1.evaluate(
            _envelope(),
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
            s1_synthesis=_build_s1(),
        )
        for s in challenge.stress_test_scenarios:
            assert len(s.named_impacts) >= 1

    @pytest.mark.asyncio
    async def test_test_3_feasibility_marked_when_no_l4(self):
        # Mock returns proposal with no L4 instruments → marked infeasible
        a1 = AccountabilitySurface(
            _a1_mock(
                scenario_named_impacts=["x"],
                proposal_l4_instruments=[],  # empty
            )
        )
        challenge = await a1.evaluate(
            _envelope(),
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
            s1_synthesis=_build_s1(),
        )
        for p in challenge.alternative_proposals:
            assert p.feasibility_check == "infeasible"

    @pytest.mark.asyncio
    async def test_test_4_accountability_flags_surfaced(self):
        flag = AccountabilityFlag(
            flag_type=AccountabilityFlagType.BRIEFING_CLOSE_PARAPHRASE,
            flagged_event_id="briefing_evt_001",
            severity=ChallengeSeverity.MEDIUM,
            rationale="Briefing text mirrors E1 reasoning_trace verbatim.",
        )
        a1 = AccountabilitySurface(
            _a1_mock(
                scenario_named_impacts=["x"],
                proposal_l4_instruments=["mf_001"],
                flags=[flag, flag],  # duplicate → dedupe
            )
        )
        challenge = await a1.evaluate(
            _envelope(),
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
            s1_synthesis=_build_s1(),
        )
        # Flag surfaces, deduped to 1
        assert len(challenge.accountability_flags) == 1
        assert (
            challenge.accountability_flags[0].flag_type
            is AccountabilityFlagType.BRIEFING_CLOSE_PARAPHRASE
        )

    @pytest.mark.asyncio
    async def test_test_5_a1_never_gates(self):
        """A1 has no Permission field → cannot gate."""
        a1 = AccountabilitySurface(
            _a1_mock(
                scenario_named_impacts=["x"], proposal_l4_instruments=["mf_001"]
            )
        )
        challenge = await a1.evaluate(
            _envelope(),
            verdicts=[_verdict("financial_risk", RiskLevel.HIGH)],
            s1_synthesis=_build_s1(),
        )
        # A1Challenge model has no permission/aggregated_status field
        with pytest.raises(AttributeError):
            challenge.permission  # noqa: B018

    @pytest.mark.asyncio
    async def test_test_6_determinism(self):
        a1 = AccountabilitySurface(
            _a1_mock(
                scenario_named_impacts=["concentration_drag"],
                proposal_l4_instruments=["mf_liquid_001"],
            )
        )
        c1 = await a1.evaluate(
            _envelope(),
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
            s1_synthesis=_build_s1(),
        )
        c2 = await a1.evaluate(
            _envelope(),
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
            s1_synthesis=_build_s1(),
        )
        assert c1.input_hash == c2.input_hash

    @pytest.mark.asyncio
    async def test_round_trip_a1_schema(self):
        a1 = AccountabilitySurface(
            _a1_mock(
                scenario_named_impacts=["x"],
                proposal_l4_instruments=["mf_001"],
            )
        )
        challenge = await a1.evaluate(
            _envelope(),
            verdicts=[_verdict("financial_risk", RiskLevel.MEDIUM)],
            s1_synthesis=_build_s1(),
        )
        round_tripped = A1Challenge.model_validate_json(challenge.model_dump_json())
        assert round_tripped == challenge
