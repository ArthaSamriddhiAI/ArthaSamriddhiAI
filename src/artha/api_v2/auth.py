"""Doc 2 §2.2 — JWT auth dependency for API v2.

This module owns the user-context plumbing for `/api/v2/`:

  * `Permission` — the role-scoped permission flag vocabulary from Doc 2 §2.2.
  * `UserContext` — Pydantic shape carrying `user_id`, `firm_id`, `role`,
    `permissions`, plus token expiry. The same shape returned by
    `/api/v2/auth/session` and embedded in JWT custom claims.
  * `JWTSigner` — encode + decode helpers. Pass 1 ships HS256 with a
    deployment-supplied secret (`SAMRIDDHI_JWT_SECRET`) for test ergonomics
    and dev local. Pass 2 (`/auth/login`/`/callback`) wires RS256 against
    the firm's OIDC IdP.
  * `get_current_user` — FastAPI dependency that reads `Authorization:
    Bearer ...`, validates the token, returns `UserContext`. Raises
    `UnauthorizedError` (401) on any failure.
  * `require_role(*roles)` and `require_permission(*perms)` — dependency
    factories that gate endpoints by role / permission.
  * `ROLE_DEFAULT_PERMISSIONS` — canonical role → permission-set map per
    Doc 2 §2.2. Tests + token issuance use it as the default.

Doc 2 §2.6 maps validation failures to RFC 7807 problem types; this module
raises `UnauthorizedError` from `api_v2.errors` rather than letting the JWT
exception bubble up as a 500.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import jwt
from fastapi import Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from artha.api_v2.errors import ForbiddenError, UnauthorizedError
from artha.canonical.views import Role

# ---------------------------------------------------------------------------
# Config — JWT issuer + secret/key
# ---------------------------------------------------------------------------

DEFAULT_JWT_ISSUER = "samriddhi.local"
DEFAULT_JWT_AUDIENCE = "samriddhi.api.v2"
DEFAULT_ACCESS_TTL_SECONDS = 15 * 60  # 15 minutes per Doc 2 §2.2


def _env_jwt_secret() -> str:
    """Read the symmetric JWT secret from env.

    Production deployments wire RS256 against the OIDC IdP in Pass 2; this
    HS256 path is for dev / tests / single-process deployments. The secret
    must be at least 32 bytes; we coerce a default for tests so suite
    bootstrap doesn't require env wiring.
    """
    secret = os.environ.get("SAMRIDDHI_JWT_SECRET", "test-secret-DO-NOT-USE-IN-PRODUCTION")
    if len(secret) < 16:
        raise RuntimeError(
            "SAMRIDDHI_JWT_SECRET must be at least 16 characters; "
            "production deploys MUST set a strong secret"
        )
    return secret


# ---------------------------------------------------------------------------
# Permission flag vocabulary (Doc 2 §2.2)
# ---------------------------------------------------------------------------


class Permission(str, Enum):
    """Doc 2 §2.2 — role-scoped permission flags.

    Each flag gates a class of operations. The role → permission map below
    binds flags to roles (a `cio` carries every `cio`-allowed flag in the
    JWT's `permissions` claim).
    """

    # Investor scope
    INVESTOR_READ_OWN_BOOK = "investor:read:own_book"
    INVESTOR_READ_FIRM = "investor:read:firm"
    INVESTOR_WRITE = "investor:write"
    INVESTOR_DELETE = "investor:delete"

    # Mandate scope
    MANDATE_READ_OWN_BOOK = "mandate:read:own_book"
    MANDATE_READ_FIRM = "mandate:read:firm"
    MANDATE_WRITE = "mandate:write"
    MANDATE_APPROVE = "mandate:approve"

    # Case scope
    CASE_READ_OWN_BOOK = "case:read:own_book"
    CASE_READ_FIRM = "case:read:firm"
    CASE_WRITE = "case:write"
    CASE_CANCEL = "case:cancel"

    # Model portfolio scope
    MODEL_PORTFOLIO_READ = "model_portfolio:read"
    MODEL_PORTFOLIO_WRITE = "model_portfolio:write"
    MODEL_PORTFOLIO_APPROVE = "model_portfolio:approve"

    # Alerts (N0)
    ALERT_READ_OWN_BOOK = "alert:read:own_book"
    ALERT_READ_FIRM = "alert:read:firm"
    ALERT_WRITE = "alert:write"

    # Monitoring (PM1)
    MONITORING_READ_OWN_BOOK = "monitoring:read:own_book"
    MONITORING_READ_FIRM = "monitoring:read:firm"

    # Committee (IC1)
    COMMITTEE_READ = "committee:read"
    COMMITTEE_WRITE = "committee:write"

    # Telemetry (T1)
    TELEMETRY_READ = "telemetry:read"
    TELEMETRY_READ_OPERATIONAL = "telemetry:read:operational"

    # Reflection (T2)
    REFLECTION_READ = "reflection:read"
    REFLECTION_WRITE = "reflection:write"

    # Governance (G1/G2/G3 + override audit)
    GOVERNANCE_READ = "governance:read"
    GOVERNANCE_WRITE = "governance:write"

    # Briefings
    BRIEFING_READ_OWN_BOOK = "briefing:read:own_book"
    BRIEFING_READ_FIRM = "briefing:read:firm"
    BRIEFING_WRITE = "briefing:write"

    # System
    SYSTEM_READ = "system:read"
    SYSTEM_READ_FIRM_INFO = "system:read:firm_info"

    # Events / SSE
    EVENTS_SUBSCRIBE = "events:subscribe"


# Doc 2 §2.2 — default permission set per role. JWT issuance reads this map.
ROLE_DEFAULT_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADVISOR: frozenset({
        Permission.INVESTOR_READ_OWN_BOOK,
        Permission.INVESTOR_WRITE,
        Permission.MANDATE_READ_OWN_BOOK,
        Permission.MANDATE_WRITE,
        Permission.CASE_READ_OWN_BOOK,
        Permission.CASE_WRITE,
        Permission.CASE_CANCEL,
        Permission.MODEL_PORTFOLIO_READ,
        Permission.ALERT_READ_OWN_BOOK,
        Permission.ALERT_WRITE,
        Permission.MONITORING_READ_OWN_BOOK,
        Permission.BRIEFING_READ_OWN_BOOK,
        Permission.BRIEFING_WRITE,
        Permission.SYSTEM_READ,
        Permission.SYSTEM_READ_FIRM_INFO,
        Permission.EVENTS_SUBSCRIBE,
    }),
    Role.CIO: frozenset({
        Permission.INVESTOR_READ_FIRM,
        Permission.INVESTOR_WRITE,
        Permission.INVESTOR_DELETE,
        Permission.MANDATE_READ_FIRM,
        Permission.MANDATE_WRITE,
        Permission.MANDATE_APPROVE,
        Permission.CASE_READ_FIRM,
        Permission.CASE_WRITE,
        Permission.CASE_CANCEL,
        Permission.MODEL_PORTFOLIO_READ,
        Permission.MODEL_PORTFOLIO_WRITE,
        Permission.MODEL_PORTFOLIO_APPROVE,
        Permission.ALERT_READ_FIRM,
        Permission.ALERT_WRITE,
        Permission.MONITORING_READ_FIRM,
        Permission.COMMITTEE_READ,
        Permission.COMMITTEE_WRITE,
        Permission.TELEMETRY_READ_OPERATIONAL,
        Permission.REFLECTION_READ,
        Permission.REFLECTION_WRITE,
        Permission.GOVERNANCE_READ,
        Permission.GOVERNANCE_WRITE,
        Permission.BRIEFING_READ_FIRM,
        Permission.BRIEFING_WRITE,
        Permission.SYSTEM_READ,
        Permission.SYSTEM_READ_FIRM_INFO,
        Permission.EVENTS_SUBSCRIBE,
    }),
    Role.COMPLIANCE: frozenset({
        Permission.INVESTOR_READ_FIRM,
        Permission.MANDATE_READ_FIRM,
        Permission.CASE_READ_FIRM,
        Permission.MODEL_PORTFOLIO_READ,
        Permission.ALERT_READ_FIRM,
        Permission.MONITORING_READ_FIRM,
        Permission.COMMITTEE_READ,
        Permission.TELEMETRY_READ,
        Permission.REFLECTION_READ,
        Permission.GOVERNANCE_READ,
        Permission.SYSTEM_READ,
        Permission.SYSTEM_READ_FIRM_INFO,
        Permission.EVENTS_SUBSCRIBE,
    }),
    Role.AUDIT: frozenset({
        Permission.INVESTOR_READ_FIRM,
        Permission.MANDATE_READ_FIRM,
        Permission.CASE_READ_FIRM,
        Permission.MODEL_PORTFOLIO_READ,
        Permission.ALERT_READ_FIRM,
        Permission.MONITORING_READ_FIRM,
        Permission.COMMITTEE_READ,
        Permission.TELEMETRY_READ,
        Permission.REFLECTION_READ,
        Permission.GOVERNANCE_READ,
        Permission.SYSTEM_READ,
        Permission.SYSTEM_READ_FIRM_INFO,
        Permission.EVENTS_SUBSCRIBE,
    }),
}


def default_permissions_for(role: Role) -> frozenset[Permission]:
    """Look up the canonical permission set for a role."""
    return ROLE_DEFAULT_PERMISSIONS[role]


# ---------------------------------------------------------------------------
# UserContext — Pydantic + transport shape
# ---------------------------------------------------------------------------


class UserContext(BaseModel):
    """Doc 2 §2.2 — authenticated user identity + scope.

    Returned by `/api/v2/auth/session` and `/api/v2/auth/refresh`. Mirrors
    the JWT's custom claims. `permissions` is a `frozenset[Permission]`
    on read; for transport (JSON serialisation) it becomes a sorted list
    of strings.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str
    firm_id: str
    role: Role
    permissions: frozenset[Permission] = Field(default_factory=frozenset)
    token_expires_at: datetime | None = None

    def has_permission(self, perm: Permission) -> bool:
        return perm in self.permissions

    def has_role(self, *roles: Role) -> bool:
        return self.role in roles


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


class JWTSigner:
    """HS256 signer + verifier for Pass 1.

    Pass 2 swaps to RS256 against the firm's OIDC IdP. The interface here
    stays stable across the swap: `encode_access_token(user)` and
    `decode_access_token(token)`.

    Construction defaults are env-driven so tests can override per case
    via `JWTSigner(secret="...", issuer="...", audience="...")`.
    """

    def __init__(
        self,
        *,
        secret: str | None = None,
        issuer: str = DEFAULT_JWT_ISSUER,
        audience: str = DEFAULT_JWT_AUDIENCE,
        access_ttl_seconds: int = DEFAULT_ACCESS_TTL_SECONDS,
    ) -> None:
        self._secret = secret or _env_jwt_secret()
        self._issuer = issuer
        self._audience = audience
        self._access_ttl = access_ttl_seconds

    def encode_access_token(
        self,
        user: UserContext,
        *,
        now: datetime | None = None,
    ) -> tuple[str, datetime]:
        """Encode a user context into an HS256 JWT.

        Returns `(token, expires_at)`. The token's `exp` claim is set to
        `now + access_ttl_seconds`.
        """
        issued_at = now or datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=self._access_ttl)
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": user.user_id,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            # Custom claims per Doc 2 §2.2
            "firm_id": user.firm_id,
            "role": user.role.value,
            "permissions": sorted(p.value for p in user.permissions),
        }
        token = jwt.encode(payload, self._secret, algorithm="HS256")
        return token, expires_at

    def decode_access_token(self, token: str) -> UserContext:
        """Validate + decode a JWT into a `UserContext`.

        Raises `UnauthorizedError` on signature mismatch, expiry, missing
        claims, malformed claim values.
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError(
                problem_type="https://samriddhi.ai/errors/access-token-expired",
                title="Access token expired",
                detail="The access token has expired; refresh via /api/v2/auth/refresh.",
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise UnauthorizedError(
                problem_type="https://samriddhi.ai/errors/access-token-invalid",
                title="Access token invalid",
                detail=str(exc),
            ) from exc

        return _user_context_from_claims(payload)


def _user_context_from_claims(claims: dict[str, Any]) -> UserContext:
    """Build a `UserContext` from a validated JWT claim dict."""
    try:
        role = Role(claims["role"])
    except (KeyError, ValueError) as exc:
        raise UnauthorizedError(
            problem_type="https://samriddhi.ai/errors/access-token-invalid",
            title="Access token invalid",
            detail=f"missing or invalid role claim: {exc}",
        ) from exc

    user_id = claims.get("sub") or claims.get("user_id")
    firm_id = claims.get("firm_id")
    if not user_id or not firm_id:
        raise UnauthorizedError(
            problem_type="https://samriddhi.ai/errors/access-token-invalid",
            title="Access token invalid",
            detail="missing sub or firm_id claim",
        )

    perm_strings = claims.get("permissions") or []
    permissions: set[Permission] = set()
    for raw in perm_strings:
        try:
            permissions.add(Permission(raw))
        except ValueError:
            # Unknown permission strings are ignored rather than rejected
            # so a future-version token with extra perms doesn't break older
            # validators. The strict permission check happens at the
            # endpoint layer via `require_permission`.
            continue

    expires_at = (
        datetime.fromtimestamp(claims["exp"], tz=UTC)
        if "exp" in claims
        else None
    )

    return UserContext(
        user_id=str(user_id),
        firm_id=str(firm_id),
        role=role,
        permissions=frozenset(permissions),
        token_expires_at=expires_at,
    )


# Process-wide default signer; tests can override via `set_default_signer`.
_default_signer: JWTSigner | None = None


def get_default_signer() -> JWTSigner:
    """Lazy global signer used by `get_current_user`. Tests override with
    `set_default_signer(JWTSigner(secret="..."))`.
    """
    global _default_signer
    if _default_signer is None:
        _default_signer = JWTSigner()
    return _default_signer


def set_default_signer(signer: JWTSigner | None) -> None:
    """Test-only: replace (or reset to None) the process-wide signer."""
    global _default_signer
    _default_signer = signer


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise UnauthorizedError(
            problem_type="https://samriddhi.ai/errors/auth-missing",
            title="Authentication required",
            detail="Missing Authorization header.",
        )
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise UnauthorizedError(
            problem_type="https://samriddhi.ai/errors/auth-malformed",
            title="Malformed Authorization header",
            detail="Expected 'Authorization: Bearer <token>'.",
        )
    return parts[1].strip()


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> UserContext:
    """FastAPI dependency: validate JWT and return `UserContext`.

    Side effects: stashes the user on `request.state.user` so downstream
    middleware (rate limiting, observability) can read it without re-
    validating the token.
    """
    token = _extract_bearer_token(authorization)
    signer = get_default_signer()
    user = signer.decode_access_token(token)
    request.state.user = user
    return user


def require_role(*roles: Role):
    """Dependency factory: gate by role. Raises 403 on mismatch."""
    role_set = set(roles)

    def _dep(user: UserContext = Depends(get_current_user)) -> UserContext:
        if user.role not in role_set:
            raise ForbiddenError(
                problem_type="https://samriddhi.ai/errors/insufficient-permissions",
                title="Insufficient permissions",
                detail=(
                    f"Endpoint requires role in {sorted(r.value for r in role_set)}; "
                    f"caller has {user.role.value!r}."
                ),
            )
        return user

    return _dep


def require_permission(*perms: Permission):
    """Dependency factory: gate by permission flag. Caller must have ALL listed perms."""
    needed = set(perms)

    def _dep(user: UserContext = Depends(get_current_user)) -> UserContext:
        missing = needed - set(user.permissions)
        if missing:
            raise ForbiddenError(
                problem_type="https://samriddhi.ai/errors/insufficient-permissions",
                title="Insufficient permissions",
                detail=(
                    "Caller is missing required permission(s): "
                    f"{sorted(p.value for p in missing)}."
                ),
            )
        return user

    return _dep


__all__ = [
    "DEFAULT_ACCESS_TTL_SECONDS",
    "DEFAULT_JWT_AUDIENCE",
    "DEFAULT_JWT_ISSUER",
    "JWTSigner",
    "Permission",
    "ROLE_DEFAULT_PERMISSIONS",
    "Role",
    "UserContext",
    "default_permissions_for",
    "get_current_user",
    "get_default_signer",
    "require_permission",
    "require_role",
    "set_default_signer",
]
