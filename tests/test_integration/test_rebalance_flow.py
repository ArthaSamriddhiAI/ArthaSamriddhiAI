"""End-to-end integration test: submit a rebalance intent through the full pipeline."""

from __future__ import annotations

import pytest
from pathlib import Path

from artha.governance.intent.models import GovernanceIntent, IntentType
from artha.governance.service import GovernanceService


RULES_DIR = Path(__file__).parent.parent.parent / "rules"


@pytest.mark.asyncio
async def test_rebalance_flow_end_to_end(db_session, frozen_clock, mock_llm):
    """Full pipeline: intent → evidence → agents → rules → permissions."""
    # Set up mock LLM responses for agents
    mock_llm.set_structured_response("Allocation", {
        "agent_id": "allocation",
        "agent_name": "Allocation Reasoning",
        "risk_level": "medium",
        "confidence": 0.7,
        "drivers": ["High tech concentration", "Low diversification"],
        "proposed_actions": [
            {"symbol": "AAPL", "action": "reduce", "target_weight": 0.15, "rationale": "Reduce concentration"},
            {"symbol": "JPM", "action": "increase", "target_weight": 0.12, "rationale": "Add financials"},
        ],
        "reasoning_summary": "Portfolio is tech-heavy, recommend diversifying into financials.",
        "flags": [],
    })
    mock_llm.set_structured_response("Risk", {
        "agent_id": "risk_interpretation",
        "agent_name": "Risk Interpretation",
        "risk_level": "medium",
        "confidence": 0.65,
        "drivers": ["Moderate portfolio risk", "Some positions near 52w highs"],
        "proposed_actions": [],
        "reasoning_summary": "Overall risk is moderate. No critical concerns.",
        "flags": [],
    })
    mock_llm.set_structured_response("Review", {
        "agent_id": "review",
        "agent_name": "Review & Explanation",
        "risk_level": "medium",
        "confidence": 0.7,
        "drivers": ["Agents agree on moderate risk", "Allocation agent proposes diversification"],
        "proposed_actions": [],
        "reasoning_summary": "Consensus: moderate risk, diversification recommended.",
        "flags": [],
    })

    # Create intent
    intent = GovernanceIntent(
        intent_type=IntentType.REBALANCE,
        symbols=["AAPL", "MSFT", "GOOGL", "JPM", "JNJ"],
        holdings={"AAPL": 100, "MSFT": 80, "GOOGL": 60, "JPM": 40, "JNJ": 30},
        parameters={"target_risk": "moderate"},
    )

    # Run the governance pipeline
    service = GovernanceService(
        session=db_session,
        llm=mock_llm,
        rules_dir=RULES_DIR,
    )
    result = await service.process_intent(intent)
    await db_session.commit()

    # Verify results
    assert result.decision_id is not None
    assert result.intent_type == "rebalance"
    assert result.status in ("approved", "escalation_required", "rejected")

    # Verify agents were consulted
    agent_ids = {o.agent_id for o in result.agent_outputs}
    assert "allocation" in agent_ids
    assert "risk_interpretation" in agent_ids

    # Verify evidence snapshot was created
    assert result.evidence_snapshot_id is not None

    # Verify rule evaluations occurred (if there were proposed actions)
    if result.rule_evaluations:
        for eval_result in result.rule_evaluations:
            assert eval_result.rule_name  # Each evaluation has a rule name
            assert eval_result.condition  # Each has the condition that was evaluated

    # Verify permission outcome exists
    assert result.permission_outcome is not None
    assert result.permission_outcome.decision_id == result.decision_id


@pytest.mark.asyncio
async def test_rebalance_with_no_actions_produces_approved(db_session, frozen_clock, mock_llm):
    """When agents propose no actions, the pipeline should still complete cleanly."""
    intent = GovernanceIntent(
        intent_type=IntentType.REBALANCE,
        symbols=["AAPL", "MSFT"],
        holdings={"AAPL": 50, "MSFT": 50},
    )

    service = GovernanceService(
        session=db_session,
        llm=mock_llm,
        rules_dir=RULES_DIR,
    )
    result = await service.process_intent(intent)
    await db_session.commit()

    assert result.decision_id is not None
    assert result.status == "approved"  # No actions = no violations = approved
    assert result.permission_outcome is not None
