"""Models for the analysis agent layer."""

from __future__ import annotations

from pydantic import BaseModel, Field

from artha.governance.agents.base import AgentOutput, ProposedAction, RiskLevel


class ClassificationOutput(BaseModel):
    """LLM-produced classification of which analysis agents to invoke."""

    selected_agents: list[str] = Field(default_factory=list)
    reasoning: str = ""
    is_unlisted_equity: bool = False
    is_pms_aif: bool = False


class AnalysisEnvelope(BaseModel):
    """Synthesized output from the analysis layer, fed into governance pipeline."""

    individual_outputs: list[AgentOutput] = Field(default_factory=list)
    synthesis_summary: str = ""
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    overall_risk_level: RiskLevel = RiskLevel.MEDIUM
    key_drivers: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    recommended_actions: list[ProposedAction] = Field(default_factory=list)
    classification_reasoning: str = ""
