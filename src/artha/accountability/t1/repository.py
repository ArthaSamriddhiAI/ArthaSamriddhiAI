"""Append-only repository for the T1 ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.accountability.t1.models import T1Event
from artha.accountability.t1.orm import T1EventRow
from artha.common.errors import ArthaError
from artha.common.standards import T1EventType
from artha.common.types import VersionPins


class T1AppendError(ArthaError):
    """Raised when an append violates T1's append-only contract.

    The most common case is attempting to insert an event whose `event_id` already
    exists — replay correctness depends on every event being unique, and silently
    overwriting would break that invariant. Catching this signals upstream that
    the caller has a bug (typically: re-using a ULID generated earlier).
    """


class T1Repository:
    """T1's append-only persistence interface.

    Surface intentionally minimal: `append`, `get`, `list_for_case`, `list_for_client`,
    `list_corrections_of`. No update or delete — corrections are appended with
    `correction_of` set, never written in place.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: T1Event) -> T1Event:
        """Append a new T1 event. Raises `T1AppendError` if `event_id` already exists."""
        existing = await self._session.get(T1EventRow, event.event_id)
        if existing is not None:
            raise T1AppendError(
                f"event_id collision: {event.event_id} already in t1_events; "
                "T1 is append-only — generate a new event_id or use correction_of"
            )

        row = T1EventRow(
            event_id=event.event_id,
            event_type=event.event_type.value,
            timestamp=event.timestamp,
            firm_id=event.firm_id,
            case_id=event.case_id,
            client_id=event.client_id,
            advisor_id=event.advisor_id,
            payload_json=json.dumps(event.payload, sort_keys=True, separators=(",", ":")),
            payload_hash=event.payload_hash,
            version_pins_json=event.version_pins.model_dump_json(),
            correction_of=event.correction_of,
        )
        self._session.add(row)
        await self._session.flush()
        return event

    async def get(self, event_id: str) -> T1Event | None:
        row = await self._session.get(T1EventRow, event_id)
        if row is None:
            return None
        return _row_to_event(row)

    async def list_for_case(self, case_id: str, *, limit: int | None = None) -> list[T1Event]:
        """Return events for a case in chronological order (timestamp asc, event_id asc)."""
        stmt = (
            select(T1EventRow)
            .where(T1EventRow.case_id == case_id)
            .order_by(T1EventRow.timestamp, T1EventRow.event_id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_row_to_event(row) for row in result.scalars().all()]

    async def list_for_client(self, client_id: str, *, limit: int | None = None) -> list[T1Event]:
        stmt = (
            select(T1EventRow)
            .where(T1EventRow.client_id == client_id)
            .order_by(T1EventRow.timestamp, T1EventRow.event_id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_row_to_event(row) for row in result.scalars().all()]

    async def list_corrections_of(self, original_event_id: str) -> list[T1Event]:
        """Return every event that corrects `original_event_id` (recursive chains not flattened)."""
        stmt = (
            select(T1EventRow)
            .where(T1EventRow.correction_of == original_event_id)
            .order_by(T1EventRow.timestamp, T1EventRow.event_id)
        )
        result = await self._session.execute(stmt)
        return [_row_to_event(row) for row in result.scalars().all()]


def _row_to_event(row: T1EventRow) -> T1Event:
    # SQLite via aiosqlite stores DateTime(timezone=True) but loses tzinfo on
    # read. T1's contract is UTC throughout; reattach tzinfo if missing so that
    # the replay invariant (persisted == reloaded) holds across the SQLite path.
    ts: datetime = row.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return T1Event(
        event_id=row.event_id,
        event_type=T1EventType(row.event_type),
        timestamp=ts,
        firm_id=row.firm_id,
        case_id=row.case_id,
        client_id=row.client_id,
        advisor_id=row.advisor_id,
        payload=json.loads(row.payload_json),
        payload_hash=row.payload_hash,
        version_pins=VersionPins.model_validate_json(row.version_pins_json),
        correction_of=row.correction_of,
    )
