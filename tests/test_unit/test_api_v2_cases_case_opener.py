"""Cluster 5 chunk 5.3 — case_opener orchestrator tests.

Pins the FR 20.1 §5.2 five-step pipeline:

1. Investor lookup + scope check.
2. M0 router decision → applicable_evidence_agents.
3. Case row insert (status=opening).
4. Snapshot pin (cluster 3 SnapshotAssembler).
5. Status transition opening → gathering_evidence.

Plus negative paths: investor outside scope, invalid mode/intent
combinations, snapshot pinning failure → case transitions to failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
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
from artha.api_v2.cases import case_opener, repository
from artha.api_v2.cases.case_opener import (
    CaseOpeningError,
    InvalidCaseModeError,
    InvestorNotFoundError,
    InvestorScopeError,
    OpenCaseDeps,
    OpenCaseRequest,
)
from artha.api_v2.cases.state_machine import CaseMode, CaseStatus
from artha.api_v2.investors.models import Household, Investor
from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# Stub boss
# ---------------------------------------------------------------------------


@dataclass
class _StubDecision:
    applicable_evidence_agents: tuple[str, ...]
    reason: str = "stub"


class _StubBoss:
    """Minimal boss that returns a fixed router decision."""

    def __init__(
        self,
        applicable_evidence_agents: tuple[str, ...] = (
            "e1_listed_fundamental_equity",
            "e3_macro_policy_news",
        ),
    ) -> None:
        self._applicable_evidence_agents = applicable_evidence_agents
        self.calls: list = []

    def route_evidence_agents(self, case) -> _StubDecision:  # noqa: ANN001
        self.calls.append(case)
        return _StubDecision(self._applicable_evidence_agents)


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
        name="Aarav Sharma",
        email="aarav@example.com",
        phone="+919999999999",
        pan="AAAAA1234F",
        age=35,
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


def _advisor_actor(user_id: str = "advisor1") -> UserContext:
    return UserContext(
        user_id=user_id,
        firm_id="firm-1",
        role=Role.ADVISOR,
        email="a@example.com",
        name="Advisor",
        session_id="s1",
    )


def _cio_actor() -> UserContext:
    return UserContext(
        user_id="cio1",
        firm_id="firm-1",
        role=Role.CIO,
        email="c@example.com",
        name="CIO",
        session_id="s2",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Orchestrator-only tests with skip_pipeline=True so we assert the
    state immediately after step 5 (transition to gathering_evidence).
    Pipeline integration is covered in test_api_v2_cases_pipeline.py.
    """

    @pytest.mark.asyncio
    async def test_opens_case_in_gathering_evidence_status(
        self, db, seeded_investor
    ):
        investor_id, _ = seeded_investor
        actor = _advisor_actor()
        boss = _StubBoss()

        result = await case_opener.open_case(
            db,
            OpenCaseRequest(
                investor_id=investor_id,
                case_mode=CaseMode.PROPOSED_ACTION,
                case_intent="rebalance_proposal",
                proposed_action="Shift 10% equity to debt",
                proposed_action_amount_inr=Decimal("500000"),
                skip_pipeline=True,
            ),
            actor=actor,
            deps=OpenCaseDeps(boss=boss),
        )
        await db.commit()

        # Re-fetch.
        case = await repository.get_case(db, case_id=result.case.case_id)
        assert case is not None
        assert case.status == CaseStatus.GATHERING_EVIDENCE.value
        assert case.snapshot_bundle_id is not None
        assert case.applicable_evidence_agents == [
            "e1_listed_fundamental_equity",
            "e3_macro_policy_news",
        ]
        assert case.opened_by == "advisor1"
        assert case.assigned_to == "advisor1"
        assert case.created_via == "api"

    @pytest.mark.asyncio
    async def test_router_called_with_mode_and_intent(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        boss = _StubBoss()
        await case_opener.open_case(
            db,
            OpenCaseRequest(
                investor_id=investor_id,
                case_mode="diagnostic",
                case_intent="portfolio_health",
                skip_pipeline=True,
            ),
            actor=_advisor_actor(),
            deps=OpenCaseDeps(boss=boss),
        )
        assert len(boss.calls) == 1
        # CaseRoutingInput should carry the typed enum values.
        call = boss.calls[0]
        assert str(call.case_mode) in ("CaseMode.DIAGNOSTIC", "diagnostic")

    @pytest.mark.asyncio
    async def test_cio_role_passes_scope(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        actor = _cio_actor()
        result = await case_opener.open_case(
            db,
            OpenCaseRequest(
                investor_id=investor_id,
                case_mode=CaseMode.DIAGNOSTIC,
                skip_pipeline=True,
            ),
            actor=actor,
            deps=OpenCaseDeps(boss=_StubBoss()),
        )
        await db.commit()
        assert result.case.opened_by == "cio1"

    @pytest.mark.asyncio
    async def test_seed_data_flag_propagates(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        result = await case_opener.open_case(
            db,
            OpenCaseRequest(
                investor_id=investor_id,
                case_mode=CaseMode.BRIEFING,
                case_intent="meeting_prep",
                is_seed_data=True,
                seed_archetype_id="aarav_sharma",
                created_via="seed_loader",
                skip_pipeline=True,
            ),
            actor=_cio_actor(),
            deps=OpenCaseDeps(boss=_StubBoss()),
        )
        await db.commit()
        case = await repository.get_case(db, case_id=result.case.case_id)
        assert case.is_seed_data is True
        assert case.seed_archetype_id == "aarav_sharma"
        assert case.created_via == "seed_loader"


# ---------------------------------------------------------------------------
# Investor scope + lookup errors
# ---------------------------------------------------------------------------


class TestInvestorErrors:
    @pytest.mark.asyncio
    async def test_unknown_investor_raises(self, db):
        with pytest.raises(InvestorNotFoundError):
            await case_opener.open_case(
                db,
                OpenCaseRequest(
                    investor_id="not_a_real_id",
                    case_mode=CaseMode.DIAGNOSTIC,
                ),
                actor=_advisor_actor(),
                deps=OpenCaseDeps(boss=_StubBoss()),
            )

    @pytest.mark.asyncio
    async def test_advisor_blocked_outside_book(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        # Different advisor than the one assigned to the investor.
        actor = _advisor_actor(user_id="advisor2")
        with pytest.raises(InvestorScopeError):
            await case_opener.open_case(
                db,
                OpenCaseRequest(
                    investor_id=investor_id,
                    case_mode=CaseMode.DIAGNOSTIC,
                ),
                actor=actor,
                deps=OpenCaseDeps(boss=_StubBoss()),
            )


# ---------------------------------------------------------------------------
# Mode / intent legality
# ---------------------------------------------------------------------------


class TestModeIntentLegality:
    @pytest.mark.asyncio
    async def test_portfolio_health_in_proposed_action_rejected(
        self, db, seeded_investor
    ):
        investor_id, _ = seeded_investor
        with pytest.raises(InvalidCaseModeError, match="diagnostic"):
            await case_opener.open_case(
                db,
                OpenCaseRequest(
                    investor_id=investor_id,
                    case_mode=CaseMode.PROPOSED_ACTION,
                    case_intent="portfolio_health",
                ),
                actor=_advisor_actor(),
                deps=OpenCaseDeps(boss=_StubBoss()),
            )

    @pytest.mark.asyncio
    async def test_meeting_prep_in_diagnostic_rejected(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        with pytest.raises(InvalidCaseModeError, match="briefing"):
            await case_opener.open_case(
                db,
                OpenCaseRequest(
                    investor_id=investor_id,
                    case_mode=CaseMode.DIAGNOSTIC,
                    case_intent="meeting_prep",
                ),
                actor=_advisor_actor(),
                deps=OpenCaseDeps(boss=_StubBoss()),
            )

    @pytest.mark.asyncio
    async def test_rebalance_in_briefing_rejected(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        with pytest.raises(InvalidCaseModeError):
            await case_opener.open_case(
                db,
                OpenCaseRequest(
                    investor_id=investor_id,
                    case_mode=CaseMode.BRIEFING,
                    case_intent="rebalance_proposal",
                ),
                actor=_advisor_actor(),
                deps=OpenCaseDeps(boss=_StubBoss()),
            )


# ---------------------------------------------------------------------------
# Snapshot pinning failure
# ---------------------------------------------------------------------------


class TestSnapshotFailure:
    @pytest.mark.asyncio
    async def test_pin_failure_transitions_case_to_failed(
        self,
        db,
        seeded_investor,
        monkeypatch,
    ):
        investor_id, _ = seeded_investor
        from artha.api_v2.cases import snapshot_pinner

        async def _explode(*args, **kwargs):
            raise snapshot_pinner.SnapshotPinningError("forced")

        monkeypatch.setattr(snapshot_pinner, "pin_snapshot_for_case", _explode)

        with pytest.raises(CaseOpeningError):
            await case_opener.open_case(
                db,
                OpenCaseRequest(
                    investor_id=investor_id,
                    case_mode=CaseMode.PROPOSED_ACTION,
                    case_intent="rebalance_proposal",
                ),
                actor=_advisor_actor(),
                deps=OpenCaseDeps(boss=_StubBoss()),
            )
        # The case row exists in failed state.
        await db.commit()
        cases, _ = await repository.list_cases(db, investor_id=investor_id)
        assert len(cases) == 1
        assert cases[0].status == CaseStatus.FAILED.value
        assert cases[0].closed_reason == "failed"


# ---------------------------------------------------------------------------
# Manual override
# ---------------------------------------------------------------------------


class TestManualOverride:
    @pytest.mark.asyncio
    async def test_manual_override_applied(self, db, seeded_investor):
        investor_id, _ = seeded_investor
        boss = _StubBoss(applicable_evidence_agents=("ignored",))
        result = await case_opener.open_case(
            db,
            OpenCaseRequest(
                investor_id=investor_id,
                case_mode=CaseMode.PROPOSED_ACTION,
                case_intent="rebalance_proposal",
                manual_override_evidence_agents=(
                    "e1_listed_fundamental_equity",
                    "e7_mutual_fund",
                ),
                skip_pipeline=True,
            ),
            actor=_cio_actor(),
            deps=OpenCaseDeps(boss=boss),
        )
        await db.commit()
        # Boss receives the override; the stub still returns its own list,
        # but the input payload's manual_override is recorded on the boss
        # invocation.
        assert boss.calls[0].manual_override == (
            "e1_listed_fundamental_equity",
            "e7_mutual_fund",
        )
        # The stub didn't honor manual override (it always returns the same
        # tuple); verify the orchestrator still passed it through to boss.
        # Real M0Boss respects manual_override (covered in m0 router unit tests).
        assert result.case is not None
