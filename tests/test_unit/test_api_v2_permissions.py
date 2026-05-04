"""Cluster 0 permissions test suite.

Covers:
- Permission enum vocabulary (5 entries per FR 17.2 §6)
- Role → permission mapping per FR 17.2 §2 / §6
- require_permission FastAPI dep behaviour: mode='all' (default), mode='any',
  passes / 403 / fast-fail on invalid factory args
- End-to-end permission gating on /api/v2/auth/whoami via real HTTP

Cluster 0's permission set is small enough that all four roles have all the
permissions they need for cluster 0 endpoints — so the HTTP-level gating
tests here are mostly mechanism-establishing for future clusters that will
restrict per role. Direct dep-level tests cover the gating behaviour
(passes / 403) by constructing a UserContext with a role missing the perm.
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
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.auth.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    permissions_for,
    require_permission,
    user_has_permission,
)
from artha.api_v2.auth.user_context import Role, UserContext
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


def _user_with_role(role: Role) -> UserContext:
    """Construct a UserContext for direct-dep testing without going through HTTP."""
    return UserContext(
        user_id="test-user",
        firm_id="demo-firm-001",
        role=role,
        email="test@demo.test",
        name="Test User",
        session_id="01ABCDEFGHJKMNPQRSTVWXYZ56",
    )


# ===========================================================================
# 1. Permission enum + role mapping per FR 17.2 §6
# ===========================================================================


class TestPermissionVocabulary:
    def test_cluster_0_five_permissions_still_present(self):
        # Per FR 17.2 §6 — these five are the cluster 0 skeleton; they must
        # remain present even as future clusters extend the enum.
        cluster_0_perms = {
            Permission.AUTH_SESSION_READ,
            Permission.AUTH_SESSION_LOGOUT,
            Permission.EVENTS_SUBSCRIBE_OWN_SCOPE,
            Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE,
            Permission.SYSTEM_FIRM_INFO_READ,
        }
        assert cluster_0_perms.issubset(set(Permission))

    def test_cluster_1_chunk_1_1_permissions_present(self):
        # Per cluster 1 chunk 1.1 — 6 new entries for investor + household
        # surfaces. FR 17.2 §7 growth pattern.
        cluster_1_chunk_1_1_perms = {
            Permission.INVESTORS_READ_OWN_BOOK,
            Permission.INVESTORS_READ_FIRM_SCOPE,
            Permission.INVESTORS_WRITE_OWN_BOOK,
            Permission.HOUSEHOLDS_READ_OWN_BOOK,
            Permission.HOUSEHOLDS_READ_FIRM_SCOPE,
            Permission.HOUSEHOLDS_WRITE_OWN_BOOK,
        }
        assert cluster_1_chunk_1_1_perms.issubset(set(Permission))

    def test_cluster_1_chunk_1_3_permissions_present(self):
        # Per cluster 1 chunk 1.3 — 2 new entries for SmartLLMRouter settings.
        # CIO is the sole role that holds them (FR 17.2 §7 growth pattern).
        cluster_1_chunk_1_3_perms = {
            Permission.SYSTEM_LLM_CONFIG_READ,
            Permission.SYSTEM_LLM_CONFIG_WRITE,
        }
        assert cluster_1_chunk_1_3_perms.issubset(set(Permission))

    def test_cluster_1_chunk_1_2_permissions_present(self):
        # Per cluster 1 chunk 1.2 — 3 new entries for C0 conversational
        # surface. Advisor gets read+write on own_book; CIO/compliance/audit
        # get firm-wide read for governance.
        cluster_1_chunk_1_2_perms = {
            Permission.CONVERSATIONS_READ_OWN_BOOK,
            Permission.CONVERSATIONS_READ_FIRM_SCOPE,
            Permission.CONVERSATIONS_WRITE_OWN_BOOK,
        }
        assert cluster_1_chunk_1_2_perms.issubset(set(Permission))

    def test_only_advisor_has_conversations_write_own_book(self):
        # The C0 conversation is the advisor's surface; CIO/compliance/audit
        # see the audit trail (T1) and read-only thread but cannot post.
        assert (
            Permission.CONVERSATIONS_WRITE_OWN_BOOK in ROLE_PERMISSIONS[Role.ADVISOR]
        )
        for role in (Role.CIO, Role.COMPLIANCE, Role.AUDIT):
            assert (
                Permission.CONVERSATIONS_WRITE_OWN_BOOK
                not in ROLE_PERMISSIONS[role]
            ), f"{role.value} should not have CONVERSATIONS_WRITE_OWN_BOOK"

    @pytest.mark.parametrize("role", [Role.CIO, Role.COMPLIANCE, Role.AUDIT])
    def test_cio_compliance_audit_have_conversations_firm_scope(self, role):
        assert (
            Permission.CONVERSATIONS_READ_FIRM_SCOPE in ROLE_PERMISSIONS[role]
        )
        assert (
            Permission.CONVERSATIONS_READ_OWN_BOOK not in ROLE_PERMISSIONS[role]
        )

    @pytest.mark.parametrize("perm", [
        Permission.SYSTEM_LLM_CONFIG_READ,
        Permission.SYSTEM_LLM_CONFIG_WRITE,
    ])
    def test_only_cio_holds_llm_config_permissions(self, perm):
        # CIO holds it.
        assert perm in ROLE_PERMISSIONS[Role.CIO]
        # Advisor / Compliance / Audit do not.
        for role in (Role.ADVISOR, Role.COMPLIANCE, Role.AUDIT):
            assert perm not in ROLE_PERMISSIONS[role], (
                f"{role.value} should not have {perm.value} in cluster 1 chunk 1.3"
            )

    def test_permission_string_values_follow_naming_convention(self):
        """``<resource>:<verb>:<scope>`` per FR 17.2 §3."""
        for perm in Permission:
            parts = perm.value.split(":")
            assert 2 <= len(parts) <= 3, f"{perm.value!r} doesn't match the convention"

    def test_all_four_roles_in_role_permissions(self):
        assert set(ROLE_PERMISSIONS.keys()) == {
            Role.ADVISOR, Role.CIO, Role.COMPLIANCE, Role.AUDIT,
        }

    def test_advisor_gets_own_scope_not_firm_scope(self):
        """Per FR 17.2 §6: advisor has events:subscribe:own_scope only."""
        advisor_perms = ROLE_PERMISSIONS[Role.ADVISOR]
        assert Permission.EVENTS_SUBSCRIBE_OWN_SCOPE in advisor_perms
        assert Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE not in advisor_perms

    @pytest.mark.parametrize("role", [Role.CIO, Role.COMPLIANCE, Role.AUDIT])
    def test_non_advisor_gets_firm_scope_not_own_scope(self, role):
        perms = ROLE_PERMISSIONS[role]
        assert Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE in perms
        assert Permission.EVENTS_SUBSCRIBE_OWN_SCOPE not in perms

    @pytest.mark.parametrize("role", list(Role))
    def test_all_roles_can_read_session_and_firm_info_and_logout(self, role):
        """Per FR 17.2 §6 — these three are universal in cluster 0."""
        perms = ROLE_PERMISSIONS[role]
        assert Permission.AUTH_SESSION_READ in perms
        assert Permission.AUTH_SESSION_LOGOUT in perms
        assert Permission.SYSTEM_FIRM_INFO_READ in perms

    def test_permissions_for_returns_correct_set(self):
        assert permissions_for(Role.ADVISOR) == ROLE_PERMISSIONS[Role.ADVISOR]

    def test_user_has_permission_true_when_granted(self):
        user = _user_with_role(Role.ADVISOR)
        assert user_has_permission(user, Permission.EVENTS_SUBSCRIBE_OWN_SCOPE)

    def test_user_has_permission_false_when_not_granted(self):
        user = _user_with_role(Role.ADVISOR)
        assert not user_has_permission(user, Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE)


# ===========================================================================
# 2. require_permission factory + dep behaviour
# ===========================================================================


class TestRequirePermissionFactory:
    def test_factory_rejects_empty_permissions(self):
        with pytest.raises(ValueError, match="at least one Permission"):
            require_permission()

    @pytest.mark.asyncio
    async def test_dep_returns_user_when_permission_granted(self):
        dep = require_permission(Permission.AUTH_SESSION_READ)
        user = _user_with_role(Role.ADVISOR)
        result = await dep(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_dep_raises_403_when_permission_missing(self):
        dep = require_permission(Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE)
        user = _user_with_role(Role.ADVISOR)  # has own_scope, not firm_scope
        with pytest.raises(Exception) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403
        assert "events:subscribe:firm_scope" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_dep_mode_all_passes_when_all_granted(self):
        dep = require_permission(
            Permission.AUTH_SESSION_READ,
            Permission.SYSTEM_FIRM_INFO_READ,
            mode="all",
        )
        user = _user_with_role(Role.ADVISOR)
        result = await dep(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_dep_mode_all_raises_when_any_missing(self):
        dep = require_permission(
            Permission.AUTH_SESSION_READ,
            Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE,  # advisor lacks this
            mode="all",
        )
        user = _user_with_role(Role.ADVISOR)
        with pytest.raises(Exception) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403
        assert "events:subscribe:firm_scope" in exc_info.value.detail
        # The granted one shouldn't appear in the missing list.
        assert "auth:session:read" not in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_dep_mode_any_passes_when_at_least_one_granted(self):
        """Advisor lacks firm_scope but has own_scope — 'any' should pass."""
        dep = require_permission(
            Permission.EVENTS_SUBSCRIBE_OWN_SCOPE,
            Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE,
            mode="any",
        )
        user = _user_with_role(Role.ADVISOR)
        result = await dep(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_dep_mode_any_raises_when_none_granted(self):
        """Construct a permission the user definitely doesn't have."""
        # All cluster 0 perms are universal except the events:subscribe split.
        # An advisor lacks EVENTS_SUBSCRIBE_FIRM_SCOPE — testing 'any' on a
        # set containing only that requires us to exhaust the granted ones.
        dep = require_permission(
            Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE,
            mode="any",
        )
        user = _user_with_role(Role.ADVISOR)
        with pytest.raises(Exception) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403


# ===========================================================================
# 3. End-to-end permission gating on /api/v2/auth/whoami
# ===========================================================================


class TestWhoamiPermissionGate:
    @pytest.mark.asyncio
    async def test_each_role_can_access_whoami(self, http, db):
        """All 4 roles have AUTH_SESSION_READ → all should reach whoami."""
        for user_id, role in [
            ("advisor1", Role.ADVISOR),
            ("cio1", Role.CIO),
            ("compliance1", Role.COMPLIANCE),
            ("audit1", Role.AUDIT),
        ]:
            login = await http.post(
                "/api/v2/auth/dev-login", json={"user_id": user_id}
            )
            token = login.json()["access_token"]
            resp = await http.get(
                "/api/v2/auth/whoami",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, f"{role.value} got {resp.status_code}"
            assert resp.json()["role"] == role.value


# ===========================================================================
# 4. End-to-end permission gating on /api/v2/events/stream
# ===========================================================================


class TestStreamPermissionGate:
    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401_not_403(self, http):
        """No JWT → 401 (auth failure), not 403 (permission failure).

        Order of checks: get_current_user runs first and fails with 401 before
        require_permission gets a chance to evaluate.
        """
        resp = await http.get("/api/v2/events/stream")
        assert resp.status_code == 401
