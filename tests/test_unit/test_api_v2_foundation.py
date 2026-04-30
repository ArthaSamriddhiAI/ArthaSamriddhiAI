"""Doc 2 Pass 1 — API v2 foundation acceptance tests.

Coverage:
  * §2.2 Auth: JWT sign/verify, UserContext, role + permission deps
  * §2.6 Errors: RFC 7807 ProblemDetails envelope, content type, custom
    extensions (request_id, ex1_category)
  * §2.9 Observability: X-Request-ID generation + validation + echo
  * §2.4 Idempotency: store record, replay, payload-mismatch detection
  * §2.8 Rate limiting: slowapi keying + 429 envelope
  * §2.1 Router: /api/v2/system/health + /auth/whoami live
  * Canonical Role.AUDIT round-trip + permission gates
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel as _PydBase

# Register the api_v2 idempotency table so conftest's create_all picks it up.
import artha.api_v2.idempotency  # noqa: F401
from artha.api_v2 import (
    APIError,
    ConflictError,
    ForbiddenError,
    IdempotencyKeyMismatchError,
    IdempotencyStore,
    JWTSigner,
    NotFoundError,
    Permission,
    ProblemDetails,
    Role,
    UnauthorizedError,
    UserContext,
    default_permissions_for,
    require_permission,
    require_role,
    set_default_signer,
    setup_api_v2,
)
from artha.api_v2.observability import (
    is_valid_request_id,
    is_valid_traceparent,
)
from artha.canonical.views import ViewerContext
from artha.views.canonical_permissions import (
    PermissionDeniedError,
    assert_can_read_client,
    assert_can_read_firm,
    assert_can_write,
)


class _ValidationPayload(_PydBase):
    """Module-scope payload used by the 422 violation-array test."""

    name: str
    count: int

# ===========================================================================
# Helpers
# ===========================================================================


def _user(
    *,
    user_id: str = "u1",
    firm_id: str = "firm_test",
    role: Role = Role.ADVISOR,
    permissions: frozenset[Permission] | None = None,
    expires_at: datetime | None = None,
) -> UserContext:
    return UserContext(
        user_id=user_id,
        firm_id=firm_id,
        role=role,
        permissions=permissions if permissions is not None else default_permissions_for(role),
        token_expires_at=expires_at,
    )


def _build_test_app() -> tuple[FastAPI, JWTSigner]:
    """Spin up a FastAPI app with the v2 foundation wired + a fresh signer."""
    signer = JWTSigner(secret="test-secret-DO-NOT-USE-IN-PRODUCTION")
    set_default_signer(signer)
    app = FastAPI()
    setup_api_v2(app)
    return app, signer


# ===========================================================================
# §2.2 Auth — JWT sign/verify + UserContext
# ===========================================================================


class TestJWTSigner:
    def test_round_trip_user_context(self):
        signer = JWTSigner(secret="abcdefghijklmnop12345678abcdefghijklmnop")
        user = _user(role=Role.ADVISOR)
        token, expires_at = signer.encode_access_token(user)
        decoded = signer.decode_access_token(token)
        assert decoded.user_id == user.user_id
        assert decoded.firm_id == user.firm_id
        assert decoded.role is Role.ADVISOR
        assert decoded.permissions == user.permissions
        assert decoded.token_expires_at == expires_at.replace(microsecond=0)

    def test_expired_token_raises_unauthorized(self):
        signer = JWTSigner(secret="abcdefghijklmnop12345678abcdefghijklmnop", access_ttl_seconds=-1)
        user = _user()
        token, _ = signer.encode_access_token(user)
        with pytest.raises(UnauthorizedError) as exc:
            signer.decode_access_token(token)
        assert "expired" in exc.value.problem_type.lower()

    def test_signature_mismatch_raises(self):
        signer1 = JWTSigner(secret="abcdefghijklmnop11111111abcdefghijklmnop")
        signer2 = JWTSigner(secret="abcdefghijklmnop22222222abcdefghijklmnop")
        token, _ = signer1.encode_access_token(_user())
        with pytest.raises(UnauthorizedError):
            signer2.decode_access_token(token)

    def test_unknown_role_rejected(self):
        signer = JWTSigner(secret="abcdefghijklmnop12345678abcdefghijklmnop")
        # Manually encode a token with a bogus role
        import jwt

        payload = {
            "iss": "samriddhi.local",
            "aud": "samriddhi.api.v2",
            "sub": "u1",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
            "firm_id": "firm_test",
            "role": "intruder",
            "permissions": [],
        }
        token = jwt.encode(payload, "abcdefghijklmnop12345678abcdefghijklmnop", algorithm="HS256")
        with pytest.raises(UnauthorizedError):
            signer.decode_access_token(token)

    def test_unknown_permissions_silently_dropped(self):
        signer = JWTSigner(secret="abcdefghijklmnop12345678abcdefghijklmnop")
        import jwt

        payload = {
            "iss": "samriddhi.local",
            "aud": "samriddhi.api.v2",
            "sub": "u1",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
            "firm_id": "firm_test",
            "role": "advisor",
            "permissions": ["case:read:own_book", "future:made_up_perm"],
        }
        token = jwt.encode(payload, "abcdefghijklmnop12345678abcdefghijklmnop", algorithm="HS256")
        decoded = signer.decode_access_token(token)
        # Future-version perm dropped; existing perm kept.
        assert Permission.CASE_READ_OWN_BOOK in decoded.permissions
        # No invalid Permission instance smuggled in.
        for p in decoded.permissions:
            assert isinstance(p, Permission)

    def test_short_secret_rejected(self):
        with pytest.raises(RuntimeError):
            import os

            os.environ.pop("SAMRIDDHI_JWT_SECRET", None)
            os.environ["SAMRIDDHI_JWT_SECRET"] = "short"
            try:
                JWTSigner()
            finally:
                os.environ.pop("SAMRIDDHI_JWT_SECRET", None)


class TestUserContext:
    def test_has_role_and_has_permission(self):
        u = _user(role=Role.CIO)
        assert u.has_role(Role.CIO)
        assert not u.has_role(Role.ADVISOR)
        assert u.has_permission(Permission.CASE_READ_FIRM)
        # Advisor doesn't get firm-scope reads
        a = _user(role=Role.ADVISOR)
        assert not a.has_permission(Permission.CASE_READ_FIRM)

    def test_default_permissions_per_role(self):
        # Advisor sees own book; CIO sees firm; Compliance read-only firm; Audit read-only firm.
        advisor_perms = default_permissions_for(Role.ADVISOR)
        cio_perms = default_permissions_for(Role.CIO)
        compliance_perms = default_permissions_for(Role.COMPLIANCE)
        audit_perms = default_permissions_for(Role.AUDIT)

        assert Permission.CASE_READ_OWN_BOOK in advisor_perms
        assert Permission.CASE_READ_FIRM not in advisor_perms

        assert Permission.MODEL_PORTFOLIO_APPROVE in cio_perms
        assert Permission.MODEL_PORTFOLIO_APPROVE not in compliance_perms
        assert Permission.MODEL_PORTFOLIO_APPROVE not in audit_perms

        # Audit is firm-wide read but no writes.
        assert Permission.CASE_READ_FIRM in audit_perms
        assert Permission.CASE_WRITE not in audit_perms
        assert Permission.MANDATE_APPROVE not in audit_perms


class TestAuthDependencies:
    def test_whoami_round_trip(self):
        app, signer = _build_test_app()
        token, _ = signer.encode_access_token(_user(role=Role.ADVISOR))
        with TestClient(app) as client:
            resp = client.get(
                "/api/v2/auth/whoami",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_id"] == "u1"
        assert body["role"] == "advisor"
        assert "case:read:own_book" in body["permissions"]

    def test_whoami_no_auth_returns_401_problem_json(self):
        app, _ = _build_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/v2/auth/whoami")
        assert resp.status_code == 401
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["title"] == "Authentication required"
        assert body["status"] == 401
        assert body["ex1_category"] == "auth_failure"

    def test_whoami_malformed_auth_returns_401(self):
        app, _ = _build_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/v2/auth/whoami",
                headers={"Authorization": "NotBearer xyz"},
            )
        assert resp.status_code == 401

    def test_role_dependency_blocks_wrong_role(self):
        app, signer = _build_test_app()

        @app.get("/cio-only")
        async def cio_endpoint(user: UserContext = Depends(require_role(Role.CIO))):
            return {"ok": True}

        # Advisor token → 403
        token, _ = signer.encode_access_token(_user(role=Role.ADVISOR))
        with TestClient(app) as client:
            resp = client.get("/cio-only", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/problem+json")

        # CIO token → 200
        cio_token, _ = signer.encode_access_token(_user(role=Role.CIO))
        with TestClient(app) as client:
            resp = client.get("/cio-only", headers={"Authorization": f"Bearer {cio_token}"})
        assert resp.status_code == 200

    def test_permission_dependency_blocks_missing_perm(self):
        app, signer = _build_test_app()

        @app.get("/needs-approve")
        async def approve_endpoint(
            user: UserContext = Depends(require_permission(Permission.MANDATE_APPROVE))
        ):
            return {"ok": True}

        # Advisor lacks MANDATE_APPROVE
        advisor_token, _ = signer.encode_access_token(_user(role=Role.ADVISOR))
        with TestClient(app) as client:
            resp = client.get(
                "/needs-approve",
                headers={"Authorization": f"Bearer {advisor_token}"},
            )
        assert resp.status_code == 403
        body = resp.json()
        assert "mandate:approve" in body["detail"]

        # CIO has it
        cio_token, _ = signer.encode_access_token(_user(role=Role.CIO))
        with TestClient(app) as client:
            resp = client.get(
                "/needs-approve",
                headers={"Authorization": f"Bearer {cio_token}"},
            )
        assert resp.status_code == 200


# ===========================================================================
# §2.6 Errors — RFC 7807 envelope
# ===========================================================================


class TestProblemDetails:
    def test_envelope_shape(self):
        p = ProblemDetails(
            type="https://samriddhi.ai/errors/test",
            title="Test",
            status=400,
            detail="Test error",
            request_id="01ABCDEFGHJKMNPQRSTVWXYZ56",
            ex1_category="schema_violation",
            originating_component="test_component",
        )
        body = p.model_dump(mode="json", exclude_none=True)
        # All custom extensions present
        assert body["request_id"] == "01ABCDEFGHJKMNPQRSTVWXYZ56"
        assert body["ex1_category"] == "schema_violation"
        assert body["originating_component"] == "test_component"

    def test_api_error_subclass_status_codes(self):
        from artha.api_v2.errors import (
            BadRequestError,
            UnprocessableEntityError,
        )

        assert BadRequestError().status == 400
        assert UnauthorizedError().status == 401
        assert ForbiddenError().status == 403
        assert NotFoundError().status == 404
        assert ConflictError().status == 409
        assert UnprocessableEntityError().status == 422

    def test_handler_emits_problem_json_with_request_id(self):
        app, _ = _build_test_app()

        @app.get("/raise-not-found")
        async def raise_nf():
            raise NotFoundError(detail="missing widget")

        with TestClient(app) as client:
            resp = client.get(
                "/raise-not-found",
                headers={"X-Request-ID": "01ABCDEFGHJKMNPQRSTVWXYZ56"},
            )
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/problem+json")
        # X-Request-ID echoed
        assert resp.headers["X-Request-ID"] == "01ABCDEFGHJKMNPQRSTVWXYZ56"
        body = resp.json()
        assert body["status"] == 404
        assert body["request_id"] == "01ABCDEFGHJKMNPQRSTVWXYZ56"
        assert body["instance"] == "/raise-not-found"

    def test_validation_error_returns_violations_array(self):
        app, _ = _build_test_app()

        from fastapi import Body

        @app.post("/echo")
        async def echo(p: _ValidationPayload = Body(...)):
            return p.model_dump()

        with TestClient(app) as client:
            resp = client.post("/echo", json={"name": "x"})  # missing count
        assert resp.status_code == 422
        body = resp.json()
        assert body["ex1_category"] == "schema_violation"
        assert "violations" in body
        assert body["violations"], "violations array should be non-empty"
        assert "count" in str(body["violations"])

    def test_unhandled_exception_returns_500_problem(self):
        app, _ = _build_test_app()

        @app.get("/boom")
        async def boom():
            raise RuntimeError("unexpected")

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/boom")
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == 500
        assert body["ex1_category"] == "service_unavailable"


# ===========================================================================
# §2.9 Observability — X-Request-ID middleware
# ===========================================================================


class TestRequestIDMiddleware:
    def test_request_id_validation(self):
        # Valid ULID
        assert is_valid_request_id("01ABCDEFGHJKMNPQRSTVWXYZ56")
        # Valid UUID
        assert is_valid_request_id("01234567-89ab-cdef-0123-456789abcdef")
        # Invalid
        assert not is_valid_request_id("not-an-id")
        assert not is_valid_request_id("")
        assert not is_valid_request_id("x" * 100)

    def test_traceparent_validation(self):
        valid = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
        assert is_valid_traceparent(valid)
        assert not is_valid_traceparent("not-a-traceparent")

    def test_middleware_honours_supplied_id(self):
        app, _ = _build_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/v2/system/health",
                headers={"X-Request-ID": "01ABCDEFGHJKMNPQRSTVWXYZ56"},
            )
        assert resp.headers["X-Request-ID"] == "01ABCDEFGHJKMNPQRSTVWXYZ56"

    def test_middleware_generates_id_when_missing(self):
        app, _ = _build_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/v2/system/health")
        assert "X-Request-ID" in resp.headers
        assert is_valid_request_id(resp.headers["X-Request-ID"])

    def test_middleware_replaces_malformed_id(self):
        app, _ = _build_test_app()
        with TestClient(app) as client:
            resp = client.get(
                "/api/v2/system/health",
                headers={"X-Request-ID": "garbage!@#"},
            )
        # Server replaced with fresh valid id
        assert is_valid_request_id(resp.headers["X-Request-ID"])
        assert resp.headers["X-Request-ID"] != "garbage!@#"


# ===========================================================================
# §2.4 Idempotency — store + replay
# ===========================================================================


class TestIdempotencyStore:
    @pytest.mark.asyncio
    async def test_record_and_lookup_round_trip(self, db_session):
        store = IdempotencyStore(db_session)
        await store.record(
            firm_id="firm_test",
            idempotency_key="key-001",
            method="POST",
            path="/api/v2/cases",
            status_code=201,
            response_body={"case_id": "case_xyz"},
            request_payload={"intent": "case", "client_id": "c1"},
        )
        row = await store.lookup(
            firm_id="firm_test",
            idempotency_key="key-001",
            method="POST",
            path="/api/v2/cases",
        )
        assert row is not None
        status, body = store.decode_response(row)
        assert status == 201
        assert body == {"case_id": "case_xyz"}

    @pytest.mark.asyncio
    async def test_lookup_miss_returns_none(self, db_session):
        store = IdempotencyStore(db_session)
        row = await store.lookup(
            firm_id="firm_test",
            idempotency_key="nonexistent",
            method="POST",
            path="/api/v2/cases",
        )
        assert row is None

    @pytest.mark.asyncio
    async def test_payload_mismatch_raises(self, db_session):
        store = IdempotencyStore(db_session)
        await store.record(
            firm_id="firm_test",
            idempotency_key="key-002",
            method="POST",
            path="/api/v2/cases",
            status_code=201,
            response_body={"case_id": "case_a"},
            request_payload={"intent": "case", "client_id": "c1"},
        )
        with pytest.raises(IdempotencyKeyMismatchError):
            await store.lookup(
                firm_id="firm_test",
                idempotency_key="key-002",
                method="POST",
                path="/api/v2/cases",
                request_payload={"intent": "case", "client_id": "DIFFERENT"},
            )

    @pytest.mark.asyncio
    async def test_expired_entry_treated_as_miss(self, db_session):
        store = IdempotencyStore(db_session, ttl_hours=0)
        await store.record(
            firm_id="firm_test",
            idempotency_key="key-003",
            method="POST",
            path="/api/v2/cases",
            status_code=201,
            response_body={},
            request_payload={},
        )
        # Fast-forward by querying with as_of in the future
        row = await store.lookup(
            firm_id="firm_test",
            idempotency_key="key-003",
            method="POST",
            path="/api/v2/cases",
            as_of=datetime.now(UTC) + timedelta(hours=1),
        )
        assert row is None

    @pytest.mark.asyncio
    async def test_purge_expired_removes_old_rows(self, db_session):
        store = IdempotencyStore(db_session, ttl_hours=0)
        await store.record(
            firm_id="firm_test",
            idempotency_key="key-old",
            method="POST",
            path="/api/v2/x",
            status_code=200,
            response_body={},
            request_payload={},
        )
        deleted = await store.purge_expired(
            as_of=datetime.now(UTC) + timedelta(hours=1)
        )
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_firm_scoping_isolates_keys(self, db_session):
        store = IdempotencyStore(db_session)
        await store.record(
            firm_id="firm_A",
            idempotency_key="shared-key",
            method="POST",
            path="/x",
            status_code=200,
            response_body={"firm": "A"},
            request_payload={},
        )
        # Different firm with same key → miss
        row = await store.lookup(
            firm_id="firm_B",
            idempotency_key="shared-key",
            method="POST",
            path="/x",
        )
        assert row is None


# ===========================================================================
# §2.8 Rate limiting — RFC 7807 envelope
# ===========================================================================


class TestRateLimit:
    def test_rate_limit_handler_emits_429_problem_json(self):
        from slowapi.errors import RateLimitExceeded

        from artha.api_v2.rate_limit import rate_limit_handler

        app = FastAPI()
        setup_api_v2(app)

        @app.get("/explode")
        async def explode():
            class _Limit:
                error_message = "60 per 1 minute"

            raise RateLimitExceeded(_Limit())

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/explode")
        assert resp.status_code == 429
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["ex1_category"] == "rate_limit_exceeded"

        # Direct handler unit test
        async def _exercise():
            from starlette.requests import Request

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/x",
                "headers": [],
                "query_string": b"",
            }
            req = Request(scope)
            class _L:
                error_message = "60/minute"
            return await rate_limit_handler(req, RateLimitExceeded(_L()))
        result = asyncio.get_event_loop().run_until_complete(_exercise())
        assert result.status_code == 429


# ===========================================================================
# Routing — health + whoami live
# ===========================================================================


class TestV2Router:
    def test_system_health_returns_200(self):
        app, _ = _build_test_app()
        with TestClient(app) as client:
            resp = client.get("/api/v2/system/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["service"] == "samriddhi-api-v2"
        assert body["phase"] == "foundation"

    def test_v2_routes_mounted_under_prefix(self):
        app, _ = _build_test_app()
        v2_paths = [r.path for r in app.routes if "/api/v2" in getattr(r, "path", "")]
        assert "/api/v2/system/health" in v2_paths
        assert "/api/v2/auth/whoami" in v2_paths


# ===========================================================================
# Canonical Role.AUDIT — extended permission helpers
# ===========================================================================


class TestAuditRole:
    def _viewer(self, role: Role, *, client_ids: tuple[str, ...] = ()) -> ViewerContext:
        return ViewerContext(
            role=role,
            user_id="user_x",
            firm_id="firm_test",
            assigned_client_ids=frozenset(client_ids),
        )

    def test_audit_can_read_firm(self):
        v = self._viewer(Role.AUDIT)
        # No raise
        assert_can_read_firm(v, firm_id="firm_test")

    def test_audit_can_read_any_client_in_firm(self):
        v = self._viewer(Role.AUDIT)
        assert_can_read_client(v, client_id="any_client", client_firm_id="firm_test")

    def test_audit_blocked_other_firm(self):
        v = self._viewer(Role.AUDIT)
        with pytest.raises(PermissionDeniedError):
            assert_can_read_firm(v, firm_id="firm_other")

    def test_audit_cannot_write(self):
        v = self._viewer(Role.AUDIT)
        with pytest.raises(PermissionDeniedError):
            assert_can_write(v, action="approve_anything")

    def test_audit_role_has_canonical_value(self):
        assert Role.AUDIT.value == "audit"
        assert Role("audit") is Role.AUDIT


# Suppress F401 on imports kept for re-export sanity.
_keep = (APIError, datetime, Any)
