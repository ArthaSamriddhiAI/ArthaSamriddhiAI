"""§8.7 / §15.13 — persistent `M0.Librarian` repository.

`PersistentM0Librarian` mirrors `M0Librarian` (Pass 14) but persists
session state to SQLAlchemy. The deterministic session contract is
preserved — turn log is append-only, running summary built
incrementally with the same overflow-headroom rule, pending items
state-machined the same way. Only the storage layer differs.

LLM-backed `retrieve_themed` from Pass 14 is intentionally not
duplicated here — it operates over an in-memory snapshot. Callers can
hydrate a `LibrarianSession` via `get_session()` and pass it to the
in-memory implementation if they need themed retrieval.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.canonical.channels import (
    C0ChannelSource,
    LibrarianSession,
    LibrarianTurn,
    PendingAmbiguity,
    PendingFollowup,
)
from artha.common.clock import get_clock
from artha.common.types import CaseIntent
from artha.common.ulid import new_ulid
from artha.m0.librarian import TurnInput
from artha.m0.librarian_orm import (
    LibrarianPendingItemRow,
    LibrarianSessionRow,
    LibrarianTurnRow,
)

logger = logging.getLogger(__name__)

_SUMMARY_OVERFLOW_HEADROOM_RATIO = 0.9


class PersistentM0Librarian:
    """§8.7 persistent session-state store."""

    agent_id = "m0_librarian.persistent"

    def __init__(
        self,
        session: AsyncSession,
        *,
        summary_token_budget: int = 1500,
        agent_version: str = "0.1.0",
    ) -> None:
        self._session = session
        self._default_budget = summary_token_budget
        self._agent_version = agent_version

    # --------------------- Session lifecycle -----------------------

    async def begin_session(
        self,
        *,
        advisor_id: str,
        firm_id: str,
        client_id: str | None = None,
        summary_token_budget: int | None = None,
    ) -> LibrarianSession:
        now = self._now()
        session_id = new_ulid()
        budget = summary_token_budget or self._default_budget
        row = LibrarianSessionRow(
            session_id=session_id,
            advisor_id=advisor_id,
            firm_id=firm_id,
            client_id=client_id,
            started_at=now,
            ended_at=None,
            running_summary="",
            summary_token_budget=budget,
        )
        self._session.add(row)
        await self._session.flush()
        return LibrarianSession(
            session_id=session_id,
            advisor_id=advisor_id,
            firm_id=firm_id,
            client_id=client_id,
            started_at=now,
            summary_token_budget=budget,
        )

    async def end_session(self, session_id: str) -> LibrarianSession:
        row = await self._must_get_session(session_id)
        if row.ended_at is None:
            row.ended_at = self._now()
            await self._session.flush()
        return await self.get_session(session_id)

    async def get_session(self, session_id: str) -> LibrarianSession:
        row = await self._must_get_session(session_id)
        turns = await self._load_turns(session_id)
        ambiguities = await self._load_pending(session_id, kind="ambiguity")
        followups = await self._load_pending(session_id, kind="followup")
        return LibrarianSession(
            session_id=row.session_id,
            advisor_id=row.advisor_id,
            firm_id=row.firm_id,
            client_id=row.client_id,
            started_at=self._normalise_dt(row.started_at) or row.started_at,
            ended_at=self._normalise_dt(row.ended_at),
            turns=turns,
            running_summary=row.running_summary,
            pending_ambiguities=[
                PendingAmbiguity(
                    ambiguity_id=p.item_id,
                    description=p.description,
                    introduced_turn_id=p.introduced_turn_id,
                    resolved=p.resolved,
                    resolved_turn_id=p.resolved_turn_id,
                )
                for p in ambiguities
            ],
            pending_followups=[
                PendingFollowup(
                    followup_id=p.item_id,
                    description=p.description,
                    introduced_turn_id=p.introduced_turn_id,
                    promised_by_turn_id=p.promised_by_turn_id,
                    resolved=p.resolved,
                    resolved_turn_id=p.resolved_turn_id,
                )
                for p in followups
            ],
            summary_token_budget=row.summary_token_budget,
        )

    # --------------------- Turn handling ---------------------------

    async def update_on_turn(
        self,
        session_id: str,
        *,
        turn: TurnInput,
    ) -> LibrarianTurn:
        row = await self._must_get_session(session_id)
        if row.ended_at is not None:
            raise ValueError(f"session {session_id} already ended")

        # Determine sequence (count of existing turns)
        count_stmt = select(LibrarianTurnRow).where(
            LibrarianTurnRow.session_id == session_id
        )
        existing = (await self._session.execute(count_stmt)).scalars().all()
        sequence = len(existing)

        turn_id = new_ulid()
        turn_row = LibrarianTurnRow(
            turn_id=turn_id,
            session_id=session_id,
            timestamp=turn.timestamp,
            channel=turn.channel.value,
            raw_text=turn.raw_text,
            parsed_intent=(
                turn.parsed_intent.value if turn.parsed_intent is not None else None
            ),
            parsed_intent_confidence=turn.parsed_intent_confidence,
            downstream_event_ids_json=json.dumps(list(turn.downstream_event_ids)),
            sequence=sequence,
        )
        self._session.add(turn_row)

        if turn.summary_fragment:
            row.running_summary = self._extend_summary(
                existing=row.running_summary,
                fragment=turn.summary_fragment,
                budget=row.summary_token_budget,
            )

        await self._session.flush()
        return LibrarianTurn(
            turn_id=turn_id,
            timestamp=turn.timestamp,
            channel=turn.channel,
            raw_text=turn.raw_text,
            parsed_intent=turn.parsed_intent,
            parsed_intent_confidence=turn.parsed_intent_confidence,
            downstream_event_ids=list(turn.downstream_event_ids),
        )

    # --------------------- Pending state ----------------------------

    async def open_pending_ambiguity(
        self,
        session_id: str,
        *,
        description: str,
        introduced_turn_id: str,
    ) -> PendingAmbiguity:
        await self._must_get_session(session_id)
        item_id = new_ulid()
        self._session.add(
            LibrarianPendingItemRow(
                item_id=item_id,
                session_id=session_id,
                kind="ambiguity",
                description=description,
                introduced_turn_id=introduced_turn_id,
            )
        )
        await self._session.flush()
        return PendingAmbiguity(
            ambiguity_id=item_id,
            description=description,
            introduced_turn_id=introduced_turn_id,
        )

    async def resolve_pending_ambiguity(
        self,
        session_id: str,
        ambiguity_id: str,
        *,
        resolved_turn_id: str,
    ) -> PendingAmbiguity:
        item = await self._session.get(LibrarianPendingItemRow, ambiguity_id)
        if item is None or item.session_id != session_id or item.kind != "ambiguity":
            raise KeyError(f"ambiguity {ambiguity_id} not found")
        item.resolved = True
        item.resolved_turn_id = resolved_turn_id
        await self._session.flush()
        return PendingAmbiguity(
            ambiguity_id=item.item_id,
            description=item.description,
            introduced_turn_id=item.introduced_turn_id,
            resolved=True,
            resolved_turn_id=resolved_turn_id,
        )

    async def open_pending_followup(
        self,
        session_id: str,
        *,
        description: str,
        introduced_turn_id: str,
        promised_by_turn_id: str | None = None,
    ) -> PendingFollowup:
        await self._must_get_session(session_id)
        item_id = new_ulid()
        self._session.add(
            LibrarianPendingItemRow(
                item_id=item_id,
                session_id=session_id,
                kind="followup",
                description=description,
                introduced_turn_id=introduced_turn_id,
                promised_by_turn_id=promised_by_turn_id,
            )
        )
        await self._session.flush()
        return PendingFollowup(
            followup_id=item_id,
            description=description,
            introduced_turn_id=introduced_turn_id,
            promised_by_turn_id=promised_by_turn_id,
        )

    async def resolve_pending_followup(
        self,
        session_id: str,
        followup_id: str,
        *,
        resolved_turn_id: str,
    ) -> PendingFollowup:
        item = await self._session.get(LibrarianPendingItemRow, followup_id)
        if item is None or item.session_id != session_id or item.kind != "followup":
            raise KeyError(f"followup {followup_id} not found")
        item.resolved = True
        item.resolved_turn_id = resolved_turn_id
        await self._session.flush()
        return PendingFollowup(
            followup_id=item.item_id,
            description=item.description,
            introduced_turn_id=item.introduced_turn_id,
            promised_by_turn_id=item.promised_by_turn_id,
            resolved=True,
            resolved_turn_id=resolved_turn_id,
        )

    async def unresolved_followups(self, session_id: str) -> list[PendingFollowup]:
        items = await self._load_pending(session_id, kind="followup", resolved=False)
        return [
            PendingFollowup(
                followup_id=p.item_id,
                description=p.description,
                introduced_turn_id=p.introduced_turn_id,
                promised_by_turn_id=p.promised_by_turn_id,
                resolved=p.resolved,
                resolved_turn_id=p.resolved_turn_id,
            )
            for p in items
        ]

    # --------------------- Retrieval -------------------------------

    async def retrieve_recent(
        self,
        session_id: str,
        *,
        n: int = 5,
    ) -> list[LibrarianTurn]:
        if n <= 0:
            return []
        await self._must_get_session(session_id)
        turns = await self._load_turns(session_id)
        return list(turns[-n:])

    # --------------------- Helpers ----------------------------------

    async def _must_get_session(self, session_id: str) -> LibrarianSessionRow:
        row = await self._session.get(LibrarianSessionRow, session_id)
        if row is None:
            raise KeyError(f"unknown session_id={session_id}")
        return row

    async def _load_turns(self, session_id: str) -> list[LibrarianTurn]:
        stmt = (
            select(LibrarianTurnRow)
            .where(LibrarianTurnRow.session_id == session_id)
            .order_by(LibrarianTurnRow.sequence)
        )
        result = await self._session.execute(stmt)
        out: list[LibrarianTurn] = []
        for r in result.scalars().all():
            timestamp = self._normalise_dt(r.timestamp) or r.timestamp
            parsed_intent = (
                CaseIntent(r.parsed_intent) if r.parsed_intent is not None else None
            )
            out.append(
                LibrarianTurn(
                    turn_id=r.turn_id,
                    timestamp=timestamp,
                    channel=C0ChannelSource(r.channel),
                    raw_text=r.raw_text,
                    parsed_intent=parsed_intent,
                    parsed_intent_confidence=r.parsed_intent_confidence,
                    downstream_event_ids=json.loads(r.downstream_event_ids_json),
                )
            )
        return out

    async def _load_pending(
        self,
        session_id: str,
        *,
        kind: str,
        resolved: bool | None = None,
    ) -> list[LibrarianPendingItemRow]:
        stmt = select(LibrarianPendingItemRow).where(
            LibrarianPendingItemRow.session_id == session_id,
            LibrarianPendingItemRow.kind == kind,
        )
        if resolved is not None:
            stmt = stmt.where(LibrarianPendingItemRow.resolved == resolved)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def _extend_summary(
        self, *, existing: str, fragment: str, budget: int
    ) -> str:
        if not fragment:
            return existing
        new_summary = (existing + " " + fragment).strip()
        budget_chars = budget * 4
        threshold = int(budget_chars * _SUMMARY_OVERFLOW_HEADROOM_RATIO)
        if len(new_summary) > threshold:
            new_summary = new_summary[-threshold:]
        return new_summary

    def _normalise_dt(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = ["PersistentM0Librarian"]
