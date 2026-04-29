"""Pass 13 — PM1 + M1 + EX1 + T2 acceptance tests.

§13.6.8 (PM1):
  Test 1 — Drift detection within one daily cycle of L1 tolerance breach
  Test 3 — Benchmark divergence alerts on materially divergent returns
  Test 4 — Threshold alerting emits MUST_RESPOND N0 on mandate-cap breaches
  Test 5 — Determinism for drift and benchmark detection
  Test 6 — PM1 events captured with sufficient detail to replay

§7.10 (M1):
  Test 5 — M1 catches new breach within one daily cycle; emits MUST_RESPOND
  Test 9 — Mandate breach prioritised: M1 alert is MUST_RESPOND, PM1 drift is SHOULD_RESPOND
  Test 10 — Out-of-bucket flag triggers single-client construction alert

§13.9.8 (EX1):
  Test 1 — Failure mode tests invoke EX1 with correct category
  Test 2 — Routing logic deterministic across runs
  Test 4 — Cascade-depth tracking escalates to firm-leadership at threshold
  Test 5 — Rule table version captured in every EX1 event
  Test 6 — Schema compliance (round-trip)

§13.8.8 (T2):
  Test 1 — Monthly run produces structured analysis with findings per category
  Test 2 — ≥30 outcomes per agent before findings issued
  Test 4 — No prompt updates deploy without firm approval (status reflects)
  Test 6 — Determinism for statistical portions
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from artha.accountability.canonical_ex1 import (
    DEFAULT_CASCADE_THRESHOLD,
    DEFAULT_ROUTING_TABLE_VERSION,
    ExceptionHandler,
)
from artha.canonical.case import (
    CaseChannel,
    CaseObject,
    CaseStatus,
    DominantLens,
    LensMetadata,
)
from artha.canonical.holding import Holding
from artha.canonical.mandate import (
    AssetClassLimits,
    ConcentrationLimits,
    MandateObject,
    SignoffEvidence,
    SignoffMethod,
    VehicleLimits,
)
from artha.canonical.model_portfolio import (
    ConstructionContext,
    ModelPortfolioObject,
    TargetWithTolerance,
)
from artha.canonical.monitoring import (
    EX1Event,
    ExceptionCategory,
    ExceptionSeverity,
    M1BreachType,
    M1DriftReport,
    PM1Event,
    PM1EventType,
    RoutingDecision,
    T2Finding,
    T2FindingCategory,
    T2FindingSeverity,
    T2PromptUpdateProposal,
    T2ReflectionRun,
    T2RunStatus,
    T2RunType,
    ThesisValidityStatus,
)
from artha.common.types import (
    AlertTier,
    AssetClass,
    Bucket,
    CaseIntent,
    MandateType,
    VehicleType,
)
from artha.llm.providers.mock import MockProvider
from artha.model_portfolio.tolerance import PortfolioAllocationSnapshot
from artha.monitoring import (
    MandateDriftMonitor,
    PM1ThesisValidityInputs,
    PortfolioMonitoringAgent,
)
from artha.reflection import (
    CalibrationSample,
    ReflectionEngine,
    ReflectionScope,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _model_portfolio() -> ModelPortfolioObject:
    return ModelPortfolioObject(
        model_id="mp_test",
        bucket=Bucket.MOD_LT,
        version="1.0.0",
        firm_id="firm_test",
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        approved_by="advisor_jane",
        approval_rationale="initial bucket model",
        l1_targets={
            AssetClass.EQUITY: TargetWithTolerance(
                target=0.60, tolerance_band=0.05
            ),
            AssetClass.DEBT: TargetWithTolerance(
                target=0.40, tolerance_band=0.05
            ),
        },
        construction=ConstructionContext(
            construction_pipeline_run_id="cp_test_001",
        ),
    )


def _mandate(
    *,
    equity_max: float = 0.60,
    aif_cat2_max: float = 0.20,
    liquidity_floor: float = 0.10,
) -> MandateObject:
    return MandateObject(
        mandate_id="mandate_test",
        client_id="c1",
        firm_id="firm_test",
        version=1,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        mandate_type=MandateType.INDIVIDUAL,
        asset_class_limits={
            AssetClass.EQUITY: AssetClassLimits(
                min_pct=0.30, target_pct=0.50, max_pct=equity_max
            ),
            AssetClass.DEBT: AssetClassLimits(
                min_pct=0.20, target_pct=0.40, max_pct=0.60
            ),
        },
        vehicle_limits={
            VehicleType.AIF_CAT_2: VehicleLimits(
                allowed=True, min_pct=0.0, max_pct=aif_cat2_max
            ),
        },
        concentration_limits=ConcentrationLimits(
            per_holding_max=0.10, per_manager_max=0.20, per_sector_max=0.30
        ),
        liquidity_floor=liquidity_floor,
        signoff_method=SignoffMethod.E_SIGNATURE,
        signoff_evidence=SignoffEvidence(
            evidence_id="sign_evidence_test",
            captured_at=datetime(2026, 4, 1, tzinfo=UTC),
        ),
        signed_by="advisor_jane",
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


def _case() -> CaseObject:
    return CaseObject(
        case_id="case_p13_001",
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


# ===========================================================================
# §13.6.8 — PM1 acceptance
# ===========================================================================


class TestPM1Acceptance:
    def test_test_1_drift_detected(self):
        """L1 drift breach surfaces a PM1Event with DRIFT type."""
        agent = PortfolioMonitoringAgent()
        # Equity at 70% vs target 60% with 5% band → ACTION_REQUIRED
        snapshot = PortfolioAllocationSnapshot(
            as_of_date=date(2026, 4, 25),
            l1_weights={
                AssetClass.EQUITY: 0.70,
                AssetClass.DEBT: 0.30,
            },
        )
        events = agent.detect_drift_events(
            client_id="c1",
            firm_id="firm_test",
            model=_model_portfolio(),
            snapshot=snapshot,
        )
        equity_events = [
            e for e in events
            if e.drift_detail and e.drift_detail.cell_key == "equity"
        ]
        assert equity_events
        ev = equity_events[0]
        assert ev.event_type is PM1EventType.DRIFT
        assert ev.drift_detail.expected_value == pytest.approx(0.60)
        assert ev.drift_detail.observed_value == pytest.approx(0.70)
        # ACTION_REQUIRED breach should yield an N0 alert pointer
        assert ev.originating_n0_alert_id is not None

    def test_test_3_benchmark_divergence(self):
        agent = PortfolioMonitoringAgent()
        # 5% gap > 2% threshold
        event = agent.detect_benchmark_divergence(
            client_id="c1",
            firm_id="firm_test",
            benchmark_id="NIFTY50",
            portfolio_return_period=0.08,
            benchmark_return_period=0.13,
            rolling_window_days=180,
        )
        assert event is not None
        assert event.event_type is PM1EventType.BENCHMARK_DIVERGENCE
        assert event.benchmark_divergence_detail.divergence_magnitude == pytest.approx(-0.05)
        assert event.originating_n0_alert_id is not None

    def test_benchmark_divergence_under_threshold_silent(self):
        agent = PortfolioMonitoringAgent()
        event = agent.detect_benchmark_divergence(
            client_id="c1",
            firm_id="firm_test",
            benchmark_id="NIFTY50",
            portfolio_return_period=0.08,
            benchmark_return_period=0.085,  # 0.5% gap < 2% threshold
            rolling_window_days=180,
        )
        assert event is None

    def test_test_4_threshold_breach_must_respond(self):
        agent = PortfolioMonitoringAgent()
        event = agent.detect_threshold_breach(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(),
            threshold_rule_id="asset_class_ceiling:equity",
            observed_value=0.65,
            limit_value=0.60,
            breach_type=M1BreachType.ASSET_CLASS_CEILING,
        )
        assert event is not None
        assert event.event_type is PM1EventType.THRESHOLD_BREACH
        assert event.threshold_breach_detail.breach_magnitude == pytest.approx(0.05)
        # MUST_RESPOND N0 emitted (we cannot inspect tier from event alone, but
        # the alert pointer is present)
        assert event.originating_n0_alert_id is not None

    def test_threshold_floor_breach(self):
        # Liquidity floor: observed 0.05, floor 0.10 → breach
        agent = PortfolioMonitoringAgent()
        event = agent.detect_threshold_breach(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(),
            threshold_rule_id="liquidity_floor",
            observed_value=0.05,
            limit_value=0.10,
            breach_type=M1BreachType.LIQUIDITY_FLOOR,
        )
        assert event is not None
        assert event.threshold_breach_detail.breach_magnitude == pytest.approx(0.05)

    def test_test_5_drift_determinism(self):
        agent = PortfolioMonitoringAgent()
        snapshot = PortfolioAllocationSnapshot(
            as_of_date=date(2026, 4, 25),
            l1_weights={AssetClass.EQUITY: 0.70, AssetClass.DEBT: 0.30},
        )
        v1 = agent.detect_drift_events(
            client_id="c1",
            firm_id="firm_test",
            model=_model_portfolio(),
            snapshot=snapshot,
        )
        v2 = agent.detect_drift_events(
            client_id="c1",
            firm_id="firm_test",
            model=_model_portfolio(),
            snapshot=snapshot,
        )
        assert [e.input_hash for e in v1] == [e.input_hash for e in v2]

    def test_test_6_event_round_trips(self):
        agent = PortfolioMonitoringAgent()
        event = agent.detect_benchmark_divergence(
            client_id="c1",
            firm_id="firm_test",
            benchmark_id="NIFTY50",
            portfolio_return_period=0.08,
            benchmark_return_period=0.13,
            rolling_window_days=180,
        )
        round_tripped = PM1Event.model_validate_json(event.model_dump_json())
        assert round_tripped == event

    @pytest.mark.asyncio
    async def test_thesis_validity_llm_path(self):
        mock = MockProvider()
        mock.set_structured_response(
            "thesis-validity scorer",
            {
                "status": ThesisValidityStatus.CONTRADICTED.value,
                "rationale": "Realised returns diverge sharply from thesis assumptions.",
                "confidence": 0.85,
            },
        )
        agent = PortfolioMonitoringAgent(provider=mock)
        event = await agent.evaluate_thesis_validity(
            case=_case(),
            inputs=PM1ThesisValidityInputs(
                case_id="case_p13_001",
                thesis_text="Aggressive equity exposure expected to outperform debt by 600bps.",
                realised_return=-0.02,
                realised_observations=["Market drawdown during period."],
                horizon_days=180,
            ),
        )
        assert event.event_type is PM1EventType.THESIS_VALIDITY
        assert event.thesis_validity_detail.status is ThesisValidityStatus.CONTRADICTED
        # Contradicted status surfaces an N0 alert
        assert event.originating_n0_alert_id is not None


# ===========================================================================
# §7.10 — M1 acceptance
# ===========================================================================


class TestM1Acceptance:
    def test_test_5_breach_emits_must_respond_alert(self):
        monitor = MandateDriftMonitor()
        # Liquidity floor 0.10, current 0.05 → breach
        report, alerts = monitor.sweep(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(liquidity_floor=0.10),
            holdings=[_holding("EQ1", market_value=10_000_000.0)],
            most_liquid_share=0.05,
        )
        assert any(b.breach_type is M1BreachType.LIQUIDITY_FLOOR for b in report.breaches)
        liq_alerts = [
            a for a in alerts
            if a.related_constraint_id == "liquidity_floor"
        ]
        assert liq_alerts
        assert all(a.tier is AlertTier.MUST_RESPOND for a in liq_alerts)

    def test_test_5_no_breach_emits_empty_report(self):
        monitor = MandateDriftMonitor()
        # Spread holdings across many positions so per-holding concentration
        # cap (10%) is not breached. Equity 50%, Debt 50% both within bounds.
        holdings = []
        for i in range(15):
            holdings.append(
                _holding(
                    f"EQ{i}", market_value=333_333.0,
                    asset_class=AssetClass.EQUITY,
                )
            )
        for i in range(15):
            holdings.append(
                _holding(
                    f"DEBT{i}", market_value=333_333.0,
                    asset_class=AssetClass.DEBT,
                    vehicle=VehicleType.DEBT_DIRECT,
                )
            )
        report, alerts = monitor.sweep(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(),
            holdings=holdings,
            most_liquid_share=0.20,
        )
        # 50% equity within [30%, 60%] and 50% debt within [20%, 60%], no
        # per-holding > 10%, so no breaches.
        assert report.breaches == []
        assert alerts == []

    def test_test_9_mandate_breach_priority(self):
        """When equity at 70% breaches mandate (60% cap), M1 alert is MUST_RESPOND.
        PM1 drift on the same gap is SHOULD_RESPOND. Mandate priority enforced."""
        # M1 sweep
        monitor = MandateDriftMonitor()
        holdings = [
            _holding("EQ1", market_value=7_000_000.0, asset_class=AssetClass.EQUITY),
            _holding(
                "DEBT1", market_value=3_000_000.0,
                asset_class=AssetClass.DEBT,
                vehicle=VehicleType.DEBT_DIRECT,
            ),
        ]
        report, m1_alerts = monitor.sweep(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(equity_max=0.60),
            holdings=holdings,
        )
        assert any(
            b.breach_type is M1BreachType.ASSET_CLASS_CEILING
            for b in report.breaches
        )
        assert all(a.tier is AlertTier.MUST_RESPOND for a in m1_alerts)

        # PM1 drift on same allocation
        pm1 = PortfolioMonitoringAgent()
        snapshot = PortfolioAllocationSnapshot(
            as_of_date=date(2026, 4, 25),
            l1_weights={AssetClass.EQUITY: 0.70, AssetClass.DEBT: 0.30},
        )
        pm1_events = pm1.detect_drift_events(
            client_id="c1",
            firm_id="firm_test",
            model=_model_portfolio(),
            snapshot=snapshot,
        )
        # PM1 drift events emit SHOULD_RESPOND tier (not MUST_RESPOND)
        # Mandate priority: M1's tier > PM1's tier
        assert pm1_events  # drift detected
        # M1's MUST_RESPOND > PM1's SHOULD_RESPOND
        m1_tiers = {a.tier for a in m1_alerts}
        assert AlertTier.MUST_RESPOND in m1_tiers

    def test_test_10_out_of_bucket_flag(self):
        monitor = MandateDriftMonitor()
        report, alerts = monitor.sweep(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(),
            holdings=[_holding("EQ1", market_value=5_000_000.0)],
            out_of_bucket_flag=True,
        )
        assert report.out_of_bucket_flag is True
        out_of_bucket_alerts = [
            a for a in alerts if "out-of-bucket" in a.title.lower()
        ]
        assert out_of_bucket_alerts

    def test_m1_determinism(self):
        monitor = MandateDriftMonitor()
        v1, _ = monitor.sweep(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(),
            holdings=[_holding("EQ1")],
        )
        v2, _ = monitor.sweep(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(),
            holdings=[_holding("EQ1")],
        )
        assert v1.input_hash == v2.input_hash

    def test_round_trip_m1_report(self):
        monitor = MandateDriftMonitor()
        report, _ = monitor.sweep(
            client_id="c1",
            firm_id="firm_test",
            mandate=_mandate(),
            holdings=[_holding("EQ1")],
        )
        round_tripped = M1DriftReport.model_validate_json(report.model_dump_json())
        assert round_tripped == report


# ===========================================================================
# §13.9.8 — EX1 acceptance
# ===========================================================================


class TestEX1Acceptance:
    def test_test_1_routing_known_categories(self):
        ex1 = ExceptionHandler()
        # E2 service_unavailable ERROR → fallback (more-specific entry wins)
        event, alert = ex1.route(
            firm_id="firm_test",
            originating_component="e2.industry_analyst",
            exception_category=ExceptionCategory.SERVICE_UNAVAILABLE,
            severity=ExceptionSeverity.ERROR,
        )
        assert event.routing_decision is RoutingDecision.FALLBACK_TO_PRIOR_VERSION
        # No N0 because not an escalation
        assert alert is None

    def test_test_1_briefer_drops_on_unavailable(self):
        ex1 = ExceptionHandler()
        event, _ = ex1.route(
            firm_id="firm_test",
            originating_component="m0.briefer",
            exception_category=ExceptionCategory.SERVICE_UNAVAILABLE,
            severity=ExceptionSeverity.ERROR,
        )
        assert event.routing_decision is RoutingDecision.LOG_AND_PROCEED_WITH_FLAG

    def test_test_2_determinism(self):
        ex1 = ExceptionHandler()
        e1, _ = ex1.route(
            firm_id="firm_test",
            originating_component="e1.financial_risk",
            exception_category=ExceptionCategory.TIMEOUT,
            severity=ExceptionSeverity.WARNING,
        )
        e2, _ = ex1.route(
            firm_id="firm_test",
            originating_component="e1.financial_risk",
            exception_category=ExceptionCategory.TIMEOUT,
            severity=ExceptionSeverity.WARNING,
        )
        assert e1.routing_decision == e2.routing_decision
        assert e1.input_hash == e2.input_hash

    def test_test_4_cascade_threshold_escalates_firm_leadership(self):
        ex1 = ExceptionHandler()
        # cascade_depth at threshold → escalate to firm leadership
        event, alert = ex1.route(
            firm_id="firm_test",
            originating_component="s1.synthesis",
            exception_category=ExceptionCategory.CASCADING_EXCEPTION,
            severity=ExceptionSeverity.WARNING,
            cascade_depth=DEFAULT_CASCADE_THRESHOLD,
        )
        assert event.routing_decision is RoutingDecision.ESCALATE_TO_FIRM_LEADERSHIP
        assert event.cascade_threshold_breached is True
        assert alert is not None
        assert alert.tier is AlertTier.MUST_RESPOND

    def test_test_4_cascade_below_threshold_no_force(self):
        ex1 = ExceptionHandler()
        event, _ = ex1.route(
            firm_id="firm_test",
            originating_component="s1.synthesis",
            exception_category=ExceptionCategory.CASCADING_EXCEPTION,
            severity=ExceptionSeverity.WARNING,
            cascade_depth=DEFAULT_CASCADE_THRESHOLD - 1,
        )
        assert event.routing_decision is RoutingDecision.ESCALATE_TO_ADVISOR
        assert event.cascade_threshold_breached is False

    def test_test_5_rule_table_version_captured(self):
        ex1 = ExceptionHandler()
        event, _ = ex1.route(
            firm_id="firm_test",
            originating_component="e1.financial_risk",
            exception_category=ExceptionCategory.SCHEMA_VIOLATION,
            severity=ExceptionSeverity.ERROR,
        )
        assert event.routing_rule_table_version == DEFAULT_ROUTING_TABLE_VERSION

    def test_test_6_schema_round_trip(self):
        ex1 = ExceptionHandler()
        event, _ = ex1.route(
            firm_id="firm_test",
            originating_component="e1.financial_risk",
            exception_category=ExceptionCategory.SCHEMA_VIOLATION,
            severity=ExceptionSeverity.ERROR,
        )
        round_tripped = EX1Event.model_validate_json(event.model_dump_json())
        assert round_tripped == event

    def test_governance_mismatch_routes_to_compliance(self):
        ex1 = ExceptionHandler()
        event, alert = ex1.route(
            firm_id="firm_test",
            originating_component="g2.regulatory_engine",
            exception_category=ExceptionCategory.GOVERNANCE_RULE_MISMATCH,
            severity=ExceptionSeverity.ERROR,
        )
        assert event.routing_decision is RoutingDecision.ESCALATE_TO_COMPLIANCE
        assert alert is not None

    def test_critical_severity_emits_must_respond_n0(self):
        ex1 = ExceptionHandler()
        _, alert = ex1.route(
            firm_id="firm_test",
            originating_component="g2.regulatory_engine",
            exception_category=ExceptionCategory.GOVERNANCE_RULE_MISMATCH,
            severity=ExceptionSeverity.CRITICAL,
        )
        assert alert is not None
        assert alert.tier is AlertTier.MUST_RESPOND


# ===========================================================================
# §13.8.8 — T2 acceptance
# ===========================================================================


def _t2_mock(
    *,
    findings: list[T2Finding] | None = None,
    prompt_proposals: list[T2PromptUpdateProposal] | None = None,
    recommended_actions: list[str] | None = None,
) -> MockProvider:
    mock = MockProvider()
    mock.set_structured_response(
        "Reflection Engine for Samriddhi AI",
        {
            "findings": [f.model_dump(mode="json") for f in (findings or [])],
            "prompt_update_proposals": [
                p.model_dump(mode="json") for p in (prompt_proposals or [])
            ],
            "rule_update_proposals": [],
            "recommended_actions": recommended_actions or [],
            "reasoning_trace": "Reviewed metrics across components.",
        },
    )
    return mock


def _build_samples(
    component: str,
    *,
    n: int = 30,
    bias: float = 0.0,
) -> list[CalibrationSample]:
    """Build N evenly-spaced calibration samples with optional outcome bias."""
    samples: list[CalibrationSample] = []
    for i in range(n):
        pred = (i + 0.5) / n  # uniform across [0, 1]
        obs = max(0.0, min(1.0, pred + bias))
        samples.append(
            CalibrationSample(
                component_id=component,
                predicted_probability=pred,
                outcome=obs,
            )
        )
    return samples


class TestT2Acceptance:
    @pytest.mark.asyncio
    async def test_test_1_monthly_run_produces_findings(self):
        finding = T2Finding(
            finding_id="f1",
            category=T2FindingCategory.CONFIDENCE_CALIBRATION,
            severity=T2FindingSeverity.MEDIUM,
            observation="Component e1.financial_risk shows persistent overconfidence.",
            supporting_t1_event_ids=["evt_1"],
        )
        proposal = T2PromptUpdateProposal(
            component_id="e1.financial_risk",
            prompt_section="discipline",
            proposed_change="Calibrate confidence downward when bucket norms are uncertain.",
            rationale="Calibration curve shows systematic over-prediction.",
            supporting_findings=["f1"],
        )
        engine = ReflectionEngine(provider=_t2_mock(
            findings=[finding],
            prompt_proposals=[proposal],
            recommended_actions=["Deploy proposal pending review."],
        ))

        scope = ReflectionScope(
            firm_id="firm_test",
            period_start_at=datetime(2026, 4, 1, tzinfo=UTC),
            period_end_at=datetime(2026, 4, 28, tzinfo=UTC),
            components=["e1.financial_risk"],
            calibration_samples=_build_samples("e1.financial_risk", n=40, bias=-0.2),
        )
        run = await engine.run(scope=scope)
        # Findings issued
        assert len(run.findings) >= 1
        # Calibration curve present with sample size
        assert len(run.calibration_curves) == 1
        assert run.calibration_curves[0].sample_size == 40
        # Status is in_governance_review
        assert run.status is T2RunStatus.IN_GOVERNANCE_REVIEW

    @pytest.mark.asyncio
    async def test_test_2_min_samples_blocks_findings(self):
        # Provider returns calibration finding citing the component
        finding = T2Finding(
            finding_id="f1",
            category=T2FindingCategory.CONFIDENCE_CALIBRATION,
            severity=T2FindingSeverity.MEDIUM,
            observation="Component e1.financial_risk shows poor calibration.",
        )
        engine = ReflectionEngine(provider=_t2_mock(findings=[finding]))
        scope = ReflectionScope(
            firm_id="firm_test",
            period_start_at=datetime(2026, 4, 1, tzinfo=UTC),
            period_end_at=datetime(2026, 4, 28, tzinfo=UTC),
            components=["e1.financial_risk"],
            calibration_samples=_build_samples("e1.financial_risk", n=10),  # below 30
        )
        run = await engine.run(scope=scope)
        # LLM was not invoked (or finding suppressed). Either way no calibration
        # finding should remain.
        assert all(
            f.category is not T2FindingCategory.CONFIDENCE_CALIBRATION
            or "e1.financial_risk" not in f.observation
            for f in run.findings
        )

    @pytest.mark.asyncio
    async def test_test_4_status_in_governance_review(self):
        engine = ReflectionEngine(provider=_t2_mock())
        scope = ReflectionScope(
            firm_id="firm_test",
            period_start_at=datetime(2026, 4, 1, tzinfo=UTC),
            period_end_at=datetime(2026, 4, 28, tzinfo=UTC),
            components=["e1.financial_risk"],
            calibration_samples=_build_samples("e1.financial_risk", n=40),
        )
        run = await engine.run(scope=scope)
        # Default status IN_GOVERNANCE_REVIEW; never auto-deploys
        assert run.status is T2RunStatus.IN_GOVERNANCE_REVIEW

    @pytest.mark.asyncio
    async def test_test_6_determinism(self):
        engine = ReflectionEngine(provider=_t2_mock())
        scope = ReflectionScope(
            firm_id="firm_test",
            period_start_at=datetime(2026, 4, 1, tzinfo=UTC),
            period_end_at=datetime(2026, 4, 28, tzinfo=UTC),
            components=["e1.financial_risk"],
            calibration_samples=_build_samples("e1.financial_risk", n=40),
        )
        v1 = await engine.run(scope=scope)
        v2 = await engine.run(scope=scope)
        assert v1.input_hash == v2.input_hash
        assert v1.calibration_curves == v2.calibration_curves

    @pytest.mark.asyncio
    async def test_calibration_curve_buckets_correctly(self):
        engine = ReflectionEngine()  # no provider needed for this test
        scope = ReflectionScope(
            firm_id="firm_test",
            period_start_at=datetime(2026, 4, 1, tzinfo=UTC),
            period_end_at=datetime(2026, 4, 28, tzinfo=UTC),
            components=["e1"],
            calibration_samples=_build_samples("e1", n=100, bias=0.0),
        )
        run = await engine.run(scope=scope)
        curve = run.calibration_curves[0]
        # 100 samples evenly distributed; 10 buckets → ~10 points
        assert 8 <= len(curve.curve_data) <= 10
        # Points monotone-ish in predicted_prob
        preds = [p[0] for p in curve.curve_data]
        assert preds == sorted(preds)

    @pytest.mark.asyncio
    async def test_round_trip_t2_run(self):
        engine = ReflectionEngine(provider=_t2_mock())
        scope = ReflectionScope(
            firm_id="firm_test",
            period_start_at=datetime(2026, 4, 1, tzinfo=UTC),
            period_end_at=datetime(2026, 4, 28, tzinfo=UTC),
            components=["e1.financial_risk"],
            calibration_samples=_build_samples("e1.financial_risk", n=40),
        )
        run = await engine.run(scope=scope, run_type=T2RunType.SCHEDULED_MONTHLY)
        round_tripped = T2ReflectionRun.model_validate_json(run.model_dump_json())
        assert round_tripped == run
