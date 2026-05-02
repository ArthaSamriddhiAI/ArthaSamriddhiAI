"""T1 emission helper — cluster 0 placeholder.

Single function :func:`emit_event` writes one immutable :class:`T1Event` row
to the database. There is no batching, no async queue, no replay machinery
in cluster 0 — those land when FR Entry 9.0 is authored.

The function takes an :class:`AsyncSession` rather than opening its own so
that emission participates in the caller's transaction. For auth flows this
matters: ``session_created`` should commit atomically with the new
:class:`SessionRow`, and ``auth_login_failed`` should commit even when the
surrounding handler raises (callers can take a separate session for that).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.observability.models import T1Event


async def emit_event(
    session: AsyncSession,
    *,
    event_name: str,
    payload: dict[str, Any],
    firm_id: str | None = None,
    request_id: str | None = None,
    emitted_at: datetime | None = None,
) -> T1Event:
    """Append one event to the T1 ledger.

    Returns the constructed row; the caller is responsible for committing
    the surrounding transaction (or rolling it back, in which case the event
    is also rolled back).
    """
    event = T1Event(
        event_id=str(ULID()),
        event_name=event_name,
        payload=payload,
        request_id=request_id,
        emitted_at=emitted_at or datetime.now(timezone.utc),
        firm_id=firm_id,
    )
    session.add(event)
    await session.flush()
    return event
