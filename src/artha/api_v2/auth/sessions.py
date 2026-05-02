"""Sessions service: create, refresh (with rotation + theft detection), revoke.

All operations take an :class:`AsyncSession` and participate in the caller's
transaction. The caller is responsible for committing.

Implements:

- FR 17.1 §2.1 (JWT issuance via :mod:`artha.api_v2.auth.jwt_signing`)
- FR 17.1 §2.2 (refresh token: 32 bytes, base64url, hash-only persistence)
- FR 17.1 §2.3 (refresh flow with rotation)
- FR 17.1 §2.5 (session revocation)
- FR 17.1 §2.6 (per-user concurrent session limit)
- FR 17.1 §6.4 (concurrent refresh race protection via atomic UPDATE)
- FR 17.0 §6.5 / FR 17.1 acceptance test 5 (refresh token theft detection)
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.auth.jwt_signing import issue_jwt
from artha.api_v2.auth.models import RevocationReason, SessionRow
from artha.api_v2.auth.user_context import Role
from artha.config import settings

# ---------------------------------------------------------------------------
# Exceptions — auth-layer signals; the router maps these to HTTP responses.
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Base for all auth/session errors."""


class RefreshTokenInvalidError(AuthError):
    """Presented refresh token does not match any current session."""


class RefreshTokenTheftError(AuthError):
    """Presented token matches a previously-rotated value. Session has been revoked."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"refresh token theft detected on session {session_id}")
        self.session_id = session_id


class SessionExpiredError(AuthError):
    """Session 8-hour window has passed.

    Carries ``session_id`` so the caller can revoke + log the expiry in a
    fresh transaction (the surrounding refresh transaction is about to roll
    back when this exception is raised).
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(f"session expired: {session_id}")
        self.session_id = session_id


class SessionRevokedError(AuthError):
    """Session is marked revoked."""


class RefreshRaceConflictError(AuthError):
    """Concurrent refresh request arrived first; this one lost the atomic UPDATE.

    Per FR 17.1 §6.4 / acceptance test 7, this is a "retry-able" error mapped
    to HTTP 409.
    """


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class IssuedSession:
    """Output of :func:`create_session` / :func:`refresh_session`.

    Carries the persisted row plus the plaintext refresh token (which is
    never persisted in plaintext) and the freshly-signed JWT. The router
    sets the cookie from ``refresh_token_plain`` and returns ``access_jwt``
    in the response body.
    """

    __slots__ = ("session", "refresh_token_plain", "access_jwt")

    def __init__(self, session: SessionRow, refresh_token_plain: str, access_jwt: str) -> None:
        self.session = session
        self.refresh_token_plain = refresh_token_plain
        self.access_jwt = access_jwt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_token(token_plain: str) -> bytes:
    """SHA-256 of the token's UTF-8 bytes. 32 bytes output."""
    return hashlib.sha256(token_plain.encode("utf-8")).digest()


def _new_refresh_token() -> str:
    """Cryptographically random 32 bytes, base64url-encoded.

    Per FR 17.1 §2.2.
    """
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Service operations
# ---------------------------------------------------------------------------


async def create_session(
    db: AsyncSession,
    *,
    user_id: str,
    firm_id: str,
    role: Role,
    email: str,
    name: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedSession:
    """Create a new session row, mint a JWT, return both plus the refresh token.

    Enforces the per-user concurrent session limit (FR 17.1 §2.6) by revoking
    the oldest active session if the user is already at the cap.
    """
    # FR 17.1 §2.6 — enforce the cap by revoking the oldest active session.
    await _enforce_session_cap(db, user_id=user_id)

    now = datetime.now(timezone.utc)
    session_id = str(ULID())
    refresh_token_plain = _new_refresh_token()
    refresh_token_hash = _hash_token(refresh_token_plain)

    row = SessionRow(
        session_id=session_id,
        user_id=user_id,
        firm_id=firm_id,
        role=role.value,
        email=email,
        name=name,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(seconds=settings.refresh_cookie_max_age_seconds),
        refresh_token_hash=refresh_token_hash,
        previous_refresh_token_hash=None,
        refresh_token_superseded_at=None,
        revoked=False,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(row)
    await db.flush()

    access_jwt = issue_jwt(
        user_id=user_id,
        firm_id=firm_id,
        role=role,
        email=email,
        name=name,
        session_id=session_id,
        issued_at=now,
    )

    return IssuedSession(
        session=row,
        refresh_token_plain=refresh_token_plain,
        access_jwt=access_jwt,
    )


async def refresh_session(
    db: AsyncSession,
    *,
    refresh_token_plain: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> IssuedSession:
    """Rotate the refresh token and reissue the access JWT.

    Sequence per FR 17.1 §2.3:
      1. Hash presented token.
      2. Look up active session by current hash.
      3. If not found, check previous hash → theft.
      4. If session expired → :class:`SessionExpired`.
      5. Atomic UPDATE rotates the hash; if 0 rows updated → :class:`RefreshRaceConflictError`.
      6. Issue fresh JWT with same session_id.
    """
    presented_hash = _hash_token(refresh_token_plain)

    # Step 2: lookup by current hash, active only.
    result = await db.execute(
        select(SessionRow).where(
            SessionRow.refresh_token_hash == presented_hash,
            SessionRow.revoked.is_(False),
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        # Step 3: maybe it's a previously-rotated token → theft detection.
        # NOTE: We do NOT revoke the session here. Auto-revoking inside the
        # same transaction that's about to roll back (because we're raising)
        # would silently lose the revoke. Instead, the caller catches the
        # exception and revokes in a fresh transaction.
        result = await db.execute(
            select(SessionRow).where(
                SessionRow.previous_refresh_token_hash == presented_hash,
            )
        )
        theft_row = result.scalar_one_or_none()
        if theft_row is not None:
            raise RefreshTokenTheftError(theft_row.session_id)
        raise RefreshTokenInvalidError()

    # Step 4: expiry check. Same rollback-vs-raise rationale as above —
    # caller revokes in a fresh transaction.
    now = datetime.now(timezone.utc)
    if _is_expired(row, now):
        raise SessionExpiredError(row.session_id)

    # Step 5: atomic rotation. The WHERE clause includes the presented hash so
    # concurrent refresh requests for the same token cannot both succeed
    # (FR 17.1 §6.4).
    new_refresh_token_plain = _new_refresh_token()
    new_hash = _hash_token(new_refresh_token_plain)
    update_result = await db.execute(
        update(SessionRow)
        .where(
            SessionRow.session_id == row.session_id,
            SessionRow.refresh_token_hash == presented_hash,
            SessionRow.revoked.is_(False),
        )
        .values(
            refresh_token_hash=new_hash,
            previous_refresh_token_hash=presented_hash,
            refresh_token_superseded_at=now,
            last_used_at=now,
            user_agent=user_agent if user_agent else row.user_agent,
            ip_address=ip_address if ip_address else row.ip_address,
        )
    )
    if update_result.rowcount == 0:
        # Lost the race or session was revoked between SELECT and UPDATE.
        raise RefreshRaceConflictError()

    await db.flush()
    # Refresh row in place so caller sees post-update state (mainly last_used_at).
    await db.refresh(row)

    # Step 6: re-issue JWT with same identity + session_id. email/name are
    # held on the session row (spec extension) so we don't lose them across
    # refresh.
    access_jwt = issue_jwt(
        user_id=row.user_id,
        firm_id=row.firm_id,
        role=Role(row.role),
        email=row.email,
        name=row.name,
        session_id=row.session_id,
        issued_at=now,
    )

    return IssuedSession(
        session=row, refresh_token_plain=new_refresh_token_plain, access_jwt=access_jwt
    )


async def revoke_session(
    db: AsyncSession,
    session_id: str,
    *,
    reason: RevocationReason = RevocationReason.USER_LOGOUT,
) -> bool:
    """Mark a session revoked. Returns True if a row changed, False if no-op.

    Idempotent: revoking an already-revoked session is a no-op.
    """
    return await _revoke_internal(db, session_id=session_id, reason=reason)


async def get_active_session(db: AsyncSession, session_id: str) -> SessionRow | None:
    """Return the session row if it's not revoked and not expired, else None."""
    result = await db.execute(
        select(SessionRow).where(
            SessionRow.session_id == session_id,
            SessionRow.revoked.is_(False),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if _is_expired(row, datetime.now(timezone.utc)):
        return None
    return row


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _is_expired(row: SessionRow, now: datetime) -> bool:
    """True if the 8-hour window has passed."""
    expires = row.expires_at
    # SQLite-via-aiosqlite stores naive datetimes by default; coerce for compare.
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= now


async def _revoke_internal(
    db: AsyncSession, *, session_id: str, reason: RevocationReason
) -> bool:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(SessionRow)
        .where(SessionRow.session_id == session_id, SessionRow.revoked.is_(False))
        .values(revoked=True, revoked_at=now, revocation_reason=reason.value)
    )
    return result.rowcount > 0


async def _enforce_session_cap(db: AsyncSession, *, user_id: str) -> None:
    """If the user is at the concurrent-session cap, revoke the oldest active.

    Per FR 17.1 §2.6: "When the user creates a fourth session, the oldest
    active session is automatically revoked."
    """
    cap = settings.max_concurrent_sessions_per_user
    result = await db.execute(
        select(SessionRow)
        .where(SessionRow.user_id == user_id, SessionRow.revoked.is_(False))
        .order_by(SessionRow.created_at.asc())
    )
    actives = list(result.scalars())
    # Filter expired (treat them as not-counting toward the cap; they're dead).
    now = datetime.now(timezone.utc)
    actives = [s for s in actives if not _is_expired(s, now)]
    while len(actives) >= cap:
        oldest = actives.pop(0)
        await _revoke_internal(
            db, session_id=oldest.session_id, reason=RevocationReason.ADMIN_REVOKED
        )
