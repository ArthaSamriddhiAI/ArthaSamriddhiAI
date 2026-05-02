"""FastAPI dependencies for authenticated routes.

The single entry point is :func:`get_current_user`, which extracts the JWT
from the ``Authorization: Bearer ...`` header, verifies its signature and
claims, and returns the constructed :class:`UserContext`. Any failure raises
:class:`HTTPException` with 401 and an RFC 7807 problem detail.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from artha.api_v2.auth.jwt_signing import JWTValidationError, verify_jwt
from artha.api_v2.auth.user_context import UserContext

# auto_error=False so we can raise our own RFC 7807-shaped error rather than
# FastAPI's default {"detail": "..."} body.
_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UserContext:
    """Resolve the authenticated user for this request.

    Raises 401 on:
      - missing or non-Bearer Authorization header
      - JWT signature/expiry/iss/aud validation failure
      - missing required claim
      - unknown role value
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Bearer token required")

    try:
        claims = verify_jwt(credentials.credentials)
    except JWTValidationError as exc:
        raise _unauthorized(f"Invalid token: {exc}") from exc

    try:
        return UserContext.from_jwt_claims(claims)
    except ValueError as exc:
        raise _unauthorized(str(exc)) from exc


CurrentUser = Annotated[UserContext, Depends(get_current_user)]
"""Type alias for routes that need the authenticated user."""
