"""JWT sign/verify (HS256 default; RS256 supported when configured).

Per FR Entry 17.0 §3.1 (claim structure) and FR Entry 17.1 §2.1 (signing key
strategy). The signing key comes from :data:`artha.config.settings.jwt_secret`;
if empty in DEVELOPMENT, a per-process random secret is generated lazily so
the system is usable out of the box. Tokens become invalid across restarts in
that mode — acceptable for local development; explicitly **not** acceptable
for any non-development environment, which raises on first sign attempt.

Validation includes:

- Signature verification against the configured key.
- ``iss`` matches :data:`settings.jwt_issuer`.
- ``aud`` matches :data:`settings.jwt_audience`.
- ``exp`` has not passed (60 second skew tolerance per FR 17.1 §6.3).
- ``iat`` is not in the future (with the same skew tolerance).
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt as pyjwt
from jwt.exceptions import InvalidTokenError

from artha.api_v2.auth.user_context import Role
from artha.config import Environment, settings

logger = logging.getLogger(__name__)


_dev_secret_cache: str | None = None


def _signing_key() -> str:
    """Resolve the active signing key.

    Production-equivalent environments require an explicit secret. Development
    falls back to a per-process random secret with a one-time warning.
    """
    if settings.jwt_secret:
        return settings.jwt_secret

    if settings.environment != Environment.DEVELOPMENT:
        raise RuntimeError(
            "JWT_SECRET must be set in non-development environments "
            "(current ENVIRONMENT=%s)." % settings.environment.value
        )

    global _dev_secret_cache
    if _dev_secret_cache is None:
        _dev_secret_cache = secrets.token_urlsafe(48)
        logger.warning(
            "JWT_SECRET unset; generated a per-process development secret. "
            "Tokens will be invalidated on backend restart. "
            "Set JWT_SECRET in .env to make tokens persist."
        )
    return _dev_secret_cache


def issue_jwt(
    *,
    user_id: str,
    firm_id: str,
    role: Role,
    email: str,
    name: str,
    session_id: str,
    issued_at: datetime | None = None,
) -> str:
    """Sign a fresh application JWT.

    Claims are exactly those listed in FR 17.0 §3.1. Lifetime is governed by
    :data:`settings.jwt_access_token_minutes` (default 15).
    """
    now = issued_at or datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_access_token_minutes)
    claims: dict[str, Any] = {
        "sub": user_id,
        "firm_id": firm_id,
        "role": role.value,
        "email": email,
        "name": name,
        "session_id": session_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return pyjwt.encode(claims, _signing_key(), algorithm=settings.jwt_algorithm)


class JWTValidationError(Exception):
    """Raised when a JWT fails validation. Translates to HTTP 401 upstream."""


def verify_jwt(token: str) -> dict[str, Any]:
    """Validate signature, exp, iat, iss, aud and return the claims dict.

    Raises :class:`JWTValidationError` on any validation failure. The
    underlying PyJWT error is chained for diagnostic purposes but the
    public exception hides specifics from callers (so HTTP responses
    don't leak signature-vs-expiry distinctions).
    """
    try:
        return pyjwt.decode(
            token,
            _signing_key(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=60,  # FR 17.1 §6.3 skew tolerance
            options={"require": ["exp", "iat", "iss", "aud", "sub", "session_id"]},
        )
    except InvalidTokenError as exc:
        raise JWTValidationError(str(exc)) from exc


def reset_dev_secret_cache() -> None:
    """Clear the per-process dev secret. Test-only helper."""
    global _dev_secret_cache
    _dev_secret_cache = None
