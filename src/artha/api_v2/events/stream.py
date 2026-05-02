"""SSE stream generator: assembles the per-connection event lifecycle.

The :func:`sse_event_stream` async generator is the body of the
``/api/v2/events/stream`` endpoint. It:

1. Validates auth (caller has already done this — we receive a UserContext).
2. Mints a connection_id and resolves the per-session shared buffer.
3. Registers in :class:`ConnectionRegistry` so :func:`publish` fan-out can
   reach this connection.
4. Emits ``connection_established`` (FR 18.0 §2.1).
5. Optionally replays buffered events with id > Last-Event-ID
   (FR 18.0 §2.5).
6. Spawns background timers:
   - heartbeat every ``settings.sse_heartbeat_interval_seconds``
     (FR 18.0 §2.4)
   - one-shot ``token_refresh_required`` at JWT exp − ``sse_token_refresh_lead_seconds``
     (FR 18.0 §2.7)
7. Drains the connection's queue, yielding sse-starlette frame dicts.
8. Cleans up on client disconnect (CancelledError) or explicit close.

T1 events ``sse_connection_opened`` and ``sse_connection_closed`` fire at
the boundaries; the latter records ``close_reason``, ``total_events_emitted``,
and ``connection_duration_seconds``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker
from ulid import ULID

from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.events.envelope import (
    ConnectionEstablishedPayload,
    EventEnvelope,
    connection_established_envelope,
    connection_heartbeat_envelope,
    token_refresh_required_envelope,
)
from artha.api_v2.events.event_names import SSE_CONNECTION_CLOSED, SSE_CONNECTION_OPENED
from artha.api_v2.events.event_types import CLUSTER_0_SUBSCRIBED
from artha.api_v2.events.registry import (
    ConnectionState,
    get_buffer_registry,
    get_registry,
)
from artha.api_v2.events.subscription import scope_for_role
from artha.api_v2.observability.t1 import emit_event
from artha.common.db.engine import get_engine
from artha.config import settings

logger = logging.getLogger(__name__)


def _frame(envelope: EventEnvelope) -> dict[str, str]:
    """Format an envelope for sse-starlette's ``EventSourceResponse``.

    sse-starlette expects a dict with ``id``/``event``/``data`` keys; it
    handles serialising into the SSE wire format.
    """
    return {
        "id": envelope.event_id,
        "event": envelope.event_type,
        "data": envelope.model_dump_json(),
    }


def _seconds_until_token_refresh(user_context: UserContext, claims_exp: int | None) -> float:
    """Return seconds until we should fire ``token_refresh_required``.

    Falls back to ``jwt_access_token_minutes * 60 - lead`` if ``exp`` isn't
    available (shouldn't happen — verify_jwt requires exp — but defensive).
    """
    lead = settings.sse_token_refresh_lead_seconds
    if claims_exp is None:
        full_lifetime = settings.jwt_access_token_minutes * 60
        return max(0.0, full_lifetime - lead)
    now_ts = datetime.now(timezone.utc).timestamp()
    return max(0.0, claims_exp - now_ts - lead)


async def sse_event_stream(
    user_context: UserContext,
    *,
    last_event_id: str | None = None,
    jwt_exp: int | None = None,
) -> AsyncIterator[dict[str, str]]:
    """The async generator driving one SSE connection.

    Caller (the endpoint) wraps this in :class:`EventSourceResponse`.
    """
    connection_id = f"conn_{ULID()}"
    buffer = get_buffer_registry().get_or_create(
        user_context.session_id,
        window=timedelta(seconds=settings.sse_buffer_window_seconds),
    )
    state = ConnectionState(
        connection_id=connection_id,
        session_id=user_context.session_id,
        user_id=user_context.user_id,
        firm_id=user_context.firm_id,
        role=user_context.role,
        buffer=buffer,
    )
    get_registry().register(state)

    # T1: sse_connection_opened.
    await _emit_t1_async(
        event_name=SSE_CONNECTION_OPENED,
        payload={
            "connection_id": connection_id,
            "session_id": user_context.session_id,
            "user_id": user_context.user_id,
            "firm_id": user_context.firm_id,
            "role": user_context.role.value,
        },
        firm_id=user_context.firm_id,
    )

    close_reason = "client_disconnect"
    heartbeat_task: asyncio.Task[None] | None = None
    token_refresh_task: asyncio.Task[None] | None = None

    try:
        # 4. Emit connection_established.
        established_envelope = connection_established_envelope(
            payload=ConnectionEstablishedPayload(
                connection_id=connection_id,
                user_id=user_context.user_id,
                role=user_context.role.value,
                subscribed_event_types=list(CLUSTER_0_SUBSCRIBED),
                subscription_scope=scope_for_role(user_context.role),
                server_time=datetime.now(timezone.utc),
                heartbeat_interval_seconds=settings.sse_heartbeat_interval_seconds,
                max_payload_bytes=settings.sse_max_payload_bytes,
            ),
            firm_id=user_context.firm_id,
        )
        # Buffer + yield.
        buffer.append(established_envelope)
        yield _frame(established_envelope)

        # 5. Replay if Last-Event-ID resolves into our buffer window.
        if last_event_id and buffer.is_replayable(last_event_id):
            for replayed in buffer.iter_since(last_event_id):
                if replayed.event_id == established_envelope.event_id:
                    # Avoid double-emitting the just-sent connection_established.
                    continue
                yield _frame(replayed)

        # 6. Background timers — heartbeat + one-shot token-refresh.
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(state),
            name=f"sse-heartbeat-{connection_id}",
        )
        token_refresh_task = asyncio.create_task(
            _token_refresh_one_shot(state, jwt_exp=jwt_exp),
            name=f"sse-token-refresh-{connection_id}",
        )

        # 7. Drain the queue.
        while True:
            envelope = await state.queue.get()
            yield _frame(envelope)

    except asyncio.CancelledError:
        # Client disconnected (server shut down or HTTP cancellation).
        close_reason = "client_disconnect"
        raise
    finally:
        # Cleanup. Order matters: cancel timers first so they stop pushing
        # into the queue, then unregister.
        for task in (heartbeat_task, token_refresh_task):
            if task is not None and not task.done():
                task.cancel()
        get_registry().unregister(connection_id)

        duration = (datetime.now(timezone.utc) - state.opened_at).total_seconds()
        await _emit_t1_async(
            event_name=SSE_CONNECTION_CLOSED,
            payload={
                "connection_id": connection_id,
                "session_id": user_context.session_id,
                "close_reason": close_reason,
                "total_events_emitted": state.events_emitted,
                "connection_duration_seconds": duration,
            },
            firm_id=user_context.firm_id,
        )


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


async def _heartbeat_loop(state: ConnectionState) -> None:
    """Push ``connection_heartbeat`` envelopes onto the connection's queue."""
    interval = settings.sse_heartbeat_interval_seconds
    while True:
        await asyncio.sleep(interval)
        envelope = connection_heartbeat_envelope(firm_id=state.firm_id)
        state.buffer.append(envelope)
        await state.queue.put(envelope)


async def _token_refresh_one_shot(
    state: ConnectionState, *, jwt_exp: int | None
) -> None:
    """Fire ``token_refresh_required`` once, ``lead`` seconds before JWT exp."""
    delay = _seconds_until_token_refresh_for_state(state, jwt_exp)
    if delay <= 0:
        # JWT is already at/near expiry — fire immediately.
        delay = 0
    await asyncio.sleep(delay)
    envelope = token_refresh_required_envelope(
        firm_id=state.firm_id,
        seconds_until_expiry=settings.sse_token_refresh_lead_seconds,
    )
    state.buffer.append(envelope)
    await state.queue.put(envelope)


def _seconds_until_token_refresh_for_state(
    state: ConnectionState, jwt_exp: int | None
) -> float:
    """Variant of :func:`_seconds_until_token_refresh` that uses state context."""
    lead = settings.sse_token_refresh_lead_seconds
    if jwt_exp is None:
        return max(0.0, settings.jwt_access_token_minutes * 60 - lead)
    now_ts = datetime.now(timezone.utc).timestamp()
    return max(0.0, jwt_exp - now_ts - lead)


# ---------------------------------------------------------------------------
# T1 emission helper — opens a fresh DB session per emit.
# ---------------------------------------------------------------------------


async def _emit_t1_async(
    *,
    event_name: str,
    payload: dict[str, Any],
    firm_id: str | None,
) -> None:
    """Emit one T1 event in its own short-lived DB session.

    The SSE generator can run for hours; we don't hold a DB session open
    across that duration. Each T1 emit takes a fresh session, commits, and
    closes. Failures are logged but not propagated (the SSE stream itself
    must not die because telemetry persistence hiccupped).
    """
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    try:
        async with factory() as db:
            async with db.begin():
                await emit_event(
                    db,
                    event_name=event_name,
                    payload=payload,
                    firm_id=firm_id,
                )
    except Exception:  # noqa: BLE001 — telemetry must not crash the stream.
        logger.warning("T1 emit failed for %s; continuing", event_name, exc_info=True)


# Re-exported so callers can validate envelope JSON shape in tests.
__all__ = ["sse_event_stream", "_frame"]


def _make_test_frame(envelope: EventEnvelope) -> dict[str, str]:
    """Test helper exposing the private :func:`_frame`."""
    return _frame(envelope)


def _envelope_from_frame_data(data_str: str) -> dict[str, Any]:
    """Test helper: parse a frame's ``data`` string back to a dict."""
    return json.loads(data_str)
