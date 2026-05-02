"""Sessions table ORM model.

Schema per FR Entry 17.1 §3.2, with one engineering extension: a
``previous_refresh_token_hash`` column to support refresh-token-theft
detection per FR 17.0 §6.5 / FR 17.1 acceptance test 5 ("a refresh token,
once used and rotated, fails on subsequent use; the session is revoked").
The FR spec describes the theft-detection behaviour but does not specify
its storage mechanism; tracking the immediate previous hash is the
minimal-storage standard pattern for single-row session models.

All column types are portable between SQLite and Postgres per the
Demo-Stage Database Addendum §1.2 (no JSONB, no Postgres-only types).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class RevocationReason(str, Enum):
    """Why a session was revoked. Enforced as a string column at the DB level."""

    USER_LOGOUT = "user_logout"
    ADMIN_REVOKED = "admin_revoked"
    THEFT_DETECTED = "theft_detected"
    EXPIRED = "expired"


class SessionRow(Base):
    """Persistent session state per FR 17.1 §3.2.

    Lifetime: 8 hours from ``created_at`` (FR 17.1 §2.2). The 15-minute
    application JWT is reissued from this session via the refresh flow
    (FR 17.1 §2.3) for as long as the session remains valid and not revoked.

    The session_id is a ULID (26 characters in Crockford base32) that also
    appears in the JWT's ``session_id`` claim, providing a stable handle from
    the JWT back to the persistent session row.
    """

    __tablename__ = "sessions"

    # ULID, primary key (FR 17.1 §3.2). 26 chars in Crockford base32.
    session_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    firm_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)

    # Identity claims that travel with the JWT (FR 17.0 §3.1). Held on the
    # session row so refresh-token rotation can re-issue a JWT with the same
    # identity without round-tripping to the IdP. Spec extension.
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # SHA-256(refresh_token) of the CURRENT refresh token. Indexed for
    # constant-time refresh lookup (FR 17.1 §2.3 step 3).
    refresh_token_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary(32), nullable=True, index=True
    )
    # SHA-256(refresh_token) of the IMMEDIATE PREVIOUS refresh token for the
    # purposes of theft detection (FR 17.0 §6.5 / FR 17.1 §2.3). When a
    # refresh request presents a hash matching this column (rather than
    # ``refresh_token_hash``), the session is revoked.
    previous_refresh_token_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary(32), nullable=True
    )

    # Timestamp of the last refresh-token rotation (null until first rotation).
    refresh_token_superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Audit fields per FR 17.1 §3.2.
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    __table_args__ = (
        Index("ix_sessions_expires_at", "expires_at"),
    )
