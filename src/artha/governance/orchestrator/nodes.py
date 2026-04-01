"""Agent execution nodes for the LangGraph orchestration pipeline."""

from __future__ import annotations

from typing import Any

from artha.governance.agents.allocation.agent import AllocationAgent
from artha.governance.agents.base import AgentOutput
from artha.governance.agents.review.agent import ReviewAgent
from artha.governance.agents.risk_interpretation.agent import RiskInterpretationAgent
from artha.llm.base import LLMProvider


def get_agent_registry(llm: LLMProvider) -> dict[str, Any]:
    """Create agent instances. Agents are subordinate, bounded, replaceable."""
    return {
        "allocation": AllocationAgent(llm),
        "risk_interpretation": RiskInterpretationAgent(llm),
        "review": ReviewAgent(llm),
    }


async def run_agent(
    agent_id: str,
    context: dict[str, Any],
    llm: LLMProvider,
) -> AgentOutput:
    """Execute a single agent by ID."""
    registry = get_agent_registry(llm)
    agent = registry.get(agent_id)
    if agent is None:
        return AgentOutput(
            agent_id=agent_id,
            agent_name=f"unknown_{agent_id}",
            reasoning_summary=f"Agent '{agent_id}' not found in registry.",
            flags=[f"AGENT_NOT_FOUND: {agent_id}"],
        )
    return await agent.run(context)
