"""Macro Analysis agent."""

from __future__ import annotations

from pathlib import Path

from artha.common.types import AgentID
from artha.governance.agents.base import BaseAgent
from artha.llm.base import LLMProvider

SKILL_PATH = Path(__file__).parent / "skill.md"


class MacroAnalysisAgent(BaseAgent):
    def __init__(self, llm: LLMProvider) -> None:
        super().__init__(
            agent_id=AgentID("analysis_macro"),
            agent_name="Macro Analysis",
            skill_path=SKILL_PATH,
            llm=llm,
        )
