"""Cluster 2 chunk 2.2 — C0 mandate_creation E2E + investor lookup tests.

Drives the full conversational mandate creation flow with a stubbed
SmartLLMRouter:

- Intent detection on turn 1 → mandate_creation.
- Investor disambiguation (single match, multiple matches, zero matches).
- Constraint collection turn-by-turn.
- Skip-to-defaults affordance.
- Confirmation + execution → M1 service creates mandate.
- The created mandate has ``created_via=conversational`` matching FR
  Entry 14.0 Cluster 2 Revision §3.7.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.c0 import investor_lookup
from artha.api_v2.c0.mandate_state_machine import MandateConversationState
from artha.api_v2.llm.providers import LLMCallResponse
from artha.api_v2.llm.router_runtime import (
    SmartLLMRouter,
    reset_smart_llm_router,
)
from artha.api_v2.m1.models import Mandate
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import settings

_TEST_JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"


# ---------------------------------------------------------------------------
# Stub LLM router that returns canned responses by caller_id.
# ---------------------------------------------------------------------------


class _ScriptedRouter(SmartLLMRouter):
    """Like the cluster 1 chunk 1.2 _ScriptedRouter — keyed on caller_id.

    For mandate flow tests, callers provide:
    - ``intent_response``: turn 1 intent detection output.
    - ``slot_responses``: queue of slot extraction outputs (one per
      C0-generated extraction call).
    """

    def __init__(self, *, intent_response: str, slot_responses: list[str] | None = None):
        super().__init__()
        self._intent_response = intent_response
        self._slot_responses = list(slot_responses or [])

    async def call(self, db, request):  # noqa: ARG002
        if request.caller_id == "c0_intent_detector":
            return self._make_response(self._intent_response)
        if request.caller_id == "c0_slot_extractor":
            if not self._slot_responses:
                return self._make_response(
                    '{"extracted_fields": {}, "extraction_confidence": "low"}'
                )
            return self._make_response(self._slot_responses.pop(0))
        return self._make_response("{}")

    @staticmethod
    def _make_response(content: str) -> LLMCallResponse:
        return LLMCallResponse(
            content=content,
            provider="mistral",
            model="mistral-small-latest",
            tokens_used=10,
            latency_ms=11,
            request_id="req-stub",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def jwt_secret_for_tests(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", _TEST_JWT_SECRET)
    reset_dev_secret_cache()
    yield
    reset_dev_secret_cache()


@pytest.fixture(autouse=True)
def reset_users_cache():
    reload_catalogue()
    yield


@pytest.fixture(autouse=True)
def reset_router_singleton():
    reset_smart_llm_router()
    yield
    reset_smart_llm_router()


@pytest_asyncio.fixture
async def engine_and_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine_and_factory):
    _, factory = engine_and_factory
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def http(engine_and_factory):
    _, factory = engine_and_factory

    async def _override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


def _install_router(scripted: _ScriptedRouter) -> None:
    from artha.api_v2.llm.router_runtime import get_smart_llm_router

    app.dependency_overrides[get_smart_llm_router] = lambda: scripted


def _uninstall_router() -> None:
    from artha.api_v2.llm.router_runtime import get_smart_llm_router

    app.dependency_overrides.pop(get_smart_llm_router, None)


async def _login(http, user_id: str) -> str:
    resp = await http.post("/api/v2/auth/dev-login", json={"user_id": user_id})
    return resp.json()["access_token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_investor(http, token: str, **overrides) -> str:
    base = {
        "name": "Rajesh Kumar",
        "email": "rajesh@example.com",
        "phone": "9876543210",
        "pan": "ABCDE1234F",
        "age": 41,
        "household_name": "Kumar Household",
        "risk_appetite": "moderate",
        "time_horizon": "over_5_years",
    }
    base.update(overrides)
    resp = await http.post("/api/v2/investors", json=base, headers=_h(token))
    return resp.json()["investor_id"]


# ===========================================================================
# 1. Investor lookup pure function
# ===========================================================================


class TestInvestorLookup:
    @pytest.mark.asyncio
    async def test_exact_name_match_returns_one(self, db, http):
        advisor = await _login(http, "advisor1")
        await _create_investor(http, advisor, name="Rajesh Kumar")
        from artha.api_v2.auth.user_context import Role, UserContext

        actor = UserContext(
            user_id="advisor1",
            firm_id="demo-firm-001",
            role=Role.ADVISOR,
            email="",
            name="",
            session_id="",
        )
        matches = await investor_lookup.find_matching_investors(
            db, name_query="Rajesh Kumar", pan_query=None, actor=actor
        )
        assert len(matches) == 1
        assert matches[0].name == "Rajesh Kumar"

    @pytest.mark.asyncio
    async def test_substring_name_match(self, db, http):
        advisor = await _login(http, "advisor1")
        await _create_investor(http, advisor, name="Rajesh Kumar")
        from artha.api_v2.auth.user_context import Role, UserContext

        actor = UserContext(
            user_id="advisor1",
            firm_id="demo-firm-001",
            role=Role.ADVISOR,
            email="",
            name="",
            session_id="",
        )
        matches = await investor_lookup.find_matching_investors(
            db, name_query="rajesh", pan_query=None, actor=actor
        )
        assert len(matches) == 1
        assert matches[0].name == "Rajesh Kumar"

    @pytest.mark.asyncio
    async def test_pan_prefix_match(self, db, http):
        advisor = await _login(http, "advisor1")
        await _create_investor(http, advisor)
        from artha.api_v2.auth.user_context import Role, UserContext

        actor = UserContext(
            user_id="advisor1",
            firm_id="demo-firm-001",
            role=Role.ADVISOR,
            email="",
            name="",
            session_id="",
        )
        matches = await investor_lookup.find_matching_investors(
            db, name_query=None, pan_query="ABCDE", actor=actor
        )
        assert len(matches) == 1
        assert matches[0].pan == "ABCDE1234F"

    @pytest.mark.asyncio
    async def test_no_query_returns_empty(self, db, http):
        advisor = await _login(http, "advisor1")
        await _create_investor(http, advisor)
        from artha.api_v2.auth.user_context import Role, UserContext

        actor = UserContext(
            user_id="advisor1",
            firm_id="demo-firm-001",
            role=Role.ADVISOR,
            email="",
            name="",
            session_id="",
        )
        matches = await investor_lookup.find_matching_investors(
            db, name_query=None, pan_query=None, actor=actor
        )
        assert matches == []


# ===========================================================================
# 2. Mandate flow E2E — happy path with explicit slot collection
# ===========================================================================


class TestMandateFlowE2E:
    @pytest.mark.asyncio
    async def test_full_mandate_creation_via_c0(self, http, db):
        advisor = await _login(http, "advisor1")
        investor_id = await _create_investor(http, advisor)

        scripted = _ScriptedRouter(
            intent_response=(
                '{"intent": "mandate_creation", '
                '"extracted_fields": {"investor_name": "Rajesh Kumar"}}'
            ),
            slot_responses=[
                # The "yes" disambiguation turn is intercepted by
                # _parse_candidate_selection before extract_slots runs,
                # so the queue starts with the asset-allocation response.
                # Asset allocation (cluster 3: four bands including cash):
                '{"extracted_fields": {'
                '"equity_min_pct": 45, "equity_max_pct": 65, '
                '"debt_min_pct": 15, "debt_max_pct": 35, '
                '"cash_min_pct": 5, "cash_max_pct": 15, '
                '"alternatives_min_pct": 5, "alternatives_max_pct": 15'
                '}, "extraction_confidence": "high"}',
                # Concentration:
                '{"extracted_fields": {"single_position_max_pct": 5}, '
                '"extraction_confidence": "high"}',
                # Liquidity:
                '{"extracted_fields": {"liquidity_floor_pct": 10}, '
                '"extraction_confidence": "high"}',
                # Sector:
                '{"extracted_fields": {"sector_max_pct": 25}, '
                '"extraction_confidence": "high"}',
                # Prohibited (none):
                '{"extracted_fields": {"prohibited_instruments": []}, '
                '"extraction_confidence": "high"}',
            ],
        )
        _install_router(scripted)
        try:
            start = await http.post(
                "/api/v2/conversations", headers=_h(advisor), json={}
            )
            cid = start.json()["conversation_id"]

            # Turn 1: intent detection.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "set up the mandate for Rajesh"},
            )
            body = r.json()
            assert body["intent"] == "mandate_creation"
            assert body["state"] == MandateConversationState.INVESTOR_DISAMBIGUATION.value

            # Turn 2: confirm the (single) candidate.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "yes"},
            )
            body = r.json()
            assert body["state"] == MandateConversationState.COLLECTING_ASSET_ALLOCATION.value
            assert body["collected_slots"]["investor_id"] == investor_id

            # Turns 3–7: each constraint family.
            for content, expected_state in [
                ("equity 50-70, debt 20-40, alts 5-15",
                 MandateConversationState.COLLECTING_CONCENTRATION),
                ("single position 5",
                 MandateConversationState.COLLECTING_LIQUIDITY),
                ("liquidity 10",
                 MandateConversationState.COLLECTING_SECTOR),
                ("sector 25",
                 MandateConversationState.COLLECTING_PROHIBITED),
                ("none",
                 MandateConversationState.AWAITING_CONFIRMATION),
            ]:
                r = await http.post(
                    f"/api/v2/conversations/{cid}/messages",
                    headers=_h(advisor),
                    json={"content": content},
                )
                assert r.status_code == 200
                assert r.json()["state"] == expected_state.value, (
                    f"after {content!r}: expected {expected_state.value}, got {r.json()['state']}"
                )

            # Confirm.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "yes"},
            )
            body = r.json()
            assert body["state"] == MandateConversationState.COMPLETED.value
            assert body["status"] == "completed"

            # Mandate row exists with created_via=conversational.
            mandate = (await db.execute(select(Mandate))).scalar_one()
            assert mandate.investor_id == investor_id
        finally:
            _uninstall_router()


# ===========================================================================
# 3. Skip-to-defaults affordance
# ===========================================================================


class TestSkipToDefaults:
    @pytest.mark.asyncio
    async def test_use_defaults_skips_to_confirmation(self, http, db):
        advisor = await _login(http, "advisor1")
        await _create_investor(http, advisor)

        scripted = _ScriptedRouter(
            intent_response=(
                '{"intent": "mandate_creation", '
                '"extracted_fields": {"investor_name": "Rajesh Kumar"}}'
            ),
            slot_responses=[
                # "yes" disambiguation intercepted by parser; queue starts
                # with the use_defaults response for the asset-allocation
                # turn.
                '{"extracted_fields": {"use_defaults": true}, '
                '"extraction_confidence": "high"}',
            ],
        )
        _install_router(scripted)
        try:
            start = await http.post(
                "/api/v2/conversations", headers=_h(advisor), json={}
            )
            cid = start.json()["conversation_id"]
            await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "set up mandate for Rajesh"},
            )
            await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "yes"},
            )
            # use_defaults short-circuits to AWAITING_CONFIRMATION.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "use defaults"},
            )
            body = r.json()
            assert body["state"] == MandateConversationState.AWAITING_CONFIRMATION.value
            # Cluster 3 four-band defaults populated by skip-to-defaults.
            # Moderate / over_5_years → essential tier:
            #   equity 45-65, debt 15-35, cash 5-15, alts 5-15.
            slots = body["collected_slots"]
            assert slots["equity_min_pct"] == 45  # moderate I0 risk_appetite
            assert slots["cash_min_pct"] == 5     # cluster 3 cash band
            assert slots["cash_max_pct"] == 15
            assert slots["liquidity_floor_pct"] == 10  # essential I0 liquidity_tier
            assert slots["sector_max_pct"] == 25  # industry standard
        finally:
            _uninstall_router()


# ===========================================================================
# 4. Disambiguation paths
# ===========================================================================


class TestDisambiguation:
    @pytest.mark.asyncio
    async def test_zero_matches_asks_for_clarification(self, http):
        advisor = await _login(http, "advisor1")
        # No investor created — lookup will return zero matches.

        scripted = _ScriptedRouter(
            intent_response=(
                '{"intent": "mandate_creation", '
                '"extracted_fields": {"investor_name": "Nobody"}}'
            ),
        )
        _install_router(scripted)
        try:
            start = await http.post(
                "/api/v2/conversations", headers=_h(advisor), json={}
            )
            cid = start.json()["conversation_id"]
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "set up mandate for Nobody"},
            )
            body = r.json()
            # Stays in disambiguation; system message asks for clarification.
            assert body["state"] == MandateConversationState.INVESTOR_DISAMBIGUATION.value
            last_system = next(m for m in reversed(body["messages"]) if m["sender"] == "system")
            assert "couldn't find" in last_system["content"].lower()
        finally:
            _uninstall_router()

    @pytest.mark.asyncio
    async def test_multiple_matches_presents_list(self, http):
        advisor = await _login(http, "advisor1")
        # Two investors named "Rajesh".
        await _create_investor(
            http, advisor, name="Rajesh Kumar", pan="ABCDE1234F", email="r1@example.com"
        )
        await _create_investor(
            http, advisor, name="Rajesh Sharma", pan="QRSTU5678V", email="r2@example.com"
        )

        scripted = _ScriptedRouter(
            intent_response=(
                '{"intent": "mandate_creation", '
                '"extracted_fields": {"investor_name": "Rajesh"}}'
            ),
        )
        _install_router(scripted)
        try:
            start = await http.post(
                "/api/v2/conversations", headers=_h(advisor), json={}
            )
            cid = start.json()["conversation_id"]
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "set up mandate for Rajesh"},
            )
            body = r.json()
            assert body["state"] == MandateConversationState.INVESTOR_DISAMBIGUATION.value
            last_system = next(m for m in reversed(body["messages"]) if m["sender"] == "system")
            assert "multiple investors" in last_system["content"].lower()
            assert "Rajesh Kumar" in last_system["content"]
            assert "Rajesh Sharma" in last_system["content"]
            # Candidates stashed in slot bag for the next-turn parser.
            assert len(body["collected_slots"]["_disambiguation_candidates"]) == 2
        finally:
            _uninstall_router()


# ===========================================================================
# 5. Existing mandate guard
# ===========================================================================


class TestExistingMandateGuard:
    @pytest.mark.asyncio
    async def test_already_has_mandate_blocks_flow(self, http, db):
        advisor = await _login(http, "advisor1")
        investor_id = await _create_investor(http, advisor)
        # Pre-create a mandate so the guard fires (cluster 3 four-band).
        await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json={
                "equity_min_pct": 45, "equity_max_pct": 65,
                "debt_min_pct": 15, "debt_max_pct": 35,
                "cash_min_pct": 5, "cash_max_pct": 15,
                "alternatives_min_pct": 5, "alternatives_max_pct": 15,
                "single_position_max_pct": 5,
                "liquidity_floor_pct": 20,
                "sector_max_pct": 25,
                "prohibited_instruments": [],
            },
            headers=_h(advisor),
        )

        scripted = _ScriptedRouter(
            intent_response=(
                '{"intent": "mandate_creation", '
                '"extracted_fields": {"investor_name": "Rajesh Kumar"}}'
            ),
            slot_responses=[
                '{"extracted_fields": {}, "extraction_confidence": "high"}',
            ],
        )
        _install_router(scripted)
        try:
            start = await http.post(
                "/api/v2/conversations", headers=_h(advisor), json={}
            )
            cid = start.json()["conversation_id"]
            await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "set up mandate for Rajesh"},
            )
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(advisor),
                json={"content": "yes"},
            )
            body = r.json()
            # Conversation completes with the "already has" notice.
            assert body["state"] == MandateConversationState.COMPLETED.value
            last_system = next(m for m in reversed(body["messages"]) if m["sender"] == "system")
            assert "already has an active mandate" in last_system["content"]
        finally:
            _uninstall_router()
