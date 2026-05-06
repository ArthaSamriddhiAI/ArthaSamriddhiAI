"""Cluster 5 chunk 5.1 — case status state machine tests.

Pins FR Entry 20.1 §1.5 transition table + §1.4 mode-specific pipeline
shapes + universal escapes (failed / archived).
"""

from __future__ import annotations

import pytest

from artha.api_v2.cases.state_machine import (
    CaseMode,
    CaseStatus,
    InvalidStateTransitionError,
    expected_pipeline_for_mode,
    is_terminal,
    validate_transition,
)

# ---------------------------------------------------------------------------
# Happy-path transitions per FR 20.1 §1.5
# ---------------------------------------------------------------------------


class TestHappyPathTransitions:
    @pytest.mark.parametrize(
        "from_state,to_state,mode",
        [
            (CaseStatus.OPENING, CaseStatus.GATHERING_EVIDENCE, CaseMode.PROPOSED_ACTION),
            (CaseStatus.OPENING, CaseStatus.GATHERING_EVIDENCE, CaseMode.DIAGNOSTIC),
            (CaseStatus.GATHERING_EVIDENCE, CaseStatus.SYNTHESIZING, CaseMode.PROPOSED_ACTION),
            # case mode: synthesizing → awaiting_committee (material)
            (CaseStatus.SYNTHESIZING, CaseStatus.AWAITING_COMMITTEE, CaseMode.PROPOSED_ACTION),
            (CaseStatus.SYNTHESIZING, CaseStatus.AWAITING_COMMITTEE, CaseMode.SCENARIO),
            # case mode: synthesizing → awaiting_governance (non-material)
            (CaseStatus.SYNTHESIZING, CaseStatus.AWAITING_GOVERNANCE, CaseMode.PROPOSED_ACTION),
            # diagnostic: synthesizing → awaiting_governance
            (CaseStatus.SYNTHESIZING, CaseStatus.AWAITING_GOVERNANCE, CaseMode.DIAGNOSTIC),
            # briefing: synthesizing → decided (skips governance)
            (CaseStatus.SYNTHESIZING, CaseStatus.DECIDED, CaseMode.BRIEFING),
            # case mode: awaiting_governance → awaiting_challenge
            (
                CaseStatus.AWAITING_GOVERNANCE,
                CaseStatus.AWAITING_CHALLENGE,
                CaseMode.PROPOSED_ACTION,
            ),
            # diagnostic: awaiting_governance → decided
            (CaseStatus.AWAITING_GOVERNANCE, CaseStatus.DECIDED, CaseMode.DIAGNOSTIC),
            # case mode: awaiting_committee → awaiting_governance
            (
                CaseStatus.AWAITING_COMMITTEE,
                CaseStatus.AWAITING_GOVERNANCE,
                CaseMode.PROPOSED_ACTION,
            ),
            # case mode: awaiting_challenge → awaiting_decision
            (
                CaseStatus.AWAITING_CHALLENGE,
                CaseStatus.AWAITING_DECISION,
                CaseMode.PROPOSED_ACTION,
            ),
            # case mode: awaiting_decision → decided
            (CaseStatus.AWAITING_DECISION, CaseStatus.DECIDED, CaseMode.PROPOSED_ACTION),
        ],
    )
    def test_valid_transitions_accepted(self, from_state, to_state, mode):
        out = validate_transition(
            from_state=from_state, to_state=to_state, case_mode=mode,
        )
        assert out == to_state


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    def test_skipping_states_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(
                from_state=CaseStatus.OPENING,
                to_state=CaseStatus.AWAITING_DECISION,
                case_mode=CaseMode.PROPOSED_ACTION,
            )

    def test_no_op_transition_raises(self):
        with pytest.raises(InvalidStateTransitionError, match="No-op"):
            validate_transition(
                from_state=CaseStatus.OPENING,
                to_state=CaseStatus.OPENING,
                case_mode=CaseMode.PROPOSED_ACTION,
            )

    def test_terminal_states_have_no_outbound(self):
        for terminal in (
            CaseStatus.DECIDED,
            CaseStatus.ARCHIVED,
            CaseStatus.FAILED,
        ):
            with pytest.raises(InvalidStateTransitionError):
                validate_transition(
                    from_state=terminal,
                    to_state=CaseStatus.OPENING,
                    case_mode=CaseMode.PROPOSED_ACTION,
                )


# ---------------------------------------------------------------------------
# Mode-aware guards
# ---------------------------------------------------------------------------


class TestModeGuards:
    def test_synthesizing_to_decided_only_briefing(self):
        # briefing OK
        validate_transition(
            from_state=CaseStatus.SYNTHESIZING,
            to_state=CaseStatus.DECIDED,
            case_mode=CaseMode.BRIEFING,
        )
        # diagnostic NOT ok — must transit awaiting_governance
        with pytest.raises(InvalidStateTransitionError, match="briefing"):
            validate_transition(
                from_state=CaseStatus.SYNTHESIZING,
                to_state=CaseStatus.DECIDED,
                case_mode=CaseMode.DIAGNOSTIC,
            )
        # proposed_action NOT ok
        with pytest.raises(InvalidStateTransitionError, match="briefing"):
            validate_transition(
                from_state=CaseStatus.SYNTHESIZING,
                to_state=CaseStatus.DECIDED,
                case_mode=CaseMode.PROPOSED_ACTION,
            )

    def test_governance_to_decided_only_diagnostic(self):
        # diagnostic OK
        validate_transition(
            from_state=CaseStatus.AWAITING_GOVERNANCE,
            to_state=CaseStatus.DECIDED,
            case_mode=CaseMode.DIAGNOSTIC,
        )
        # case mode NOT ok — must transit awaiting_challenge
        with pytest.raises(InvalidStateTransitionError, match="diagnostic"):
            validate_transition(
                from_state=CaseStatus.AWAITING_GOVERNANCE,
                to_state=CaseStatus.DECIDED,
                case_mode=CaseMode.PROPOSED_ACTION,
            )

    def test_awaiting_committee_only_case_modes(self):
        # diagnostic NOT ok — materiality is mode-excluded
        with pytest.raises(InvalidStateTransitionError, match="awaiting_committee"):
            validate_transition(
                from_state=CaseStatus.SYNTHESIZING,
                to_state=CaseStatus.AWAITING_COMMITTEE,
                case_mode=CaseMode.DIAGNOSTIC,
            )
        # briefing NOT ok
        with pytest.raises(InvalidStateTransitionError, match="awaiting_committee"):
            validate_transition(
                from_state=CaseStatus.SYNTHESIZING,
                to_state=CaseStatus.AWAITING_COMMITTEE,
                case_mode=CaseMode.BRIEFING,
            )

    def test_awaiting_challenge_only_case_modes(self):
        with pytest.raises(InvalidStateTransitionError, match="awaiting_challenge"):
            validate_transition(
                from_state=CaseStatus.AWAITING_GOVERNANCE,
                to_state=CaseStatus.AWAITING_CHALLENGE,
                case_mode=CaseMode.DIAGNOSTIC,
            )


# ---------------------------------------------------------------------------
# Universal escapes (FR 20.1 §3.5)
# ---------------------------------------------------------------------------


class TestUniversalEscapes:
    @pytest.mark.parametrize(
        "from_state",
        [
            CaseStatus.OPENING,
            CaseStatus.GATHERING_EVIDENCE,
            CaseStatus.SYNTHESIZING,
            CaseStatus.AWAITING_COMMITTEE,
            CaseStatus.AWAITING_GOVERNANCE,
            CaseStatus.AWAITING_CHALLENGE,
            CaseStatus.AWAITING_DECISION,
        ],
    )
    def test_failed_universal_from_non_terminal(self, from_state):
        validate_transition(
            from_state=from_state,
            to_state=CaseStatus.FAILED,
            case_mode=CaseMode.PROPOSED_ACTION,
        )

    @pytest.mark.parametrize(
        "from_state",
        [
            CaseStatus.OPENING,
            CaseStatus.GATHERING_EVIDENCE,
            CaseStatus.SYNTHESIZING,
            CaseStatus.AWAITING_COMMITTEE,
            CaseStatus.AWAITING_GOVERNANCE,
            CaseStatus.AWAITING_CHALLENGE,
            CaseStatus.AWAITING_DECISION,
        ],
    )
    def test_archived_universal_from_non_terminal(self, from_state):
        validate_transition(
            from_state=from_state,
            to_state=CaseStatus.ARCHIVED,
            case_mode=CaseMode.PROPOSED_ACTION,
        )


class TestTerminalCheck:
    def test_terminal_recognised(self):
        assert is_terminal(CaseStatus.DECIDED)
        assert is_terminal(CaseStatus.ARCHIVED)
        assert is_terminal(CaseStatus.FAILED)
        assert not is_terminal(CaseStatus.OPENING)
        assert not is_terminal(CaseStatus.AWAITING_DECISION)


# ---------------------------------------------------------------------------
# Expected-pipeline helper (used by case detail UI in 5.5)
# ---------------------------------------------------------------------------


class TestExpectedPipeline:
    def test_proposed_action_full_pipeline(self):
        seq = expected_pipeline_for_mode(CaseMode.PROPOSED_ACTION)
        assert seq[0] == CaseStatus.OPENING
        assert seq[-1] == CaseStatus.DECIDED
        # awaiting_committee NOT in the canonical sequence — UI inserts it
        # for material cases.
        assert CaseStatus.AWAITING_COMMITTEE not in seq
        assert CaseStatus.AWAITING_DECISION in seq

    def test_diagnostic_pipeline_skips_committee_challenge(self):
        seq = expected_pipeline_for_mode(CaseMode.DIAGNOSTIC)
        assert CaseStatus.AWAITING_COMMITTEE not in seq
        assert CaseStatus.AWAITING_CHALLENGE not in seq
        assert CaseStatus.AWAITING_DECISION not in seq
        assert CaseStatus.AWAITING_GOVERNANCE in seq

    def test_briefing_pipeline_skips_governance(self):
        seq = expected_pipeline_for_mode(CaseMode.BRIEFING)
        assert CaseStatus.AWAITING_GOVERNANCE not in seq
        assert seq == (
            CaseStatus.OPENING,
            CaseStatus.GATHERING_EVIDENCE,
            CaseStatus.SYNTHESIZING,
            CaseStatus.DECIDED,
        )


# ---------------------------------------------------------------------------
# String-input tolerance
# ---------------------------------------------------------------------------


class TestStringInputs:
    def test_string_inputs_accepted(self):
        out = validate_transition(
            from_state="opening",
            to_state="gathering_evidence",
            case_mode="proposed_action",
        )
        assert out == CaseStatus.GATHERING_EVIDENCE

    def test_invalid_string_state_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_transition(
                from_state="not_a_state",
                to_state="gathering_evidence",
                case_mode="proposed_action",
            )
