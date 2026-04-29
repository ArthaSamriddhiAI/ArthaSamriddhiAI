"""§10.1 — C0 Conversational Channel.

C0 ingests advisor inputs and emits a structured `C0ParseOutput`. Per §10.1.2
C0 is **not** a chatbot — it parses + pre-tags + extracts entities, then
hands off to M0.Router. Discipline (§10.1.4):

  * Never guess. Surface `ambiguity_flags` instead.
  * Resolve entities deterministically against the firm's client directory.
  * Use session context (M0.Librarian snapshot) only for anaphora resolution.

Pass 14 ships an LLM-backed parser with deterministic entity resolution.
The directory is a `ClientDirectory` protocol — production wires this to the
firm's KYC registry; tests use `InMemoryClientDirectory`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol

from artha.canonical.channels import (
    C0AmbiguityType,
    C0ChannelSource,
    C0ExtractedEntities,
    C0ParseOutput,
    C0SessionMetadata,
    LibrarianSession,
    _LlmC0ParseOutput,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.types import (
    CaseIntent,
    InputsUsedManifest,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


class C0LLMUnavailableError(ArthaError):
    """Raised when C0's parser LLM provider fails."""


# ===========================================================================
# Client directory protocol
# ===========================================================================


class ClientDirectory(Protocol):
    """Firm KYC registry. Production wires SQL/CRM here; tests use the in-memory impl."""

    def find_by_name(self, raw_name: str) -> list[dict[str, str]]:
        """Return list of `{"client_id": str, "display_name": str}` matches."""
        ...


class InMemoryClientDirectory:
    """In-memory directory keyed by lowercased name fragments.

    Multiple clients can share a name → multiple matches → C0 surfaces
    `client_name_ambiguous`. A match miss returns an empty list.
    """

    def __init__(self, clients: list[dict[str, str]] | None = None) -> None:
        self._clients = clients or []

    def add(self, client_id: str, display_name: str) -> None:
        self._clients.append({"client_id": client_id, "display_name": display_name})

    def find_by_name(self, raw_name: str) -> list[dict[str, str]]:
        if not raw_name:
            return []
        needle = raw_name.lower().strip()
        return [
            c
            for c in self._clients
            if needle in c["display_name"].lower()
        ]


# ===========================================================================
# System prompt
# ===========================================================================


_SYSTEM_PROMPT = """\
You are C0, the Conversational Channel parser for Samriddhi AI (§10.1).

Your job: parse the advisor's verbatim text into a structured pre-tag for
M0.Router. You are NOT a chatbot — you do not respond, you classify.

Strict rules:
- Output JSON with: parsed_intent_value (one of: case, diagnostic, briefing,
  monitoring_response, knowledge_query, profile_update, rebalance_trigger,
  mandate_review), parsed_intent_confidence (0.0-1.0), extracted_entities
  (named fields where present, null otherwise), ambiguity_flags.
- Confidence ≥ 0.85 for unambiguous inputs; < 0.6 when multiple intents are
  plausible.
- Never guess. If the client name is ambiguous or absent, leave client_id
  null and surface `client_name_ambiguous` in ambiguity_flags.
- Honour session context (the prior turn's parsed_intent + extracted entities)
  for anaphora ("for him", "the same one") only. Do NOT pull data from prior
  turns into the current entities except when the advisor's text references
  them.
"""


# ===========================================================================
# Agent
# ===========================================================================


class ConversationalChannel:
    """§10.1 conversational channel.

    Construction:
      * `provider` — LLM provider for the parse step.
      * `directory` — `ClientDirectory` for entity resolution.
      * `parser_version` — pinned for replay.
    """

    agent_id = "c0_parser"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        directory: ClientDirectory | None = None,
        parser_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._directory = directory or InMemoryClientDirectory()
        self._parser_version = parser_version

    # --------------------- Public API --------------------------------

    async def parse(
        self,
        *,
        raw_text: str,
        advisor_id: str,
        firm_id: str,
        case_id: str | None = None,
        session: LibrarianSession | None = None,
        channel_source: C0ChannelSource = C0ChannelSource.UI_CHAT,
    ) -> C0ParseOutput:
        """Parse one inbound advisor input."""
        # ----- 1) LLM parse -----
        signals_block = self._render_signals(raw_text=raw_text, session=session)
        try:
            llm_output = await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=_SYSTEM_PROMPT),
                        LLMMessage(role="user", content=self._render_user_prompt(
                            raw_text=raw_text, signals_block=signals_block
                        )),
                    ],
                    temperature=0.0,
                ),
                _LlmC0ParseOutput,
            )
        except Exception as exc:
            logger.warning("C0 parser LLM unavailable: %s", exc)
            raise C0LLMUnavailableError(
                f"c0 parser LLM provider unavailable: {exc}"
            ) from exc

        try:
            parsed_intent = CaseIntent(llm_output.parsed_intent_value)
        except ValueError as exc:
            raise C0LLMUnavailableError(
                f"C0 LLM returned non-canonical intent "
                f"{llm_output.parsed_intent_value!r}"
            ) from exc

        # ----- 2) Deterministic entity resolution + ambiguity surfacing -----
        entities, additional_flags = self._resolve_entities(
            llm_output.extracted_entities, session=session
        )

        # Merge LLM-emitted ambiguity_flags + deterministic ones (deduplicate).
        merged_flags: list[C0AmbiguityType] = []
        seen: set[C0AmbiguityType] = set()
        for raw_flag in llm_output.ambiguity_flags:
            try:
                f = C0AmbiguityType(raw_flag)
            except ValueError:
                continue
            if f not in seen:
                merged_flags.append(f)
                seen.add(f)
        for f in additional_flags:
            if f not in seen:
                merged_flags.append(f)
                seen.add(f)

        # ----- 3) Build session metadata -----
        session_metadata = C0SessionMetadata(
            continuity=bool(session and session.turns),
            session_id=session.session_id if session else None,
            parent_turn_id=(
                session.turns[-1].turn_id if (session and session.turns) else None
            ),
            timestamp=get_clock().now(),
            channel_source=channel_source,
        )

        # ----- 4) Hash + manifest -----
        signals_input = self._collect_input_for_hash(
            raw_text=raw_text,
            advisor_id=advisor_id,
            firm_id=firm_id,
            session=session,
            channel_source=channel_source,
        )

        return C0ParseOutput(
            case_id=case_id,
            advisor_id=advisor_id,
            firm_id=firm_id,
            raw_text=raw_text,
            parsed_intent=parsed_intent,
            parsed_intent_confidence=llm_output.parsed_intent_confidence,
            extracted_entities=entities,
            ambiguity_flags=merged_flags,
            session_metadata=session_metadata,
            parser_version=self._parser_version,
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            timestamp=get_clock().now(),
        )

    # --------------------- Helpers ----------------------------------

    def _resolve_entities(
        self,
        entities: C0ExtractedEntities,
        *,
        session: LibrarianSession | None,
    ) -> tuple[C0ExtractedEntities, list[C0AmbiguityType]]:
        """Resolve client_id from raw name; surface ambiguity flags."""
        flags: list[C0AmbiguityType] = []

        # Resolve client_id from client_name_raw via directory.
        if entities.client_id is None and entities.client_name_raw:
            matches = self._directory.find_by_name(entities.client_name_raw)
            if len(matches) == 1:
                entities = entities.model_copy(
                    update={"client_id": matches[0]["client_id"]}
                )
            elif len(matches) > 1:
                flags.append(C0AmbiguityType.CLIENT_NAME_AMBIGUOUS)
            else:
                flags.append(C0AmbiguityType.CLIENT_NAME_AMBIGUOUS)

        # If neither client_id nor name surfaces but session has an active
        # client, the LLM is expected to have used it for anaphora — we don't
        # silently inherit here. If client_id is still null AND no flag yet
        # AND advisor used a pronoun-style phrasing, flag REFERENT_UNRESOLVED.
        if (
            entities.client_id is None
            and entities.client_name_raw is None
            and session is not None
            and session.client_id is not None
        ):
            # We don't auto-inherit; require the LLM to surface the entity.
            # If it didn't, surface as REFERENT_UNRESOLVED.
            flags.append(C0AmbiguityType.REFERENT_UNRESOLVED)

        return entities, flags

    def _render_signals(
        self,
        *,
        raw_text: str,
        session: LibrarianSession | None,
    ) -> str:
        lines = [f"raw_text = {raw_text}"]
        if session is not None:
            lines.append(f"session.client_id = {session.client_id or '<none>'}")
            recent = session.turns[-3:]
            for t in recent:
                lines.append(
                    f"prior_turn.{t.turn_id}.intent = "
                    f"{t.parsed_intent.value if t.parsed_intent else '<unset>'}"
                )
                lines.append(f"prior_turn.{t.turn_id}.text = {t.raw_text[:200]}")
            for amb in session.pending_ambiguities:
                if not amb.resolved:
                    lines.append(f"pending_ambiguity = {amb.description[:200]}")
            for fu in session.pending_followups:
                if not fu.resolved:
                    lines.append(f"pending_followup = {fu.description[:200]}")
        return "\n".join(lines)

    def _render_user_prompt(self, *, raw_text: str, signals_block: str) -> str:
        return "\n".join(
            [
                "Signals:",
                signals_block,
                "Produce the structured C0 parse output per the system prompt.",
            ]
        )

    def _collect_input_for_hash(
        self,
        *,
        raw_text: str,
        advisor_id: str,
        firm_id: str,
        session: LibrarianSession | None,
        channel_source: C0ChannelSource,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "raw_text": raw_text,
            "advisor_id": advisor_id,
            "firm_id": firm_id,
            "channel_source": channel_source.value,
            "session_id": session.session_id if session else None,
            "session_turn_count": len(session.turns) if session else 0,
            "parser_version": self._parser_version,
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "C0LLMUnavailableError",
    "ClientDirectory",
    "ConversationalChannel",
    "InMemoryClientDirectory",
]
