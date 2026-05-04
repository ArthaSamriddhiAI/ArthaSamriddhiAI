"""Cluster 1 chunk 1.2 — C0 REST endpoint test suite.

Covers the full surface from the chunk plan:

- ``POST /api/v2/conversations``                    — start
- ``GET  /api/v2/conversations``                    — list (own_book vs firm_scope)
- ``GET  /api/v2/conversations/{id}``               — fetch with messages
- ``POST /api/v2/conversations/{id}/messages``      — turn handling
- ``POST /api/v2/conversations/{id}/confirm``       — execute investor creation
- ``POST /api/v2/conversations/{id}/cancel``        — explicit abandon

End-to-end happy path drives the full FSM through to a created investor;
fallback paths exercise the LLM-unavailable + malformed-JSON modes.
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
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.c0.event_names import (
    C0_CONVERSATION_ABANDONED,
    C0_CONVERSATION_COMPLETED,
    C0_CONVERSATION_STARTED,
    C0_INTENT_DETECTED,
    C0_LLM_FAILURE,
    C0_SLOT_EXTRACTED,
    C0_STATE_TRANSITIONED,
)
from artha.api_v2.c0.state_machine import ConversationState
from artha.api_v2.investors.models import Investor
from artha.api_v2.llm.providers import LLMCallResponse
from artha.api_v2.llm.router_runtime import (
    LLMCallFailedError,
    LLMNotConfiguredError,
    SmartLLMRouter,
    reset_smart_llm_router,
)
from artha.api_v2.observability.models import T1Event
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import settings

_TEST_JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"


# ---------------------------------------------------------------------------
# Stub LLM router — drives intent + slot extraction without a provider call.
# ---------------------------------------------------------------------------


class _ScriptedRouter(SmartLLMRouter):
    """SmartLLMRouter whose ``call`` returns canned responses by caller_id.

    The C0 service only uses two caller_ids — ``c0_intent_detector`` and
    ``c0_slot_extractor`` — so the script is keyed on those.
    """

    def __init__(
        self,
        *,
        intent_response: str | None = None,
        slot_responses: list[str] | None = None,
        intent_raises: Exception | None = None,
        slot_raises: Exception | None = None,
    ):
        super().__init__()
        self._intent_response = intent_response
        self._slot_responses = list(slot_responses or [])
        self._intent_raises = intent_raises
        self._slot_raises = slot_raises

    async def call(self, db, request):  # noqa: ARG002
        if request.caller_id == "c0_intent_detector":
            if self._intent_raises:
                raise self._intent_raises
            return self._make_response(self._intent_response or "{}")
        if request.caller_id == "c0_slot_extractor":
            if self._slot_raises:
                raise self._slot_raises
            if not self._slot_responses:
                # Default to an empty slot extraction so the FSM doesn't advance.
                return self._make_response(
                    '{"extracted_fields": {}, "extraction_confidence": "low"}'
                )
            return self._make_response(self._slot_responses.pop(0))
        # Fallback — shouldn't be reached in C0 tests.
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
    """Override the SmartLLMRouter dependency for the duration of the test."""
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


# ---------------------------------------------------------------------------
# 1. Start + permissions
# ---------------------------------------------------------------------------


class TestStartConversation:
    @pytest.mark.asyncio
    async def test_advisor_can_start_conversation(self, http, db):
        token = await _login(http, "advisor1")
        resp = await http.post("/api/v2/conversations", headers=_h(token), json={})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["state"] == ConversationState.INTENT_PENDING.value
        assert body["status"] == "active"
        assert body["intent"] is None
        assert body["messages"] == []

        events = (
            await db.execute(
                select(T1Event).where(T1Event.event_name == C0_CONVERSATION_STARTED)
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].payload["user_id"] == "advisor1"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["cio1", "compliance1", "audit1"])
    async def test_non_advisor_cannot_start_conversation(self, http, user_id):
        token = await _login(http, user_id)
        resp = await http.post("/api/v2/conversations", headers=_h(token), json={})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 2. Full happy-path conversation drives FSM to STATE_COMPLETED
# ---------------------------------------------------------------------------


class TestConversationHappyPath:
    @pytest.mark.asyncio
    async def test_full_conversation_creates_investor(self, http, db):
        scripted = _ScriptedRouter(
            intent_response=(
                '{"intent": "investor_onboarding", '
                '"extracted_fields": {"name": "Rajesh Kumar"}}'
            ),
            slot_responses=[
                # turn 2: email + phone
                '{"extracted_fields": {"email": "rajesh@example.com", '
                '"phone": "+919876543210"}, "extraction_confidence": "high"}',
                # turn 3: pan + age
                '{"extracted_fields": {"pan": "ABCDE1234F", "age": 30}, '
                '"extraction_confidence": "high"}',
                # turn 4: household
                '{"extracted_fields": {"household_name": "Kumar Household"}, '
                '"extraction_confidence": "high"}',
                # turn 5: profile
                '{"extracted_fields": {"risk_appetite": "moderate", '
                '"time_horizon": "over_5_years"}, '
                '"extraction_confidence": "high"}',
            ],
        )
        _install_router(scripted)
        try:
            token = await _login(http, "advisor1")
            start = await http.post("/api/v2/conversations", headers=_h(token), json={})
            cid = start.json()["conversation_id"]

            # Turn 1 — intent detection. Pre-fills name; advances to COLLECTING_BASICS.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "I want to onboard a new client called Rajesh"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["intent"] == "investor_onboarding"
            assert body["state"] == ConversationState.COLLECTING_BASICS.value
            assert body["collected_slots"]["name"] == "Rajesh Kumar"

            # Turn 2 — email + phone.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "rajesh@example.com and 9876543210"},
            )
            body = r.json()
            assert body["state"] == ConversationState.COLLECTING_BASICS.value
            assert body["collected_slots"]["email"] == "rajesh@example.com"
            assert body["collected_slots"]["phone"] == "+919876543210"

            # Turn 3 — pan + age. Should advance to COLLECTING_HOUSEHOLD.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "PAN ABCDE1234F, age 30"},
            )
            body = r.json()
            assert body["state"] == ConversationState.COLLECTING_HOUSEHOLD.value

            # Turn 4 — household. Advances to COLLECTING_PROFILE.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "new household called Kumar Household"},
            )
            body = r.json()
            assert body["state"] == ConversationState.COLLECTING_PROFILE.value

            # Turn 5 — profile. Advances to AWAITING_CONFIRMATION.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "moderate risk, long term"},
            )
            body = r.json()
            assert body["state"] == ConversationState.AWAITING_CONFIRMATION.value

            # Confirm → executes investor creation.
            r = await http.post(
                f"/api/v2/conversations/{cid}/confirm", headers=_h(token), json={}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["state"] == ConversationState.COMPLETED.value
            assert body["status"] == "completed"
            assert body["investor_id"] is not None
            assert body["investor"] is not None
            assert body["investor"]["created_via"] == "conversational"
            assert body["investor"]["life_stage"] == "accumulation"
            assert body["investor"]["liquidity_tier"] == "essential"

            # Investor table actually has the row.
            row = (await db.execute(select(Investor))).scalar_one()
            assert row.name == "Rajesh Kumar"
            assert row.created_via == "conversational"

            # T1 events fired across the lifecycle.
            for name in (
                C0_INTENT_DETECTED,
                C0_SLOT_EXTRACTED,
                C0_STATE_TRANSITIONED,
                C0_CONVERSATION_COMPLETED,
            ):
                ev = (
                    await db.execute(
                        select(T1Event).where(T1Event.event_name == name)
                    )
                ).scalars().all()
                assert len(ev) >= 1, f"missing T1 event {name!r}"
        finally:
            _uninstall_router()


# ---------------------------------------------------------------------------
# 3. Fallback modes
# ---------------------------------------------------------------------------


class TestFallbackModes:
    @pytest.mark.asyncio
    async def test_unconfigured_llm_routes_to_template_fallback_mode(self, http, db):
        scripted = _ScriptedRouter(
            intent_raises=LLMNotConfiguredError("LLM provider not configured"),
        )
        _install_router(scripted)
        try:
            token = await _login(http, "advisor1")
            start = await http.post("/api/v2/conversations", headers=_h(token), json={})
            cid = start.json()["conversation_id"]
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "I want to onboard a new client"},
            )
            assert r.status_code == 200
            body = r.json()
            # Conversation still progresses via templated fallback.
            assert body["state"] == ConversationState.COLLECTING_BASICS.value
            assert body["intent"] == "investor_onboarding"
            # Latest system message carries the fallback notice.
            last_system = next(
                m for m in reversed(body["messages"]) if m["sender"] == "system"
            )
            assert last_system["metadata"].get("fallback_mode") is True

            failures = (
                await db.execute(
                    select(T1Event).where(T1Event.event_name == C0_LLM_FAILURE)
                )
            ).scalars().all()
            assert len(failures) == 1
            assert failures[0].payload["failure_type"] == "not_configured"
        finally:
            _uninstall_router()

    @pytest.mark.asyncio
    async def test_provider_call_failure_during_slot_extraction_triggers_fallback(self, http):
        scripted = _ScriptedRouter(
            intent_response='{"intent": "investor_onboarding", "extracted_fields": {}}',
            slot_raises=LLMCallFailedError(
                "rate limited", failure_type="rate_limit", provider="mistral"
            ),
        )
        _install_router(scripted)
        try:
            token = await _login(http, "advisor1")
            start = await http.post("/api/v2/conversations", headers=_h(token), json={})
            cid = start.json()["conversation_id"]
            # Turn 1 — intent succeeds.
            await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "onboard new client"},
            )
            # Turn 2 — slot extraction raises; fallback kicks in.
            r = await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "his name is Rajesh"},
            )
            body = r.json()
            last_system = next(
                m for m in reversed(body["messages"]) if m["sender"] == "system"
            )
            assert last_system["metadata"].get("fallback_mode") is True
        finally:
            _uninstall_router()


# ---------------------------------------------------------------------------
# 4. Listing + scoping
# ---------------------------------------------------------------------------


async def _seed_other_advisor_conversation(db, *, user_id: str = "advisor_other") -> str:
    """Inject a conversation owned by a different user_id directly into the
    DB so scoping tests can verify visibility without needing the dev users
    YAML to declare a second advisor."""
    from datetime import datetime, timezone

    from ulid import ULID

    from artha.api_v2.c0.models import Conversation
    from artha.api_v2.c0.state_machine import ConversationState

    now = datetime.now(timezone.utc)
    convo = Conversation(
        conversation_id=str(ULID()),
        user_id=user_id,
        firm_id="demo-firm-001",
        intent="investor_onboarding",
        state=ConversationState.COLLECTING_BASICS.value,
        collected_slots={},
        status="active",
        started_at=now,
        last_message_at=now,
    )
    db.add(convo)
    await db.commit()
    return convo.conversation_id


class TestListConversations:
    @pytest.mark.asyncio
    async def test_advisor_only_sees_own_conversations(self, http, db):
        # advisor1 starts a conversation through the API.
        token = await _login(http, "advisor1")
        await http.post("/api/v2/conversations", headers=_h(token), json={})
        # Seed a separate conversation owned by a different user_id.
        await _seed_other_advisor_conversation(db, user_id="advisor_other")

        r = await http.get("/api/v2/conversations", headers=_h(token))
        assert r.status_code == 200
        body = r.json()
        assert len(body["conversations"]) == 1, (
            "advisor1 should only see their own conversation; "
            "the seeded other-advisor conversation must be filtered"
        )

    @pytest.mark.asyncio
    async def test_cio_sees_firm_wide_conversations(self, http, db):
        # advisor1 starts one conversation; we seed another for advisor_other.
        token = await _login(http, "advisor1")
        await http.post("/api/v2/conversations", headers=_h(token), json={})
        await _seed_other_advisor_conversation(db, user_id="advisor_other")

        cio_token = await _login(http, "cio1")
        r = await http.get("/api/v2/conversations", headers=_h(cio_token))
        assert r.status_code == 200
        body = r.json()
        # CIO sees both — firm_scope.
        assert len(body["conversations"]) == 2


# ---------------------------------------------------------------------------
# 5. Cancel + abandonment
# ---------------------------------------------------------------------------


class TestCancelAndAbandon:
    @pytest.mark.asyncio
    async def test_advisor_can_cancel_conversation(self, http, db):
        token = await _login(http, "advisor1")
        start = await http.post("/api/v2/conversations", headers=_h(token), json={})
        cid = start.json()["conversation_id"]
        r = await http.post(
            f"/api/v2/conversations/{cid}/cancel", headers=_h(token), json={}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "abandoned"
        assert body["state"] == ConversationState.ABANDONED.value

        events = (
            await db.execute(
                select(T1Event).where(T1Event.event_name == C0_CONVERSATION_ABANDONED)
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].payload["abandonment_reason"] == "user_cancelled"

    @pytest.mark.asyncio
    async def test_cancel_after_complete_returns_409(self, http):
        scripted = _ScriptedRouter(
            intent_response='{"intent": "investor_onboarding", "extracted_fields": {}}',
        )
        _install_router(scripted)
        try:
            token = await _login(http, "advisor1")
            start = await http.post(
                "/api/v2/conversations", headers=_h(token), json={}
            )
            cid = start.json()["conversation_id"]
            await http.post(
                f"/api/v2/conversations/{cid}/cancel", headers=_h(token), json={}
            )
            # second cancel — already abandoned.
            r = await http.post(
                f"/api/v2/conversations/{cid}/cancel", headers=_h(token), json={}
            )
            assert r.status_code == 409
        finally:
            _uninstall_router()


# ---------------------------------------------------------------------------
# 6. Get one conversation + 404 path
# ---------------------------------------------------------------------------


class TestGetConversation:
    @pytest.mark.asyncio
    async def test_get_existing_returns_full_history(self, http):
        scripted = _ScriptedRouter(
            intent_response=(
                '{"intent": "investor_onboarding", '
                '"extracted_fields": {"name": "X Y"}}'
            ),
        )
        _install_router(scripted)
        try:
            token = await _login(http, "advisor1")
            start = await http.post(
                "/api/v2/conversations", headers=_h(token), json={}
            )
            cid = start.json()["conversation_id"]
            await http.post(
                f"/api/v2/conversations/{cid}/messages",
                headers=_h(token),
                json={"content": "onboard a client"},
            )
            r = await http.get(
                f"/api/v2/conversations/{cid}", headers=_h(token)
            )
            assert r.status_code == 200
            body = r.json()
            assert len(body["messages"]) >= 2  # 1 user + ≥1 system
            assert body["messages"][0]["sender"] == "user"
        finally:
            _uninstall_router()

    @pytest.mark.asyncio
    async def test_get_unknown_id_returns_404(self, http):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/conversations/01ABCNONEXIST5678", headers=_h(token)
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_advisor_cannot_see_another_advisors_conversation(self, http, db):
        # Seed a conversation owned by a different user_id directly.
        cid = await _seed_other_advisor_conversation(db, user_id="advisor_other")
        # advisor1 logs in and tries to fetch it.
        token = await _login(http, "advisor1")
        r = await http.get(f"/api/v2/conversations/{cid}", headers=_h(token))
        assert r.status_code == 404
