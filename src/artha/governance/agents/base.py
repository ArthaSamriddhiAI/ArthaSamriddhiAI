"""Base agent class — loads skill.md, calls LLM, returns structured output."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from artha.common.types import AgentID
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProposedAction(BaseModel):
    """A single proposed portfolio action from an agent."""

    symbol: str
    action: str  # "buy", "sell", "hold", "reduce", "increase"
    target_weight: float | None = None
    rationale: str = ""


class AgentOutput(BaseModel):
    """Structured output from a reasoning agent. No chain-of-thought stored."""

    agent_id: str = ""
    agent_name: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    drivers: list[str] = Field(default_factory=list)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    reasoning_summary: str = ""
    flags: list[str] = Field(default_factory=list)


class BaseAgent:
    """Base class for specialized reasoning agents.

    Each agent:
    - Loads its skill.md at invocation time (versioned, governed)
    - Constructs a system prompt from skill.md + context
    - Calls the LLM with structured output
    - Returns an AgentOutput (structured JSON, not free text)
    """

    def __init__(
        self,
        agent_id: AgentID,
        agent_name: str,
        skill_path: Path,
        llm: LLMProvider,
    ) -> None:
        self._agent_id = agent_id
        self._agent_name = agent_name
        self._skill_path = skill_path
        self._llm = llm
        self._skill_content: str | None = None

    @property
    def agent_id(self) -> AgentID:
        return self._agent_id

    @property
    def agent_name(self) -> str:
        return self._agent_name

    def _load_skill(self) -> str:
        """Load skill.md content. Re-read each invocation for governed updates."""
        self._skill_content = self._skill_path.read_text(encoding="utf-8")
        return self._skill_content

    def _build_system_prompt(self, context: dict[str, Any]) -> str:
        """Construct system prompt from skill.md + context."""
        skill = self._load_skill()
        return (
            f"You are the {self._agent_name} agent in a Portfolio Operating System.\n\n"
            f"## Your Skill Definition\n{skill}\n\n"
            f"## Constraints\n"
            f"- You produce STRUCTURED analysis only. No decision authority.\n"
            f"- Your output will be reviewed by a rule engine and human decision maker.\n"
            f"- Be precise about confidence levels and risk drivers.\n"
            f"- Flag any uncertainties or data gaps explicitly.\n"
        )

    async def run(self, context: dict[str, Any]) -> AgentOutput:
        """Execute the agent with the given context."""
        system_prompt = self._build_system_prompt(context)
        user_message = self._format_context(context)

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_message),
            ],
            temperature=0.0,
        )

        output = await self._llm.complete_structured(request, AgentOutput)
        output.agent_id = self._agent_id
        output.agent_name = self._agent_name
        return output

    def _format_context(self, context: dict[str, Any]) -> str:
        """Format the context dict into a user message for the LLM."""
        parts = ["Analyze the following portfolio context and provide your assessment:\n"]
        for key, value in context.items():
            if isinstance(value, dict):
                import json
                parts.append(f"### {key}\n```json\n{json.dumps(value, indent=2, default=str)}\n```\n")
            elif isinstance(value, list):
                import json
                parts.append(f"### {key}\n```json\n{json.dumps(value, indent=2, default=str)}\n```\n")
            else:
                parts.append(f"### {key}\n{value}\n")
        return "\n".join(parts)
