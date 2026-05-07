"""Cluster 5 chunk 5.5 — decision recording tests.

Pins:

- Happy path: CIO records on awaiting_decision case → artifact written
  with correct hashes + case transitions to decided.
- Permission: non-CIO actor → :class:`NotAuthorisedToDecideError`.
- Status guard: case not in awaiting_decision → error.
- Idempotency: second call → :class:`DecisionAlreadyRecordedError`.
- Audit replay: ``compute_hashes_for_case`` re-derives the same bundle
  on a fresh read.
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
from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.cases import pipeline, repository
from artha.api_v2.cases.case_decider import (
    CaseNotInAwaitingDecisionError,
    NotAuthorisedToDecideError,
    RecordDecisionRequest,
    compute_hashes_for_case,
    record_decision,
)
from artha.api_v2.cases.repository import DecisionAlreadyRecordedError
from artha.api_v2.cases.state_machine import CaseStatus, DecisionVerdict
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


def _cio() -> UserContext:
    return UserContext(
        user_id="cio1",
        firm_id="firm-1",
        role=Role.CIO,
        email="c@example.com",
        name="CIO",
        session_id="s",
    )


def _advisor() -> UserContext:
    return UserContext(
        user_id="advisor1",
        firm_id="firm-1",
        role=Role.ADVISOR,
        email="a@example.com",
        name="A",
        session_id="s",
    )


@pytest_asyncio.fixture
async def case_in_awaiting_decision(db):
    """Build a proposed_action case that has been run through the chunk
    5.4 pipeline and now sits in awaiting_decision."""
    now = datetime.now(timezone.utc)
    household = Household(
        household_id=str(ULID()),
        name="Decider Family",
        created_by="advisor1",
        created_at=now,
    )
    db.add(household)
    investor = Investor(
        investor_id=str(ULID()),
        household_id=household.household_id,
        name="Decider Investor",
        email="d@example.com",
        phone="+919999999990",
        pan="DCDR1234FF",
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

    case = await repository.create_case(
        db,
        investor_id=investor.investor_id,
        household_id=household.household_id,
        opened_by="advisor1",
        assigned_to="advisor1",
        case_mode="proposed_action",
        case_intent="rebalance_proposal",
        dominant_lens=None,
        proposed_action="Test action",
        proposed_action_amount_inr=Decimal("100000"),
        proposed_action_products=[],
        materiality_manual_flag=False,
        created_via="api",
        applicable_evidence_agents=["e1_listed_fundamental_equity", "e3_macro_policy_news"],
    )
    case.snapshot_bundle_id = "fake-snapshot"
    await db.flush()
    await repository.transition_status(
        db, case=case, to_status=CaseStatus.GATHERING_EVIDENCE,
    )
    await pipeline.run_pipeline(db, case=case)
    await db.commit()
    return case


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_cio_records_decision_and_case_transitions(
        self, db, case_in_awaiting_decision,
    ):
        case = case_in_awaiting_decision
        result = await record_decision(
            db,
            case_id=case.case_id,
            request=RecordDecisionRequest(
                decision=DecisionVerdict.APPROVED,
                rationale="Aligned with mandate; concentration within cap.",
                conditions={"items": ["review_in_30_days"]},
            ),
            actor=_cio(),
        )
        await db.commit()

        assert result.artifact.decision == "approved"
        assert result.artifact.decided_by == "cio1"
        assert result.artifact.evidence_packet_hash == result.hashes.evidence_packet_hash
        assert result.hashes.synthesis_hash
        assert result.hashes.governance_packet_hash
        assert result.hashes.a1_hash
        # Non-material → no IC1.
        assert result.hashes.ic1_hash is None
        # Portfolio risk always present.
        assert result.hashes.portfolio_risk_hash

        # Case transitioned.
        case = await repository.get_case(db, case_id=case.case_id)
        assert case.status == CaseStatus.DECIDED.value
        assert case.closed_reason == "decided"

    @pytest.mark.asyncio
    async def test_string_decision_coerced(self, db, case_in_awaiting_decision):
        case = case_in_awaiting_decision
        result = await record_decision(
            db,
            case_id=case.case_id,
            request=RecordDecisionRequest(
                decision="modified",
                rationale="Reducing size given timing premium.",
                modifications={"size_reduction_pct": 30},
            ),
            actor=_cio(),
        )
        await db.commit()
        assert result.artifact.decision == "modified"

    @pytest.mark.asyncio
    async def test_t1_case_decided_emitted(self, db, case_in_awaiting_decision):
        case = case_in_awaiting_decision
        await record_decision(
            db,
            case_id=case.case_id,
            request=RecordDecisionRequest(
                decision="approved",
                rationale="Approved.",
            ),
            actor=_cio(),
        )
        await db.commit()
        events = list(
            (
                await db.execute(
                    select(T1Event).where(T1Event.event_name == "case_decided")
                )
            ).scalars()
        )
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Permission + status guards
# ---------------------------------------------------------------------------


class TestGuards:
    @pytest.mark.asyncio
    async def test_advisor_blocked(self, db, case_in_awaiting_decision):
        case = case_in_awaiting_decision
        with pytest.raises(NotAuthorisedToDecideError):
            await record_decision(
                db,
                case_id=case.case_id,
                request=RecordDecisionRequest(
                    decision="approved", rationale="x",
                ),
                actor=_advisor(),
            )

    @pytest.mark.asyncio
    async def test_case_not_in_awaiting_decision(
        self,
        db,
        case_in_awaiting_decision,
    ):
        # Force the case to a non-decision status.
        case = case_in_awaiting_decision
        case.status = CaseStatus.GATHERING_EVIDENCE.value
        await db.flush()
        with pytest.raises(CaseNotInAwaitingDecisionError):
            await record_decision(
                db,
                case_id=case.case_id,
                request=RecordDecisionRequest(
                    decision="approved", rationale="x",
                ),
                actor=_cio(),
            )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_second_record_raises(self, db, case_in_awaiting_decision):
        case = case_in_awaiting_decision
        await record_decision(
            db,
            case_id=case.case_id,
            request=RecordDecisionRequest(
                decision="approved", rationale="x",
            ),
            actor=_cio(),
        )
        await db.commit()
        # Force back to awaiting_decision so the status guard doesn't
        # fire first; the UNIQUE constraint should still trip.
        case = await repository.get_case(db, case_id=case.case_id)
        case.status = CaseStatus.AWAITING_DECISION.value
        case.closed_at = None
        case.closed_reason = None
        await db.flush()
        with pytest.raises(DecisionAlreadyRecordedError):
            await record_decision(
                db,
                case_id=case.case_id,
                request=RecordDecisionRequest(
                    decision="approved", rationale="x",
                ),
                actor=_cio(),
            )


# ---------------------------------------------------------------------------
# Replay determinism
# ---------------------------------------------------------------------------


class TestReplayDeterminism:
    @pytest.mark.asyncio
    async def test_compute_hashes_is_deterministic(
        self, db, case_in_awaiting_decision,
    ):
        case = case_in_awaiting_decision
        a = await compute_hashes_for_case(db, case_id=case.case_id)
        b = await compute_hashes_for_case(db, case_id=case.case_id)
        assert a == b

    @pytest.mark.asyncio
    async def test_recorded_hashes_match_recompute(
        self, db, case_in_awaiting_decision,
    ):
        case = case_in_awaiting_decision
        result = await record_decision(
            db,
            case_id=case.case_id,
            request=RecordDecisionRequest(decision="approved", rationale="x"),
            actor=_cio(),
        )
        await db.commit()
        # Re-fetch from DB and compare to the freshly computed bundle.
        artifact = await repository.get_decision_artifact(
            db, case_id=case.case_id,
        )
        bundle = await compute_hashes_for_case(db, case_id=case.case_id)
        assert artifact.evidence_packet_hash == bundle.evidence_packet_hash
        assert artifact.synthesis_hash == bundle.synthesis_hash
        assert artifact.governance_packet_hash == bundle.governance_packet_hash
        assert artifact.a1_hash == bundle.a1_hash
        # Result hashes equal to artifact hashes too.
        assert result.hashes == bundle
