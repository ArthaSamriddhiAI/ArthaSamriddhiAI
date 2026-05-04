"""Mandate-creation state machine — FR Entry 14.0 Cluster 2 Revision §2.3.

Pure-Python FSM for the cluster 2 ``mandate_creation`` intent. Eight
states matching the FR's lifecycle, parallel to the cluster 1
investor_onboarding FSM in :mod:`artha.api_v2.c0.state_machine`.

Like the cluster 1 FSM, no LLM lives in transition logic. The LLM is
invoked only at the *edges*: intent detection on turn 1 and slot
extraction on subsequent turns. The state machine handles everything
else (which fields to ask for, what next prompt to render, when to
advance the cursor).

Per the FR: structured investor disambiguation (no LLM fuzzy matching);
skip-to-defaults affordance recognised by the slot extractor and acted
on here by populating remaining slots and jumping to confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MandateConversationState(str, Enum):
    """The mandate_creation FSM cursor."""

    INVESTOR_DISAMBIGUATION = "STATE_INVESTOR_DISAMBIGUATION"
    COLLECTING_ASSET_ALLOCATION = "STATE_COLLECTING_ASSET_ALLOCATION"
    COLLECTING_CONCENTRATION = "STATE_COLLECTING_CONCENTRATION"
    COLLECTING_LIQUIDITY = "STATE_COLLECTING_LIQUIDITY"
    COLLECTING_SECTOR = "STATE_COLLECTING_SECTOR"
    COLLECTING_PROHIBITED = "STATE_COLLECTING_PROHIBITED"
    AWAITING_CONFIRMATION = "STATE_AWAITING_CONFIRMATION"
    EXECUTING = "STATE_EXECUTING"
    COMPLETED = "STATE_COMPLETED"
    ABANDONED = "STATE_ABANDONED"


# ---------------------------------------------------------------------------
# Per-state expected fields
# ---------------------------------------------------------------------------


ASSET_ALLOCATION_FIELDS: tuple[str, ...] = (
    "equity_min_pct", "equity_max_pct",
    "debt_min_pct", "debt_max_pct",
    "alternatives_min_pct", "alternatives_max_pct",
)

CONCENTRATION_FIELDS: tuple[str, ...] = ("single_position_max_pct",)
LIQUIDITY_FIELDS: tuple[str, ...] = ("liquidity_floor_pct",)
SECTOR_FIELDS: tuple[str, ...] = ("sector_max_pct",)
PROHIBITED_FIELDS: tuple[str, ...] = ("prohibited_instruments",)

# Disambiguation slots; the service layer fills these after structured
# lookup against the advisor's investor book (no LLM fuzzy matching, per
# FR Entry 14.0 cluster 2 revision §2.5).
DISAMBIGUATION_FIELDS: tuple[str, ...] = ("investor_id", "investor_name", "investor_pan")


# ---------------------------------------------------------------------------
# Transition logic
# ---------------------------------------------------------------------------


def initial_state() -> MandateConversationState:
    return MandateConversationState.INVESTOR_DISAMBIGUATION


def expected_fields_for(state: MandateConversationState) -> tuple[str, ...]:
    """Which fields the slot extractor should hunt for in ``state``."""
    if state is MandateConversationState.INVESTOR_DISAMBIGUATION:
        # The advisor's reply may either name an investor (free text) or
        # confirm a specific candidate from the disambiguation list (the
        # service handles both); the slot extractor tries the name/pan
        # fields plus the use_defaults affordance.
        return ("investor_name", "investor_pan", "use_defaults")
    if state is MandateConversationState.COLLECTING_ASSET_ALLOCATION:
        return ASSET_ALLOCATION_FIELDS + ("use_defaults",)
    if state is MandateConversationState.COLLECTING_CONCENTRATION:
        return CONCENTRATION_FIELDS + ("use_defaults",)
    if state is MandateConversationState.COLLECTING_LIQUIDITY:
        return LIQUIDITY_FIELDS + ("use_defaults",)
    if state is MandateConversationState.COLLECTING_SECTOR:
        return SECTOR_FIELDS + ("use_defaults",)
    if state is MandateConversationState.COLLECTING_PROHIBITED:
        return PROHIBITED_FIELDS + ("use_defaults",)
    return ()


def has_asset_allocation(slots: dict[str, Any]) -> bool:
    return all(slots.get(f) is not None for f in ASSET_ALLOCATION_FIELDS)


def has_concentration(slots: dict[str, Any]) -> bool:
    return slots.get("single_position_max_pct") is not None


def has_liquidity(slots: dict[str, Any]) -> bool:
    return slots.get("liquidity_floor_pct") is not None


def has_sector(slots: dict[str, Any]) -> bool:
    return slots.get("sector_max_pct") is not None


def has_prohibited(slots: dict[str, Any]) -> bool:
    """Prohibited list is "filled" once the user has explicitly responded.

    The service layer stamps ``prohibited_instruments_collected: True`` once
    the user replies to the prompt (with a list, "none", etc.). Empty list
    is a valid value, so we don't gate on truthiness of the list itself.
    """
    return bool(slots.get("prohibited_instruments_collected"))


def all_constraints_filled(slots: dict[str, Any]) -> bool:
    return (
        has_asset_allocation(slots)
        and has_concentration(slots)
        and has_liquidity(slots)
        and has_sector(slots)
        and has_prohibited(slots)
    )


def next_state_after(
    current: MandateConversationState, slots: dict[str, Any]
) -> MandateConversationState:
    """Compute the next FSM state given the current state + slot bag."""
    if current is MandateConversationState.INVESTOR_DISAMBIGUATION:
        # The service drives this transition explicitly once it locks in
        # an investor_id (single match confirmed, or list selection made).
        if slots.get("investor_id"):
            return MandateConversationState.COLLECTING_ASSET_ALLOCATION
        return MandateConversationState.INVESTOR_DISAMBIGUATION

    if current is MandateConversationState.COLLECTING_ASSET_ALLOCATION:
        if has_asset_allocation(slots):
            return MandateConversationState.COLLECTING_CONCENTRATION
        return current

    if current is MandateConversationState.COLLECTING_CONCENTRATION:
        if has_concentration(slots):
            return MandateConversationState.COLLECTING_LIQUIDITY
        return current

    if current is MandateConversationState.COLLECTING_LIQUIDITY:
        if has_liquidity(slots):
            return MandateConversationState.COLLECTING_SECTOR
        return current

    if current is MandateConversationState.COLLECTING_SECTOR:
        if has_sector(slots):
            return MandateConversationState.COLLECTING_PROHIBITED
        return current

    if current is MandateConversationState.COLLECTING_PROHIBITED:
        if has_prohibited(slots):
            return MandateConversationState.AWAITING_CONFIRMATION
        return current

    # Confirmation, executing, completed, abandoned: service-driven.
    return current


# ---------------------------------------------------------------------------
# Skip-to-defaults affordance (FR Entry 14.0 Cluster 2 Revision §2.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkipToDefaultsResult:
    """The payload the service applies when the slot extractor signals
    ``use_defaults: true``."""

    next_state: MandateConversationState
    slot_updates: dict[str, Any]


def apply_skip_to_defaults(
    *,
    current: MandateConversationState,
    defaults: dict[str, Any],
    existing_slots: dict[str, Any],
) -> SkipToDefaultsResult:
    """Fill unfilled slots from defaults and jump to confirmation.

    ``defaults`` is the M1-computed default bundle (from the investor's
    I0 enrichment + industry-standard defaults). Cluster 1 chunk 1.3
    promised this for chunk 2.2; this is the realised affordance.

    Existing slot values are preserved — the advisor only fills *remaining*
    fields with defaults, not overwrites already-customised values.
    """
    slot_updates: dict[str, Any] = {}
    for field in (
        *ASSET_ALLOCATION_FIELDS,
        *CONCENTRATION_FIELDS,
        *LIQUIDITY_FIELDS,
        *SECTOR_FIELDS,
    ):
        if existing_slots.get(field) is None and field in defaults:
            slot_updates[field] = defaults[field]
    if existing_slots.get("prohibited_instruments") is None:
        slot_updates["prohibited_instruments"] = list(
            defaults.get("prohibited_instruments", [])
        )
    slot_updates["prohibited_instruments_collected"] = True
    return SkipToDefaultsResult(
        next_state=MandateConversationState.AWAITING_CONFIRMATION,
        slot_updates=slot_updates,
    )


# ---------------------------------------------------------------------------
# Templated prompts per state
# ---------------------------------------------------------------------------


def system_prompt_for(
    state: MandateConversationState, slots: dict[str, Any]
) -> str:
    """Produce the templated system message for the current FSM step.

    Like cluster 1's investor onboarding prompts, these are bounded by
    the structure the FSM defines; the LLM never composes them, only
    fills the slot values they ask for.
    """
    investor_name = slots.get("investor_name") or "the client"

    if state is MandateConversationState.INVESTOR_DISAMBIGUATION:
        return (
            "Which client is the mandate for? Tell me their name or PAN, and "
            "I'll look them up."
        )

    if state is MandateConversationState.COLLECTING_ASSET_ALLOCATION:
        return (
            f"Let's start with asset allocation for {investor_name}. What "
            "should the equity, debt, and alternatives ranges be? You can "
            "say 'use defaults' to apply I0-suggested values."
        )

    if state is MandateConversationState.COLLECTING_CONCENTRATION:
        return (
            f"What's the maximum percentage of {investor_name}'s portfolio "
            "in any single instrument? (Industry standard: 5%.)"
        )

    if state is MandateConversationState.COLLECTING_LIQUIDITY:
        return (
            f"What liquidity floor for {investor_name}? Minimum percentage "
            "of the portfolio in highly liquid instruments. I0's suggestion "
            "is shown alongside this prompt in the chat."
        )

    if state is MandateConversationState.COLLECTING_SECTOR:
        return (
            "What's the maximum percentage in any single GICS sector? "
            "(Industry standard: 25%.)"
        )

    if state is MandateConversationState.COLLECTING_PROHIBITED:
        return (
            "Any prohibited instruments to exclude? List specific tickers, "
            "categories, or themes (e.g. 'tobacco stocks', 'fossil fuels'). "
            "Reply 'none' if there are no exclusions."
        )

    if state is MandateConversationState.AWAITING_CONFIRMATION:
        return _summary_prompt(slots)

    if state is MandateConversationState.COMPLETED:
        return (
            "Done — the mandate is created and active. You can view it from "
            "the investor's profile."
        )

    if state is MandateConversationState.ABANDONED:
        return "This conversation was cancelled. You can start a new one any time."

    return "How can I help?"


def _summary_prompt(slots: dict[str, Any]) -> str:
    """Confirmation card text mirroring the form path's summary."""
    lines = [
        f"Here's the mandate for {slots.get('investor_name') or 'the client'}:",
    ]
    if slots.get("equity_min_pct") is not None:
        lines.append(
            f"  • Equity: {slots['equity_min_pct']}-{slots['equity_max_pct']}%"
        )
    if slots.get("debt_min_pct") is not None:
        lines.append(
            f"  • Debt: {slots['debt_min_pct']}-{slots['debt_max_pct']}%"
        )
    if slots.get("alternatives_min_pct") is not None:
        lines.append(
            f"  • Alternatives: {slots['alternatives_min_pct']}"
            f"-{slots['alternatives_max_pct']}%"
        )
    if slots.get("single_position_max_pct") is not None:
        lines.append(f"  • Single-position max: {slots['single_position_max_pct']}%")
    if slots.get("liquidity_floor_pct") is not None:
        lines.append(f"  • Liquidity floor: {slots['liquidity_floor_pct']}%")
    if slots.get("sector_max_pct") is not None:
        lines.append(f"  • Sector cap: {slots['sector_max_pct']}%")
    prohibited = slots.get("prohibited_instruments") or []
    if prohibited:
        lines.append(f"  • Prohibited: {', '.join(prohibited)}")
    else:
        lines.append("  • Prohibited: none")
    lines.append("")
    lines.append("Reply 'yes' to create the mandate or 'cancel' to abort.")
    return "\n".join(lines)
