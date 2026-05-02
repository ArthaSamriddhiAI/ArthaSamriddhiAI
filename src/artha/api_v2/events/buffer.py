"""Per-connection event buffer for Last-Event-ID reconnect replay.

Per FR Entry 18.0 §2.5:

    "The buffer holds the last 5 minutes of events per active connection
     identity. Events older than 5 minutes are not replayable; the client
     must do a full state refresh by fetching current data through REST
     endpoints."

Implementation: a deque of (envelope, ingested_at) tuples; pruned on each
``append`` and ``iter_since``. Single-process, in-memory; cluster 0 demo
runs single-worker uvicorn so this is sufficient (DB Addendum §3.1 single-
process write constraint applies similarly here).

When a future cluster moves to multi-worker, the buffer migrates to a shared
store (Redis Streams is the natural fit for SSE replay).
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from artha.api_v2.events.envelope import EventEnvelope


class ConnectionBuffer:
    """Bounded-time ring buffer of envelopes for one connection identity.

    Bounded by ``window`` (default 5 minutes). The buffer evicts entries
    older than ``window`` lazily — entries are pruned when ``append`` runs
    and when ``iter_since`` is called, so the buffer never holds more than
    ``window`` worth of history regardless of read frequency.
    """

    def __init__(self, window: timedelta = timedelta(minutes=5)) -> None:
        self._window = window
        self._items: deque[tuple[EventEnvelope, datetime]] = deque()

    @property
    def window(self) -> timedelta:
        return self._window

    def __len__(self) -> int:
        return len(self._items)

    def append(self, envelope: EventEnvelope, *, ingested_at: datetime | None = None) -> None:
        """Add an envelope and prune anything beyond the window."""
        ts = ingested_at or datetime.now(timezone.utc)
        self._items.append((envelope, ts))
        self._prune(now=ts)

    def iter_since(
        self,
        last_event_id: str | None,
        *,
        now: datetime | None = None,
    ) -> list[EventEnvelope]:
        """Return envelopes with ``event_id > last_event_id``, newest last.

        If ``last_event_id`` is None, returns the entire current buffer.

        ULIDs sort lexicographically by emission time, so a simple string
        compare on ``event_id`` is correct here. (FR 18.0 §2.5 / §2.4 events
        are strictly ordered within a connection.)
        """
        self._prune(now=now or datetime.now(timezone.utc))
        if last_event_id is None:
            return [env for env, _ in self._items]
        return [env for env, _ in self._items if env.event_id > last_event_id]

    def is_replayable(self, last_event_id: str, *, now: datetime | None = None) -> bool:
        """True if the buffer's oldest event is at or before ``last_event_id``.

        Per FR 18.0 §2.5: "If Last-Event-ID is older than the buffer's earliest
        event, the backend emits a ``connection_established`` event (signalling
        the client should treat the connection as fresh) and then begins normal
        event delivery."
        """
        self._prune(now=now or datetime.now(timezone.utc))
        if not self._items:
            # Empty buffer can replay anything (nothing to replay, but no gap).
            return True
        oldest_id = self._items[0][0].event_id
        return last_event_id >= oldest_id

    def _prune(self, *, now: datetime) -> None:
        cutoff = now - self._window
        while self._items and self._items[0][1] < cutoff:
            self._items.popleft()
