"""Auth router: dev-login, dev-users, refresh, logout, OIDC stubs, whoami.

Endpoint surface for cluster 0 demo stage. Per Cluster 0 Dev-Mode Addendum:

- ``POST /api/v2/auth/dev-login`` — stub auth that mints a JWT against
  ``dev/test_users.yaml``. Production phase removes this.
- ``GET  /api/v2/auth/dev-users`` — list of test users for the dev-login
  dropdown. Production phase removes this.
- ``POST /api/v2/auth/refresh`` — refresh-token rotation per FR 17.1 §2.3.
- ``POST /api/v2/auth/logout`` — revokes the current session.
- ``GET  /api/v2/auth/whoami`` — returns the current authenticated user.
- ``GET  /api/v2/auth/login`` and ``GET /api/v2/auth/callback`` — production
  OIDC entry points. Return 501 with a problem detail in demo stage per
  Dev-Mode Addendum §3.4.

T1 events (FR 17.0 §5 / FR 17.1 §5) are emitted within the same DB
transaction as the state change so they roll back together if the surrounding
operation fails.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth import sessions as sessions_service
from artha.api_v2.auth.dev_users import DemoUser, get_catalogue
from artha.api_v2.auth.event_names import (
    AUTH_LOGIN_COMPLETED,
    AUTH_LOGIN_FAILED,
    AUTH_LOGOUT,
    SESSION_CREATED,
    SESSION_EXPIRED,
    SESSION_REFRESHED,
    SESSION_REVOKED,
)
from artha.api_v2.auth.models import RevocationReason, SessionRow
from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.sessions import (
    RefreshRaceConflictError,
    RefreshTokenInvalidError,
    RefreshTokenTheftError,
    SessionExpiredError,
)
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.observability.t1 import emit_event
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session
from artha.config import settings

router = APIRouter(prefix="/api/v2/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class DevLoginRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"


class DevUserPublic(BaseModel):
    """Subset of DemoUser fields safe to expose to the dev-login UI."""

    user_id: str
    name: str
    role: str


class DevUsersResponse(BaseModel):
    users: list[DevUserPublic]


class WhoAmIResponse(BaseModel):
    user_id: str
    firm_id: str
    role: str
    email: str
    name: str
    session_id: str


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _set_refresh_cookie(response: Response, refresh_token_plain: str) -> None:
    """Set the refresh cookie per FR 17.1 §2.2."""
    response.set_cookie(
        key="samriddhi_refresh",
        value=refresh_token_plain,
        max_age=settings.refresh_cookie_max_age_seconds,
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key="samriddhi_refresh",
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _request_audit_fields(request: Request) -> tuple[str | None, str | None]:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return (ua[:500] if ua else None, ip)


# ---------------------------------------------------------------------------
# Dev-mode endpoints (Dev-Mode Addendum §3.2 / §3.3)
# ---------------------------------------------------------------------------


@router.get("/dev-users", response_model=DevUsersResponse)
async def dev_users() -> DevUsersResponse:
    """Return the demo user catalogue for the dev-login dropdown.

    Email is omitted (the addendum says "minus any sensitive fields").
    """
    catalogue = get_catalogue()
    return DevUsersResponse(
        users=[
            DevUserPublic(user_id=u.user_id, name=u.name, role=u.role.value)
            for u in catalogue.users
        ]
    )


@router.post("/dev-login", response_model=TokenResponse)
async def dev_login(
    body: DevLoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Stub auth: mint a JWT for a YAML-defined test user.

    Replaces FR 17.0's six-step OIDC flow for cluster 0 demo stage. The
    issued JWT is byte-identical in structure to what production OIDC will
    issue, so downstream code is unchanged.
    """
    catalogue = get_catalogue()
    user_agent, ip_address = _request_audit_fields(request)

    user: DemoUser | None = catalogue.find_user(body.user_id)
    if user is None:
        # Emit the failure event in its own transaction so it persists even
        # though we're returning an error.
        async with db.begin():
            await emit_event(
                db,
                event_name=AUTH_LOGIN_FAILED,
                payload={
                    "reason": "unknown_user_id",
                    "presented_user_id": body.user_id,
                    "ip_address": ip_address,
                },
            )
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Unknown demo user",
            detail=f"No demo user with user_id={body.user_id!r} in dev/test_users.yaml.",
        )

    async with db.begin():
        issued = await sessions_service.create_session(
            db,
            user_id=user.user_id,
            firm_id=catalogue.firm.firm_id,
            role=user.role,
            email=user.email,
            name=user.name,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await emit_event(
            db,
            event_name=SESSION_CREATED,
            payload={
                "session_id": issued.session.session_id,
                "user_id": user.user_id,
                "firm_id": catalogue.firm.firm_id,
                "role": user.role.value,
                "user_agent": user_agent,
                "ip_address": ip_address,
            },
            firm_id=catalogue.firm.firm_id,
        )
        await emit_event(
            db,
            event_name=AUTH_LOGIN_COMPLETED,
            payload={
                "user_id": user.user_id,
                "firm_id": catalogue.firm.firm_id,
                "role": user.role.value,
                "session_id": issued.session.session_id,
                "auth_source": "stub_dev_login",
            },
            firm_id=catalogue.firm.firm_id,
        )

    _set_refresh_cookie(response, issued.refresh_token_plain)
    return TokenResponse(
        access_token=issued.access_jwt,
        expires_in=settings.jwt_access_token_minutes * 60,
    )


# ---------------------------------------------------------------------------
# Refresh / logout
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Rotate the refresh token and reissue the access JWT (FR 17.1 §2.3)."""
    refresh_cookie = request.cookies.get("samriddhi_refresh")
    if not refresh_cookie:
        return problem_response(
            status=status.HTTP_401_UNAUTHORIZED,
            title="Missing refresh cookie",
            detail="No samriddhi_refresh cookie present on the request.",
        )

    user_agent, ip_address = _request_audit_fields(request)

    try:
        async with db.begin():
            issued = await sessions_service.refresh_session(
                db,
                refresh_token_plain=refresh_cookie,
                user_agent=user_agent,
                ip_address=ip_address,
            )
            await emit_event(
                db,
                event_name=SESSION_REFRESHED,
                payload={
                    "session_id": issued.session.session_id,
                    "user_id": issued.session.user_id,
                },
                firm_id=issued.session.firm_id,
            )
    except RefreshTokenTheftError as exc:
        # Revoke + emit in a fresh transaction (the refresh transaction
        # already rolled back when the exception was raised).
        async with db.begin():
            await sessions_service.revoke_session(
                db, exc.session_id, reason=RevocationReason.THEFT_DETECTED
            )
            await emit_event(
                db,
                event_name=SESSION_REVOKED,
                payload={
                    "session_id": exc.session_id,
                    "reason": RevocationReason.THEFT_DETECTED.value,
                },
            )
        _clear_refresh_cookie(response)
        return problem_response(
            status=status.HTTP_401_UNAUTHORIZED,
            title="Refresh token theft detected",
            detail="Session has been revoked. Re-authenticate to continue.",
        )
    except SessionExpiredError as exc:
        async with db.begin():
            await sessions_service.revoke_session(
                db, exc.session_id, reason=RevocationReason.EXPIRED
            )
            await emit_event(
                db,
                event_name=SESSION_EXPIRED,
                payload={"session_id": exc.session_id},
            )
        _clear_refresh_cookie(response)
        return problem_response(
            status=status.HTTP_401_UNAUTHORIZED,
            title="Session expired",
            detail="The 8-hour session window has elapsed.",
        )
    except RefreshTokenInvalidError:
        return problem_response(
            status=status.HTTP_401_UNAUTHORIZED,
            title="Invalid refresh token",
        )
    except RefreshRaceConflictError:
        # Per FR 17.1 §6.4 — retry-able 409.
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Refresh in progress",
            detail="A concurrent refresh request rotated this session's token first; retry.",
        )

    _set_refresh_cookie(response, issued.refresh_token_plain)
    return TokenResponse(
        access_token=issued.access_jwt,
        expires_in=settings.jwt_access_token_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Revoke the current session and clear the refresh cookie."""
    refresh_cookie = request.cookies.get("samriddhi_refresh")
    if refresh_cookie:
        # Look up the session by current refresh hash and revoke.
        token_hash = hashlib.sha256(refresh_cookie.encode("utf-8")).digest()
        async with db.begin():
            result = await db.execute(
                select(SessionRow).where(
                    SessionRow.refresh_token_hash == token_hash,
                    SessionRow.revoked.is_(False),
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                await sessions_service.revoke_session(
                    db, row.session_id, reason=RevocationReason.USER_LOGOUT
                )
                await emit_event(
                    db,
                    event_name=SESSION_REVOKED,
                    payload={
                        "session_id": row.session_id,
                        "reason": RevocationReason.USER_LOGOUT.value,
                    },
                    firm_id=row.firm_id,
                )
                await emit_event(
                    db,
                    event_name=AUTH_LOGOUT,
                    payload={
                        "session_id": row.session_id,
                        "user_id": row.user_id,
                        "logout_type": "local",
                    },
                    firm_id=row.firm_id,
                )

    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# ---------------------------------------------------------------------------
# Whoami (small dev affordance + integration check)
# ---------------------------------------------------------------------------


@router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(
    user: Annotated[
        UserContext,
        Depends(require_permission(Permission.AUTH_SESSION_READ)),
    ],
) -> WhoAmIResponse:
    return WhoAmIResponse(
        user_id=user.user_id,
        firm_id=user.firm_id,
        role=user.role.value,
        email=user.email,
        name=user.name,
        session_id=user.session_id,
    )


# ---------------------------------------------------------------------------
# Production OIDC stubs (Dev-Mode Addendum §3.4)
# ---------------------------------------------------------------------------


_OIDC_NOT_ENABLED_DETAIL = (
    "Production OIDC auth is not enabled in this build. "
    "Demo stage uses the stub /api/v2/auth/dev-login endpoint instead. "
    "See Cluster 0 Dev-Mode Addendum §3.4."
)


@router.get("/login")
async def production_login_stub() -> Response:
    return problem_response(
        status=status.HTTP_501_NOT_IMPLEMENTED,
        title="Production OIDC login not implemented",
        detail=_OIDC_NOT_ENABLED_DETAIL,
    )


@router.get("/callback")
async def production_callback_stub() -> Response:
    return problem_response(
        status=status.HTTP_501_NOT_IMPLEMENTED,
        title="Production OIDC callback not implemented",
        detail=_OIDC_NOT_ENABLED_DETAIL,
    )
