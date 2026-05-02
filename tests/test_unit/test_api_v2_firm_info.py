"""Cluster 0 firm-info endpoint test suite.

Covers:
- Returns the demo firm config from dev/test_users.yaml
- Required permission gates correctly (all four roles can read)
- Firm-id mismatch defence-in-depth (Dev-Mode Addendum §3.5)
- Response shape per chunk plan §scope_in (firm_id, firm_name, firm_display_name,
  branding{primary_color, accent_color, logo_url}, feature_flags placeholder,
  regulatory_jurisdiction)
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import issue_jwt, reset_dev_secret_cache
from artha.api_v2.auth.user_context import Role
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


async def _login_and_get_token(http, user_id: str) -> str:
    resp = await http.post("/api/v2/auth/dev-login", json={"user_id": user_id})
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------


class TestFirmInfoHappyPath:
    @pytest.mark.asyncio
    async def test_returns_demo_firm_config(self, http):
        token = await _login_and_get_token(http, "advisor1")
        resp = await http.get(
            "/api/v2/system/firm-info",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["firm_id"] == "demo-firm-001"
        assert body["firm_name"] == "Demo Wealth Advisory"
        assert body["firm_display_name"] == "Demo Wealth Advisory Pvt Ltd"
        assert body["regulatory_jurisdiction"] == "IN"
        assert body["feature_flags"] == {}  # placeholder
        # Branding object
        assert body["branding"]["primary_color"] == "#0D2944"
        assert body["branding"]["accent_color"] == "#1A8A8A"
        assert body["branding"]["logo_url"] == "/static/demo-logo.png"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "user_id,role_value",
        [("advisor1", "advisor"), ("cio1", "cio"),
         ("compliance1", "compliance"), ("audit1", "audit")],
    )
    async def test_all_four_roles_can_read_firm_info(self, http, user_id, role_value):
        token = await _login_and_get_token(http, user_id)
        resp = await http.get(
            "/api/v2/system/firm-info",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"{role_value} got {resp.status_code}"
        assert resp.json()["firm_id"] == "demo-firm-001"


class TestFirmInfoAuthRequired:
    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, http):
        resp = await http.get("/api/v2/system/firm-info")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_token_returns_401(self, http):
        resp = await http.get(
            "/api/v2/system/firm-info",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert resp.status_code == 401


class TestFirmInfoFirmIdMismatch:
    """Per Dev-Mode Addendum §3.5 — defence-in-depth firm-id check."""

    @pytest.mark.asyncio
    async def test_jwt_with_wrong_firm_id_returns_403(self, http):
        # Mint a JWT with a fake firm_id (something the YAML doesn't know).
        token = issue_jwt(
            user_id="rogue-user",
            firm_id="some-other-firm",  # mismatch!
            role=Role.ADVISOR,
            email="rogue@elsewhere.test",
            name="Rogue",
            session_id="01ABCDEFGHJKMNPQRSTVWXYZ56",
        )
        resp = await http.get(
            "/api/v2/system/firm-info",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert "does not match" in resp.json()["detail"].lower()
