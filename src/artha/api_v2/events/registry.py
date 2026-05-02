"""Active connection registry + per-session buffer registry + publisher.

Two singletons live here:

- :class:`ConnectionRegistry` — maps ``connection_id`` to :class:`ConnectionState`.
  One entry per active SSE stream.
- :class:`BufferRegistry` — maps ``session_id`` to :class:`ConnectionBuffer`.
  The buffer is shared across reconnects within the same auth session so
  Last-Event-ID replay works across a brief disconnect (FR 18.0 §2.5 /
  §2.7's "connection_session_token persists across reconnects within the
  same session").

Cluster 0 buffers are held indefinitely (until process restart). A future
cluster adds TTL eviction / per-session memory caps. For demo-stage scale
(single user at a time on a laptop), this is acceptable; the buffer's own
5-minute window keeps the per-session footprint bounded.

Publisher is the interface future cluster emitters use:

    from artha.api_v2.events.registry import publish

    async def some_event_emitter(...):
        env = envelope(event_type="case_progress_update", payload={...}, firm_id=...)
        await publish(env)

Cluster 0 has no such emitters outside connection lifecycle; ``publish`` is
unused but in place. Once cluster 5+ ships, those clusters call ``publish``
and the existing fan-out / filtering / buffering machinery delivers events
to subscribed connections without further changes here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from artha.api_v2.auth.user_context import Role
from artha.api_v2.events.buffer import ConnectionBuffer
from artha.api_v2.events.envelope import EventEnvelope
from artha.api_v2.events.subscription import event_passes_scope


@dataclass
class ConnectionState:
    """Per-connection runtime state held by the registry.

    ``buffer`` is the SHARED per-session buffer (so reconnects can replay).
    ``queue`` is per-connection (each live stream drains its own).
    """

    connection_id: str
    session_id: str
    user_id: str
    firm_id: str
    role: Role
    buffer: ConnectionBuffer
    queue: asyncio.Queue[EventEnvelope] = field(default_factory=asyncio.Queue)
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    events_emitted: int = 0


class ConnectionRegistry:
    """In-memory map of connection_id → :class:`ConnectionState`.

    Concurrency: writes (register / unregister) and reads (publish iter)
    happen on the asyncio event loop; the registry itself doesn't take a
    lock because the operations are short and synchronous.
    """

    def __init__(self) -> None:
        self._connections: dict[str, ConnectionState] = {}

    def register(self, state: ConnectionState) -> None:
        self._connections[state.connection_id] = state

    def unregister(self, connection_id: str) -> ConnectionState | None:
        return self._connections.pop(connection_id, None)

    def get(self, connection_id: str) -> ConnectionState | None:
        return self._connections.get(connection_id)

    def __len__(self) -> int:
        return len(self._connections)

    def all_states(self) -> list[ConnectionState]:
        # Snapshot to allow safe iteration even if concurrent register fires.
        return list(self._connections.values())


class BufferRegistry:
    """Per-session shared buffers for Last-Event-ID replay across reconnects."""

    def __init__(self, default_window: timedelta = timedelta(minutes=5)) -> None:
        self._buffers: dict[str, ConnectionBuffer] = {}
        self._default_window = default_window

    def get_or_create(
        self, session_id: str, *, window: timedelta | None = None
    ) -> ConnectionBuffer:
        if session_id not in self._buffers:
            self._buffers[session_id] = ConnectionBuffer(window=window or self._default_window)
        return self._buffers[session_id]

    def discard(self, session_id: str) -> None:
        """Drop a session's buffer. Used when the session is revoked."""
        self._buffers.pop(session_id, None)

    def __len__(self) -> int:
        return len(self._buffers)


# Module-level singletons. Tests reset via ``reset_for_tests()``.
_registry = ConnectionRegistry()
_buffers = BufferRegistry()


def get_registry() -> ConnectionRegistry:
    return _registry


def get_buffer_registry() -> BufferRegistry:
    return _buffers


def reset_for_tests() -> None:
    """Clear both registries. Test-only helper."""
    global _registry, _buffers
    _registry = ConnectionRegistry()
    _buffers = BufferRegistry()


async def publish(envelope: EventEnvelope, *, owner_user_id: str | None = None) -> int:
    """Fan out one envelope to every subscribed connection.

    Returns the number of connections the event was delivered to. The
    delivery itself is non-blocking: the envelope is appended to each
    matching session's buffer (deduped per-session for Last-Event-ID replay)
    and pushed onto each matching connection's queue (for the live stream
    to drain).

    ``owner_user_id`` is the per-event ownership scope used by advisor's
    ``own_scope`` filter (None means "no per-user owner; firm-scoped").
    """
    delivered = 0
    sessions_buffered: set[str] = set()
    for state in _registry.all_states():
        if not event_passes_scope(
            role=state.role,
            user_id=state.user_id,
            firm_id=state.firm_id,
            event_firm_id=envelope.firm_id,
            event_owner_user_id=owner_user_id,
        ):
            continue
        # Buffer once per session, even if multiple connections of that
        # session match (rare but possible if user has multiple tabs).
        if state.session_id not in sessions_buffered:
            state.buffer.append(envelope)
            sessions_buffered.add(state.session_id)
        await state.queue.put(envelope)
        state.events_emitted += 1
        delivered += 1
    return delivered
