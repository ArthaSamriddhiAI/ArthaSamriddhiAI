"""Cluster 0 chunk 0.2 backend test suite.

Covers the backend half of role-based home tree routing:

- TokenResponse.redirect_url is computed per-role for /api/v2/auth/dev-login
- Refresh response also carries redirect_url
- POST /api/v2/system/role-home-visited gates on auth + emits T1
- T1 event payload shape per chunk plan §scope_in (criterion 11)
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.observability.models import T1Event
from artha.api_v2.system.event_names import ROLE_HOME_VISITED
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import settings

_TEST_JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"


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


@pytest_asyncio.fixture
async def db():
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
async def http(db):
    async def _override_get_session():
        yield db

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


# ===========================================================================
# 1. redirect_url on dev-login + refresh
# ===========================================================================


class TestRedirectUrl:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "user_id,expected_url",
        [
            ("advisor1", "/app/advisor"),
            ("cio1", "/app/cio"),
            ("compliance1", "/app/compliance"),
            ("audit1", "/app/audit"),
        ],
    )
    async def test_dev_login_returns_role_specific_redirect_url(
        self, http, user_id, expected_url
    ):
        response = await http.post(
            "/api/v2/auth/dev-login", json={"user_id": user_id}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["redirect_url"] == expected_url

    @pytest.mark.asyncio
    async def test_refresh_response_also_carries_redirect_url(self, http):
        # Login first to set the cookie.
        login = await http.post(
            "/api/v2/auth/dev-login", json={"user_id": "cio1"}
        )
        cookie = login.cookies.get("samriddhi_refresh")

        refresh = await http.post(
            "/api/v2/auth/refresh", cookies={"samriddhi_refresh": cookie}
        )
        assert refresh.status_code == 200
        body = refresh.json()
        assert body["redirect_url"] == "/app/cio"


# ===========================================================================
# 2. /api/v2/system/role-home-visited
# ===========================================================================


class TestRoleHomeVisitedEndpoint:
    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, http):
        response = await http.post("/api/v2/system/role-home-visited")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_returns_204(self, http):
        login = await http.post(
            "/api/v2/auth/dev-login", json={"user_id": "advisor1"}
        )
        token = login.json()["access_token"]
        response = await http.post(
            "/api/v2/system/role-home-visited",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 204
        # 204 → empty body
        assert response.text == ""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "user_id,expected_role",
        [
            ("advisor1", "advisor"),
            ("cio1", "cio"),
            ("compliance1", "compliance"),
            ("audit1", "audit"),
        ],
    )
    async def test_emits_role_home_visited_t1_with_correct_payload(
        self, http, db, user_id, expected_role
    ):
        login = await http.post(
            "/api/v2/auth/dev-login", json={"user_id": user_id}
        )
        token = login.json()["access_token"]
        await http.post(
            "/api/v2/system/role-home-visited",
            headers={"Authorization": f"Bearer {token}"},
        )

        result = await db.execute(
            select(T1Event).where(T1Event.event_name == ROLE_HOME_VISITED)
        )
        events = list(result.scalars())
        assert len(events) == 1
        payload = events[0].payload
        # Per chunk 0.2 acceptance criterion 11:
        # "role_home_visited with payload {role, user_id}"
        assert payload["role"] == expected_role
        assert payload["user_id"] == user_id
        # firm_id is also captured for audit scope.
        assert events[0].firm_id == "demo-firm-001"

    @pytest.mark.asyncio
    async def test_multiple_visits_emit_multiple_events(self, http, db):
        """Each navigation should produce its own event (per criterion 11)."""
        login = await http.post(
            "/api/v2/auth/dev-login", json={"user_id": "advisor1"}
        )
        token = login.json()["access_token"]
        for _ in range(3):
            await http.post(
                "/api/v2/system/role-home-visited",
                headers={"Authorization": f"Bearer {token}"},
            )
        result = await db.execute(
            select(T1Event).where(T1Event.event_name == ROLE_HOME_VISITED)
        )
        events = list(result.scalars())
        assert len(events) == 3
