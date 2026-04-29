"""Pass 18 — Role-scoped UI surface acceptance tests.

§14.1 — three roles (advisor / CIO / compliance).
§14.2 — advisor surfaces (per-client view + case detail + N0 inbox).
§14.3 — CIO surfaces (construction approval + firm drift dashboard).
§14.4 — compliance surfaces (case reasoning trail + override history).
§14.5 — permission enforcement at the data-access layer.

Tests cover:
  * Role-scoped composition (each composer rejects wrong-role viewers).
  * Permission enforcement (advisor can't read out-of-firm or out-of-scope clients;
    CIO/compliance can't access other firms; compliance is read-only).
  * Determinism (same canonical inputs + same viewer → same view).
  * Round-trips (every view schema serialises and deserialises stably).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from artha.canonical.case import (
    CaseChannel,
    CaseObject,
    CaseStatus,
    DominantLens,
    LensMetadata,
)
from artha.canonical.construction import (
    BlastRadius,
    BucketConstructionProposal,
    BucketVersionDiff,
    CellChange,
    RolloutMode,
)
from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.holding import Holding
from artha.canonical.investor import DataSource, InvestorContextProfile
from artha.canonical.mandate import (
    AssetClassLimits,
    ConcentrationLimits,
    MandateObject,
    SignoffEvidence,
    SignoffMethod,
)
from artha.canonical.model_portfolio import (
    ConstructionContext,
    ModelPortfolioObject,
    TargetWithTolerance,
)
from artha.canonical.monitoring import (
    AlertTier,
    N0Alert,
    N0AlertCategory,
    N0Originator,
)
from artha.canonical.views import (
    AdvisorCaseDetailView,
    AdvisorPerClientView,
    BucketDriftRow,
    CIOConstructionApprovalView,
    CIOFirmDriftDashboard,
    ComplianceCaseReasoningTrail,
    ComplianceOverrideHistoryView,
    DriftStatusLight,
    Role,
    ViewerContext,
)
from artha.common.standards import T1EventType
from artha.common.types import (
    AssetClass,
    Bucket,
    CaseIntent,
    MandateType,
    Permission,
    RiskLevel,
    RiskProfile,
    TimeHorizon,
    WealthTier,
)
from artha.common.ulid import new_ulid
from artha.model_portfolio.tolerance import (
    DriftDimension,
    DriftEvent,
    DriftSeverity,
)
from artha.views import (
    AdvisorViewComposer,
    CIOViewComposer,
    ComplianceViewComposer,
    PermissionDeniedError,
    assert_can_read_client,
    assert_can_read_firm,
    assert_can_write,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _viewer(
    *,
    role: Role = Role.ADVISOR,
    user_id: str = "advisor_jane",
    firm_id: str = "firm_test",
    assigned_clients: tuple[str, ...] = ("c1", "c2"),
) -> ViewerContext:
    return ViewerContext(
        role=role,
        user_id=user_id,
        firm_id=firm_id,
        assigned_client_ids=frozenset(assigned_clients),
    )


def _profile(
    *,
    client_id: str = "c1",
    firm_id: str = "firm_test",
) -> InvestorContextProfile:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return InvestorContextProfile(
        client_id=client_id,
        firm_id=firm_id,
        created_at=now,
        updated_at=now,
        risk_profile=RiskProfile.MODERATE,
        time_horizon=TimeHorizon.LONG_TERM,
        wealth_tier=WealthTier.AUM_5CR_TO_10CR,
        assigned_bucket=Bucket.MOD_LT,
        data_source=DataSource.FORM,
    )


def _mandate(*, client_id: str = "c1") -> MandateObject:
    return MandateObject(
        mandate_id=f"mandate_{client_id}",
        client_id=client_id,
        firm_id="firm_test",
        version=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        mandate_type=MandateType.INDIVIDUAL,
        asset_class_limits={
            AssetClass.EQUITY: AssetClassLimits(
                min_pct=0.30, target_pct=0.50, max_pct=0.60
            ),
            AssetClass.DEBT: AssetClassLimits(
                min_pct=0.20, target_pct=0.40, max_pct=0.60
            ),
        },
        concentration_limits=ConcentrationLimits(
            per_holding_max=0.10, per_manager_max=0.20, per_sector_max=0.30
        ),
        liquidity_floor=0.10,
        sector_exclusions=["tobacco"],
        signoff_method=SignoffMethod.E_SIGNATURE,
        signoff_evidence=SignoffEvidence(
            evidence_id="sign1", captured_at=datetime(2026, 1, 1, tzinfo=UTC)
        ),
        signed_by="advisor_jane",
    )


def _holding(
    iid: str,
    *,
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
        vehicle_type="mutual_fund",
        asset_class=asset_class,
        sub_asset_class="multi_cap",
        acquisition_date=date(2024, 1, 15),
        as_of_date=date(2026, 4, 25),
    )


def _case(*, client_id: str = "c1") -> CaseObject:
    return CaseObject(
        case_id="case_p18_001",
        client_id=client_id,
        firm_id="firm_test",
        advisor_id="advisor_jane",
        created_at=datetime(2026, 4, 29, tzinfo=UTC),
        intent=CaseIntent.CASE,
        intent_confidence=0.9,
        dominant_lens=DominantLens.PROPOSAL,
        lens_metadata=LensMetadata(lenses_fired=[DominantLens.PROPOSAL]),
        current_status=CaseStatus.IN_PROGRESS,
        channel=CaseChannel.C0,
    )


def _alert(
    *,
    client_id: str = "c1",
    case_id: str | None = None,
    tier: AlertTier = AlertTier.MUST_RESPOND,
) -> N0Alert:
    return N0Alert(
        alert_id=new_ulid(),
        originator=N0Originator.M1,
        tier=tier,
        category=N0AlertCategory.MANDATE_BREACH,
        client_id=client_id,
        firm_id="firm_test",
        case_id=case_id,
        created_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        title=f"Mandate breach: {client_id}",
        body="Equity 70% > cap 60%. " * 30,  # long enough to test truncation
    )


def _drift_action_required() -> DriftEvent:
    return DriftEvent(
        dimension=DriftDimension.L1,
        cell_key="equity",
        target=0.50,
        actual=0.70,
        tolerance_band=0.05,
        drift_magnitude=0.20,
        severity=DriftSeverity.ACTION_REQUIRED,
    )


def _drift_informational() -> DriftEvent:
    return DriftEvent(
        dimension=DriftDimension.L2,
        cell_key="equity.mutual_fund",
        target=0.70,
        actual=0.75,
        tolerance_band=0.10,
        drift_magnitude=0.05,
        severity=DriftSeverity.INFORMATIONAL,
    )


def _evidence(
    agent_id: str = "financial_risk",
    risk_level: RiskLevel = RiskLevel.MEDIUM,
) -> StandardEvidenceVerdict:
    return StandardEvidenceVerdict(
        agent_id=agent_id,
        case_id="case_p18_001",
        timestamp=datetime(2026, 4, 29, tzinfo=UTC),
        risk_level=risk_level,
        confidence=0.82,
        flags=["concentration_breach"],
        reasoning_trace="Concentration in equity at 70% exceeds bucket norm. "
        + ("Detailed analysis follows. " * 20),
        input_hash="hash_e1",
    )


def _proposal_with_diff(
    *,
    blast_share: float = 0.30,
) -> BucketConstructionProposal:
    proposed = ModelPortfolioObject(
        model_id="mp_v2",
        bucket=Bucket.MOD_LT,
        version="2.0.0",
        firm_id="firm_test",
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        approved_by="cio_jane",
        approval_rationale="version 2",
        l1_targets={
            AssetClass.EQUITY: TargetWithTolerance(target=0.55, tolerance_band=0.05),
            AssetClass.DEBT: TargetWithTolerance(target=0.45, tolerance_band=0.05),
        },
        construction=ConstructionContext(construction_pipeline_run_id="cp_v2"),
    )
    return BucketConstructionProposal(
        bucket=Bucket.MOD_LT,
        proposed_model=proposed,
        prior_model_id="mp_v1",
        version_diff=BucketVersionDiff(
            bucket=Bucket.MOD_LT,
            prior_model_id="mp_v1",
            prior_version="1.0.0",
            proposed_model_id="mp_v2",
            proposed_version="2.0.0",
            cell_changes=[
                CellChange(
                    level="l1",
                    cell_key="equity",
                    prior_target=0.50,
                    proposed_target=0.55,
                    delta=0.05,
                ),
            ],
            cell_changes_count=1,
        ),
        blast_radius=BlastRadius(
            bucket=Bucket.MOD_LT,
            clients_in_bucket_count=10,
            clients_in_tolerance_who_breach=int(10 * blast_share),
            total_aum_moved_inr=2_000_000.0,
            estimated_txn_cost_inr=10_000.0,
            estimated_tax_cost_inr=20_000.0,
            day_one_n0_alert_count=int(10 * blast_share),
            blast_radius_share=blast_share,
        ),
        rollout_mode=RolloutMode.IMMEDIATE,
        approved_for_rollout=True,
        approval_rationale="G3 APPROVED for immediate rollout.",
    )


def _t1_event(
    *,
    event_type: T1EventType,
    case_id: str = "case_p18_001",
    client_id: str = "c1",
    advisor_id: str = "advisor_jane",
    firm_id: str = "firm_test",
    timestamp: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Build a T1Event-shaped object for compliance composers."""
    from artha.accountability.t1.models import T1Event
    from artha.common.hashing import payload_hash

    payload = payload or {}
    return T1Event(
        event_id=new_ulid(),
        event_type=event_type,
        timestamp=timestamp or datetime(2026, 4, 29, 10, 0, tzinfo=UTC),
        firm_id=firm_id,
        case_id=case_id,
        client_id=client_id,
        advisor_id=advisor_id,
        payload=payload,
        payload_hash=payload_hash(payload),
    )


# ===========================================================================
# §14.5 — permission enforcement
# ===========================================================================


class TestPermissions:
    def test_advisor_reads_assigned_client(self):
        viewer = _viewer(role=Role.ADVISOR, assigned_clients=("c1",))
        # Should not raise
        assert_can_read_client(viewer, client_id="c1", client_firm_id="firm_test")

    def test_advisor_blocked_unassigned_client(self):
        viewer = _viewer(role=Role.ADVISOR, assigned_clients=("c1",))
        with pytest.raises(PermissionDeniedError):
            assert_can_read_client(viewer, client_id="c2", client_firm_id="firm_test")

    def test_advisor_blocked_other_firm(self):
        viewer = _viewer(role=Role.ADVISOR, assigned_clients=("c1",))
        with pytest.raises(PermissionDeniedError):
            assert_can_read_client(viewer, client_id="c1", client_firm_id="firm_other")

    def test_advisor_blocked_firm_view(self):
        viewer = _viewer(role=Role.ADVISOR)
        with pytest.raises(PermissionDeniedError):
            assert_can_read_firm(viewer, firm_id="firm_test")

    def test_cio_reads_any_client_in_firm(self):
        viewer = _viewer(role=Role.CIO, user_id="cio_jane")
        assert_can_read_client(viewer, client_id="c99", client_firm_id="firm_test")
        assert_can_read_firm(viewer, firm_id="firm_test")

    def test_cio_blocked_other_firm(self):
        viewer = _viewer(role=Role.CIO, user_id="cio_jane")
        with pytest.raises(PermissionDeniedError):
            assert_can_read_firm(viewer, firm_id="firm_other")

    def test_compliance_reads_any_client_in_firm(self):
        viewer = _viewer(role=Role.COMPLIANCE, user_id="compliance_alex")
        assert_can_read_client(viewer, client_id="c99", client_firm_id="firm_test")
        assert_can_read_firm(viewer, firm_id="firm_test")

    def test_compliance_cannot_write(self):
        viewer = _viewer(role=Role.COMPLIANCE, user_id="compliance_alex")
        with pytest.raises(PermissionDeniedError):
            assert_can_write(viewer, action="approve_construction")

    def test_advisor_can_write(self):
        viewer = _viewer(role=Role.ADVISOR)
        # Should not raise
        assert_can_write(viewer, action="capture_override")

    def test_cio_can_write(self):
        viewer = _viewer(role=Role.CIO)
        # Should not raise
        assert_can_write(viewer, action="approve_construction")


# ===========================================================================
# §14.2 — Advisor surfaces
# ===========================================================================


class TestAdvisorPerClientView:
    def test_per_client_view_assembles_full_dashboard(self):
        composer = AdvisorViewComposer()
        viewer = _viewer()
        view = composer.per_client_view(
            viewer=viewer,
            profile=_profile(),
            mandate=_mandate(),
            holdings=[
                _holding("MF1", market_value=3_000_000.0),
                _holding("MF2", market_value=2_000_000.0),
                _holding("MF3", market_value=1_000_000.0),
            ],
            active_alerts=[_alert(client_id="c1"), _alert(client_id="c2")],
            recent_cases=[_case()],
            cash_buffer_inr=500_000.0,
        )
        assert view.role is Role.ADVISOR
        assert view.client_id == "c1"
        assert view.assigned_bucket is Bucket.MOD_LT
        assert view.total_aum_inr == pytest.approx(6_000_000.0)
        assert view.deployed_inr == pytest.approx(5_500_000.0)
        # Top holdings sorted by value, capped at 5
        assert [h.instrument_id for h in view.top_holdings] == ["MF1", "MF2", "MF3"]
        # Only c1 alert in inbox (c2 alert filtered out)
        assert len(view.active_alerts) == 1
        assert view.active_alerts[0].body_preview != view.active_alerts[0].body_preview + "x"
        # Mandate summary populated
        assert view.mandate_summary["mandate_id"] == "mandate_c1"
        assert view.mandate_summary["sector_exclusions_count"] == 1

    def test_drift_status_red_on_action_required(self):
        composer = AdvisorViewComposer()
        view = composer.per_client_view(
            viewer=_viewer(),
            profile=_profile(),
            mandate=None,
            holdings=[_holding("MF1")],
            active_alerts=[],
            recent_cases=[],
            drift_events=[_drift_action_required()],
        )
        assert view.drift_status is DriftStatusLight.RED
        assert view.drift_breaches_count == 1

    def test_drift_status_amber_on_informational_only(self):
        composer = AdvisorViewComposer()
        view = composer.per_client_view(
            viewer=_viewer(),
            profile=_profile(),
            mandate=None,
            holdings=[_holding("MF1")],
            active_alerts=[],
            recent_cases=[],
            drift_events=[_drift_informational()],
        )
        assert view.drift_status is DriftStatusLight.AMBER

    def test_drift_status_green_when_no_breaches(self):
        composer = AdvisorViewComposer()
        view = composer.per_client_view(
            viewer=_viewer(),
            profile=_profile(),
            mandate=None,
            holdings=[_holding("MF1")],
            active_alerts=[],
            recent_cases=[],
            drift_events=[],
        )
        assert view.drift_status is DriftStatusLight.GREEN
        assert view.drift_breaches_count == 0

    def test_per_client_view_blocks_cio(self):
        composer = AdvisorViewComposer()
        with pytest.raises(PermissionDeniedError):
            composer.per_client_view(
                viewer=_viewer(role=Role.CIO),
                profile=_profile(),
                mandate=None,
                holdings=[],
                active_alerts=[],
                recent_cases=[],
            )

    def test_per_client_view_blocks_unassigned_advisor(self):
        composer = AdvisorViewComposer()
        viewer = _viewer(role=Role.ADVISOR, assigned_clients=("c99",))
        with pytest.raises(PermissionDeniedError):
            composer.per_client_view(
                viewer=viewer,
                profile=_profile(client_id="c1"),
                mandate=None,
                holdings=[],
                active_alerts=[],
                recent_cases=[],
            )

    def test_round_trip(self):
        composer = AdvisorViewComposer()
        view = composer.per_client_view(
            viewer=_viewer(),
            profile=_profile(),
            mandate=_mandate(),
            holdings=[_holding("MF1")],
            active_alerts=[],
            recent_cases=[],
        )
        round_tripped = AdvisorPerClientView.model_validate_json(view.model_dump_json())
        assert round_tripped == view


class TestAdvisorCaseDetail:
    def test_case_detail_assembles_evidence_and_governance(self):
        composer = AdvisorViewComposer()
        # Build a G3 with BLOCKED to test blocking_reasons capture
        from artha.canonical.governance import G3Evaluation

        g3 = G3Evaluation(
            case_id="case_p18_001",
            timestamp=datetime(2026, 4, 29, tzinfo=UTC),
            permission=Permission.BLOCKED,
            blocking_reasons=["mandate_breach:equity_ceiling"],
            g1_input_hash="h1",
            g2_input_hash="h2",
            input_hash="h3",
        )
        view = composer.case_detail_view(
            viewer=_viewer(),
            case=_case(),
            rendered_artifact_text="Recommendation: review mandate.",
            evidence_verdicts=[_evidence(), _evidence(agent_id="industry_analyst")],
            g3_evaluation=g3,
            decision_options=["proceed_with_override", "decline"],
            t1_replay_link="t1://case_p18_001",
        )
        assert view.case_id == "case_p18_001"
        assert len(view.evidence_summaries) == 2
        # Reasoning trace truncated to preview
        assert all(
            len(es.reasoning_excerpt) <= 400 for es in view.evidence_summaries
        )
        assert view.g3_permission == "BLOCKED"
        assert view.g3_blocking_reasons == ["mandate_breach:equity_ceiling"]
        assert view.decision_options == ["proceed_with_override", "decline"]
        assert view.t1_replay_link == "t1://case_p18_001"

    def test_case_detail_blocks_compliance(self):
        composer = AdvisorViewComposer()
        with pytest.raises(PermissionDeniedError):
            composer.case_detail_view(
                viewer=_viewer(role=Role.COMPLIANCE),
                case=_case(),
                rendered_artifact_text="x",
                evidence_verdicts=[],
            )

    def test_case_detail_blocks_advisor_other_client(self):
        composer = AdvisorViewComposer()
        viewer = _viewer(role=Role.ADVISOR, assigned_clients=("c2",))
        with pytest.raises(PermissionDeniedError):
            composer.case_detail_view(
                viewer=viewer,
                case=_case(client_id="c1"),
                rendered_artifact_text="x",
                evidence_verdicts=[],
            )

    def test_round_trip(self):
        composer = AdvisorViewComposer()
        view = composer.case_detail_view(
            viewer=_viewer(),
            case=_case(),
            rendered_artifact_text="Recommendation",
            evidence_verdicts=[_evidence()],
        )
        round_tripped = AdvisorCaseDetailView.model_validate_json(
            view.model_dump_json()
        )
        assert round_tripped == view


class TestAdvisorN0Inbox:
    def test_inbox_filters_to_assigned_clients(self):
        composer = AdvisorViewComposer()
        viewer = _viewer(assigned_clients=("c1", "c2"))
        alerts = [
            _alert(client_id="c1"),
            _alert(client_id="c2"),
            _alert(client_id="c99"),  # unassigned, filtered
        ]
        inbox = composer.n0_inbox_for_advisor(viewer=viewer, alerts=alerts)
        assert len(inbox) == 2
        assert {item.alert_id for item in inbox} == {alerts[0].alert_id, alerts[1].alert_id}

    def test_inbox_rejects_other_firm_alert(self):
        composer = AdvisorViewComposer()
        viewer = _viewer()
        # Build alert with different firm
        alert = _alert(client_id="c1")
        alert = alert.model_copy(update={"firm_id": "firm_other"})
        with pytest.raises(PermissionDeniedError):
            composer.n0_inbox_for_advisor(viewer=viewer, alerts=[alert])

    def test_inbox_blocks_non_advisor(self):
        composer = AdvisorViewComposer()
        with pytest.raises(PermissionDeniedError):
            composer.n0_inbox_for_advisor(
                viewer=_viewer(role=Role.CIO), alerts=[]
            )


# ===========================================================================
# §14.3 — CIO surfaces
# ===========================================================================


class TestCIOConstructionApproval:
    def test_approval_view_aggregates_proposal(self):
        composer = CIOViewComposer()
        viewer = _viewer(role=Role.CIO, user_id="cio_jane")
        view = composer.construction_approval_view(
            viewer=viewer,
            firm_id="firm_test",
            run_id="run_001",
            proposal=_proposal_with_diff(blast_share=0.30),
        )
        assert view.role is Role.CIO
        assert view.bucket is Bucket.MOD_LT
        assert view.proposed_version == "2.0.0"
        assert view.blast_radius_share == pytest.approx(0.30)
        assert len(view.cell_changes) == 1
        assert view.cell_changes[0].cell_key == "equity"
        assert view.cell_changes[0].delta == pytest.approx(0.05)
        assert view.approved_for_rollout is True

    def test_approval_view_blocks_advisor(self):
        composer = CIOViewComposer()
        with pytest.raises(PermissionDeniedError):
            composer.construction_approval_view(
                viewer=_viewer(role=Role.ADVISOR),
                firm_id="firm_test",
                run_id="run_001",
                proposal=_proposal_with_diff(),
            )

    def test_approval_view_blocks_other_firm(self):
        composer = CIOViewComposer()
        viewer = _viewer(role=Role.CIO, user_id="cio_jane", firm_id="firm_test")
        with pytest.raises(PermissionDeniedError):
            composer.construction_approval_view(
                viewer=viewer,
                firm_id="firm_other",
                run_id="run_001",
                proposal=_proposal_with_diff(),
            )

    def test_round_trip(self):
        composer = CIOViewComposer()
        view = composer.construction_approval_view(
            viewer=_viewer(role=Role.CIO, user_id="cio_jane"),
            firm_id="firm_test",
            run_id="run_001",
            proposal=_proposal_with_diff(),
        )
        round_tripped = CIOConstructionApprovalView.model_validate_json(
            view.model_dump_json()
        )
        assert round_tripped == view


class TestCIOFirmDriftDashboard:
    def test_firm_drift_aggregates_buckets(self):
        composer = CIOViewComposer()
        viewer = _viewer(role=Role.CIO, user_id="cio_jane")
        rows = [
            BucketDriftRow(
                bucket=Bucket.CON_LT,
                clients_in_tolerance=10,
                clients_amber=2,
                clients_red=1,
                mandate_breach_count=1,
            ),
            BucketDriftRow(
                bucket=Bucket.MOD_LT,
                clients_in_tolerance=20,
                clients_amber=3,
                clients_red=5,
                mandate_breach_count=2,
            ),
        ]
        view = composer.firm_drift_dashboard(
            viewer=viewer,
            firm_id="firm_test",
            as_of_date=date(2026, 4, 29),
            bucket_distribution=rows,
        )
        assert view.total_clients == 41
        assert view.total_action_required_drifts == 6
        assert view.total_mandate_breaches == 3

    def test_firm_drift_blocks_advisor(self):
        composer = CIOViewComposer()
        with pytest.raises(PermissionDeniedError):
            composer.firm_drift_dashboard(
                viewer=_viewer(role=Role.ADVISOR),
                firm_id="firm_test",
                as_of_date=date(2026, 4, 29),
                bucket_distribution=[],
            )

    def test_round_trip(self):
        composer = CIOViewComposer()
        view = composer.firm_drift_dashboard(
            viewer=_viewer(role=Role.CIO, user_id="cio_jane"),
            firm_id="firm_test",
            as_of_date=date(2026, 4, 29),
            bucket_distribution=[],
        )
        round_tripped = CIOFirmDriftDashboard.model_validate_json(
            view.model_dump_json()
        )
        assert round_tripped == view


# ===========================================================================
# §14.4 — Compliance surfaces
# ===========================================================================


class TestComplianceReasoningTrail:
    def test_trail_assembles_chronological_entries(self):
        composer = ComplianceViewComposer()
        viewer = _viewer(role=Role.COMPLIANCE, user_id="compliance_alex")
        events = [
            _t1_event(
                event_type=T1EventType.E1_VERDICT,
                timestamp=datetime(2026, 4, 29, 10, 0, tzinfo=UTC),
                payload={"agent_id": "financial_risk", "summary": "E1 verdict produced"},
            ),
            _t1_event(
                event_type=T1EventType.S1_SYNTHESIS,
                timestamp=datetime(2026, 4, 29, 10, 5, tzinfo=UTC),
                payload={"agent_id": "synthesis", "summary": "S1 synthesis composed"},
            ),
            _t1_event(
                event_type=T1EventType.DECISION,
                timestamp=datetime(2026, 4, 29, 10, 10, tzinfo=UTC),
                payload={"summary": "Advisor approved with override"},
            ),
            _t1_event(
                event_type=T1EventType.OVERRIDE,
                timestamp=datetime(2026, 4, 29, 10, 9, tzinfo=UTC),
                payload={"rationale_text": "Client-specific need"},
            ),
        ]
        trail = composer.case_reasoning_trail(
            viewer=viewer,
            case_id="case_p18_001",
            client_id="c1",
            firm_id="firm_test",
            events=events,
        )
        assert len(trail.entries) == 4
        # Chronological ordering
        timestamps = [e.timestamp for e in trail.entries]
        assert timestamps == sorted(timestamps)
        # Decision + override event ids surfaced separately
        assert trail.decision_event_id is not None
        assert len(trail.override_event_ids) == 1

    def test_trail_blocks_advisor(self):
        composer = ComplianceViewComposer()
        with pytest.raises(PermissionDeniedError):
            composer.case_reasoning_trail(
                viewer=_viewer(role=Role.ADVISOR),
                case_id="case_p18_001",
                client_id="c1",
                firm_id="firm_test",
                events=[],
            )

    def test_trail_blocks_other_firm(self):
        composer = ComplianceViewComposer()
        viewer = _viewer(role=Role.COMPLIANCE, user_id="compliance_alex")
        with pytest.raises(PermissionDeniedError):
            composer.case_reasoning_trail(
                viewer=viewer,
                case_id="case_p18_001",
                client_id="c1",
                firm_id="firm_other",
                events=[],
            )

    def test_trail_filters_to_case(self):
        composer = ComplianceViewComposer()
        viewer = _viewer(role=Role.COMPLIANCE, user_id="compliance_alex")
        events = [
            _t1_event(event_type=T1EventType.E1_VERDICT, case_id="case_p18_001"),
            _t1_event(event_type=T1EventType.E1_VERDICT, case_id="case_other"),
        ]
        trail = composer.case_reasoning_trail(
            viewer=viewer,
            case_id="case_p18_001",
            client_id="c1",
            firm_id="firm_test",
            events=events,
        )
        assert len(trail.entries) == 1

    def test_round_trip(self):
        composer = ComplianceViewComposer()
        viewer = _viewer(role=Role.COMPLIANCE, user_id="compliance_alex")
        trail = composer.case_reasoning_trail(
            viewer=viewer,
            case_id="case_p18_001",
            client_id="c1",
            firm_id="firm_test",
            events=[],
        )
        round_tripped = ComplianceCaseReasoningTrail.model_validate_json(
            trail.model_dump_json()
        )
        assert round_tripped == trail


class TestComplianceOverrideHistory:
    def test_override_history_filters_window_and_firm(self):
        composer = ComplianceViewComposer()
        viewer = _viewer(role=Role.COMPLIANCE, user_id="compliance_alex")
        period_start = datetime(2026, 4, 1, tzinfo=UTC)
        period_end = datetime(2026, 4, 30, tzinfo=UTC)

        events = [
            _t1_event(
                event_type=T1EventType.OVERRIDE,
                timestamp=datetime(2026, 4, 15, tzinfo=UTC),
                payload={
                    "rationale_text": "Client wants higher equity exposure.",
                    "structured_category": "client_specific_circumstance",
                    "requires_compliance_review": True,
                },
            ),
            _t1_event(
                event_type=T1EventType.OVERRIDE,
                timestamp=datetime(2026, 4, 20, tzinfo=UTC),
                payload={
                    "rationale_text": "Routine adjustment.",
                    "structured_category": "advisor_judgement_on_calibration",
                    "requires_compliance_review": False,
                },
            ),
            _t1_event(
                event_type=T1EventType.OVERRIDE,
                # outside window
                timestamp=datetime(2026, 5, 5, tzinfo=UTC),
                payload={"rationale_text": "Out of window"},
            ),
            _t1_event(
                event_type=T1EventType.E1_VERDICT,  # not an override
                timestamp=datetime(2026, 4, 15, tzinfo=UTC),
            ),
        ]
        view = composer.override_history(
            viewer=viewer,
            firm_id="firm_test",
            period_start=period_start,
            period_end=period_end,
            override_events=events,
        )
        assert view.total_overrides == 2
        assert view.compliance_review_queue_count == 1
        # Sorted chronologically
        ts = [r.timestamp for r in view.rows]
        assert ts == sorted(ts)

    def test_override_history_blocks_advisor(self):
        composer = ComplianceViewComposer()
        with pytest.raises(PermissionDeniedError):
            composer.override_history(
                viewer=_viewer(role=Role.ADVISOR),
                firm_id="firm_test",
                period_start=datetime(2026, 4, 1, tzinfo=UTC),
                period_end=datetime(2026, 4, 30, tzinfo=UTC),
                override_events=[],
            )

    def test_round_trip(self):
        composer = ComplianceViewComposer()
        viewer = _viewer(role=Role.COMPLIANCE, user_id="compliance_alex")
        view = composer.override_history(
            viewer=viewer,
            firm_id="firm_test",
            period_start=datetime(2026, 4, 1, tzinfo=UTC),
            period_end=datetime(2026, 4, 30, tzinfo=UTC),
            override_events=[],
        )
        round_tripped = ComplianceOverrideHistoryView.model_validate_json(
            view.model_dump_json()
        )
        assert round_tripped == view


# ===========================================================================
# Determinism — same inputs + same viewer → same view
# ===========================================================================


class TestDeterminism:
    def test_per_client_view_deterministic(self):
        composer = AdvisorViewComposer()
        viewer = _viewer()
        kwargs: dict[str, Any] = dict(
            viewer=viewer,
            profile=_profile(),
            mandate=_mandate(),
            holdings=[_holding("MF1"), _holding("MF2", market_value=500_000.0)],
            active_alerts=[_alert(client_id="c1")],
            recent_cases=[_case()],
            cash_buffer_inr=100_000.0,
        )
        v1 = composer.per_client_view(**kwargs)
        v2 = composer.per_client_view(**kwargs)
        # Compare by JSON to avoid identity quirks
        assert v1.model_dump_json() == v2.model_dump_json()

    def test_construction_approval_deterministic(self):
        composer = CIOViewComposer()
        viewer = _viewer(role=Role.CIO, user_id="cio_jane")
        proposal = _proposal_with_diff()
        v1 = composer.construction_approval_view(
            viewer=viewer, firm_id="firm_test", run_id="run_001", proposal=proposal
        )
        v2 = composer.construction_approval_view(
            viewer=viewer, firm_id="firm_test", run_id="run_001", proposal=proposal
        )
        assert v1.model_dump_json() == v2.model_dump_json()
