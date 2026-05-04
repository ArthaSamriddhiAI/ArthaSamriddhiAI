"""Cluster 2 chunk 2.2 — mandate-FSM pure-function test suite.

Pins FR Entry 14.0 Cluster 2 Revision §2.3 transitions + §2.4 skip-to-
defaults affordance. The FSM is pure Python — no DB, no LLM — so these
tests run in microseconds and lock the contract that the C0 service
depends on.
"""

from __future__ import annotations

import pytest

from artha.api_v2.c0 import mandate_state_machine as msm
from artha.api_v2.c0.mandate_state_machine import MandateConversationState


class TestExpectedFields:
    @pytest.mark.parametrize(
        "state,must_contain",
        [
            (MandateConversationState.INVESTOR_DISAMBIGUATION, "investor_name"),
            (MandateConversationState.COLLECTING_ASSET_ALLOCATION, "equity_min_pct"),
            (MandateConversationState.COLLECTING_CONCENTRATION, "single_position_max_pct"),
            (MandateConversationState.COLLECTING_LIQUIDITY, "liquidity_floor_pct"),
            (MandateConversationState.COLLECTING_SECTOR, "sector_max_pct"),
            (MandateConversationState.COLLECTING_PROHIBITED, "prohibited_instruments"),
        ],
    )
    def test_state_expects_relevant_fields(self, state, must_contain):
        assert must_contain in msm.expected_fields_for(state)

    def test_use_defaults_in_every_collection_state(self):
        for state in (
            MandateConversationState.COLLECTING_ASSET_ALLOCATION,
            MandateConversationState.COLLECTING_CONCENTRATION,
            MandateConversationState.COLLECTING_LIQUIDITY,
            MandateConversationState.COLLECTING_SECTOR,
            MandateConversationState.COLLECTING_PROHIBITED,
        ):
            assert "use_defaults" in msm.expected_fields_for(state)

    @pytest.mark.parametrize(
        "state",
        [
            MandateConversationState.AWAITING_CONFIRMATION,
            MandateConversationState.EXECUTING,
            MandateConversationState.COMPLETED,
            MandateConversationState.ABANDONED,
        ],
    )
    def test_terminal_states_expect_no_fields(self, state):
        assert msm.expected_fields_for(state) == ()


class TestSlotGates:
    def test_asset_allocation_complete(self):
        slots = {
            "equity_min_pct": 50, "equity_max_pct": 70,
            "debt_min_pct": 20, "debt_max_pct": 40,
            "alternatives_min_pct": 5, "alternatives_max_pct": 15,
        }
        assert msm.has_asset_allocation(slots) is True

    def test_asset_allocation_partial_fails(self):
        slots = {"equity_min_pct": 50, "equity_max_pct": 70}
        assert msm.has_asset_allocation(slots) is False

    def test_prohibited_marked_complete_via_collected_flag(self):
        # Empty list is valid — the user said "none". The FSM gates on
        # the collected_flag, not list truthiness.
        assert msm.has_prohibited({"prohibited_instruments_collected": True}) is True

    def test_prohibited_with_list_only_not_complete_until_flag_set(self):
        assert msm.has_prohibited(
            {"prohibited_instruments": ["tobacco"]}
        ) is False

    def test_all_constraints_filled_requires_all_five_families(self):
        slots = {
            "equity_min_pct": 50, "equity_max_pct": 70,
            "debt_min_pct": 20, "debt_max_pct": 40,
            "alternatives_min_pct": 5, "alternatives_max_pct": 15,
            "single_position_max_pct": 5,
            "liquidity_floor_pct": 20,
            "sector_max_pct": 25,
            "prohibited_instruments_collected": True,
        }
        assert msm.all_constraints_filled(slots) is True


class TestStateTransitions:
    def test_disambiguation_advances_when_investor_id_set(self):
        assert (
            msm.next_state_after(
                MandateConversationState.INVESTOR_DISAMBIGUATION,
                {"investor_id": "01ABC"},
            )
            is MandateConversationState.COLLECTING_ASSET_ALLOCATION
        )

    def test_disambiguation_holds_when_no_investor_id(self):
        assert (
            msm.next_state_after(
                MandateConversationState.INVESTOR_DISAMBIGUATION, {}
            )
            is MandateConversationState.INVESTOR_DISAMBIGUATION
        )

    def test_asset_allocation_advances_when_complete(self):
        slots = {
            "equity_min_pct": 50, "equity_max_pct": 70,
            "debt_min_pct": 20, "debt_max_pct": 40,
            "alternatives_min_pct": 5, "alternatives_max_pct": 15,
        }
        assert (
            msm.next_state_after(
                MandateConversationState.COLLECTING_ASSET_ALLOCATION, slots
            )
            is MandateConversationState.COLLECTING_CONCENTRATION
        )

    def test_concentration_to_liquidity(self):
        assert (
            msm.next_state_after(
                MandateConversationState.COLLECTING_CONCENTRATION,
                {"single_position_max_pct": 5},
            )
            is MandateConversationState.COLLECTING_LIQUIDITY
        )

    def test_liquidity_to_sector(self):
        assert (
            msm.next_state_after(
                MandateConversationState.COLLECTING_LIQUIDITY,
                {"liquidity_floor_pct": 20},
            )
            is MandateConversationState.COLLECTING_SECTOR
        )

    def test_sector_to_prohibited(self):
        assert (
            msm.next_state_after(
                MandateConversationState.COLLECTING_SECTOR,
                {"sector_max_pct": 25},
            )
            is MandateConversationState.COLLECTING_PROHIBITED
        )

    def test_prohibited_to_confirmation(self):
        assert (
            msm.next_state_after(
                MandateConversationState.COLLECTING_PROHIBITED,
                {"prohibited_instruments_collected": True},
            )
            is MandateConversationState.AWAITING_CONFIRMATION
        )

    def test_prohibited_holds_until_collected_flag(self):
        assert (
            msm.next_state_after(
                MandateConversationState.COLLECTING_PROHIBITED,
                {"prohibited_instruments": ["tobacco"]},
            )
            is MandateConversationState.COLLECTING_PROHIBITED
        )

    def test_terminal_states_dont_self_advance(self):
        for state in (
            MandateConversationState.AWAITING_CONFIRMATION,
            MandateConversationState.EXECUTING,
            MandateConversationState.COMPLETED,
            MandateConversationState.ABANDONED,
        ):
            assert msm.next_state_after(state, {}) is state


class TestSkipToDefaults:
    def test_fills_unfilled_slots_from_defaults(self):
        defaults = {
            "equity_min_pct": 50, "equity_max_pct": 70,
            "debt_min_pct": 20, "debt_max_pct": 40,
            "alternatives_min_pct": 5, "alternatives_max_pct": 15,
            "single_position_max_pct": 5,
            "liquidity_floor_pct": 20,
            "sector_max_pct": 25,
            "prohibited_instruments": [],
        }
        result = msm.apply_skip_to_defaults(
            current=MandateConversationState.COLLECTING_ASSET_ALLOCATION,
            defaults=defaults,
            existing_slots={},
        )
        assert result.next_state is MandateConversationState.AWAITING_CONFIRMATION
        assert result.slot_updates["equity_min_pct"] == 50
        assert result.slot_updates["liquidity_floor_pct"] == 20
        assert result.slot_updates["prohibited_instruments_collected"] is True

    def test_preserves_already_customised_values(self):
        defaults = {
            "equity_min_pct": 50, "equity_max_pct": 70,
            "debt_min_pct": 20, "debt_max_pct": 40,
            "alternatives_min_pct": 5, "alternatives_max_pct": 15,
            "single_position_max_pct": 5,
            "liquidity_floor_pct": 20,
            "sector_max_pct": 25,
            "prohibited_instruments": [],
        }
        existing = {"equity_min_pct": 40, "equity_max_pct": 80}
        result = msm.apply_skip_to_defaults(
            current=MandateConversationState.COLLECTING_LIQUIDITY,
            defaults=defaults,
            existing_slots=existing,
        )
        # equity_min_pct already customised — not overwritten by defaults.
        assert "equity_min_pct" not in result.slot_updates
        # liquidity_floor_pct unfilled — picked up from defaults.
        assert result.slot_updates["liquidity_floor_pct"] == 20


class TestSystemPrompts:
    def test_disambiguation_asks_for_name_or_pan(self):
        prompt = msm.system_prompt_for(
            MandateConversationState.INVESTOR_DISAMBIGUATION, {}
        )
        assert "name" in prompt.lower() or "pan" in prompt.lower()

    def test_asset_allocation_uses_investor_name(self):
        prompt = msm.system_prompt_for(
            MandateConversationState.COLLECTING_ASSET_ALLOCATION,
            {"investor_name": "Rajesh Kumar"},
        )
        assert "Rajesh Kumar" in prompt

    def test_summary_includes_all_constraint_families(self):
        slots = {
            "investor_name": "Rajesh Kumar",
            "equity_min_pct": 70, "equity_max_pct": 90,
            "debt_min_pct": 5, "debt_max_pct": 25,
            "alternatives_min_pct": 5, "alternatives_max_pct": 15,
            "single_position_max_pct": 5,
            "liquidity_floor_pct": 10,
            "sector_max_pct": 25,
            "prohibited_instruments": ["tobacco stocks"],
        }
        prompt = msm.system_prompt_for(
            MandateConversationState.AWAITING_CONFIRMATION, slots
        )
        for fragment in (
            "Rajesh Kumar", "70-90", "5-25", "5-15",
            "5%", "10%", "25%", "tobacco stocks",
        ):
            assert fragment in prompt
