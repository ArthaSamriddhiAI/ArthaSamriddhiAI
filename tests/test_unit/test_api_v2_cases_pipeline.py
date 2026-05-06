"""Cluster 5 chunk 5.4 — pipeline orchestrator tests.

Pins the FR 20.1 §1.4 mode-specific shapes:

- ``proposed_action`` / ``scenario`` (full pipeline) — stops at
  ``awaiting_decision``.
- ``proposed_action`` with materiality trigger — runs IC1 between
  synthesis and governance.
- ``diagnostic`` — auto-decides; HealthReport stage row written; only
  G1 governance gate runs.
- ``briefing`` — auto-decides; BriefingNote stage row written; no
  governance gates.
- Pipeline expects ``status=gathering_evidence`` to start; rejects
  other start states.
- Each stage emits a ``stub_dispatched`` + ``pipeline_stage_completed``
  T1 event.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from ulid import ULID

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.cases.models  # noqa: F401
import artha.api_v2.d0.industry.models  # noqa: F401
import artha.api_v2.d0.instruments.models  # noqa: F401
import artha.api_v2.d0.macro.models  # noqa: F401
import artha.api_v2.d0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.m2.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.cases import event_names, pipeline, repository
from artha.api_v2.cases.models import Case
from artha.api_v2.cases.pipeline import PipelineError, run_pipeline
from artha.api_v2.cases.state_machine import CaseStatus
from artha.api_v2.investors.models import Household, Investor
from artha.api_v2.observability.models import T1Event
from artha.common.db.base import Base


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_investor(db) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    household = Household(
        household_id=str(ULID()),
        name="Test Household",
        created_by="advisor1",
        created_at=now,
    )
    db.add(household)
    investor = Investor(
        investor_id=str(ULID()),
        household_id=household.household_id,
        name="Pipeline Tester",
        email="p@example.com",
        phone="+919999999990",
        pan="PIPLT1234F",
        age=40,
        advisor_id="advisor1",
        risk_appetite="moderate",
        time_horizon="3_to_5_years",
        kyc_status="pending",
        created_at=now,
        created_by="advisor1",
        created_via="form",
        last_modified_at=now,
        last_modified_by="advisor1",
    )
    db.add(investor)
    await db.commit()
    return investor.investor_id, household.household_id


async def _make_case_in_gathering(
    db,
    investor_id: str,
    *,
    case_mode: str = "proposed_action",
    case_intent: str | None = "rebalance_proposal",
    proposed_action_amount_inr: Decimal | None = None,
    proposed_action_products: list[str] | None = None,
    applicable_evidence_agents: list[str] | None = None,
    is_seed_data: bool = False,
    materiality_manual_flag: bool = False,
) -> Case:
    """Build a case directly in the gathering_evidence state."""
    case = await repository.create_case(
        db,
        investor_id=investor_id,
        household_id=None,
        opened_by="advisor1",
        assigned_to="advisor1",
        case_mode=case_mode,
        case_intent=case_intent,
        dominant_lens=None,
        proposed_action="test action",
        proposed_action_amount_inr=proposed_action_amount_inr,
        proposed_action_products=proposed_action_products or [],
        materiality_manual_flag=materiality_manual_flag,
        created_via="api",
        applicable_evidence_agents=applicable_evidence_agents or [
            "e1_equity_evidence",
            "e1_macro_evidence",
        ],
        is_seed_data=is_seed_data,
    )
    # Mark snapshot pinned (skip the cluster-3 dependency for these
    # focused pipeline tests).
    case.snapshot_bundle_id = "fake-snapshot-id"
    await db.flush()
    await repository.transition_status(
        db, case=case, to_status=CaseStatus.GATHERING_EVIDENCE,
    )
    await db.commit()
    return case


# ---------------------------------------------------------------------------
# Mode-specific pipelines
# ---------------------------------------------------------------------------


class TestProposedActionPipeline:
    @pytest.mark.asyncio
    async def test_non_material_skips_committee(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        case = await _make_case_in_gathering(
            db,
            investor_id,
            case_mode="proposed_action",
            case_intent="rebalance_proposal",
            proposed_action_amount_inr=Decimal("100000"),  # well below threshold
        )

        result = await run_pipeline(db, case=case)
        await db.commit()

        # Stops at awaiting_decision (CIO records decision in chunk 5.5).
        assert result.final_status == CaseStatus.AWAITING_DECISION

        case = await repository.get_case(db, case_id=case.case_id)
        assert case.status == CaseStatus.AWAITING_DECISION.value
        assert case.is_material is False
        assert case.materiality_reason == "no_rule_triggered"

        # All stage rows present except IC1 (skipped) + decision artifact.
        assert (
            await repository.get_portfolio_risk_analytics(
                db, case_id=case.case_id,
            )
        ) is not None
        assert (
            await repository.get_synthesis(db, case_id=case.case_id)
        ) is not None
        assert (
            await repository.get_ic1_deliberation(db, case_id=case.case_id)
        ) is None
        gov = await repository.list_governance_results(db, case_id=case.case_id)
        assert len(gov) == 3  # G1 + G2 + G3
        assert {g.gate for g in gov} == {
            "g1_mandate", "g2_sebi_regulatory", "g3_action_filter",
        }
        assert (
            await repository.get_a1_challenge(db, case_id=case.case_id)
        ) is not None
        assert (
            await repository.get_decision_artifact(db, case_id=case.case_id)
        ) is None

    @pytest.mark.asyncio
    async def test_material_runs_ic1_and_committee(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        case = await _make_case_in_gathering(
            db,
            investor_id,
            case_mode="proposed_action",
            case_intent="new_investment",
            proposed_action_amount_inr=Decimal("20000000"),  # 2 Cr > threshold
            proposed_action_products=["pms"],
        )

        result = await run_pipeline(db, case=case)
        await db.commit()

        case = await repository.get_case(db, case_id=case.case_id)
        assert case.status == CaseStatus.AWAITING_DECISION.value
        assert case.is_material is True
        # Both rules fire.
        assert "MAT_TICKET_SIZE" in case.materiality_reason
        assert "MAT_PRODUCT_PMS_AIF_SIF" in case.materiality_reason

        ic1 = await repository.get_ic1_deliberation(db, case_id=case.case_id)
        assert ic1 is not None
        assert ic1.recommendation == "support_with_conditions"

        assert "ic1_chair" in result.stages_run

    @pytest.mark.asyncio
    async def test_manual_materiality_flag_triggers_ic1(
        self, db, seeded_investor,
    ):
        investor_id, _ = seeded_investor
        case = await _make_case_in_gathering(
            db,
            investor_id,
            case_mode="proposed_action",
            case_intent="rebalance_proposal",
            proposed_action_amount_inr=Decimal("500000"),
            materiality_manual_flag=True,
        )
        await run_pipeline(db, case=case)
        await db.commit()
        case = await repository.get_case(db, case_id=case.case_id)
        assert case.materiality_reason == "manual_flag"
        assert (
            await repository.get_ic1_deliberation(db, case_id=case.case_id)
        ) is not None


class TestDiagnosticPipeline:
    @pytest.mark.asyncio
    async def test_diagnostic_decides_with_health_report(
        self, db, seeded_investor,
    ):
        investor_id, _ = seeded_investor
        case = await _make_case_in_gathering(
            db,
            investor_id,
            case_mode="diagnostic",
            case_intent="portfolio_health",
        )

        result = await run_pipeline(db, case=case)
        await db.commit()

        assert result.final_status == CaseStatus.DECIDED
        case = await repository.get_case(db, case_id=case.case_id)
        assert case.status == CaseStatus.DECIDED.value
        assert case.closed_reason == "decided"

        health = await repository.get_health_report(db, case_id=case.case_id)
        assert health is not None
        assert health.overall_health == "healthy"

        # Diagnostic skips IC1, A1, and G2/G3.
        assert (
            await repository.get_ic1_deliberation(db, case_id=case.case_id)
        ) is None
        assert (
            await repository.get_a1_challenge(db, case_id=case.case_id)
        ) is None
        gov = await repository.list_governance_results(db, case_id=case.case_id)
        assert len(gov) == 1
        assert gov[0].gate == "g1_mandate"


class TestBriefingPipeline:
    @pytest.mark.asyncio
    async def test_briefing_decides_with_briefing_note(
        self, db, seeded_investor,
    ):
        investor_id, _ = seeded_investor
        case = await _make_case_in_gathering(
            db,
            investor_id,
            case_mode="briefing",
            case_intent="meeting_prep",
        )

        result = await run_pipeline(db, case=case)
        await db.commit()

        assert result.final_status == CaseStatus.DECIDED
        case = await repository.get_case(db, case_id=case.case_id)
        assert case.status == CaseStatus.DECIDED.value

        briefing = await repository.get_briefing_note(db, case_id=case.case_id)
        assert briefing is not None

        # Briefing skips governance entirely + IC1 + A1.
        gov = await repository.list_governance_results(db, case_id=case.case_id)
        assert gov == []
        assert (
            await repository.get_ic1_deliberation(db, case_id=case.case_id)
        ) is None


# ---------------------------------------------------------------------------
# Bad start state
# ---------------------------------------------------------------------------


class TestBadStartState:
    @pytest.mark.asyncio
    async def test_pipeline_rejects_non_gathering_start(
        self, db, seeded_investor,
    ):
        investor_id, _ = seeded_investor
        case = await repository.create_case(
            db,
            investor_id=investor_id,
            household_id=None,
            opened_by="advisor1",
            assigned_to="advisor1",
            case_mode="diagnostic",
            case_intent=None,
            dominant_lens=None,
            proposed_action=None,
            proposed_action_amount_inr=None,
            proposed_action_products=[],
            materiality_manual_flag=False,
            created_via="api",
            applicable_evidence_agents=[],
        )
        await db.commit()
        # Still in opening — pipeline should refuse.
        with pytest.raises(PipelineError, match="gathering_evidence"):
            await run_pipeline(db, case=case)


# ---------------------------------------------------------------------------
# T1 telemetry
# ---------------------------------------------------------------------------


class TestT1Telemetry:
    @pytest.mark.asyncio
    async def test_pipeline_stage_events_emitted(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        case = await _make_case_in_gathering(
            db,
            investor_id,
            case_mode="diagnostic",
            case_intent="portfolio_health",
        )
        await run_pipeline(db, case=case)
        await db.commit()

        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == event_names.PIPELINE_STAGE_COMPLETED,
                    )
                )
            ).scalars()
        )
        # portfolio_risk + 2 evidence + synthesis + g1 = 5 stages.
        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_stub_dispatched_emits_per_stage(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        case = await _make_case_in_gathering(
            db,
            investor_id,
            case_mode="diagnostic",
            case_intent="portfolio_health",
        )
        await run_pipeline(db, case=case)
        await db.commit()

        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == event_names.STUB_DISPATCHED,
                    )
                )
            ).scalars()
        )
        # Same 5 stub-dispatched events as stages.
        assert len(events) == 5


# ---------------------------------------------------------------------------
# Seed-tagged production
# ---------------------------------------------------------------------------


class TestSeedTagging:
    @pytest.mark.asyncio
    async def test_seed_case_rows_tagged_seed(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        case = await _make_case_in_gathering(
            db,
            investor_id,
            case_mode="diagnostic",
            case_intent="portfolio_health",
            is_seed_data=True,
        )
        await run_pipeline(db, case=case)
        await db.commit()

        risk = await repository.get_portfolio_risk_analytics(
            db, case_id=case.case_id,
        )
        assert risk.produced_via == "lookup_stub_seed"
        assert risk.is_seed_data is True
        evidence = await repository.list_evidence_verdicts(
            db, case_id=case.case_id,
        )
        for e in evidence:
            assert e.produced_via == "lookup_stub_seed"
            assert e.is_seed_data is True


# Re-export to keep ruff happy
_ = pipeline
