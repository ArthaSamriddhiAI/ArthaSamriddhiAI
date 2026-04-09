"""Execute analysis batches in parallel via asyncio.gather."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from artha.governance.agents.base import AgentOutput, RiskLevel
from artha.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def _get_agent_instance(agent_id: str, llm: LLMProvider) -> Any:
    """Lazily import and instantiate the appropriate analysis agent."""
    if agent_id == "financial_risk":
        from artha.governance.agents.analysis.financial_risk.agent import FinancialRiskAgent
        return FinancialRiskAgent(llm)
    elif agent_id == "unlisted_equity":
        from artha.governance.agents.analysis.unlisted_equity.agent import UnlistedEquityAgent
        return UnlistedEquityAgent(llm)
    elif agent_id == "pms_aif":
        from artha.governance.agents.analysis.pms_aif.agent import PmsAifAgent
        return PmsAifAgent(llm)
    elif agent_id == "industry_business":
        from artha.governance.agents.analysis.industry_business.agent import IndustryBusinessAgent
        return IndustryBusinessAgent(llm)
    elif agent_id == "macro":
        from artha.governance.agents.analysis.macro.agent import MacroAnalysisAgent
        return MacroAnalysisAgent(llm)
    elif agent_id == "behavioural_historical":
        from artha.governance.agents.analysis.behavioural_historical.agent import BehaviouralHistoricalAgent
        return BehaviouralHistoricalAgent(llm)
    else:
        raise ValueError(f"Unknown agent_id: {agent_id}")


async def _run_single_holding(
    agent: Any, holding: dict, mode: str = "portfolio_review"
) -> dict:
    """Run an agent against a single holding, returning the result dict."""
    context = {
        "mode": mode,
        "holding": holding,
        "holding_id": holding.get("holding_id", "unknown"),
    }
    try:
        output: AgentOutput = await agent.run(context)
        return {
            "holding_id": holding.get("holding_id"),
            "status": "ok",
            "output": output.model_dump(mode="json"),
        }
    except Exception as e:
        logger.warning(
            "Agent failed for holding %s: %s", holding.get("holding_id"), e
        )
        return {
            "holding_id": holding.get("holding_id"),
            "status": "AGENT_UNAVAILABLE",
            "error": str(e),
            "output": AgentOutput(
                agent_id="unknown",
                agent_name="unknown",
                reasoning_summary=f"Agent unavailable: {e}",
                flags=["AGENT_UNAVAILABLE"],
                confidence=0.0,
            ).model_dump(mode="json"),
        }


async def _run_batch(batch: dict, llm: LLMProvider) -> dict:
    """Execute a single batch — all holdings sent to the agent in one context.

    On batch failure, retry individual holdings. If individual fails, mark as
    AGENT_UNAVAILABLE.
    """
    agent_id = batch["agent_id"]
    holdings = batch["holdings"]
    batch_index = batch["batch_index"]

    try:
        agent = _get_agent_instance(agent_id, llm)
    except ValueError as e:
        logger.error("Cannot instantiate agent: %s", e)
        return {
            "agent_id": agent_id,
            "batch_index": batch_index,
            "status": "AGENT_UNAVAILABLE",
            "results": [
                {
                    "holding_id": h.get("holding_id"),
                    "status": "AGENT_UNAVAILABLE",
                    "error": str(e),
                    "output": AgentOutput(
                        agent_id=agent_id,
                        reasoning_summary=f"Agent unavailable: {e}",
                        flags=["AGENT_UNAVAILABLE"],
                        confidence=0.0,
                    ).model_dump(mode="json"),
                }
                for h in holdings
            ],
        }

    # Try the full batch as one call
    batch_context = {
        "mode": "portfolio_review",
        "holdings": holdings,
        "holding_ids": [h.get("holding_id") for h in holdings],
        "batch_index": batch_index,
    }

    try:
        output: AgentOutput = await agent.run(batch_context)
        return {
            "agent_id": agent_id,
            "batch_index": batch_index,
            "status": "ok",
            "batch_output": output.model_dump(mode="json"),
            "results": [
                {
                    "holding_id": h.get("holding_id"),
                    "status": "ok",
                    "output": output.model_dump(mode="json"),
                }
                for h in holdings
            ],
        }
    except Exception as batch_err:
        logger.warning(
            "Batch %s-%d failed (%s), retrying individual holdings",
            agent_id, batch_index, batch_err,
        )

    # Fallback: retry each holding individually
    individual_results = await asyncio.gather(
        *[_run_single_holding(agent, h) for h in holdings]
    )

    return {
        "agent_id": agent_id,
        "batch_index": batch_index,
        "status": "partial",
        "results": list(individual_results),
    }


async def execute_batches(batches: list[dict], llm: LLMProvider) -> list[dict]:
    """Run all batches in parallel via asyncio.gather.

    Parameters
    ----------
    batches : list[dict]
        Output of ``build_batches``.
    llm : LLMProvider
        LLM provider for agent calls.

    Returns
    -------
    list of batch result dicts, each containing per-holding results.
    """
    if not batches:
        return []

    results = await asyncio.gather(
        *[_run_batch(b, llm) for b in batches],
        return_exceptions=True,
    )

    # Convert any unexpected exceptions to error results
    cleaned: list[dict] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            batch = batches[i]
            logger.error("Unexpected error in batch %s-%d: %s", batch["agent_id"], batch["batch_index"], r)
            cleaned.append({
                "agent_id": batch["agent_id"],
                "batch_index": batch["batch_index"],
                "status": "error",
                "error": str(r),
                "results": [
                    {
                        "holding_id": h.get("holding_id"),
                        "status": "AGENT_UNAVAILABLE",
                        "error": str(r),
                        "output": AgentOutput(
                            agent_id=batch["agent_id"],
                            reasoning_summary=f"Batch execution error: {r}",
                            flags=["AGENT_UNAVAILABLE"],
                            confidence=0.0,
                        ).model_dump(mode="json"),
                    }
                    for h in batch["holdings"]
                ],
            })
        else:
            cleaned.append(r)

    return cleaned
