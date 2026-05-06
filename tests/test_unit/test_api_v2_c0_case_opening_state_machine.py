"""Cluster 5 chunk 5.3 — C0 case_opening FSM tests.

Pins the minimal 3-state pipeline:

- INVESTOR_DISAMBIGUATION → COLLECTING_DETAILS (after investor_id locked)
- COLLECTING_DETAILS → AWAITING_CONFIRMATION (after case_mode collected)
- terminal states (EXECUTING / COMPLETED / ABANDONED) are service-driven.
"""

from __future__ import annotations

import pytest

from artha.api_v2.c0 import case_opening_state_machine as fsm
from artha.api_v2.c0.case_opening_state_machine import CaseOpeningState


class TestInitial:
    def test_initial_is_disambiguation(self) -> None:
        assert fsm.initial_state() is CaseOpeningState.INVESTOR_DISAMBIGUATION


class TestExpectedFields:
    def test_disambiguation_fields(self) -> None:
        assert fsm.expected_fields_for(
            CaseOpeningState.INVESTOR_DISAMBIGUATION,
        ) == ("investor_name", "investor_pan")

    def test_details_fields(self) -> None:
        assert fsm.expected_fields_for(
            CaseOpeningState.COLLECTING_DETAILS,
        ) == ("case_mode", "case_intent", "proposed_action")

    @pytest.mark.parametrize(
        "state",
        [
            CaseOpeningState.AWAITING_CONFIRMATION,
            CaseOpeningState.EXECUTING,
            CaseOpeningState.COMPLETED,
            CaseOpeningState.ABANDONED,
        ],
    )
    def test_terminal_states_have_no_fields(self, state) -> None:
        assert fsm.expected_fields_for(state) == ()


class TestSlotPredicates:
    def test_investor_lock_requires_id(self) -> None:
        assert not fsm.has_investor_lock({})
        assert fsm.has_investor_lock({"investor_id": "X"})

    def test_case_mode_must_be_known(self) -> None:
        assert not fsm.has_case_mode({"case_mode": "weird"})
        for mode in (
            "proposed_action",
            "scenario",
            "diagnostic",
            "briefing",
        ):
            assert fsm.has_case_mode({"case_mode": mode})

    def test_required_details_only_needs_mode(self) -> None:
        assert not fsm.has_required_details({})
        assert fsm.has_required_details({"case_mode": "diagnostic"})


class TestNextState:
    def test_disambiguation_advances_when_id_present(self) -> None:
        assert (
            fsm.next_state_after(
                CaseOpeningState.INVESTOR_DISAMBIGUATION,
                {"investor_id": "X"},
            )
            is CaseOpeningState.COLLECTING_DETAILS
        )

    def test_disambiguation_stays_without_id(self) -> None:
        assert (
            fsm.next_state_after(
                CaseOpeningState.INVESTOR_DISAMBIGUATION,
                {},
            )
            is CaseOpeningState.INVESTOR_DISAMBIGUATION
        )

    def test_details_advances_after_mode(self) -> None:
        assert (
            fsm.next_state_after(
                CaseOpeningState.COLLECTING_DETAILS,
                {"investor_id": "X", "case_mode": "diagnostic"},
            )
            is CaseOpeningState.AWAITING_CONFIRMATION
        )

    def test_details_stays_without_mode(self) -> None:
        assert (
            fsm.next_state_after(
                CaseOpeningState.COLLECTING_DETAILS,
                {"investor_id": "X"},
            )
            is CaseOpeningState.COLLECTING_DETAILS
        )

    @pytest.mark.parametrize(
        "state",
        [
            CaseOpeningState.AWAITING_CONFIRMATION,
            CaseOpeningState.EXECUTING,
            CaseOpeningState.COMPLETED,
            CaseOpeningState.ABANDONED,
        ],
    )
    def test_terminal_states_unchanged_by_fsm(self, state) -> None:
        assert fsm.next_state_after(state, {}) is state


class TestPrompts:
    def test_disambiguation_prompt_asks_for_name_or_pan(self) -> None:
        prompt = fsm.system_prompt_for(
            CaseOpeningState.INVESTOR_DISAMBIGUATION,
            {},
        )
        assert "name or PAN" in prompt.lower() or "name" in prompt.lower()

    def test_details_prompt_lists_modes(self) -> None:
        prompt = fsm.system_prompt_for(
            CaseOpeningState.COLLECTING_DETAILS,
            {"investor_name": "Aarav"},
        )
        assert "Aarav" in prompt
        assert "proposed_action" in prompt
        assert "diagnostic" in prompt
        assert "briefing" in prompt

    def test_confirmation_prompt_includes_summary(self) -> None:
        prompt = fsm.system_prompt_for(
            CaseOpeningState.AWAITING_CONFIRMATION,
            {
                "investor_name": "Aarav",
                "case_mode": "diagnostic",
                "case_intent": "portfolio_health",
            },
        )
        assert "Aarav" in prompt
        assert "diagnostic" in prompt
        assert "portfolio_health" in prompt
        assert "confirm" in prompt.lower()
