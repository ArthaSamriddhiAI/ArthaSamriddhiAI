"""§8.7 — M0.Librarian: session-level memory across multi-turn conversations.

Authoritative session state lives in `LibrarianSession` objects. Per §8.7.6:

  * Sessions are isolated — each `session_id` owns its own state.
  * Turn log is append-only.
  * `running_summary` is built incrementally, capped at the session's
    `summary_token_budget`.
  * Pending ambiguities + pending followups are tracked deterministically.
  * LLM retrieval framing operates over a read-only snapshot and never
    invents content (test §8.7.6 #3 — themed retrieval correctness).

MVP scope (§8.7.2): session granularity only. Cross-session persistent
memory is deferred to v2.
"""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from artha.canonical.channels import (
    C0ChannelSource,
    LibrarianSession,
    LibrarianTurn,
    PendingAmbiguity,
    PendingFollowup,
    _LlmLibrarianRetrievalOutput,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.types import (
    CaseIntent,
    ConfidenceField,
)
from artha.common.ulid import new_ulid
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


class LibrarianRetrievalUnavailableError(ArthaError):
    """Raised when LLM-backed retrieval framing fails."""


# Token budget headroom — when the running_summary approaches budget,
# new summary fragments truncate older ones.
_SUMMARY_OVERFLOW_HEADROOM_RATIO = 0.9


class TurnInput(BaseModel):
    """Input shape for `Librarian.update_on_turn`.

    Reflects what M0.Router (and other M0 sub-agents) supplies to record one
    turn. The Librarian wraps it into a `LibrarianTurn` with a generated id.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    channel: C0ChannelSource
    raw_text: str
    parsed_intent: CaseIntent | None = None
    parsed_intent_confidence: ConfidenceField | None = None
    downstream_event_ids: list[str] = []
    summary_fragment: str = ""  # short hand-summary the caller appends


_RETRIEVAL_PROMPT = """\
You are M0.Librarian's themed retrieval surface (§8.7.5).

Your job: given a query and the session's turn log, produce a short summary
of the matching content with citations to specific turn_ids. You must NOT
invent content. If no turns are relevant, set `no_relevant_turns=true` and
leave `summary` empty.

Strict rules:
- Output JSON with: summary (≤200 tokens, plain prose), cited_turn_ids
  (non-empty subset of supplied turn_ids when summary is non-empty),
  no_relevant_turns (bool).
- Cite turn_ids verbatim. Never invent ids.
- Quote sparingly; paraphrase faithfully. No editorialising.
"""


class M0Librarian:
    """§8.7 session-state store + LLM-backed themed retrieval.

    Construction:
      * `provider` — LLM provider for themed retrieval (None disables it).
      * `summary_token_budget` — default budget for new sessions.
    """

    agent_id = "m0_librarian"

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        summary_token_budget: int = 1500,
        agent_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._default_budget = summary_token_budget
        self._agent_version = agent_version
        self._sessions: dict[str, LibrarianSession] = {}

    # --------------------- Session lifecycle ----------------------------

    def begin_session(
        self,
        *,
        advisor_id: str,
        firm_id: str,
        client_id: str | None = None,
        summary_token_budget: int | None = None,
    ) -> LibrarianSession:
        session = LibrarianSession(
            session_id=new_ulid(),
            advisor_id=advisor_id,
            firm_id=firm_id,
            client_id=client_id,
            started_at=self._now(),
            summary_token_budget=summary_token_budget or self._default_budget,
        )
        self._sessions[session.session_id] = session
        return session

    def end_session(self, session_id: str) -> LibrarianSession:
        session = self._must_get(session_id)
        if session.ended_at is None:
            session.ended_at = self._now()
        return session

    def get_session(self, session_id: str) -> LibrarianSession:
        return self._must_get(session_id)

    # --------------------- Turn handling --------------------------------

    def update_on_turn(
        self,
        session_id: str,
        *,
        turn: TurnInput,
    ) -> LibrarianTurn:
        """Record a turn; update running_summary deterministically."""
        session = self._must_get(session_id)
        if session.ended_at is not None:
            raise ValueError(f"session {session_id} already ended")

        recorded_turn = LibrarianTurn(
            turn_id=new_ulid(),
            timestamp=turn.timestamp,
            channel=turn.channel,
            raw_text=turn.raw_text,
            parsed_intent=turn.parsed_intent,
            parsed_intent_confidence=turn.parsed_intent_confidence,
            downstream_event_ids=list(turn.downstream_event_ids),
        )
        session.turns.append(recorded_turn)

        # Append summary fragment with simple budget enforcement.
        if turn.summary_fragment:
            self._append_summary(session, turn.summary_fragment)

        return recorded_turn

    def open_pending_ambiguity(
        self,
        session_id: str,
        *,
        description: str,
        introduced_turn_id: str,
    ) -> PendingAmbiguity:
        session = self._must_get(session_id)
        amb = PendingAmbiguity(
            ambiguity_id=new_ulid(),
            description=description,
            introduced_turn_id=introduced_turn_id,
        )
        session.pending_ambiguities.append(amb)
        return amb

    def resolve_pending_ambiguity(
        self,
        session_id: str,
        ambiguity_id: str,
        *,
        resolved_turn_id: str,
    ) -> PendingAmbiguity:
        session = self._must_get(session_id)
        for amb in session.pending_ambiguities:
            if amb.ambiguity_id == ambiguity_id:
                amb.resolved = True
                amb.resolved_turn_id = resolved_turn_id
                return amb
        raise KeyError(f"ambiguity {ambiguity_id} not found")

    def open_pending_followup(
        self,
        session_id: str,
        *,
        description: str,
        introduced_turn_id: str,
        promised_by_turn_id: str | None = None,
    ) -> PendingFollowup:
        session = self._must_get(session_id)
        fu = PendingFollowup(
            followup_id=new_ulid(),
            description=description,
            introduced_turn_id=introduced_turn_id,
            promised_by_turn_id=promised_by_turn_id,
        )
        session.pending_followups.append(fu)
        return fu

    def resolve_pending_followup(
        self,
        session_id: str,
        followup_id: str,
        *,
        resolved_turn_id: str,
    ) -> PendingFollowup:
        session = self._must_get(session_id)
        for fu in session.pending_followups:
            if fu.followup_id == followup_id:
                fu.resolved = True
                fu.resolved_turn_id = resolved_turn_id
                return fu
        raise KeyError(f"followup {followup_id} not found")

    def unresolved_followups(self, session_id: str) -> list[PendingFollowup]:
        """Return the followups still pending — used at session-close to feed N0."""
        session = self._must_get(session_id)
        return [fu for fu in session.pending_followups if not fu.resolved]

    # --------------------- Retrieval ------------------------------------

    def retrieve_recent(
        self,
        session_id: str,
        *,
        n: int = 5,
    ) -> list[LibrarianTurn]:
        """Return the last `n` turns (chronological order; deterministic)."""
        session = self._must_get(session_id)
        if n <= 0:
            return []
        return list(session.turns[-n:])

    async def retrieve_themed(
        self,
        session_id: str,
        *,
        query: str,
    ) -> tuple[str, list[str]]:
        """LLM-backed themed retrieval.

        Returns `(summary, cited_turn_ids)`. Returns `("", [])` when no
        turns match. Discipline: the LLM may only cite turn_ids present in
        the session; the deterministic post-check scrubs any invented ids
        and forces an empty summary when the LLM returns no valid citations.
        """
        if self._provider is None:
            raise LibrarianRetrievalUnavailableError(
                "themed retrieval requires an LLM provider"
            )
        session = self._must_get(session_id)
        if not session.turns:
            return "", []

        signals_block = self._render_retrieval_signals(session, query)
        try:
            llm_output = await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=_RETRIEVAL_PROMPT),
                        LLMMessage(role="user", content=signals_block),
                    ],
                    temperature=0.0,
                ),
                _LlmLibrarianRetrievalOutput,
            )
        except Exception as exc:
            logger.warning("Librarian retrieval LLM unavailable: %s", exc)
            raise LibrarianRetrievalUnavailableError(
                f"librarian retrieval LLM unavailable: {exc}"
            ) from exc

        if llm_output.no_relevant_turns:
            return "", []

        valid_ids = {t.turn_id for t in session.turns}
        cited = [tid for tid in llm_output.cited_turn_ids if tid in valid_ids]
        if not cited:
            # Discipline: no valid citations → suppress the summary.
            return "", []
        return llm_output.summary, cited

    # --------------------- Helpers ----------------------------------

    def _render_retrieval_signals(
        self,
        session: LibrarianSession,
        query: str,
    ) -> str:
        lines = [f"query = {query}"]
        for t in session.turns:
            lines.append(f"turn_id={t.turn_id} text={t.raw_text[:300]}")
        lines.append(
            "Produce JSON: summary (≤200 tokens), cited_turn_ids "
            "(must be a subset of the turn_ids above), no_relevant_turns (bool)."
        )
        return "\n".join(lines)

    def _append_summary(self, session: LibrarianSession, fragment: str) -> None:
        if not fragment:
            return
        new_summary = (session.running_summary + " " + fragment).strip()
        budget_chars = session.summary_token_budget * 4  # ~4 chars per token
        if len(new_summary) > budget_chars * _SUMMARY_OVERFLOW_HEADROOM_RATIO:
            # Drop the oldest characters; keep the tail under budget.
            keep_chars = int(budget_chars * _SUMMARY_OVERFLOW_HEADROOM_RATIO)
            new_summary = new_summary[-keep_chars:]
        session.running_summary = new_summary

    def _must_get(self, session_id: str) -> LibrarianSession:
        if session_id not in self._sessions:
            raise KeyError(f"unknown session_id={session_id}")
        return self._sessions[session_id]

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "LibrarianRetrievalUnavailableError",
    "M0Librarian",
    "TurnInput",
]
