"""Case-opening state machine for C0 (chunk 5.3).

Pure-Python FSM for the cluster-5 ``case_opening`` intent. Mirrors the
investor-onboarding + mandate-creation patterns: the LLM only acts on
the edges (intent classification + slot extraction), the FSM owns
transitions + which fields to ask for next.

States:

- ``INVESTOR_DISAMBIGUATION`` — same investor lookup pattern as
  mandate_creation (FR 14.0 cluster-2 revision §2.5). Service layer
  resolves a candidate investor_id from the user's free-text reference.
- ``COLLECTING_DETAILS`` — case_mode + (optional) case_intent +
  (optional) proposed_action fields gathered in a single sweep.
- ``AWAITING_CONFIRMATION`` — summary card; user confirms or cancels.
- ``EXECUTING`` — service handing off to ``case_opener.open_case``.
- ``COMPLETED`` / ``ABANDONED`` — terminal.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class CaseOpeningState(str, Enum):
    """The case_opening FSM cursor."""

    INVESTOR_DISAMBIGUATION = "STATE_INVESTOR_DISAMBIGUATION"
    COLLECTING_DETAILS = "STATE_COLLECTING_DETAILS"
    AWAITING_CONFIRMATION = "STATE_AWAITING_CONFIRMATION"
    EXECUTING = "STATE_EXECUTING"
    COMPLETED = "STATE_COMPLETED"
    ABANDONED = "STATE_ABANDONED"


# ---------------------------------------------------------------------------
# Per-state field expectations
# ---------------------------------------------------------------------------

#: Disambiguation slots (free-text references the slot extractor recovers).
DISAMBIGUATION_FIELDS: tuple[str, ...] = (
    "investor_name",
    "investor_pan",
)

#: Case-detail slots collected after the investor is locked in. ``case_mode``
#: is required; the other two are optional but commonly present in the same
#: utterance (e.g. "open a rebalance proposal for Aarav").
DETAIL_FIELDS: tuple[str, ...] = (
    "case_mode",
    "case_intent",
    "proposed_action",
)


VALID_CASE_MODES: frozenset[str] = frozenset({
    "proposed_action",
    "scenario",
    "diagnostic",
    "briefing",
})


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def initial_state() -> CaseOpeningState:
    return CaseOpeningState.INVESTOR_DISAMBIGUATION


def expected_fields_for(state: CaseOpeningState) -> tuple[str, ...]:
    if state is CaseOpeningState.INVESTOR_DISAMBIGUATION:
        return DISAMBIGUATION_FIELDS
    if state is CaseOpeningState.COLLECTING_DETAILS:
        return DETAIL_FIELDS
    return ()


def has_investor_lock(slots: dict[str, Any]) -> bool:
    """An ``investor_id`` populated by the service-layer disambiguation."""
    return bool(slots.get("investor_id"))


def has_case_mode(slots: dict[str, Any]) -> bool:
    mode = slots.get("case_mode")
    return isinstance(mode, str) and mode in VALID_CASE_MODES


def has_required_details(slots: dict[str, Any]) -> bool:
    """Required = case_mode. Intent + action are optional but encouraged."""
    return has_case_mode(slots)


def next_state_after(
    current: CaseOpeningState, slots: dict[str, Any]
) -> CaseOpeningState:
    """Advance the FSM cursor based on the current slot bag."""
    if current is CaseOpeningState.INVESTOR_DISAMBIGUATION:
        if has_investor_lock(slots):
            return CaseOpeningState.COLLECTING_DETAILS
        return CaseOpeningState.INVESTOR_DISAMBIGUATION

    if current is CaseOpeningState.COLLECTING_DETAILS:
        if has_required_details(slots):
            return CaseOpeningState.AWAITING_CONFIRMATION
        return CaseOpeningState.COLLECTING_DETAILS

    # Confirmation / executing / completed / abandoned: service-driven.
    return current


# ---------------------------------------------------------------------------
# Templated prompts
# ---------------------------------------------------------------------------


def system_prompt_for(state: CaseOpeningState, slots: dict[str, Any]) -> str:
    """Produce the templated system message for the current FSM step."""
    investor_name = slots.get("investor_name") or "the client"

    if state is CaseOpeningState.INVESTOR_DISAMBIGUATION:
        return (
            "Which client is the case for? Give me a name or PAN and I'll "
            "look them up."
        )

    if state is CaseOpeningState.COLLECTING_DETAILS:
        return (
            f"Got it — case is for {investor_name}. What kind of case is "
            "this? Pick one of:\n\n"
            "  • proposed_action — a specific action you're considering "
            "(buy / sell / rebalance)\n"
            "  • scenario — a what-if exploration\n"
            "  • diagnostic — a portfolio health snapshot\n"
            "  • briefing — meeting prep\n\n"
            "If it's a proposed action, tell me what you're considering."
        )

    if state is CaseOpeningState.AWAITING_CONFIRMATION:
        return _summary_prompt(slots)

    if state is CaseOpeningState.COMPLETED:
        return (
            "Done — the case is open and gathering evidence. You'll see it "
            "appear in the case list shortly."
        )

    if state is CaseOpeningState.ABANDONED:
        return "This case-opening conversation was cancelled."

    return "How can I help?"


def _summary_prompt(slots: dict[str, Any]) -> str:
    investor_name = slots.get("investor_name") or "the client"
    case_mode = slots.get("case_mode") or "?"
    case_intent = slots.get("case_intent")
    proposed = slots.get("proposed_action")

    lines = [f"Here's the case for {investor_name}:"]
    lines.append(f"  • Mode: {case_mode}")
    if case_intent:
        lines.append(f"  • Intent: {case_intent}")
    if proposed:
        lines.append(f"  • Proposed action: {proposed}")
    lines.append("")
    lines.append("Reply 'confirm' to open the case, or 'cancel' to discard.")
    return "\n".join(lines)


__all__ = [
    "DETAIL_FIELDS",
    "DISAMBIGUATION_FIELDS",
    "VALID_CASE_MODES",
    "CaseOpeningState",
    "expected_fields_for",
    "has_case_mode",
    "has_investor_lock",
    "has_required_details",
    "initial_state",
    "next_state_after",
    "system_prompt_for",
]
