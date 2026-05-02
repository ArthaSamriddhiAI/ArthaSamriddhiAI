"""Cluster 0 auth + sessions test suite.

Covers:
- JWT signing: roundtrip, expiry, signature/issuer/audience/missing-claim failures
  (FR 17.0 §3.1, FR 17.1 §2.1)
- UserContext construction from JWT claims (FR 17.2)
- dev_users YAML loader (Dev-Mode Addendum §3.1)
- Sessions service: create, refresh w/ rotation, theft detection, expiry,
  revoke, per-user concurrent session cap
  (FR 17.1 §2.3 / §2.5 / §2.6 / §6.4 / acceptance tests 1-10)
- HTTP endpoints via httpx.AsyncClient: dev-login, dev-users, refresh, logout,
  whoami, OIDC stubs (Dev-Mode Addendum §3.2-§3.4)
- T1 events fire with correct payloads (FR 17.0 §5, FR 17.1 §5)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Force the new ORM modules to register on Base.metadata before fixtures run.
import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth import sessions as sessions_service
from artha.api_v2.auth.dev_users import get_catalogue
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.event_names import (
    AUTH_LOGIN_COMPLETED,
    AUTH_LOGIN_FAILED,
    AUTH_LOGOUT,
    SESSION_CREATED,
    SESSION_REFRESHED,
    SESSION_REVOKED,
)
from artha.api_v2.auth.jwt_signing import (
    JWTValidationError,
    issue_jwt,
    reset_dev_secret_cache,
    verify_jwt,
)
from artha.api_v2.auth.models import RevocationReason, SessionRow
from artha.api_v2.auth.sessions import (
    RefreshTokenInvalidError,
    RefreshTokenTheftError,
    SessionExpiredError,
)
from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.observability.models import T1Event
from artha.api_v2.observability.t1 import emit_event
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_TEST_JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"


@pytest.fixture(autouse=True)
def jwt_secret_for_tests(monkeypatch):
    """Pin a deterministic JWT secret across all tests."""
    monkeypatch.setattr(settings, "jwt_secret", _TEST_JWT_SECRET)
    reset_dev_secret_cache()
    yield
    reset_dev_secret_cache()


@pytest.fixture(autouse=True)
def reset_dev_users_cache():
    """Reload the dev users YAML before each test so changes propagate."""
    reload_catalogue()
    yield


@pytest_asyncio.fixture
async def db():
    """Fresh in-memory SQLite for each test, with cluster 0 schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def http(db):
    """HTTP client wired to the FastAPI app, with get_session overridden to db."""

    async def _override_get_session():
        yield db

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# JWT signing  (FR 17.0 §3.1, FR 17.1 §2.1)
# ---------------------------------------------------------------------------


class TestJWTSigning:
    def test_roundtrip_recovers_claims(self):
        token = issue_jwt(
            user_id="advisor1",
            firm_id="demo-firm-001",
            role=Role.ADVISOR,
            email="advisor1@demo.test",
            name="Anjali Mehta",
            session_id="01J0K8YYYZZZAAAA1234567890",
        )
        claims = verify_jwt(token)
        assert claims["sub"] == "advisor1"
        assert claims["firm_id"] == "demo-firm-001"
        assert claims["role"] == "advisor"
        assert claims["email"] == "advisor1@demo.test"
        assert claims["name"] == "Anjali Mehta"
        assert claims["session_id"] == "01J0K8YYYZZZAAAA1234567890"
        assert claims["iss"] == settings.jwt_issuer
        assert claims["aud"] == settings.jwt_audience

    def test_expired_token_rejected(self):
        # Hand-build an already-expired JWT.
        now = int(time.time())
        token = pyjwt.encode(
            {
                "sub": "advisor1",
                "firm_id": "demo-firm-001",
                "role": "advisor",
                "email": "x@y.z",
                "session_id": "01J0K8YYYZZZAAAA1234567890",
                "iat": now - 1000,
                "exp": now - 100,  # past, beyond 60s leeway
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(JWTValidationError):
            verify_jwt(token)

    def test_bad_signature_rejected(self):
        token = issue_jwt(
            user_id="advisor1", firm_id="demo-firm-001", role=Role.ADVISOR,
            email="x@y.z", name="X", session_id="01J0K8YYYZZZAAAA1234567890",
        )
        # Tamper with the last segment (signature).
        tampered = token[:-4] + "AAAA"
        with pytest.raises(JWTValidationError):
            verify_jwt(tampered)

    def test_missing_required_claim_rejected(self):
        # Hand-build a JWT missing session_id.
        now = int(time.time())
        token = pyjwt.encode(
            {
                "sub": "advisor1",
                "firm_id": "demo-firm-001",
                "role": "advisor",
                "email": "x@y.z",
                "iat": now,
                "exp": now + 900,
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(JWTValidationError):
            verify_jwt(token)

    def test_wrong_audience_rejected(self):
        now = int(time.time())
        token = pyjwt.encode(
            {
                "sub": "advisor1", "firm_id": "demo-firm-001", "role": "advisor",
                "email": "x@y.z", "session_id": "01J0K8YYYZZZAAAA1234567890",
                "iat": now, "exp": now + 900,
                "iss": settings.jwt_issuer,
                "aud": "wrong-audience",
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(JWTValidationError):
            verify_jwt(token)


# ---------------------------------------------------------------------------
# UserContext  (FR 17.2)
# ---------------------------------------------------------------------------


class TestUserContext:
    def test_from_valid_claims(self):
        ctx = UserContext.from_jwt_claims({
            "sub": "advisor1",
            "firm_id": "demo-firm-001",
            "role": "advisor",
            "email": "advisor1@demo.test",
            "name": "Anjali Mehta",
            "session_id": "01J0K8YYYZZZAAAA1234567890",
        })
        assert ctx.user_id == "advisor1"
        assert ctx.firm_id == "demo-firm-001"
        assert ctx.role == Role.ADVISOR
        assert ctx.email == "advisor1@demo.test"
        assert ctx.name == "Anjali Mehta"
        assert ctx.session_id == "01J0K8YYYZZZAAAA1234567890"

    def test_missing_required_claim_raises(self):
        with pytest.raises(ValueError, match="firm_id"):
            UserContext.from_jwt_claims({
                "sub": "advisor1",
                "role": "advisor",
                "email": "x@y.z",
                "session_id": "01J0K8YYYZZZAAAA1234567890",
            })

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="unknown role"):
            UserContext.from_jwt_claims({
                "sub": "x", "firm_id": "f", "role": "intern",
                "email": "x@y.z", "session_id": "01J0K8YYYZZZAAAA1234567890",
            })

    def test_name_falls_back_to_email(self):
        ctx = UserContext.from_jwt_claims({
            "sub": "x", "firm_id": "f", "role": "advisor",
            "email": "x@y.z", "name": None, "session_id": "01J0K8YYYZZZAAAA1234567890",
        })
        assert ctx.name == "x@y.z"


# ---------------------------------------------------------------------------
# dev_users YAML loader  (Dev-Mode Addendum §3.1)
# ---------------------------------------------------------------------------


class TestDevUsers:
    def test_catalogue_loads_demo_firm_and_four_users(self):
        cat = get_catalogue()
        assert cat.firm.firm_id == "demo-firm-001"
        assert cat.firm.regulatory_jurisdiction == "IN"
        assert len(cat.users) == 4
        roles = {u.role for u in cat.users}
        assert roles == {Role.ADVISOR, Role.CIO, Role.COMPLIANCE, Role.AUDIT}

    def test_find_user_returns_match(self):
        u = get_catalogue().find_user("advisor1")
        assert u is not None
        assert u.role == Role.ADVISOR
        assert u.email == "advisor1@demo.test"

    def test_find_user_unknown_returns_none(self):
        assert get_catalogue().find_user("not-a-real-user") is None


# ---------------------------------------------------------------------------
# Sessions service  (FR 17.1 acceptance tests 1-10)
# ---------------------------------------------------------------------------


class TestSessionsService:
    @pytest.mark.asyncio
    async def test_create_session_persists_row_with_correct_fields(self, db):
        async with db.begin():
            issued = await sessions_service.create_session(
                db,
                user_id="advisor1",
                firm_id="demo-firm-001",
                role=Role.ADVISOR,
                email="advisor1@demo.test",
                name="Anjali Mehta",
                user_agent="pytest",
                ip_address="127.0.0.1",
            )
        row = issued.session
        assert row.user_id == "advisor1"
        assert row.firm_id == "demo-firm-001"
        assert row.role == "advisor"
        assert row.email == "advisor1@demo.test"
        assert row.name == "Anjali Mehta"
        assert len(row.session_id) == 26  # ULID
        assert row.refresh_token_hash is not None
        assert len(row.refresh_token_hash) == 32  # SHA-256
        assert row.previous_refresh_token_hash is None
        assert row.refresh_token_superseded_at is None
        assert row.revoked is False
        # 8-hour window
        expected_window = timedelta(seconds=settings.refresh_cookie_max_age_seconds)
        assert row.expires_at - row.created_at == expected_window

    @pytest.mark.asyncio
    async def test_create_session_returns_jwt_carrying_session_id(self, db):
        async with db.begin():
            issued = await sessions_service.create_session(
                db, user_id="cio1", firm_id="demo-firm-001", role=Role.CIO,
                email="cio1@demo.test", name="Rajiv Sharma",
            )
        claims = verify_jwt(issued.access_jwt)
        assert claims["session_id"] == issued.session.session_id
        assert claims["sub"] == "cio1"
        assert claims["role"] == "cio"

    @pytest.mark.asyncio
    async def test_session_cap_revokes_oldest_when_exceeded(self, db, monkeypatch):
        monkeypatch.setattr(settings, "max_concurrent_sessions_per_user", 2)
        sids = []
        for _ in range(3):
            async with db.begin():
                issued = await sessions_service.create_session(
                    db, user_id="advisor1", firm_id="demo-firm-001", role=Role.ADVISOR,
                    email="x@y.z", name="X",
                )
                sids.append(issued.session.session_id)
                # Create a gap so created_at differs reliably for ordering.
                await asyncio.sleep(0.01)

        # Oldest (sids[0]) should now be revoked; newer two active.
        result = await db.execute(select(SessionRow).where(SessionRow.user_id == "advisor1"))
        rows = {r.session_id: r for r in result.scalars()}
        assert rows[sids[0]].revoked is True
        assert rows[sids[1]].revoked is False
        assert rows[sids[2]].revoked is False

    @pytest.mark.asyncio
    async def test_get_active_session_returns_row(self, db):
        async with db.begin():
            issued = await sessions_service.create_session(
                db, user_id="x", firm_id="f", role=Role.ADVISOR,
                email="x@y.z", name="X",
            )
        row = await sessions_service.get_active_session(db, issued.session.session_id)
        assert row is not None
        assert row.session_id == issued.session.session_id

    @pytest.mark.asyncio
    async def test_get_active_session_returns_none_for_revoked(self, db):
        async with db.begin():
            issued = await sessions_service.create_session(
                db, user_id="x", firm_id="f", role=Role.ADVISOR,
                email="x@y.z", name="X",
            )
            await sessions_service.revoke_session(db, issued.session.session_id)
        assert await sessions_service.get_active_session(db, issued.session.session_id) is None

    @pytest.mark.asyncio
    async def test_refresh_session_rotates_token_and_reissues_jwt(self, db):
        async with db.begin():
            issued = await sessions_service.create_session(
                db, user_id="advisor1", firm_id="demo-firm-001", role=Role.ADVISOR,
                email="advisor1@demo.test", name="Anjali Mehta",
            )
        old_token = issued.refresh_token_plain
        old_hash = issued.session.refresh_token_hash

        async with db.begin():
            refreshed = await sessions_service.refresh_session(
                db, refresh_token_plain=old_token,
            )

        assert refreshed.refresh_token_plain != old_token
        assert refreshed.session.refresh_token_hash != old_hash
        assert refreshed.session.previous_refresh_token_hash == old_hash
        assert refreshed.session.refresh_token_superseded_at is not None
        # Same session, new JWT.
        assert refreshed.session.session_id == issued.session.session_id
        new_claims = verify_jwt(refreshed.access_jwt)
        assert new_claims["session_id"] == issued.session.session_id
        assert new_claims["email"] == "advisor1@demo.test"

    @pytest.mark.asyncio
    async def test_refresh_session_invalid_token_raises(self, db):
        with pytest.raises(RefreshTokenInvalidError):
            async with db.begin():
                await sessions_service.refresh_session(db, refresh_token_plain="not-a-real-token")

    @pytest.mark.asyncio
    async def test_refresh_session_theft_detection_raises_with_session_id(self, db):
        """Service contract: stale token raises with the session_id.

        Caller (router) is responsible for revoking. End-to-end "session is
        revoked" behaviour is covered by the HTTP integration test.
        """
        async with db.begin():
            issued = await sessions_service.create_session(
                db, user_id="x", firm_id="f", role=Role.ADVISOR,
                email="x@y.z", name="X",
            )
        # Capture upfront — rollback inside the failing transaction below
        # will expire the ORM-attached session_row.
        session_id = issued.session.session_id
        old_token = issued.refresh_token_plain

        # First refresh succeeds.
        async with db.begin():
            await sessions_service.refresh_session(db, refresh_token_plain=old_token)

        # Re-presenting the OLD token raises with the session_id.
        with pytest.raises(RefreshTokenTheftError) as exc_info:
            async with db.begin():
                await sessions_service.refresh_session(db, refresh_token_plain=old_token)
        assert exc_info.value.session_id == session_id

    @pytest.mark.asyncio
    async def test_refresh_session_expired_raises_with_session_id(self, db):
        """Service contract: expired session raises SessionExpiredError with session_id."""
        async with db.begin():
            issued = await sessions_service.create_session(
                db, user_id="x", firm_id="f", role=Role.ADVISOR,
                email="x@y.z", name="X",
            )
            # Force the session into the past.
            issued.session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            await db.flush()
        # Capture before the failing transaction below.
        session_id = issued.session.session_id
        refresh_token = issued.refresh_token_plain

        with pytest.raises(SessionExpiredError) as exc_info:
            async with db.begin():
                await sessions_service.refresh_session(
                    db, refresh_token_plain=refresh_token
                )
        assert exc_info.value.session_id == session_id

    @pytest.mark.asyncio
    async def test_revoke_session_marks_revoked(self, db):
        async with db.begin():
            issued = await sessions_service.create_session(
                db, user_id="x", firm_id="f", role=Role.ADVISOR,
                email="x@y.z", name="X",
            )
            changed = await sessions_service.revoke_session(db, issued.session.session_id)
        assert changed is True
        # Fresh select to bypass any ORM identity-map staleness.
        result = await db.execute(
            select(SessionRow).where(SessionRow.session_id == issued.session.session_id)
        )
        row = result.scalar_one()
        await db.refresh(row)
        assert row.revoked is True
        assert row.revocation_reason == RevocationReason.USER_LOGOUT.value

    @pytest.mark.asyncio
    async def test_revoke_session_idempotent(self, db):
        async with db.begin():
            issued = await sessions_service.create_session(
                db, user_id="x", firm_id="f", role=Role.ADVISOR,
                email="x@y.z", name="X",
            )
            await sessions_service.revoke_session(db, issued.session.session_id)
            again = await sessions_service.revoke_session(db, issued.session.session_id)
        assert again is False  # second call is no-op


# ---------------------------------------------------------------------------
# T1 emission
# ---------------------------------------------------------------------------


class TestT1Emit:
    @pytest.mark.asyncio
    async def test_emit_event_persists_row(self, db):
        async with db.begin():
            event = await emit_event(
                db,
                event_name="test_event",
                payload={"foo": "bar"},
                firm_id="demo-firm-001",
            )
        assert len(event.event_id) == 26
        # Round-trip via DB.
        result = await db.execute(select(T1Event).where(T1Event.event_id == event.event_id))
        row = result.scalar_one()
        assert row.event_name == "test_event"
        assert row.payload == {"foo": "bar"}
        assert row.firm_id == "demo-firm-001"


# ---------------------------------------------------------------------------
# HTTP endpoints — happy + sad paths
# ---------------------------------------------------------------------------


class TestDevUsersEndpoint:
    @pytest.mark.asyncio
    async def test_returns_four_users_without_email(self, http):
        resp = await http.get("/api/v2/auth/dev-users")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["users"]) == 4
        for u in body["users"]:
            assert set(u.keys()) == {"user_id", "name", "role"}
            assert "email" not in u  # sensitive field omitted


class TestDevLoginEndpoint:
    @pytest.mark.asyncio
    async def test_valid_user_returns_jwt_and_sets_cookie(self, http, db):
        resp = await http.post("/api/v2/auth/dev-login", json={"user_id": "advisor1"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == settings.jwt_access_token_minutes * 60
        # JWT validates and carries advisor identity.
        claims = verify_jwt(body["access_token"])
        assert claims["sub"] == "advisor1"
        assert claims["role"] == "advisor"
        assert claims["firm_id"] == "demo-firm-001"
        # Refresh cookie is set with proper attributes.
        cookie_header = resp.headers.get("set-cookie", "")
        assert "samriddhi_refresh=" in cookie_header
        assert "HttpOnly" in cookie_header
        assert "samesite=strict" in cookie_header.lower()
        assert "path=/api/v2/auth/refresh" in cookie_header.lower()

    @pytest.mark.asyncio
    async def test_unknown_user_returns_404_problem_details(self, http):
        resp = await http.post("/api/v2/auth/dev-login", json={"user_id": "nope"})
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["status"] == 404
        assert "Unknown demo user" in body["title"]

    @pytest.mark.asyncio
    async def test_emits_session_created_and_login_completed_t1(self, http, db):
        await http.post("/api/v2/auth/dev-login", json={"user_id": "advisor1"})
        result = await db.execute(select(T1Event))
        names = {e.event_name for e in result.scalars()}
        assert SESSION_CREATED in names
        assert AUTH_LOGIN_COMPLETED in names

    @pytest.mark.asyncio
    async def test_unknown_user_emits_login_failed_t1(self, http, db):
        await http.post("/api/v2/auth/dev-login", json={"user_id": "nope"})
        result = await db.execute(
            select(T1Event).where(T1Event.event_name == AUTH_LOGIN_FAILED)
        )
        events = list(result.scalars())
        assert len(events) == 1
        assert events[0].payload["reason"] == "unknown_user_id"
        assert events[0].payload["presented_user_id"] == "nope"


class TestRefreshEndpoint:
    @pytest.mark.asyncio
    async def test_with_valid_cookie_rotates(self, http, db):
        # Login first to get a refresh cookie.
        login_resp = await http.post("/api/v2/auth/dev-login", json={"user_id": "advisor1"})
        old_cookie = login_resp.cookies.get("samriddhi_refresh")
        assert old_cookie

        refresh_resp = await http.post(
            "/api/v2/auth/refresh",
            cookies={"samriddhi_refresh": old_cookie},
        )
        assert refresh_resp.status_code == 200
        body = refresh_resp.json()
        assert body["token_type"] == "Bearer"
        # New cookie is different from old.
        new_cookie = refresh_resp.cookies.get("samriddhi_refresh")
        assert new_cookie
        assert new_cookie != old_cookie

    @pytest.mark.asyncio
    async def test_no_cookie_returns_401(self, http):
        resp = await http.post("/api/v2/auth/refresh")
        assert resp.status_code == 401
        assert resp.headers["content-type"].startswith("application/problem+json")

    @pytest.mark.asyncio
    async def test_emits_session_refreshed(self, http, db):
        login_resp = await http.post("/api/v2/auth/dev-login", json={"user_id": "advisor1"})
        cookie = login_resp.cookies.get("samriddhi_refresh")
        await http.post("/api/v2/auth/refresh", cookies={"samriddhi_refresh": cookie})
        result = await db.execute(
            select(T1Event).where(T1Event.event_name == SESSION_REFRESHED)
        )
        events = list(result.scalars())
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_stale_token_replay_revokes_session_e2e(self, http, db):
        """End-to-end FR 17.1 acceptance test 5: replay-after-rotation revokes."""
        # Login → get cookie A.
        login_resp = await http.post("/api/v2/auth/dev-login", json={"user_id": "advisor1"})
        cookie_a = login_resp.cookies.get("samriddhi_refresh")

        # First refresh succeeds → cookie A is now stale, cookie B is current.
        first_refresh = await http.post(
            "/api/v2/auth/refresh", cookies={"samriddhi_refresh": cookie_a}
        )
        assert first_refresh.status_code == 200

        # Replay cookie A → 401 + session revoked.
        replay = await http.post(
            "/api/v2/auth/refresh", cookies={"samriddhi_refresh": cookie_a}
        )
        assert replay.status_code == 401
        assert "theft" in replay.json()["title"].lower()

        # Verify session marked revoked w/ THEFT_DETECTED reason.
        result = await db.execute(
            select(SessionRow).where(SessionRow.user_id == "advisor1")
        )
        row = result.scalar_one()
        await db.refresh(row)
        assert row.revoked is True
        assert row.revocation_reason == RevocationReason.THEFT_DETECTED.value


class TestLogoutEndpoint:
    @pytest.mark.asyncio
    async def test_clears_cookie_and_revokes_session(self, http, db):
        login_resp = await http.post("/api/v2/auth/dev-login", json={"user_id": "advisor1"})
        cookie = login_resp.cookies.get("samriddhi_refresh")

        logout_resp = await http.post(
            "/api/v2/auth/logout",
            cookies={"samriddhi_refresh": cookie},
        )
        assert logout_resp.status_code == 204
        # Cookie is cleared (Max-Age=0 in Set-Cookie header)
        cookie_header = logout_resp.headers.get("set-cookie", "")
        assert "samriddhi_refresh=" in cookie_header

        # Session in DB is revoked.
        result = await db.execute(
            select(SessionRow).where(SessionRow.user_id == "advisor1")
        )
        row = result.scalar_one()
        assert row.revoked is True
        assert row.revocation_reason == RevocationReason.USER_LOGOUT.value

    @pytest.mark.asyncio
    async def test_emits_session_revoked_and_auth_logout_t1(self, http, db):
        login_resp = await http.post("/api/v2/auth/dev-login", json={"user_id": "advisor1"})
        cookie = login_resp.cookies.get("samriddhi_refresh")
        await http.post("/api/v2/auth/logout", cookies={"samriddhi_refresh": cookie})

        result = await db.execute(select(T1Event))
        names = {e.event_name for e in result.scalars()}
        assert SESSION_REVOKED in names
        assert AUTH_LOGOUT in names


class TestWhoamiEndpoint:
    @pytest.mark.asyncio
    async def test_with_valid_token_returns_user(self, http):
        login_resp = await http.post("/api/v2/auth/dev-login", json={"user_id": "cio1"})
        token = login_resp.json()["access_token"]

        resp = await http.get(
            "/api/v2/auth/whoami",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "cio1"
        assert body["role"] == "cio"
        assert body["firm_id"] == "demo-firm-001"
        assert body["email"] == "cio1@demo.test"

    @pytest.mark.asyncio
    async def test_with_no_auth_returns_401(self, http):
        resp = await http.get("/api/v2/auth/whoami")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_with_bad_token_returns_401(self, http):
        resp = await http.get(
            "/api/v2/auth/whoami",
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        assert resp.status_code == 401


class TestProductionOIDCStubs:
    @pytest.mark.asyncio
    async def test_login_returns_501(self, http):
        resp = await http.get("/api/v2/auth/login")
        assert resp.status_code == 501
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert "Production OIDC" in resp.json()["title"]

    @pytest.mark.asyncio
    async def test_callback_returns_501(self, http):
        resp = await http.get("/api/v2/auth/callback")
        assert resp.status_code == 501
        assert resp.headers["content-type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# Four-role coverage  (FR 17.2 acceptance tests 1-2)
# ---------------------------------------------------------------------------


class TestFourRoleCoverage:
    @pytest.mark.parametrize("user_id,expected_role", [
        ("advisor1", "advisor"),
        ("cio1", "cio"),
        ("compliance1", "compliance"),
        ("audit1", "audit"),
    ])
    @pytest.mark.asyncio
    async def test_each_role_logs_in_with_correct_jwt_role(self, http, user_id, expected_role):
        resp = await http.post("/api/v2/auth/dev-login", json={"user_id": user_id})
        assert resp.status_code == 200
        claims = verify_jwt(resp.json()["access_token"])
        assert claims["role"] == expected_role
