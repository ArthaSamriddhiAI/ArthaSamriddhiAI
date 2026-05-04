"""Cluster 1 chunk 1.3 — REST endpoint test suite.

Covers the full surface from the chunk plan:

- ``GET    /api/v2/llm/config``
- ``GET    /api/v2/llm/status``
- ``PUT    /api/v2/llm/config``
- ``POST   /api/v2/llm/test-connection``
- ``POST   /api/v2/llm/kill-switch/activate``
- ``POST   /api/v2/llm/kill-switch/deactivate``

Each endpoint is verified for:

- CIO can call (200/201).
- Advisor / Compliance / Audit cannot (403).
- Validation errors → 400 problem details with the right code.
- Side-effects: T1 events fire; API keys are stored encrypted (never
  plaintext); masking shows up in the GET response.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.llm.encryption import reset_encryption_cache
from artha.api_v2.llm.event_names import (
    LLM_KILL_SWITCH_ACTIVATED,
    LLM_KILL_SWITCH_DEACTIVATED,
    LLM_PROVIDER_CONFIGURATION_CHANGED,
)
from artha.api_v2.llm.models import LLMProviderConfig
from artha.api_v2.observability.models import T1Event
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import Environment, settings

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
def deterministic_encryption_key(monkeypatch):
    monkeypatch.setattr(
        settings, "samriddhi_encryption_key", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setattr(settings, "environment", Environment.DEVELOPMENT)
    reset_encryption_cache()
    yield
    reset_encryption_cache()


@pytest.fixture(autouse=True)
def reset_users_cache():
    reload_catalogue()
    yield


@pytest_asyncio.fixture
async def engine_and_factory():
    """A fresh engine + session factory per test (StaticPool keeps the
    in-memory SQLite DB visible across all sessions yielded from the factory)."""
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
    """A standalone session for direct DB verification at the end of tests.

    Production-mirroring HTTP requests (see :func:`http`) get their own fresh
    session per request via the factory, exactly like production
    :func:`artha.common.db.session.get_session` does.
    """
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


async def _login(http, user_id: str) -> str:
    resp = await http.post("/api/v2/auth/dev-login", json={"user_id": user_id})
    return resp.json()["access_token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _stub_test_connection(monkeypatch, *, success: bool):
    """Replace the test-connection backend so we don't hit a real provider."""
    from artha.api_v2.llm import service

    async def fake_test(db, *, payload):
        from artha.api_v2.llm.schemas import TestConnectionResponse
        if success:
            return TestConnectionResponse(
                success=True, provider=payload.provider,
                detail="Connection successful (response: 'OK')", failure_type=None,
                latency_ms=42,
            )
        return TestConnectionResponse(
            success=False, provider=payload.provider,
            detail="Authentication failed", failure_type="auth_error",
        )

    monkeypatch.setattr(service, "test_connection", fake_test)


# ===========================================================================
# 1. GET /api/v2/llm/config — CIO can read; first-run defaults
# ===========================================================================


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_cio_first_run_returns_defaults_with_is_configured_false(self, http):
        token = await _login(http, "cio1")
        resp = await http.get("/api/v2/llm/config", headers=_h(token))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["active_provider"] is None
        assert body["mistral_api_key_masked"] is None
        assert body["claude_api_key_masked"] is None
        assert body["is_configured"] is False
        assert body["kill_switch_active"] is False
        assert body["rate_limit_calls_per_minute"] == 60
        assert body["request_timeout_seconds"] == 30
        assert "mistral" in body["supported_providers"]
        assert "claude" in body["supported_providers"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["advisor1", "compliance1", "audit1"])
    async def test_non_cio_returns_403(self, http, user_id):
        token = await _login(http, user_id)
        resp = await http.get("/api/v2/llm/config", headers=_h(token))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, http):
        resp = await http.get("/api/v2/llm/config")
        assert resp.status_code == 401


# ===========================================================================
# 2. GET /api/v2/llm/status — first-run banner check
# ===========================================================================


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_status_false_before_save(self, http):
        token = await _login(http, "cio1")
        resp = await http.get("/api/v2/llm/status", headers=_h(token))
        assert resp.status_code == 200
        assert resp.json() == {"is_configured": False}

    @pytest.mark.asyncio
    async def test_status_true_after_save(self, http):
        token = await _login(http, "cio1")
        await http.put(
            "/api/v2/llm/config",
            headers=_h(token),
            json={"active_provider": "mistral", "mistral_api_key": "sk-test"},
        )
        resp = await http.get("/api/v2/llm/status", headers=_h(token))
        assert resp.json() == {"is_configured": True}


# ===========================================================================
# 3. PUT /api/v2/llm/config — write surface
# ===========================================================================


class TestPutConfig:
    @pytest.mark.asyncio
    async def test_cio_can_save_initial_config(self, http, db):
        token = await _login(http, "cio1")
        resp = await http.put(
            "/api/v2/llm/config",
            headers=_h(token),
            json={"active_provider": "mistral", "mistral_api_key": "sk-mistral-test-1234"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["active_provider"] == "mistral"
        assert body["mistral_api_key_masked"] == "sk-m****"
        assert body["is_configured"] is True
        assert body["updated_by"] == "cio1"

        # Plaintext key is NOT in the database.
        stored = (await db.execute(select(LLMProviderConfig))).scalar_one()
        assert b"sk-mistral-test-1234" not in (stored.mistral_api_key_encrypted or b"")

        # T1 event emitted.
        events = (
            await db.execute(
                select(T1Event).where(
                    T1Event.event_name == LLM_PROVIDER_CONFIGURATION_CHANGED
                )
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].payload["new_provider"] == "mistral"
        assert events[0].payload["mistral_key_updated"] is True

    @pytest.mark.asyncio
    async def test_active_provider_without_key_returns_400(self, http):
        token = await _login(http, "cio1")
        resp = await http.put(
            "/api/v2/llm/config",
            headers=_h(token),
            json={"active_provider": "mistral"},  # no key supplied
        )
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["title"] == "LLM configuration invalid"
        assert body["code"] == "missing_mistral_api_key"

    @pytest.mark.asyncio
    async def test_can_save_both_keys_and_then_switch_providers(self, http):
        token = await _login(http, "cio1")
        # Save Mistral first.
        r1 = await http.put(
            "/api/v2/llm/config",
            headers=_h(token),
            json={"active_provider": "mistral", "mistral_api_key": "sk-mistral-123"},
        )
        assert r1.status_code == 200
        # Add Claude key but don't switch yet.
        r2 = await http.put(
            "/api/v2/llm/config",
            headers=_h(token),
            json={"claude_api_key": "sk-claude-456"},
        )
        assert r2.status_code == 200
        assert r2.json()["mistral_api_key_masked"] == "sk-m****"
        assert r2.json()["claude_api_key_masked"] == "sk-c****"
        # Switch to Claude.
        r3 = await http.put(
            "/api/v2/llm/config",
            headers=_h(token),
            json={"active_provider": "claude"},
        )
        assert r3.status_code == 200
        assert r3.json()["active_provider"] == "claude"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["advisor1", "compliance1", "audit1"])
    async def test_non_cio_cannot_write(self, http, user_id):
        token = await _login(http, user_id)
        resp = await http.put(
            "/api/v2/llm/config",
            headers=_h(token),
            json={"active_provider": "mistral", "mistral_api_key": "sk-x"},
        )
        assert resp.status_code == 403


# ===========================================================================
# 4. POST /api/v2/llm/test-connection
# ===========================================================================


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_cio_test_connection_success(self, http, monkeypatch):
        _stub_test_connection(monkeypatch, success=True)
        token = await _login(http, "cio1")
        resp = await http.post(
            "/api/v2/llm/test-connection",
            headers=_h(token),
            json={"provider": "mistral", "api_key": "sk-test"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["provider"] == "mistral"
        assert body["latency_ms"] == 42

    @pytest.mark.asyncio
    async def test_cio_test_connection_failure(self, http, monkeypatch):
        _stub_test_connection(monkeypatch, success=False)
        token = await _login(http, "cio1")
        resp = await http.post(
            "/api/v2/llm/test-connection",
            headers=_h(token),
            json={"provider": "claude", "api_key": "sk-bad"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["failure_type"] == "auth_error"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["advisor1", "compliance1", "audit1"])
    async def test_non_cio_cannot_test_connection(self, http, user_id):
        token = await _login(http, user_id)
        resp = await http.post(
            "/api/v2/llm/test-connection",
            headers=_h(token),
            json={"provider": "mistral", "api_key": "sk-x"},
        )
        assert resp.status_code == 403


# ===========================================================================
# 5. Kill switch
# ===========================================================================


class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_cio_can_activate_and_deactivate(self, http, db):
        token = await _login(http, "cio1")
        r1 = await http.post(
            "/api/v2/llm/kill-switch/activate", headers=_h(token)
        )
        assert r1.status_code == 200
        assert r1.json()["kill_switch_active"] is True
        # T1 event.
        ev = (await db.execute(
            select(T1Event).where(T1Event.event_name == LLM_KILL_SWITCH_ACTIVATED)
        )).scalars().all()
        assert len(ev) == 1

        r2 = await http.post(
            "/api/v2/llm/kill-switch/deactivate", headers=_h(token)
        )
        assert r2.status_code == 200
        assert r2.json()["kill_switch_active"] is False
        ev = (await db.execute(
            select(T1Event).where(T1Event.event_name == LLM_KILL_SWITCH_DEACTIVATED)
        )).scalars().all()
        assert len(ev) == 1

    @pytest.mark.asyncio
    async def test_kill_switch_visible_in_get_config(self, http):
        token = await _login(http, "cio1")
        await http.post("/api/v2/llm/kill-switch/activate", headers=_h(token))
        resp = await http.get("/api/v2/llm/config", headers=_h(token))
        assert resp.json()["kill_switch_active"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["advisor1", "compliance1", "audit1"])
    async def test_non_cio_cannot_activate(self, http, user_id):
        token = await _login(http, user_id)
        resp = await http.post(
            "/api/v2/llm/kill-switch/activate", headers=_h(token)
        )
        assert resp.status_code == 403


# ===========================================================================
# 6. End-to-end: save + flip provider + verify state
# ===========================================================================


class TestEndToEndConfigFlow:
    @pytest.mark.asyncio
    async def test_full_flow_first_run_to_configured(self, http, db):
        token = await _login(http, "cio1")

        # First-run banner check.
        st1 = await http.get("/api/v2/llm/status", headers=_h(token))
        assert st1.json() == {"is_configured": False}

        # Save initial config.
        save = await http.put(
            "/api/v2/llm/config",
            headers=_h(token),
            json={
                "active_provider": "mistral",
                "mistral_api_key": "sk-mistral-init",
            },
        )
        assert save.status_code == 200

        # Banner now hides.
        st2 = await http.get("/api/v2/llm/status", headers=_h(token))
        assert st2.json() == {"is_configured": True}

        # Audit trail captured exactly the right T1 events.
        events = (
            await db.execute(
                select(T1Event).where(
                    T1Event.event_name == LLM_PROVIDER_CONFIGURATION_CHANGED
                )
            )
        ).scalars().all()
        assert len(events) == 1
