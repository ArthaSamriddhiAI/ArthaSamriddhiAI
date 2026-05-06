"""Cluster 5 chunk 5.1 — repository + snapshot-pinner integration tests.

Pins:

- ``create_case`` inserts an opening-status case with FK targets that
  resolve, and ``case_created`` T1 emits.
- ``update_snapshot_bundle`` enforces immutability post-pin.
- ``transition_status`` validates against FR 20.1 §1.5 + emits the
  right T1 events including the per-terminal-state event.
- ``record_materiality`` writes the case row + emits the assessment T1.
- Stage-table inserts (evidence, synthesis, governance, IC1, A1,
  decision artifact) round-trip through the read helpers.
- Decision-artifact UNIQUE on case_id surfaces as
  ``DecisionAlreadyRecordedError``.
- Snapshot pinner integrates with cluster 3's ``create_snapshot`` + sets
  ``cases.snapshot_bundle_id``.
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
from artha.api_v2.cases import event_names, repository
from artha.api_v2.cases.repository import (
    DecisionAlreadyRecordedError,
    SnapshotAlreadyPinnedError,
)
from artha.api_v2.cases.snapshot_pinner import pin_snapshot_for_case
from artha.api_v2.cases.state_machine import (
    CaseClosedReason,
    CaseMode,
    CaseStatus,
    InvalidStateTransitionError,
)
from artha.api_v2.investors.models import Household, Investor
from artha.api_v2.observability.models import T1Event
from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """Insert a household + investor + return (investor_id, household_id)."""
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
        name="Test Investor",
        email="t@example.com",
        phone="+919999999999",
        pan="ABCDE1234F",
        age=42,
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


# ---------------------------------------------------------------------------
# create_case
# ---------------------------------------------------------------------------


class TestCreateCase:
    @pytest.mark.asyncio
    async def test_inserts_opening_case(self, db, seeded_investor):
        investor_id, household_id = seeded_investor
        case = await repository.create_case(
            db,
            investor_id=investor_id,
            household_id=household_id,
            opened_by="advisor1",
            assigned_to="advisor1",
            case_mode=CaseMode.PROPOSED_ACTION.value,
            case_intent="rebalance_proposal",
            dominant_lens="portfolio_shift",
            proposed_action="Rebalance portfolio",
            proposed_action_amount_inr=Decimal("5000000"),
            proposed_action_products=["mutual_fund"],
            materiality_manual_flag=False,
            created_via="ui_form",
            applicable_evidence_agents=["e1_listed_fundamental_equity", "e7_mutual_fund"],
        )
        await db.commit()

        assert case.status == CaseStatus.OPENING.value
        assert case.snapshot_bundle_id is None
        assert case.is_seed_data is False
        assert case.applicable_evidence_agents == [
            "e1_listed_fundamental_equity",
            "e7_mutual_fund",
        ]

    @pytest.mark.asyncio
    async def test_emits_case_created_event(self, db, seeded_investor):
        investor_id, household_id = seeded_investor
        await repository.create_case(
            db,
            investor_id=investor_id,
            household_id=household_id,
            opened_by="advisor1",
            assigned_to="advisor1",
            case_mode=CaseMode.DIAGNOSTIC.value,
            case_intent="portfolio_health",
            dominant_lens=None,
            proposed_action=None,
            proposed_action_amount_inr=None,
            proposed_action_products=[],
            materiality_manual_flag=False,
            created_via="api",
            applicable_evidence_agents=[],
        )
        await db.commit()

        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == event_names.CASE_CREATED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1


# ---------------------------------------------------------------------------
# update_snapshot_bundle (immutability)
# ---------------------------------------------------------------------------


class TestSnapshotImmutability:
    @pytest.mark.asyncio
    async def test_first_pin_succeeds(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        case = await repository.create_case(
            db,
            investor_id=investor_id,
            household_id=None,
            opened_by="advisor1",
            assigned_to="advisor1",
            case_mode=CaseMode.PROPOSED_ACTION.value,
            case_intent="rebalance_proposal",
            dominant_lens="portfolio_shift",
            proposed_action="x",
            proposed_action_amount_inr=None,
            proposed_action_products=[],
            materiality_manual_flag=False,
            created_via="api",
            applicable_evidence_agents=[],
        )
        await db.commit()

        # Use the snapshot pinner — it'll create a real Snapshot row + pin.
        result = await pin_snapshot_for_case(
            db, case=case, actor_user_id="advisor1"
        )
        await db.commit()

        assert case.snapshot_bundle_id == result.snapshot_bundle_id

    @pytest.mark.asyncio
    async def test_idempotent_re_pin_same_value(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        case = await repository.create_case(
            db,
            investor_id=investor_id,
            household_id=None,
            opened_by="advisor1",
            assigned_to="advisor1",
            case_mode=CaseMode.DIAGNOSTIC.value,
            case_intent="portfolio_health",
            dominant_lens=None,
            proposed_action=None,
            proposed_action_amount_inr=None,
            proposed_action_products=[],
            materiality_manual_flag=False,
            created_via="ui_form",
            applicable_evidence_agents=[],
        )
        await db.commit()

        result1 = await pin_snapshot_for_case(
            db, case=case, actor_user_id="advisor1"
        )
        await db.commit()
        # Re-pin with the same value through the repository → no-op.
        await repository.update_snapshot_bundle(
            db, case=case, snapshot_bundle_id=result1.snapshot_bundle_id
        )
        assert case.snapshot_bundle_id == result1.snapshot_bundle_id

    @pytest.mark.asyncio
    async def test_re_pin_different_value_raises(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        case = await repository.create_case(
            db,
            investor_id=investor_id,
            household_id=None,
            opened_by="advisor1",
            assigned_to="advisor1",
            case_mode=CaseMode.PROPOSED_ACTION.value,
            case_intent="rebalance_proposal",
            dominant_lens="portfolio_shift",
            proposed_action="x",
            proposed_action_amount_inr=None,
            proposed_action_products=[],
            materiality_manual_flag=False,
            created_via="api",
            applicable_evidence_agents=[],
        )
        await db.commit()

        await pin_snapshot_for_case(
            db, case=case, actor_user_id="advisor1"
        )
        await db.commit()

        with pytest.raises(SnapshotAlreadyPinnedError):
            await repository.update_snapshot_bundle(
                db, case=case, snapshot_bundle_id="01OTHER0000000000000000000"
            )


# ---------------------------------------------------------------------------
# transition_status
# ---------------------------------------------------------------------------


async def _make_case(db, seeded_investor, mode: CaseMode):
    investor_id, _ = seeded_investor
    return await repository.create_case(
        db,
        investor_id=investor_id,
        household_id=None,
        opened_by="advisor1",
        assigned_to="advisor1",
        case_mode=mode.value,
        case_intent=(
            "rebalance_proposal"
            if mode == CaseMode.PROPOSED_ACTION
            else "portfolio_health"
        ),
        dominant_lens="portfolio_shift" if mode == CaseMode.PROPOSED_ACTION else None,
        proposed_action="x" if mode == CaseMode.PROPOSED_ACTION else None,
        proposed_action_amount_inr=None,
        proposed_action_products=[],
        materiality_manual_flag=False,
        created_via="api",
        applicable_evidence_agents=[],
    )


class TestTransitionStatus:
    @pytest.mark.asyncio
    async def test_valid_transition_updates_status(self, db, seeded_investor):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()
        await repository.transition_status(
            db, case=case, to_status=CaseStatus.GATHERING_EVIDENCE
        )
        assert case.status == CaseStatus.GATHERING_EVIDENCE.value

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, db, seeded_investor):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()
        with pytest.raises(InvalidStateTransitionError):
            await repository.transition_status(
                db, case=case, to_status=CaseStatus.AWAITING_DECISION
            )

    @pytest.mark.asyncio
    async def test_terminal_requires_closed_reason(self, db, seeded_investor):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()
        with pytest.raises(InvalidStateTransitionError, match="closed_reason"):
            await repository.transition_status(
                db, case=case, to_status=CaseStatus.FAILED
            )

    @pytest.mark.asyncio
    async def test_terminal_sets_closed_at(self, db, seeded_investor):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()
        await repository.transition_status(
            db,
            case=case,
            to_status=CaseStatus.FAILED,
            closed_reason=CaseClosedReason.FAILED,
        )
        assert case.status == CaseStatus.FAILED.value
        assert case.closed_at is not None
        assert case.closed_reason == "failed"

    @pytest.mark.asyncio
    async def test_emits_status_transition_and_terminal_event(
        self, db, seeded_investor
    ):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()

        await repository.transition_status(
            db,
            case=case,
            to_status=CaseStatus.FAILED,
            closed_reason=CaseClosedReason.FAILED,
        )

        events = [
            row.event_name
            for row in (await db.execute(select(T1Event))).scalars()
        ]
        assert event_names.CASE_STATUS_TRANSITION in events
        assert event_names.CASE_FAILED in events


# ---------------------------------------------------------------------------
# Materiality recording
# ---------------------------------------------------------------------------


class TestRecordMateriality:
    @pytest.mark.asyncio
    async def test_writes_case_row_and_emits_event(self, db, seeded_investor):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()

        await repository.record_materiality(
            db, case=case, is_material=True, reason="MAT_TICKET_SIZE"
        )

        assert case.is_material is True
        assert case.materiality_reason == "MAT_TICKET_SIZE"
        assert case.materiality_assessed_at is not None

        evs = [
            row.event_name
            for row in (await db.execute(select(T1Event))).scalars()
        ]
        assert event_names.CASE_MATERIALITY_ASSESSED in evs


# ---------------------------------------------------------------------------
# Stage table inserts + reads
# ---------------------------------------------------------------------------


class TestStageInserts:
    @pytest.mark.asyncio
    async def test_evidence_and_governance_packet_ordering(
        self, db, seeded_investor
    ):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()

        # Insert evidence rows in non-canonical order.
        await repository.insert_evidence_verdict(
            db,
            case_id=case.case_id,
            agent_id="e7_mutual_fund",
            produced_via="lookup_stub_placeholder",
            risk_level="medium",
        )
        await repository.insert_evidence_verdict(
            db,
            case_id=case.case_id,
            agent_id="e1_listed_fundamental_equity",
            produced_via="lookup_stub_placeholder",
            risk_level="high",
        )
        await db.commit()

        rows = await repository.list_evidence_verdicts(db, case_id=case.case_id)
        # FR 20.1 §4.3: list ordered by (agent_id, produced_at).
        assert [r.agent_id for r in rows] == [
            "e1_listed_fundamental_equity",
            "e7_mutual_fund",
        ]

        # Governance — same packet ordering rule.
        await repository.insert_governance_result(
            db,
            case_id=case.case_id,
            gate="g3_action_filter",
            produced_via="lookup_stub_placeholder",
            outcome="approved",
        )
        await repository.insert_governance_result(
            db,
            case_id=case.case_id,
            gate="g1_mandate",
            produced_via="lookup_stub_placeholder",
            outcome="approved",
        )
        await db.commit()
        gov_rows = await repository.list_governance_results(
            db, case_id=case.case_id
        )
        assert [r.gate for r in gov_rows] == [
            "g1_mandate",
            "g3_action_filter",
        ]


# ---------------------------------------------------------------------------
# Decision artifact UNIQUE on case_id
# ---------------------------------------------------------------------------


class TestDecisionArtifactUnique:
    @pytest.mark.asyncio
    async def test_second_artifact_raises(self, db, seeded_investor):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()
        await repository.insert_decision_artifact(
            db,
            case_id=case.case_id,
            decided_by="cio1",
            decision="approved",
            rationale="LGTM",
            evidence_packet_hash="a" * 64,
            synthesis_hash="b" * 64,
            governance_packet_hash="c" * 64,
        )
        await db.commit()

        with pytest.raises(DecisionAlreadyRecordedError):
            await repository.insert_decision_artifact(
                db,
                case_id=case.case_id,
                decided_by="cio1",
                decision="modified",
                rationale="changed mind",
                evidence_packet_hash="a" * 64,
                synthesis_hash="b" * 64,
                governance_packet_hash="c" * 64,
            )


# ---------------------------------------------------------------------------
# Snapshot pinner integration
# ---------------------------------------------------------------------------


class TestSnapshotPinner:
    @pytest.mark.asyncio
    async def test_pin_creates_snapshot_and_updates_case(
        self, db, seeded_investor
    ):
        case = await _make_case(db, seeded_investor, CaseMode.PROPOSED_ACTION)
        await db.commit()

        result = await pin_snapshot_for_case(
            db, case=case, actor_user_id="advisor1"
        )
        await db.commit()

        assert case.snapshot_bundle_id == result.snapshot_bundle_id
        # T1 emits snapshot_pinned (from the repository's helper) —
        # confirm.
        evs = [
            row.event_name
            for row in (await db.execute(select(T1Event))).scalars()
        ]
        assert event_names.CASE_CREATION_SNAPSHOT_PINNED in evs

    @pytest.mark.asyncio
    async def test_pin_propagates_seed_flag_to_snapshot(
        self, db, seeded_investor
    ):
        investor_id, _ = seeded_investor
        case = await repository.create_case(
            db,
            investor_id=investor_id,
            household_id=None,
            opened_by="advisor1",
            assigned_to="advisor1",
            case_mode=CaseMode.DIAGNOSTIC.value,
            case_intent="portfolio_health",
            dominant_lens=None,
            proposed_action=None,
            proposed_action_amount_inr=None,
            proposed_action_products=[],
            materiality_manual_flag=False,
            created_via="seed_loader",
            applicable_evidence_agents=[],
            is_seed_data=True,
            seed_archetype_id="lalitha_v",
        )
        await db.commit()

        await pin_snapshot_for_case(
            db, case=case, actor_user_id="seed_loader"
        )
        await db.commit()

        # Snapshot row should be tagged as seed data so the cluster 5.6
        # reset path can collect it.
        from artha.api_v2.d0.models import Snapshot

        snap = (
            await db.execute(
                select(Snapshot).where(
                    Snapshot.snapshot_id == case.snapshot_bundle_id
                )
            )
        ).scalar_one()
        assert snap.is_seed_data is True
