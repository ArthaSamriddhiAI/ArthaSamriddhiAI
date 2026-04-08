"""Unlisted Equity specialist agent."""

from __future__ import annotations

from pathlib import Path

from artha.common.types import AgentID
from artha.governance.agents.base import BaseAgent
from artha.llm.base import LLMProvider

SKILL_PATH = Path(__file__).parent / "skill.md"


class UnlistedEquityAgent(BaseAgent):
    def __init__(self, llm: LLMProvider) -> None:
        super().__init__(
            agent_id=AgentID("analysis_unlisted_equity"),
            agent_name="Unlisted Equity Specialist",
            skill_path=SKILL_PATH,
            llm=llm,
        )
