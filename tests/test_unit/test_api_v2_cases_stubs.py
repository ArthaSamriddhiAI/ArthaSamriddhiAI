"""Cluster 5 chunk 5.4 — stub-layer unit tests.

Pins:

- Each of the 16 stub functions returns a dict with the expected
  schema-required keys.
- Stubs are deterministic for the same case + seed_archetype.
- Seed-payload short-circuit: when a seed key is present, the stub
  returns the seed payload verbatim instead of the placeholder.
- Numeric variability comes from a pure-function hash of case_id (no
  randomness, no clock).
"""

from __future__ import annotations

import pytest

from artha.api_v2.cases.materiality import MaterialityResult
from artha.api_v2.cases.state_machine import ProducedVia
from artha.api_v2.cases.stubs import (
    StubContext,
    stub_a1_challenge,
    stub_briefing_note,
    stub_evidence_alternatives,
    stub_evidence_behavioural,
    stub_evidence_debt,
    stub_evidence_equity,
    stub_evidence_macro,
    stub_evidence_sentiment,
    stub_evidence_tax,
    stub_governance_g1_mandate,
    stub_governance_g2_sebi,
    stub_governance_g3_action_filter,
    stub_health_report,
    stub_ic1_deliberation,
    stub_portfolio_risk_analytics,
    stub_synthesis_briefing_mode,
    stub_synthesis_case_mode,
    stub_synthesis_diagnostic_mode,
)


class _FakeCase:
    """Minimal stand-in for the Case ORM row (only fields the stubs read)."""

    def __init__(
        self,
        *,
        case_id: str = "01HQZTEST00000000000000001",
        is_seed_data: bool = False,
        seed_archetype_id: str | None = None,
    ) -> None:
        self.case_id = case_id
        self.is_seed_data = is_seed_data
        self.seed_archetype_id = seed_archetype_id


def _ctx(
    *,
    seed_payload: dict | None = None,
    case_id: str = "01HQZTEST00000000000000001",
) -> StubContext:
    return StubContext(
        case=_FakeCase(case_id=case_id),
        produced_via=ProducedVia.LOOKUP_STUB_PLACEHOLDER,
        seed_payload=seed_payload or {},
    )


# ---------------------------------------------------------------------------
# Portfolio risk analytics
# ---------------------------------------------------------------------------


class TestPortfolioRiskAnalytics:
    def test_required_keys_present(self) -> None:
        out = stub_portfolio_risk_analytics(_ctx())
        for key in (
            "concentration_assessment",
            "leverage_assessment",
            "liquidity_assessment",
            "return_quality_assessment",
            "deployment_assessment",
            "cascade_assessment",
            "overall_risk_level",
            "overall_confidence",
            "drivers",
            "flags",
            "reasoning_summary",
            "portfolio_analytics_input_hash",
        ):
            assert key in out

    def test_deterministic(self) -> None:
        a = stub_portfolio_risk_analytics(_ctx())
        b = stub_portfolio_risk_analytics(_ctx())
        assert a == b

    def test_seed_short_circuit(self) -> None:
        seed = {"portfolio_risk_analytics": {"overall_risk_level": "high"}}
        out = stub_portfolio_risk_analytics(_ctx(seed_payload=seed))
        assert out == seed["portfolio_risk_analytics"]


# ---------------------------------------------------------------------------
# Evidence (7 agents)
# ---------------------------------------------------------------------------


class TestEvidence:
    @pytest.mark.parametrize(
        "fn,agent_id",
        [
            (stub_evidence_equity, "e1_equity_evidence"),
            (stub_evidence_debt, "e1_debt_evidence"),
            (stub_evidence_alternatives, "e1_alternatives_evidence"),
            (stub_evidence_macro, "e1_macro_evidence"),
            (stub_evidence_sentiment, "e1_sentiment_evidence"),
            (stub_evidence_behavioural, "e1_behavioural_evidence"),
            (stub_evidence_tax, "e1_tax_evidence"),
        ],
    )
    def test_evidence_schema(self, fn, agent_id: str) -> None:
        out = fn(_ctx())
        assert out["agent_id"] == agent_id
        assert out["risk_level"] in {"low", "medium", "high", "critical"}
        assert 0.0 <= float(out["confidence"]) <= 1.0
        assert "drivers" in out
        assert "structured_output" in out
        assert "reasoning_summary" in out

    def test_seed_short_circuit(self) -> None:
        seed = {"evidence.e1_equity_evidence": {"agent_id": "X", "risk_level": "critical"}}
        out = stub_evidence_equity(_ctx(seed_payload=seed))
        assert out == seed["evidence.e1_equity_evidence"]

    def test_deterministic_per_case(self) -> None:
        a = stub_evidence_equity(_ctx(case_id="01CASEA"))
        b = stub_evidence_equity(_ctx(case_id="01CASEA"))
        c = stub_evidence_equity(_ctx(case_id="01CASEB"))
        assert a == b
        # Different case → different confidence number.
        assert a["confidence"] != c["confidence"]


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


class TestSynthesis:
    @pytest.mark.parametrize(
        "fn,mode",
        [
            (stub_synthesis_case_mode, "case_mode"),
            (stub_synthesis_diagnostic_mode, "diagnostic"),
            (stub_synthesis_briefing_mode, "briefing"),
        ],
    )
    def test_synthesis_schema(self, fn, mode: str) -> None:
        out = fn(_ctx())
        assert out["output_mode"] == mode
        assert "synthesis_narrative" in out
        assert "recommendation" in out
        assert "consensus" in out
        assert "agreement_areas" in out

    def test_seed_short_circuit(self) -> None:
        seed = {"synthesis.case_mode": {"output_mode": "case_mode", "recommendation": "X"}}
        out = stub_synthesis_case_mode(_ctx(seed_payload=seed))
        assert out == seed["synthesis.case_mode"]


# ---------------------------------------------------------------------------
# IC1
# ---------------------------------------------------------------------------


class TestIC1:
    def test_schema(self) -> None:
        out = stub_ic1_deliberation(_ctx())
        assert "chair_summary" in out
        assert "minutes" in out
        assert out["recommendation"] in {
            "proceed", "support_with_conditions", "oppose", "defer",
        }
        assert "members_present" in out["minutes"]


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


class TestGovernance:
    @pytest.mark.parametrize(
        "fn,gate",
        [
            (stub_governance_g1_mandate, "g1_mandate"),
            (stub_governance_g2_sebi, "g2_sebi_regulatory"),
            (stub_governance_g3_action_filter, "g3_action_filter"),
        ],
    )
    def test_schema(self, fn, gate: str) -> None:
        out = fn(_ctx())
        assert out["gate"] == gate
        assert out["outcome"] == "approved"
        # Reasoning is text per the GovernanceResult column type.
        assert isinstance(out["reasoning"], str)


# ---------------------------------------------------------------------------
# A1 challenge
# ---------------------------------------------------------------------------


class TestA1Challenge:
    def test_schema(self) -> None:
        out = stub_a1_challenge(_ctx())
        assert "counter_arguments" in out
        assert "alternative_proposals" in out
        assert "stress_test_scenarios" in out
        assert "edge_cases" in out


# ---------------------------------------------------------------------------
# Briefing + health
# ---------------------------------------------------------------------------


class TestBriefingAndHealth:
    def test_briefing_schema(self) -> None:
        out = stub_briefing_note(_ctx())
        assert "meeting_context" in out
        assert "prep_questions" in out

    def test_health_default_overall_healthy(self) -> None:
        out = stub_health_report(_ctx())
        assert out["overall_health"] == "healthy"

    def test_health_attention_when_material(self) -> None:
        mat = MaterialityResult(
            is_material=True, reason="MAT_TICKET_SIZE", rules_triggered=(),
        )
        out = stub_health_report(_ctx(), materiality=mat)
        assert out["overall_health"] == "attention_needed"
