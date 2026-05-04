"""Investor-onboarding state machine — FR Entry 14.0 §2.4.

Pure-Python FSM. No LLM call lives in transition logic; the LLM is only
invoked at the *edges* (intent detection on the first message, slot
extraction on subsequent user messages). The service layer
(:mod:`artha.api_v2.c0.service`) wires the LLM client into those edges
and feeds the extracted slots back into :func:`advance`.

The FSM is intentionally tiny: cluster 1 ships exactly one intent
(``investor_onboarding``). Future intents add their own state machines
keyed off the detected intent in the dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConversationState(str, Enum):
    """The FSM cursor.

    String-valued so it round-trips cleanly to the ``state`` column on
    :class:`Conversation` (SQLite has no ENUM type; cluster 1 keeps things
    portable per the demo-stage DB addendum §1.2).
    """

    INTENT_PENDING = "STATE_INTENT_PENDING"
    COLLECTING_BASICS = "STATE_COLLECTING_BASICS"
    COLLECTING_HOUSEHOLD = "STATE_COLLECTING_HOUSEHOLD"
    COLLECTING_PROFILE = "STATE_COLLECTING_PROFILE"
    AWAITING_CONFIRMATION = "STATE_AWAITING_CONFIRMATION"
    EXECUTING = "STATE_EXECUTING"
    COMPLETED = "STATE_COMPLETED"
    ABANDONED = "STATE_ABANDONED"


# ---------------------------------------------------------------------------
# Slot definitions per state (FR 14.0 §2.4)
# ---------------------------------------------------------------------------


#: Identity fields collected in the first FSM step.
BASIC_FIELDS: tuple[str, ...] = ("name", "email", "phone", "pan", "age")

#: Household-resolution fields. Exactly one of (existing) household_id or
#: (new) household_name must end up in the slot bag before transitioning.
HOUSEHOLD_FIELDS: tuple[str, ...] = ("household_choice", "household_id", "household_name")

#: Investment-profile fields collected last before confirmation.
PROFILE_FIELDS: tuple[str, ...] = ("risk_appetite", "time_horizon")

#: Aggregate of every required field that must be in ``collected_slots``
#: by the time the FSM enters :attr:`ConversationState.AWAITING_CONFIRMATION`.
#: ``household_id`` and ``household_name`` are mutually exclusive — the
#: confirmation gate accepts either one.
ALL_REQUIRED_FIELDS: tuple[str, ...] = (
    *BASIC_FIELDS,
    *PROFILE_FIELDS,
)


@dataclass(frozen=True)
class TurnResult:
    """One :func:`advance` step's output bundle.

    Used by the service layer to drive both the persisted conversation
    update AND the system message it appends to the thread.
    """

    next_state: ConversationState
    system_message: str
    expected_fields: tuple[str, ...] = ()
    is_terminal: bool = False  # COMPLETED | ABANDONED | error states


# ---------------------------------------------------------------------------
# Transition logic
# ---------------------------------------------------------------------------


def initial_state() -> ConversationState:
    return ConversationState.INTENT_PENDING


def expected_fields_for(state: ConversationState) -> tuple[str, ...]:
    """Which fields the slot extractor should hunt for in ``state``."""
    if state is ConversationState.COLLECTING_BASICS:
        return BASIC_FIELDS
    if state is ConversationState.COLLECTING_HOUSEHOLD:
        return HOUSEHOLD_FIELDS
    if state is ConversationState.COLLECTING_PROFILE:
        return PROFILE_FIELDS
    return ()


def has_basics(slots: dict[str, Any]) -> bool:
    return all(slots.get(f) is not None for f in BASIC_FIELDS)


def has_household(slots: dict[str, Any]) -> bool:
    """Either an existing household_id or a fresh household_name."""
    return bool(slots.get("household_id")) or bool(slots.get("household_name"))


def has_profile(slots: dict[str, Any]) -> bool:
    return all(slots.get(f) is not None for f in PROFILE_FIELDS)


def all_slots_filled(slots: dict[str, Any]) -> bool:
    return has_basics(slots) and has_household(slots) and has_profile(slots)


def missing_fields(state: ConversationState, slots: dict[str, Any]) -> list[str]:
    """Return the still-missing fields the user should be prompted for."""
    if state is ConversationState.COLLECTING_BASICS:
        return [f for f in BASIC_FIELDS if slots.get(f) is None]
    if state is ConversationState.COLLECTING_HOUSEHOLD:
        if has_household(slots):
            return []
        return ["household_choice"]
    if state is ConversationState.COLLECTING_PROFILE:
        return [f for f in PROFILE_FIELDS if slots.get(f) is None]
    return []


def next_state_after(
    current: ConversationState, slots: dict[str, Any]
) -> ConversationState:
    """Compute the next FSM state given the current state + slot bag.

    Pure function — depends only on the inputs. The service layer calls
    this after applying any extracted slots so the cursor advances exactly
    when its preconditions are met.
    """
    if current is ConversationState.INTENT_PENDING:
        # Intent detection is handled by the service before invoking this.
        return ConversationState.COLLECTING_BASICS

    if current is ConversationState.COLLECTING_BASICS:
        if has_basics(slots):
            return ConversationState.COLLECTING_HOUSEHOLD
        return ConversationState.COLLECTING_BASICS

    if current is ConversationState.COLLECTING_HOUSEHOLD:
        if has_household(slots):
            return ConversationState.COLLECTING_PROFILE
        return ConversationState.COLLECTING_HOUSEHOLD

    if current is ConversationState.COLLECTING_PROFILE:
        if has_profile(slots):
            return ConversationState.AWAITING_CONFIRMATION
        return ConversationState.COLLECTING_PROFILE

    # Confirmation, executing, completed, abandoned: the service drives
    # those explicitly via dedicated transitions.
    return current


# ---------------------------------------------------------------------------
# System message generation
# ---------------------------------------------------------------------------


def system_prompt_for(
    state: ConversationState, slots: dict[str, Any]
) -> str:
    """Produce the templated system message for the current FSM step.

    These prompts are the structure that the LLM is *bounded by* (per FR
    14.0 §1: "C0 is bounded by structure but powered by an LLM"). The
    LLM never composes them; it only fills the slot values they ask for.
    """
    if state is ConversationState.COLLECTING_BASICS:
        missing = missing_fields(state, slots)
        if "name" in missing and len(missing) == len(BASIC_FIELDS):
            return (
                "Got it — let's onboard a new client. What's their full name "
                "to start?"
            )
        if not missing:
            return _summary_prompt(slots)
        # Group "email and phone" / "pan and age" naturally where possible.
        if {"email", "phone"}.issubset(missing):
            who = slots.get("name", "the client")
            return f"Thanks. What's {who}'s email address and phone number?"
        if {"pan", "age"}.issubset(missing):
            return "Got it. What's their PAN and age?"
        # Fallback: ask for the first missing field individually.
        return _single_field_prompt(missing[0])

    if state is ConversationState.COLLECTING_HOUSEHOLD:
        return (
            "Is this client part of an existing household, or should I create "
            "a new household for them? You can reply with the household name "
            "or just say 'new household' to create one."
        )

    if state is ConversationState.COLLECTING_PROFILE:
        missing = missing_fields(state, slots)
        if missing == list(PROFILE_FIELDS):
            return (
                "Almost done. How would you describe their risk appetite "
                "(aggressive, moderate, or conservative), and what's their "
                "investment time horizon (under 3 years, 3 to 5 years, or "
                "over 5 years)?"
            )
        if missing == ["risk_appetite"]:
            return "And what's their risk appetite — aggressive, moderate, or conservative?"
        if missing == ["time_horizon"]:
            return (
                "And what's their investment time horizon — under 3 years, "
                "3 to 5 years, or over 5 years?"
            )
        return _summary_prompt(slots)

    if state is ConversationState.AWAITING_CONFIRMATION:
        return _summary_prompt(slots)

    if state is ConversationState.COMPLETED:
        return (
            "Done — the investor record is created and enriched. You can "
            "view the full profile from the investor list."
        )

    if state is ConversationState.ABANDONED:
        return "This conversation was cancelled. You can start a new one any time."

    # Default: a noop prompt — should never be reached in normal flow.
    return "How can I help?"


def _single_field_prompt(field: str) -> str:
    """Friendly per-field nudge when the FSM falls back to single-field prompts.

    Shared by the happy path (single field missing in COLLECTING_BASICS) and
    by template fallback (LLM unavailable; service forces single-field mode).
    """
    return {
        "name": "What's their full name?",
        "email": "What's their email address?",
        "phone": "What's their phone number?",
        "pan": "What's their PAN? (10 characters, e.g. ABCDE1234F)",
        "age": "What's their age?",
        "risk_appetite": "Risk appetite — aggressive, moderate, or conservative?",
        "time_horizon": "Time horizon — under 3 years, 3 to 5 years, or over 5 years?",
        "household_name": "What name should I use for the new household?",
    }.get(field, f"Please tell me the {field}.")


def _summary_prompt(slots: dict[str, Any]) -> str:
    """Confirmation card text. The frontend renders the card; the message
    body is also a human-readable rollup so plain-text replays make sense."""
    lines = ["Here's what I have. Confirm and I'll create the record:"]
    for label, key in [
        ("Name", "name"),
        ("Email", "email"),
        ("Phone", "phone"),
        ("PAN", "pan"),
        ("Age", "age"),
        ("Risk appetite", "risk_appetite"),
        ("Time horizon", "time_horizon"),
    ]:
        if slots.get(key):
            lines.append(f"  • {label}: {slots[key]}")
    if slots.get("household_id"):
        lines.append(f"  • Household: existing ({slots['household_id']})")
    elif slots.get("household_name"):
        lines.append(f"  • Household: new ({slots['household_name']})")
    return "\n".join(lines)
