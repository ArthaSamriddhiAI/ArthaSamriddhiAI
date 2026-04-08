"""Master Analysis Agent — classifies intent, dispatches sub-agents, synthesizes."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from artha.governance.agents.analysis.models import (
    AnalysisEnvelope,
    ClassificationOutput,
)
from artha.governance.agents.base import AgentOutput, ProposedAction, RiskLevel
from artha.governance.intent.models import GovernanceIntent
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).parent / "skill.md"

# Core analysis agents — always available
CORE_AGENTS = ["fundamental", "technical", "sectoral", "macro", "sentiment"]

# Specialist agents — invoked only when classification says so
SPECIALIST_AGENTS = ["unlisted_equity", "pms_aif"]


def _get_analysis_agent_registry(llm: LLMProvider) -> dict[str, Any]:
    """Lazy import to avoid circular deps. Returns agent instances by ID."""
    from artha.governance.agents.analysis.fundamental.agent import FundamentalAnalysisAgent
    from artha.governance.agents.analysis.macro.agent import MacroAnalysisAgent
    from artha.governance.agents.analysis.pms_aif.agent import PmsAifAgent
    from artha.governance.agents.analysis.sectoral.agent import SectoralAnalysisAgent
    from artha.governance.agents.analysis.sentiment.agent import SentimentAnalysisAgent
    from artha.governance.agents.analysis.technical.agent import TechnicalAnalysisAgent
    from artha.governance.agents.analysis.unlisted_equity.agent import UnlistedEquityAgent

    return {
        "fundamental": FundamentalAnalysisAgent(llm),
        "technical": TechnicalAnalysisAgent(llm),
        "sectoral": SectoralAnalysisAgent(llm),
        "macro": MacroAnalysisAgent(llm),
        "sentiment": SentimentAnalysisAgent(llm),
        "unlisted_equity": UnlistedEquityAgent(llm),
        "pms_aif": PmsAifAgent(llm),
    }


class MasterAnalysisAgent:
    """Orchestrates the analysis layer: classify → dispatch → synthesize.

    NOT a BaseAgent subclass — different lifecycle and return type.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm
        self._skill_path = SKILL_PATH

    def _load_skill(self) -> str:
        return self._skill_path.read_text(encoding="utf-8")

    async def run(
        self, intent: GovernanceIntent, evidence_context: dict[str, Any]
    ) -> AnalysisEnvelope:
        """Execute the full analysis layer: classify, dispatch, synthesize."""
        skill = self._load_skill()

        # Step 1: Classify which agents to invoke
        classification = await self._classify(intent, evidence_context, skill)

        # Step 2: Build agent list from classification
        agent_ids = self._resolve_agents(classification)

        # Step 3: Run selected agents in parallel
        outputs = await self._dispatch(agent_ids, evidence_context)

        # Step 4: Synthesize all outputs
        envelope = await self._synthesize(outputs, intent, evidence_context, skill)
        envelope.individual_outputs = outputs
        envelope.classification_reasoning = classification.reasoning
        return envelope

    async def _classify(
        self,
        intent: GovernanceIntent,
        evidence_context: dict[str, Any],
        skill: str,
    ) -> ClassificationOutput:
        """Use LLM to classify which analysis agents to invoke."""
        system_prompt = (
            "You are the Master Analysis Agent classifier.\n\n"
            f"## Classification Rules\n{skill}\n\n"
            "Based on the intent and context below, determine which analysis agents "
            "should be invoked. Return structured output.\n"
        )

        context_summary = {
            "intent_type": intent.intent_type.value,
            "symbols": intent.symbols,
            "parameters": intent.parameters,
            "regime": evidence_context.get("regime_classification", {}),
            "has_holdings": bool(intent.holdings),
        }

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(
                    role="user",
                    content=(
                        "Classify which analysis agents to invoke for this intent:\n"
                        f"```json\n{json.dumps(context_summary, default=str, indent=2)}\n```"
                    ),
                ),
            ],
            temperature=0.0,
        )

        try:
            return await self._llm.complete_structured(request, ClassificationOutput)
        except Exception:
            logger.warning("Classification LLM call failed, falling back to all core agents")
            return ClassificationOutput(
                selected_agents=CORE_AGENTS,
                reasoning="Fallback: classification failed, invoking all core agents.",
            )

    def _resolve_agents(self, classification: ClassificationOutput) -> list[str]:
        """Build final list of agent IDs to invoke."""
        agents = list(classification.selected_agents)

        # Add specialists based on classification flags
        if classification.is_unlisted_equity and "unlisted_equity" not in agents:
            agents.append("unlisted_equity")
        if classification.is_pms_aif and "pms_aif" not in agents:
            agents.append("pms_aif")

        # Validate — only allow known agent IDs
        valid = set(CORE_AGENTS + SPECIALIST_AGENTS)
        agents = [a for a in agents if a in valid]

        # Fallback: if no valid agents selected, invoke all core agents
        if not agents:
            logger.info("No agents selected by classification, falling back to all core agents")
            agents = list(CORE_AGENTS)

        return agents

    async def _dispatch(
        self, agent_ids: list[str], evidence_context: dict[str, Any]
    ) -> list[AgentOutput]:
        """Run selected analysis agents in parallel."""
        registry = _get_analysis_agent_registry(self._llm)

        async def _run_one(agent_id: str) -> AgentOutput:
            agent = registry.get(agent_id)
            if agent is None:
                return AgentOutput(
                    agent_id=agent_id,
                    agent_name=f"unknown_{agent_id}",
                    reasoning_summary=f"Agent '{agent_id}' not found.",
                    flags=[f"AGENT_NOT_FOUND: {agent_id}"],
                )
            try:
                return await agent.run(evidence_context)
            except Exception as e:
                logger.warning(f"Analysis agent '{agent_id}' failed: {e}")
                return AgentOutput(
                    agent_id=agent_id,
                    agent_name=agent.agent_name,
                    reasoning_summary=f"Agent failed: {e}",
                    flags=[f"AGENT_ERROR: {e}"],
                    confidence=0.0,
                )

        return await asyncio.gather(*[_run_one(aid) for aid in agent_ids])

    async def _synthesize(
        self,
        outputs: list[AgentOutput],
        intent: GovernanceIntent,
        evidence_context: dict[str, Any],
        skill: str,
    ) -> AnalysisEnvelope:
        """Use LLM to synthesize all agent outputs into a unified assessment."""
        system_prompt = (
            "You are the Master Analysis Agent synthesizer.\n\n"
            f"## Synthesis Guidelines\n{skill}\n\n"
            "Synthesize the analysis outputs below into a unified assessment. "
            "Return structured output with: synthesis_summary, overall_confidence, "
            "overall_risk_level, key_drivers, conflicts, flags, recommended_actions.\n"
        )

        # Serialize agent outputs for the LLM
        agent_summaries = []
        for o in outputs:
            agent_summaries.append({
                "agent_id": o.agent_id,
                "agent_name": o.agent_name,
                "risk_level": o.risk_level.value,
                "confidence": o.confidence,
                "drivers": o.drivers,
                "flags": o.flags,
                "proposed_actions": [a.model_dump() for a in o.proposed_actions],
                "reasoning_summary": o.reasoning_summary,
            })

        user_content = (
            f"Intent: {intent.intent_type.value} for symbols {intent.symbols}\n\n"
            f"## Agent Outputs\n```json\n{json.dumps(agent_summaries, indent=2, default=str)}\n```"
        )

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_content),
            ],
            temperature=0.0,
        )

        try:
            return await self._llm.complete_structured(request, AnalysisEnvelope)
        except Exception:
            logger.warning("Synthesis LLM call failed, building minimal envelope")
            return self._fallback_envelope(outputs)

    def _fallback_envelope(self, outputs: list[AgentOutput]) -> AnalysisEnvelope:
        """Build a minimal envelope when synthesis LLM call fails."""
        all_drivers: list[str] = []
        all_flags: list[str] = ["SYNTHESIS_FAILED: LLM call failed, showing raw agent outputs"]
        all_actions: list[ProposedAction] = []
        confidences: list[float] = []

        for o in outputs:
            all_drivers.extend(o.drivers)
            all_flags.extend(o.flags)
            all_actions.extend(o.proposed_actions)
            confidences.append(o.confidence)

        risk_levels = [o.risk_level for o in outputs]
        worst_risk = max(risk_levels, key=lambda r: list(RiskLevel).index(r), default=RiskLevel.MEDIUM)

        return AnalysisEnvelope(
            individual_outputs=outputs,
            synthesis_summary="Synthesis failed — individual agent outputs preserved below.",
            overall_confidence=min(confidences) if confidences else 0.0,
            overall_risk_level=worst_risk,
            key_drivers=all_drivers[:10],
            conflicts=[],
            flags=all_flags,
            recommended_actions=all_actions,
            classification_reasoning="",
        )
