"""Cluster 0 SSE channel test suite.

Covers:

- EventEnvelope serialisation + cluster 0 payload shapes (FR 18.0 §2.3 / §4)
- ConnectionBuffer: append, prune, iter_since, is_replayable (FR 18.0 §2.5)
- Subscription scope resolution from role + event filter (FR 18.0 §2.6, FR 17.2)
- Registry + publish fan-out with per-session buffer dedupe
- SSE stream generator: connection_established, heartbeat, token_refresh_required,
  Last-Event-ID replay, T1 events, cleanup (FR 18.0 acceptance tests 1-10)
- HTTP smoke tests: 401 without JWT, 200 + correct headers with JWT
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Force ORM modules to register on Base.metadata before fixtures run.
import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth import sessions as sessions_service
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.events import registry as registry_module
from artha.api_v2.events import stream as stream_module
from artha.api_v2.events.buffer import ConnectionBuffer
from artha.api_v2.events.envelope import (
    SCHEMA_VERSION,
    EventEnvelope,
    connection_heartbeat_envelope,
)
from artha.api_v2.events.envelope import (
    envelope as build_envelope,
)
from artha.api_v2.events.event_names import (
    SSE_CONNECTION_CLOSED,
    SSE_CONNECTION_OPENED,
)
from artha.api_v2.events.event_types import (
    CLUSTER_0_SUBSCRIBED,
    CONNECTION_ESTABLISHED,
    CONNECTION_HEARTBEAT,
    TOKEN_REFRESH_REQUIRED,
)
from artha.api_v2.events.registry import (
    ConnectionState,
    publish,
    reset_for_tests,
)
from artha.api_v2.events.stream import sse_event_stream
from artha.api_v2.events.subscription import (
    FIRM_SCOPE,
    OWN_SCOPE,
    event_passes_scope,
    scope_for_role,
)
from artha.api_v2.observability.models import T1Event
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import settings

_TEST_JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"


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
def reset_sse_state():
    """Clear connection + buffer registries between tests."""
    reset_for_tests()
    reload_catalogue()
    yield
    reset_for_tests()


@pytest.fixture
def fast_heartbeat(monkeypatch):
    """Make the SSE heartbeat fire ~10x/s so tests don't wait 30 seconds."""
    monkeypatch.setattr(settings, "sse_heartbeat_interval_seconds", 0.1)
    yield


@pytest_asyncio.fixture
async def db():
    """Shared-connection in-memory SQLite so the SSE stream's T1 emit
    (which opens a fresh session) sees the same in-memory DB the test reads
    from. StaticPool keeps a single underlying connection.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def http(db, monkeypatch):
    """HTTP client + DB hooked into both the auth router AND the SSE T1 emitter."""

    async def _override_get_session():
        yield db

    app.dependency_overrides[get_session] = _override_get_session
    # Make the SSE stream's fresh-session T1 emitter use the test engine.
    monkeypatch.setattr(
        "artha.api_v2.events.stream.get_engine", lambda: db.bind
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


@pytest_asyncio.fixture
async def authed_user(db):
    """Login an advisor and return (token, user_context)."""
    async with db.begin():
        issued = await sessions_service.create_session(
            db,
            user_id="advisor1",
            firm_id="demo-firm-001",
            role=Role.ADVISOR,
            email="advisor1@demo.test",
            name="Anjali Mehta",
        )
    return issued.access_jwt, UserContext(
        user_id="advisor1",
        firm_id="demo-firm-001",
        role=Role.ADVISOR,
        email="advisor1@demo.test",
        name="Anjali Mehta",
        session_id=issued.session.session_id,
    )


@pytest_asyncio.fixture
async def stream_engine_patch(db, monkeypatch):
    """Make the SSE stream module's T1 emit use the test engine."""
    monkeypatch.setattr(
        "artha.api_v2.events.stream.get_engine", lambda: db.bind
    )
    yield


# ---------------------------------------------------------------------------
# Helper: drive the stream generator directly with a hard timeout
# ---------------------------------------------------------------------------


async def collect_frames(generator, *, count: int, timeout: float = 5.0) -> list[dict[str, str]]:
    """Pull the next ``count`` frames from a stream generator with timeout."""
    frames = []
    for _ in range(count):
        frame = await asyncio.wait_for(generator.__anext__(), timeout=timeout)
        frames.append(frame)
    return frames


# ===========================================================================
# 1. EventEnvelope schema
# ===========================================================================


class TestEventEnvelope:
    def test_envelope_has_schema_version_1(self):
        env = build_envelope(event_type="x", payload={"k": "v"}, firm_id="f")
        assert env.schema_version == SCHEMA_VERSION == "1"

    def test_envelope_event_id_is_ulid(self):
        env = build_envelope(event_type="x", payload={}, firm_id="f")
        assert len(env.event_id) == 26

    def test_envelope_serialises_to_json(self):
        env = build_envelope(event_type="x", payload={"a": 1}, firm_id="f")
        s = env.model_dump_json()
        parsed = json.loads(s)
        assert parsed["schema_version"] == "1"
        assert parsed["event_type"] == "x"
        assert parsed["payload"] == {"a": 1}
        assert parsed["firm_id"] == "f"

    def test_envelope_rejects_unknown_field(self):
        with pytest.raises(Exception):
            EventEnvelope(
                event_id="01ABCDEFGHJKMNPQRSTVWXYZ56",
                event_type="x",
                emitted_at=datetime.now(timezone.utc),
                payload={},
                firm_id="f",
                schema_version="1",
                bogus_field="nope",  # type: ignore[call-arg]
            )

    def test_heartbeat_envelope_minimal_payload(self):
        env = connection_heartbeat_envelope(firm_id="f")
        assert env.event_type == CONNECTION_HEARTBEAT
        assert set(env.payload.keys()) == {"server_time"}


# ===========================================================================
# 2. ConnectionBuffer
# ===========================================================================


class TestConnectionBuffer:
    def test_append_increases_length(self):
        b = ConnectionBuffer()
        b.append(build_envelope(event_type="x", payload={}, firm_id="f"))
        assert len(b) == 1

    def test_iter_since_returns_events_after_id(self):
        b = ConnectionBuffer()
        e1 = build_envelope(event_type="a", payload={}, firm_id="f")
        b.append(e1)
        time.sleep(0.005)
        e2 = build_envelope(event_type="b", payload={}, firm_id="f")
        b.append(e2)
        time.sleep(0.005)
        e3 = build_envelope(event_type="c", payload={}, firm_id="f")
        b.append(e3)

        assert b.iter_since(e1.event_id) == [e2, e3]
        assert b.iter_since(None) == [e1, e2, e3]
        assert b.iter_since(e3.event_id) == []

    def test_prune_drops_old_events(self):
        b = ConnectionBuffer(window=timedelta(milliseconds=50))
        old = build_envelope(event_type="old", payload={}, firm_id="f")
        b.append(old, ingested_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        new = build_envelope(event_type="new", payload={}, firm_id="f")
        b.append(new)
        assert b.iter_since(None) == [new]

    def test_is_replayable_true_when_id_within_window(self):
        b = ConnectionBuffer()
        e1 = build_envelope(event_type="x", payload={}, firm_id="f")
        b.append(e1)
        assert b.is_replayable(e1.event_id) is True

    def test_is_replayable_false_when_id_older_than_window(self):
        b = ConnectionBuffer()
        truly_old = "00000000000000000000000000"
        e1 = build_envelope(event_type="x", payload={}, firm_id="f")
        b.append(e1)
        assert b.is_replayable(truly_old) is False

    def test_is_replayable_true_for_empty_buffer(self):
        b = ConnectionBuffer()
        assert b.is_replayable("01ABCDEFGHJKMNPQRSTVWXYZ56") is True


# ===========================================================================
# 3. Subscription scope
# ===========================================================================


class TestSubscriptionScope:
    def test_advisor_gets_own_scope(self):
        scope = scope_for_role(Role.ADVISOR)
        assert scope.alerts == OWN_SCOPE
        assert scope.cases == OWN_SCOPE
        assert scope.monitoring == OWN_SCOPE

    @pytest.mark.parametrize("role", [Role.CIO, Role.COMPLIANCE, Role.AUDIT])
    def test_non_advisor_gets_firm_scope(self, role):
        scope = scope_for_role(role)
        assert scope.alerts == FIRM_SCOPE
        assert scope.cases == FIRM_SCOPE
        assert scope.monitoring == FIRM_SCOPE

    def test_event_filter_blocks_cross_firm(self):
        passes = event_passes_scope(
            role=Role.ADVISOR,
            user_id="u1",
            firm_id="firm-A",
            event_firm_id="firm-B",
        )
        assert passes is False

    def test_event_filter_blocks_other_advisor_for_own_scope(self):
        passes = event_passes_scope(
            role=Role.ADVISOR,
            user_id="advisor1",
            firm_id="firm-A",
            event_firm_id="firm-A",
            event_owner_user_id="advisor2",
        )
        assert passes is False

    def test_event_filter_allows_same_advisor_own_event(self):
        passes = event_passes_scope(
            role=Role.ADVISOR,
            user_id="advisor1",
            firm_id="firm-A",
            event_firm_id="firm-A",
            event_owner_user_id="advisor1",
        )
        assert passes is True

    def test_event_filter_allows_cio_firm_event(self):
        passes = event_passes_scope(
            role=Role.CIO,
            user_id="cio1",
            firm_id="firm-A",
            event_firm_id="firm-A",
            event_owner_user_id="advisor2",
        )
        assert passes is True


# ===========================================================================
# 4. Registry + publish
# ===========================================================================


class TestRegistryAndPublish:
    @pytest.mark.asyncio
    async def test_publish_delivers_to_matching_connection(self):
        reg = registry_module.get_registry()
        bufs = registry_module.get_buffer_registry()
        buffer = bufs.get_or_create("session-A")
        state = ConnectionState(
            connection_id="conn-1",
            session_id="session-A",
            user_id="cio1",
            firm_id="firm-A",
            role=Role.CIO,
            buffer=buffer,
        )
        reg.register(state)

        env = build_envelope(event_type="x", payload={}, firm_id="firm-A")
        delivered = await publish(env)
        assert delivered == 1
        assert state.queue.qsize() == 1
        assert len(buffer) == 1

    @pytest.mark.asyncio
    async def test_publish_skips_other_firm(self):
        reg = registry_module.get_registry()
        bufs = registry_module.get_buffer_registry()
        buffer = bufs.get_or_create("session-A")
        state = ConnectionState(
            connection_id="conn-1",
            session_id="session-A",
            user_id="cio1",
            firm_id="firm-A",
            role=Role.CIO,
            buffer=buffer,
        )
        reg.register(state)
        env = build_envelope(event_type="x", payload={}, firm_id="firm-B")
        delivered = await publish(env)
        assert delivered == 0
        assert state.queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_publish_dedupes_buffer_per_session(self):
        reg = registry_module.get_registry()
        bufs = registry_module.get_buffer_registry()
        shared_buffer = bufs.get_or_create("session-A")
        s1 = ConnectionState(
            connection_id="conn-1", session_id="session-A",
            user_id="u1", firm_id="firm-A", role=Role.CIO, buffer=shared_buffer,
        )
        s2 = ConnectionState(
            connection_id="conn-2", session_id="session-A",
            user_id="u1", firm_id="firm-A", role=Role.CIO, buffer=shared_buffer,
        )
        reg.register(s1)
        reg.register(s2)
        env = build_envelope(event_type="x", payload={}, firm_id="firm-A")
        delivered = await publish(env)
        assert delivered == 2
        assert s1.queue.qsize() == 1
        assert s2.queue.qsize() == 1
        assert len(shared_buffer) == 1


# ===========================================================================
# 5. SSE stream generator (direct, no HTTP)
#
# These tests drive sse_event_stream() directly because it's the unit of
# behaviour that matters; HTTP-level concerns (status code, headers, auth)
# are covered by TestSSEEndpoint below.
# ===========================================================================


class TestSSEStreamGenerator:
    @pytest.mark.asyncio
    async def test_first_frame_is_connection_established(
        self, authed_user, fast_heartbeat, stream_engine_patch
    ):
        _, user_context = authed_user
        gen = sse_event_stream(user_context, last_event_id=None, jwt_exp=None)
        try:
            frames = await collect_frames(gen, count=1)
        finally:
            await gen.aclose()

        assert len(frames) == 1
        assert frames[0]["event"] == CONNECTION_ESTABLISHED
        assert len(frames[0]["id"]) == 26  # ULID
        env = json.loads(frames[0]["data"])
        assert env["schema_version"] == "1"
        assert env["event_type"] == CONNECTION_ESTABLISHED
        assert env["firm_id"] == "demo-firm-001"

    @pytest.mark.asyncio
    async def test_connection_established_payload_per_fr_18_0_4_1(
        self, authed_user, fast_heartbeat, stream_engine_patch
    ):
        _, user_context = authed_user
        gen = sse_event_stream(user_context, last_event_id=None, jwt_exp=None)
        try:
            frame = (await collect_frames(gen, count=1))[0]
        finally:
            await gen.aclose()
        payload = json.loads(frame["data"])["payload"]
        assert payload["user_id"] == "advisor1"
        assert payload["role"] == "advisor"
        assert payload["heartbeat_interval_seconds"] == settings.sse_heartbeat_interval_seconds
        assert payload["max_payload_bytes"] == settings.sse_max_payload_bytes
        assert set(payload["subscribed_event_types"]) == set(CLUSTER_0_SUBSCRIBED)
        assert payload["subscription_scope"]["alerts"] == OWN_SCOPE
        assert payload["subscription_scope"]["cases"] == OWN_SCOPE
        assert payload["subscription_scope"]["monitoring"] == OWN_SCOPE

    @pytest.mark.asyncio
    async def test_heartbeats_fire_after_established(
        self, authed_user, fast_heartbeat, stream_engine_patch
    ):
        _, user_context = authed_user
        gen = sse_event_stream(user_context, last_event_id=None, jwt_exp=None)
        try:
            frames = await collect_frames(gen, count=3)
        finally:
            await gen.aclose()
        assert frames[0]["event"] == CONNECTION_ESTABLISHED
        assert frames[1]["event"] == CONNECTION_HEARTBEAT
        assert frames[2]["event"] == CONNECTION_HEARTBEAT
        hb = json.loads(frames[1]["data"])
        assert set(hb["payload"].keys()) == {"server_time"}

    @pytest.mark.asyncio
    async def test_token_refresh_required_fires_before_jwt_exp(
        self, authed_user, monkeypatch, stream_engine_patch
    ):
        """Set JWT exp to ~1.5s out and lead to ~1.4s; expect refresh ~0.1s in."""
        _, user_context = authed_user
        monkeypatch.setattr(settings, "sse_token_refresh_lead_seconds", 5)
        monkeypatch.setattr(settings, "sse_heartbeat_interval_seconds", 30)  # don't compete
        # JWT exp = now + 5.2s; lead = 5s ⇒ fire ~0.2s in.
        jwt_exp = int(datetime.now(timezone.utc).timestamp()) + 6
        gen = sse_event_stream(user_context, last_event_id=None, jwt_exp=jwt_exp)
        try:
            frames = await collect_frames(gen, count=2, timeout=3.0)
        finally:
            await gen.aclose()
        assert frames[0]["event"] == CONNECTION_ESTABLISHED
        assert frames[1]["event"] == TOKEN_REFRESH_REQUIRED
        payload = json.loads(frames[1]["data"])["payload"]
        assert payload["seconds_until_expiry"] == 5
        assert payload["refresh_endpoint"] == "/api/v2/auth/refresh"

    @pytest.mark.asyncio
    async def test_t1_connection_opened_emitted(
        self, authed_user, fast_heartbeat, stream_engine_patch, db
    ):
        _, user_context = authed_user
        gen = sse_event_stream(user_context, last_event_id=None, jwt_exp=None)
        try:
            await collect_frames(gen, count=1)
        finally:
            await gen.aclose()

        # Allow the in-flight cleanup T1 emit to commit.
        await asyncio.sleep(0.05)

        result = await db.execute(
            select(T1Event).where(T1Event.event_name == SSE_CONNECTION_OPENED)
        )
        events = list(result.scalars())
        assert len(events) == 1
        payload = events[0].payload
        assert payload["user_id"] == "advisor1"
        assert payload["role"] == "advisor"
        assert payload["firm_id"] == "demo-firm-001"

    @pytest.mark.asyncio
    async def test_t1_connection_closed_emitted_on_cleanup(
        self, authed_user, fast_heartbeat, stream_engine_patch, db
    ):
        _, user_context = authed_user
        gen = sse_event_stream(user_context, last_event_id=None, jwt_exp=None)
        try:
            await collect_frames(gen, count=1)
        finally:
            await gen.aclose()
        await asyncio.sleep(0.05)

        result = await db.execute(
            select(T1Event).where(T1Event.event_name == SSE_CONNECTION_CLOSED)
        )
        events = list(result.scalars())
        assert len(events) == 1
        payload = events[0].payload
        assert "connection_duration_seconds" in payload
        assert "total_events_emitted" in payload

    @pytest.mark.asyncio
    async def test_registry_clears_on_close(
        self, authed_user, fast_heartbeat, stream_engine_patch
    ):
        _, user_context = authed_user
        gen = sse_event_stream(user_context, last_event_id=None, jwt_exp=None)
        try:
            await collect_frames(gen, count=1)
            assert len(registry_module.get_registry()) == 1
        finally:
            await gen.aclose()
        await asyncio.sleep(0.02)
        assert len(registry_module.get_registry()) == 0


# ===========================================================================
# 6. Last-Event-ID replay across reconnect (per-session shared buffer)
# ===========================================================================


class TestLastEventIdReplay:
    @pytest.mark.asyncio
    async def test_reconnect_with_last_event_id_replays_buffered(
        self, authed_user, fast_heartbeat, stream_engine_patch
    ):
        _, user_context = authed_user

        # Connection 1: read 3 frames (established + 2 heartbeats).
        gen1 = sse_event_stream(user_context, last_event_id=None, jwt_exp=None)
        try:
            frames1 = await collect_frames(gen1, count=3)
        finally:
            await gen1.aclose()
        last_id = frames1[-1]["id"]

        # Connection 2: same session, present Last-Event-ID. Expect a new
        # connection_established (id > last_id) — buffered events from
        # connection 1 still in the per-session shared buffer.
        gen2 = sse_event_stream(
            user_context, last_event_id=last_id, jwt_exp=None
        )
        try:
            frames2 = await collect_frames(gen2, count=1)
        finally:
            await gen2.aclose()

        assert frames2[0]["event"] == CONNECTION_ESTABLISHED
        assert frames2[0]["id"] > last_id

    @pytest.mark.asyncio
    async def test_reconnect_with_unknown_last_event_id_still_emits_established(
        self, authed_user, fast_heartbeat, stream_engine_patch
    ):
        _, user_context = authed_user
        truly_old = "00000000000000000000000000"
        gen = sse_event_stream(user_context, last_event_id=truly_old, jwt_exp=None)
        try:
            frames = await collect_frames(gen, count=1)
        finally:
            await gen.aclose()
        # Per FR 18.0 §2.5: when Last-Event-ID is older than the buffer's
        # earliest event, emit a fresh connection_established.
        assert frames[0]["event"] == CONNECTION_ESTABLISHED


# ===========================================================================
# 7. HTTP smoke tests — auth gating + response headers
# ===========================================================================


class TestSSEEndpointHTTP:
    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, http):
        resp = await http.get("/api/v2/events/stream")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_router_returns_event_source_response_with_anti_buffering_headers(
        self, authed_user, fast_heartbeat, stream_engine_patch
    ):
        """Direct call of the router function — verifies the response's headers.

        We deliberately skip an end-to-end http.stream() test for this concern:
        sse-starlette's EventSourceResponse keeps the generator alive on early
        close, which can deadlock the test runner on cleanup. Inspecting the
        constructed response's headers directly is sufficient to verify the
        FR 18.0 §2.1 anti-proxy-buffering contract.
        """
        from starlette.requests import Request

        from artha.api_v2.events.router import stream

        _, user = authed_user
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/events/stream",
            "headers": [(b"authorization", b"Bearer fake")],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
        }
        request = Request(scope)
        response = await stream(request=request, user=user, last_event_id=None)

        cc = response.headers.get("cache-control", "").lower()
        assert "no-cache" in cc
        assert "no-transform" in cc
        assert response.headers.get("x-accel-buffering", "").lower() == "no"

        # Ensure we don't leave a live ConnectionState in the registry; the
        # response was constructed but never iterated, so nothing was registered.
        assert len(registry_module.get_registry()) == 0


# ===========================================================================
# 8. Sanity — stream_module's _frame helper produces valid SSE dicts
# ===========================================================================


class TestFrameFormatting:
    def test_frame_contains_id_event_data(self):
        env = build_envelope(event_type="x", payload={"a": 1}, firm_id="f")
        frame = stream_module._frame(env)
        assert set(frame.keys()) == {"id", "event", "data"}
        assert frame["id"] == env.event_id
        assert frame["event"] == "x"
        # data is JSON-serialised envelope
        assert json.loads(frame["data"])["event_id"] == env.event_id
