"""Fundamental Analysis agent."""

from __future__ import annotations

from pathlib import Path

from artha.common.types import AgentID
from artha.governance.agents.base import BaseAgent
from artha.llm.base import LLMProvider

SKILL_PATH = Path(__file__).parent / "skill.md"


class FundamentalAnalysisAgent(BaseAgent):
    def __init__(self, llm: LLMProvider) -> None:
        super().__init__(
            agent_id=AgentID("analysis_fundamental"),
            agent_name="Fundamental Analysis",
            skill_path=SKILL_PATH,
            llm=llm,
        )
