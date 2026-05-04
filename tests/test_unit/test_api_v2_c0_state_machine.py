"""Cluster 1 chunk 1.2 — pure-FSM test suite.

The state machine in :mod:`artha.api_v2.c0.state_machine` is a small
deterministic FSM with no LLM dependency. These tests pin its transition
behaviour, slot-completion gates, and templated prompt selection so any
later refactor that breaks the contract trips loudly.
"""

from __future__ import annotations

import pytest

from artha.api_v2.c0 import state_machine as sm
from artha.api_v2.c0.state_machine import ConversationState


class TestExpectedFields:
    @pytest.mark.parametrize(
        "state,expected",
        [
            (ConversationState.COLLECTING_BASICS, sm.BASIC_FIELDS),
            (ConversationState.COLLECTING_HOUSEHOLD, sm.HOUSEHOLD_FIELDS),
            (ConversationState.COLLECTING_PROFILE, sm.PROFILE_FIELDS),
        ],
    )
    def test_per_state_field_sets(self, state, expected):
        assert sm.expected_fields_for(state) == expected

    @pytest.mark.parametrize(
        "state",
        [
            ConversationState.INTENT_PENDING,
            ConversationState.AWAITING_CONFIRMATION,
            ConversationState.EXECUTING,
            ConversationState.COMPLETED,
            ConversationState.ABANDONED,
        ],
    )
    def test_terminal_or_meta_states_expect_no_fields(self, state):
        assert sm.expected_fields_for(state) == ()


class TestSlotGates:
    def test_basics_complete(self):
        slots = {"name": "X", "email": "x@example.com", "phone": "+91", "pan": "Y", "age": 30}
        assert sm.has_basics(slots)

    def test_basics_partial_returns_false(self):
        slots = {"name": "X", "email": "x@example.com"}
        assert not sm.has_basics(slots)

    def test_household_existing_id_satisfies(self):
        assert sm.has_household({"household_id": "01ABC"})

    def test_household_new_name_satisfies(self):
        assert sm.has_household({"household_name": "Mehta"})

    def test_household_neither_fails(self):
        assert not sm.has_household({})

    def test_profile_complete(self):
        assert sm.has_profile(
            {"risk_appetite": "moderate", "time_horizon": "over_5_years"}
        )

    def test_all_slots_filled_requires_basics_household_profile(self):
        assert not sm.all_slots_filled({})
        full = {
            "name": "Anjali Mehta",
            "email": "a@example.com",
            "phone": "+919876543210",
            "pan": "ABCDE1234F",
            "age": 30,
            "household_name": "Mehta Household",
            "risk_appetite": "moderate",
            "time_horizon": "over_5_years",
        }
        assert sm.all_slots_filled(full)


class TestMissingFields:
    def test_basics_missing_lists_unfilled(self):
        slots = {"name": "X", "age": 30}
        missing = sm.missing_fields(ConversationState.COLLECTING_BASICS, slots)
        assert "email" in missing
        assert "phone" in missing
        assert "pan" in missing

    def test_household_missing_when_neither_set(self):
        missing = sm.missing_fields(ConversationState.COLLECTING_HOUSEHOLD, {})
        assert missing == ["household_choice"]

    def test_household_missing_empty_when_id_set(self):
        missing = sm.missing_fields(
            ConversationState.COLLECTING_HOUSEHOLD,
            {"household_id": "01ABC"},
        )
        assert missing == []

    def test_profile_missing_lists_unfilled(self):
        missing = sm.missing_fields(
            ConversationState.COLLECTING_PROFILE,
            {"risk_appetite": "moderate"},
        )
        assert missing == ["time_horizon"]


class TestStateTransitions:
    def test_intent_pending_advances_to_collecting_basics(self):
        assert (
            sm.next_state_after(ConversationState.INTENT_PENDING, {})
            is ConversationState.COLLECTING_BASICS
        )

    def test_basics_advances_to_household_when_complete(self):
        slots = {
            "name": "X",
            "email": "x@example.com",
            "phone": "+91",
            "pan": "Y",
            "age": 30,
        }
        assert (
            sm.next_state_after(ConversationState.COLLECTING_BASICS, slots)
            is ConversationState.COLLECTING_HOUSEHOLD
        )

    def test_basics_holds_when_incomplete(self):
        assert (
            sm.next_state_after(
                ConversationState.COLLECTING_BASICS, {"name": "X"}
            )
            is ConversationState.COLLECTING_BASICS
        )

    def test_household_advances_to_profile_when_existing(self):
        assert (
            sm.next_state_after(
                ConversationState.COLLECTING_HOUSEHOLD, {"household_id": "01ABC"}
            )
            is ConversationState.COLLECTING_PROFILE
        )

    def test_household_advances_to_profile_when_new(self):
        assert (
            sm.next_state_after(
                ConversationState.COLLECTING_HOUSEHOLD,
                {"household_name": "Mehta Household"},
            )
            is ConversationState.COLLECTING_PROFILE
        )

    def test_household_holds_when_unset(self):
        assert (
            sm.next_state_after(ConversationState.COLLECTING_HOUSEHOLD, {})
            is ConversationState.COLLECTING_HOUSEHOLD
        )

    def test_profile_advances_to_confirmation_when_complete(self):
        slots = {"risk_appetite": "moderate", "time_horizon": "over_5_years"}
        assert (
            sm.next_state_after(ConversationState.COLLECTING_PROFILE, slots)
            is ConversationState.AWAITING_CONFIRMATION
        )

    def test_profile_holds_when_partial(self):
        slots = {"risk_appetite": "moderate"}
        assert (
            sm.next_state_after(ConversationState.COLLECTING_PROFILE, slots)
            is ConversationState.COLLECTING_PROFILE
        )

    def test_terminal_states_dont_self_advance(self):
        for state in (
            ConversationState.AWAITING_CONFIRMATION,
            ConversationState.EXECUTING,
            ConversationState.COMPLETED,
            ConversationState.ABANDONED,
        ):
            assert sm.next_state_after(state, {}) is state


class TestSystemPrompts:
    def test_collecting_basics_with_no_slots_asks_for_name(self):
        prompt = sm.system_prompt_for(ConversationState.COLLECTING_BASICS, {})
        assert "name" in prompt.lower() or "client" in prompt.lower()

    def test_collecting_basics_groups_email_phone(self):
        slots = {"name": "Anjali Mehta", "age": 30}
        prompt = sm.system_prompt_for(ConversationState.COLLECTING_BASICS, slots)
        assert "email" in prompt.lower() and "phone" in prompt.lower()

    def test_collecting_basics_groups_pan_and_age(self):
        slots = {"name": "X", "email": "x@example.com", "phone": "+91"}
        prompt = sm.system_prompt_for(ConversationState.COLLECTING_BASICS, slots)
        assert "pan" in prompt.lower() and "age" in prompt.lower()

    def test_collecting_household_asks_existing_or_new(self):
        prompt = sm.system_prompt_for(ConversationState.COLLECTING_HOUSEHOLD, {})
        assert "household" in prompt.lower()

    def test_collecting_profile_groups_risk_and_horizon(self):
        prompt = sm.system_prompt_for(ConversationState.COLLECTING_PROFILE, {})
        assert "risk" in prompt.lower() and "horizon" in prompt.lower()

    def test_summary_lists_filled_slots(self):
        slots = {
            "name": "Anjali Mehta",
            "email": "a@example.com",
            "phone": "+919876543210",
            "pan": "ABCDE1234F",
            "age": 30,
            "household_name": "Mehta",
            "risk_appetite": "moderate",
            "time_horizon": "over_5_years",
        }
        prompt = sm.system_prompt_for(ConversationState.AWAITING_CONFIRMATION, slots)
        for value in ("Anjali Mehta", "ABCDE1234F", "moderate", "over_5_years"):
            assert value in prompt

    def test_completed_state_has_friendly_prompt(self):
        prompt = sm.system_prompt_for(ConversationState.COMPLETED, {})
        assert "investor" in prompt.lower() or "done" in prompt.lower()

    def test_abandoned_state_says_cancelled(self):
        prompt = sm.system_prompt_for(ConversationState.ABANDONED, {})
        assert "cancel" in prompt.lower()
