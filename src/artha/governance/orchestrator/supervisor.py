"""Supervisor node — decides which agents to consult. Bounded, no authority."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from artha.governance.agents.base import AgentOutput
from artha.governance.intent.models import GovernanceIntent, IntentType
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest


AVAILABLE_AGENTS = ["allocation", "risk_interpretation", "review"]

AGENT_DESCRIPTIONS = {
    "allocation": "Analyzes portfolio weights, diversification, proposes allocation changes",
    "risk_interpretation": "Interprets risk scores, flags concerns, identifies tail risks",
    "review": "Synthesizes all agent outputs into a coherent explanation for decision makers",
}


class SupervisorDispatch(BaseModel):
    """Supervisor output — which agents to consult next."""

    agents: list[str] = Field(default_factory=list)
    reasoning: str = ""
    synthesis_complete: bool = False


class Supervisor:
    """Orchestrator supervisor with bounded authority.

    CANNOT place trades.
    CANNOT override rules.
    CANNOT invent objectives.
    Only coordinates agent consultation order.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def decide_agents(
        self,
        intent: GovernanceIntent,
        prior_outputs: list[AgentOutput],
        evidence_context: dict[str, Any],
        loop_count: int,
        max_loops: int,
    ) -> SupervisorDispatch:
        """Decide which agents to consult next based on intent and prior outputs."""
        # For the first loop, use rule-based dispatch (no LLM needed for simple cases)
        if loop_count == 0:
            return self._initial_dispatch(intent)

        # If we've already consulted agents, check if we need the review agent
        consulted = {o.agent_id for o in prior_outputs}
        if "review" not in consulted and len(prior_outputs) >= 2:
            return SupervisorDispatch(
                agents=["review"],
                reasoning="All primary agents consulted. Running review for synthesis.",
                synthesis_complete=False,
            )

        # If review is done or we're at max loops, mark synthesis complete
        if "review" in consulted or loop_count >= max_loops:
            return SupervisorDispatch(
                agents=[],
                reasoning="All agents consulted. Synthesis complete.",
                synthesis_complete=True,
            )

        return SupervisorDispatch(
            agents=[],
            reasoning="Synthesis complete.",
            synthesis_complete=True,
        )

    def _initial_dispatch(self, intent: GovernanceIntent) -> SupervisorDispatch:
        """Determine initial agent set based on intent type."""
        if intent.intent_type == IntentType.REBALANCE:
            return SupervisorDispatch(
                agents=["allocation", "risk_interpretation"],
                reasoning="Rebalance intent requires allocation and risk assessment.",
            )
        elif intent.intent_type == IntentType.RISK_REVIEW:
            return SupervisorDispatch(
                agents=["risk_interpretation"],
                reasoning="Risk review focuses on risk interpretation.",
            )
        elif intent.intent_type == IntentType.TRADE_PROPOSAL:
            return SupervisorDispatch(
                agents=["risk_interpretation", "allocation"],
                reasoning="Trade proposal needs risk and allocation assessment.",
            )
        else:
            return SupervisorDispatch(
                agents=["allocation", "risk_interpretation"],
                reasoning="Default: consult allocation and risk agents.",
            )
