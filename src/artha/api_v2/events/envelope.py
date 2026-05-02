"""EventEnvelope and cluster 0 payload models.

Per FR Entry 18.0 §2.3 (the common envelope) and §4 (cluster 0 payloads).

The envelope is the JSON-serialised body of every SSE frame's ``data:`` line.
Its shape is stable across the contract version (``schema_version="1"``); the
payload field's shape is per-event-type.

Wire format (FR 18.0 §2.2):

    id: <event_id>
    event: <event_type>
    data: <JSON-serialised EventEnvelope>

    (terminating blank line)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID

from artha.api_v2.events.event_types import (
    CONNECTION_ESTABLISHED,
    CONNECTION_HEARTBEAT,
    CONNECTION_TERMINATING,
    TOKEN_REFRESH_REQUIRED,
)

#: Multiplex schema version. Clients ignore events whose ``schema_version``
#: they do not recognise rather than failing (FR 18.0 §2.3).
SCHEMA_VERSION = "1"


class EventEnvelope(BaseModel):
    """Common envelope wrapping every per-event-type payload.

    The ``payload`` field carries event-type-specific fields; its shape is
    declared by each event type's payload model (see :class:`ConnectionEstablishedPayload`
    etc. below for cluster 0 types).
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(description="ULID; matches the SSE frame's `id` field.")
    event_type: str
    emitted_at: datetime
    firm_id: str | None = None
    schema_version: str = SCHEMA_VERSION
    payload: dict[str, Any]
    request_id: str | None = None


def new_event_id() -> str:
    """Mint a fresh ULID for use as ``event_id``.

    ULIDs are lexicographically sortable by emission time, which gives
    Last-Event-ID replay a stable ordering without needing a separate
    sequence column on the buffer.
    """
    return str(ULID())


def envelope(
    *,
    event_type: str,
    payload: dict[str, Any],
    firm_id: str | None = None,
    request_id: str | None = None,
    emitted_at: datetime | None = None,
) -> EventEnvelope:
    """Construct an :class:`EventEnvelope` with sane defaults.

    Centralising construction keeps the envelope shape consistent across
    all emitters; future emitters import this rather than building the dict
    manually.
    """
    return EventEnvelope(
        event_id=new_event_id(),
        event_type=event_type,
        emitted_at=emitted_at or datetime.now(timezone.utc),
        firm_id=firm_id,
        schema_version=SCHEMA_VERSION,
        payload=payload,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Cluster 0 per-event-type payload models  (FR 18.0 §4)
# ---------------------------------------------------------------------------


class SubscriptionScope(BaseModel):
    """Per-event-family scope: ``own_scope`` or ``firm_scope``.

    Carried in the ``connection_established`` payload so the client knows
    which event variants to expect for each family. Per FR 18.0 §2.6 the
    server applies scope filtering at emission time, but the client uses
    this to drive UI behaviour (e.g., advisor sees only own-book alerts).
    """

    model_config = ConfigDict(extra="forbid")

    alerts: str  # "own_scope" | "firm_scope"
    cases: str
    monitoring: str


class ConnectionEstablishedPayload(BaseModel):
    """FR 18.0 §4.1.

    ``heartbeat_interval_seconds`` is typed as ``float`` rather than ``int``
    so tests can configure sub-second intervals; production values are
    integral (default 30). JSON serialisation preserves the int/float
    distinction Pydantic was given.
    """

    model_config = ConfigDict(extra="forbid")

    connection_id: str
    user_id: str
    role: str
    subscribed_event_types: list[str]
    subscription_scope: SubscriptionScope
    server_time: datetime
    heartbeat_interval_seconds: float
    max_payload_bytes: int


class ConnectionHeartbeatPayload(BaseModel):
    """FR 18.0 §4.2.

    Minimal payload — heartbeats are frequent and high-volume; keeping the
    payload tiny minimises bandwidth.
    """

    model_config = ConfigDict(extra="forbid")

    server_time: datetime


class TokenRefreshRequiredPayload(BaseModel):
    """Mechanism-only in cluster 0; payload mirrors what production OIDC will use.

    The client receives this 60 seconds before the access JWT expires and is
    expected to call ``POST /api/v2/auth/refresh`` (out-of-band, not on the SSE
    channel). The SSE connection itself remains alive across the refresh.
    """

    model_config = ConfigDict(extra="forbid")

    seconds_until_expiry: int
    refresh_endpoint: str = "/api/v2/auth/refresh"


class ConnectionTerminatingPayload(BaseModel):
    """Mechanism-only in cluster 0.

    Emitted when the backend has decided to close this connection (e.g., the
    underlying refresh session is about to expire and re-auth is required).
    The client should redirect to login on receiving this with
    ``session_will_expire=True``.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str
    session_will_expire: bool = False


# Convenience shortcuts that keep the call sites tidy.

def connection_established_envelope(
    *,
    payload: ConnectionEstablishedPayload,
    firm_id: str,
    request_id: str | None = None,
) -> EventEnvelope:
    return envelope(
        event_type=CONNECTION_ESTABLISHED,
        payload=payload.model_dump(mode="json"),
        firm_id=firm_id,
        request_id=request_id,
    )


def connection_heartbeat_envelope(*, firm_id: str) -> EventEnvelope:
    return envelope(
        event_type=CONNECTION_HEARTBEAT,
        payload=ConnectionHeartbeatPayload(
            server_time=datetime.now(timezone.utc)
        ).model_dump(mode="json"),
        firm_id=firm_id,
    )


def token_refresh_required_envelope(
    *, firm_id: str, seconds_until_expiry: int
) -> EventEnvelope:
    return envelope(
        event_type=TOKEN_REFRESH_REQUIRED,
        payload=TokenRefreshRequiredPayload(
            seconds_until_expiry=seconds_until_expiry,
        ).model_dump(mode="json"),
        firm_id=firm_id,
    )


def connection_terminating_envelope(
    *, firm_id: str, reason: str, session_will_expire: bool = False
) -> EventEnvelope:
    return envelope(
        event_type=CONNECTION_TERMINATING,
        payload=ConnectionTerminatingPayload(
            reason=reason,
            session_will_expire=session_will_expire,
        ).model_dump(mode="json"),
        firm_id=firm_id,
    )
