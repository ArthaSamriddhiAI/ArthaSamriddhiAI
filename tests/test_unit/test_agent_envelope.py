"""Pass 6 — AgentActivationEnvelope tests covering Thesis 4.2 plumbing.

These schemas are consumed by Phase C agents; Pass 6's tests verify the
envelope round-trips, run_mode defaults correctly, and the briefing /
clarification dialog shapes are valid.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from artha.canonical.agent_envelope import (
    AgentActivationEnvelope,
    ClarificationDialog,
    M0Briefing,
)
from artha.canonical.case import (
    CaseChannel,
    CaseObject,
    CaseStatus,
    DominantLens,
    LensMetadata,
)
from artha.common.standards import ClarificationRequest
from artha.common.types import (
    CaseIntent,
    RunMode,
    VersionPins,
)


def _case() -> CaseObject:
    return CaseObject(
        case_id="case_001",
        client_id="c1",
        firm_id="firm_test",
        advisor_id="advisor_jane",
        created_at=datetime(2026, 4, 25, tzinfo=UTC),
        intent=CaseIntent.CASE,
        intent_confidence=0.9,
        dominant_lens=DominantLens.PROPOSAL,
        lens_metadata=LensMetadata(lenses_fired=[DominantLens.PROPOSAL]),
        current_status=CaseStatus.IN_PROGRESS,
        channel=CaseChannel.C0,
    )


class TestEnvelopeBasics:
    def test_minimal_envelope(self):
        env = AgentActivationEnvelope(case=_case(), target_agent="e1_financial_risk")
        assert env.run_mode is RunMode.CASE
        assert env.briefing is None
        assert env.clarification is None

    def test_envelope_carries_run_mode_construction(self):
        env = AgentActivationEnvelope(
            case=_case(),
            target_agent="e1_financial_risk",
            run_mode=RunMode.CONSTRUCTION,
        )
        assert env.run_mode is RunMode.CONSTRUCTION

    def test_envelope_carries_run_mode_diagnostic(self):
        env = AgentActivationEnvelope(
            case=_case(),
            target_agent="s1_synthesis",
            run_mode=RunMode.DIAGNOSTIC,
        )
        assert env.run_mode is RunMode.DIAGNOSTIC

    def test_envelope_with_version_pins(self):
        env = AgentActivationEnvelope(
            case=_case(),
            target_agent="e1_financial_risk",
            version_pins=VersionPins(
                model_portfolio_version="3.4.0",
                mandate_version="1",
                agent_version="0.1.0",
            ),
        )
        assert env.version_pins.model_portfolio_version == "3.4.0"

    def test_envelope_round_trips_via_json(self):
        env = AgentActivationEnvelope(
            case=_case(),
            target_agent="e1_financial_risk",
            run_mode=RunMode.CASE,
        )
        round_tripped = AgentActivationEnvelope.model_validate_json(env.model_dump_json())
        assert round_tripped == env

    def test_envelope_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            AgentActivationEnvelope(
                case=_case(),
                target_agent="e1",
                made_up_field="bad",  # type: ignore[call-arg]
            )


class TestBriefingShape:
    def test_briefing_carries_token_count_and_trigger(self):
        b = M0Briefing(
            text="The client just retired. Capacity trajectory is shifting.",
            token_count=120,
            trigger_flag="structural_anomaly",
        )
        assert b.briefer_version == "0.1.0"

    def test_briefing_attaches_to_envelope(self):
        env = AgentActivationEnvelope(
            case=_case(),
            target_agent="e1_financial_risk",
            briefing=M0Briefing(
                text="x", token_count=100, trigger_flag="multi_product"
            ),
        )
        assert env.briefing is not None
        assert env.briefing.trigger_flag == "multi_product"


class TestClarificationDialog:
    def test_request_only(self):
        dialog = ClarificationDialog(
            request=ClarificationRequest(
                requesting_agent="e6_aif_cat_2",
                clarification_field="commitment_period_status",
                reason="AIF commitment period status missing from input bundle",
            )
        )
        assert dialog.response_text is None

    def test_request_plus_response(self):
        dialog = ClarificationDialog(
            request=ClarificationRequest(
                requesting_agent="e6_aif_cat_2",
                clarification_field="commitment_period_status",
                reason="missing from input",
            ),
            response_text="Commitment period extends to 2031-06-15.",
            response_token_count=80,
            responding_actor="m0",
        )
        assert dialog.response_text is not None
        assert dialog.responding_actor == "m0"

    def test_dialog_attaches_to_envelope(self):
        env = AgentActivationEnvelope(
            case=_case(),
            target_agent="e6_aif_cat_2",
            clarification=ClarificationDialog(
                request=ClarificationRequest(
                    requesting_agent="e6_aif_cat_2",
                    clarification_field="x",
                    reason="y",
                )
            ),
        )
        assert env.clarification is not None
