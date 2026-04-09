"""Portfolio Analysis Orchestrator — the main PAM orchestration class.

Phases:
  Phase 1 (CPR): Comprehensive Portfolio Review
  Phase 2 (ISE): Investment Suggestion Engine
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.types import DecisionID
from artha.governance.agents.analysis.master.agent import MasterAnalysisAgent
from artha.governance.agents.base import AgentOutput
from artha.governance.intent.models import (
    GovernanceIntent,
    IntentSource,
    IntentType,
)
from artha.llm.base import LLMProvider
from artha.portfolio_analysis.ingestion.schema_validator import CanonicalPortfolio
from artha.portfolio_analysis.orchestrator.asset_class_classifier import classify_holdings
from artha.portfolio_analysis.orchestrator.batch_builder import build_batches
from artha.portfolio_analysis.orchestrator.context_condenser import condense_for_synthesis
from artha.portfolio_analysis.orchestrator.parallel_executor import execute_batches
from artha.portfolio_analysis.rebalancing.exit_proceeds_calculator import calculate_exit_proceeds
from artha.portfolio_analysis.telemetry.pam_event_types import record_pam_event

logger = logging.getLogger(__name__)


class PortfolioAnalysisOrchestrator:
    """Orchestrates the full portfolio analysis pipeline."""

    def __init__(self, session: AsyncSession, llm: LLMProvider) -> None:
        self._session = session
        self._llm = llm

    # ── Phase 1: Comprehensive Portfolio Review ──────────────────────

    async def run_phase1_cpr(
        self, portfolio: CanonicalPortfolio, client_profile: dict
    ) -> dict:
        """Phase 1: Comprehensive Portfolio Review.

        Steps:
          1. Classify holdings by agent
          2. Build batches
          3. Execute in parallel (financial_risk, unlisted_equity, pms_aif
             batches + single calls to industry_business, macro,
             behavioural_historical)
          4. Condense for S1
          5. Call master agent with mode=portfolio_review
          6. Record portfolio_review_complete telemetry event
          7. Return CPR dict with all 10 sections
        """
        review_id = str(uuid.uuid4())
        portfolio_id = client_profile.get("portfolio_id", review_id)
        client_id = client_profile.get("client_id", "unknown")

        holdings_dicts = [h.model_dump(mode="json") for h in portfolio.holdings]

        # 1. Classify holdings
        classified = classify_holdings(holdings_dicts)

        # 2. Build batches
        batches = build_batches(classified)

        # 3a. Execute holding-level batches in parallel
        batch_results = await execute_batches(batches, self._llm)

        # 3b. Run cross-portfolio agents (single call each, in parallel)
        cross_portfolio_context = {
            "mode": "portfolio_review",
            "portfolio_summary": {
                "total_aum": portfolio.total_value_inr,
                "holdings_count": len(portfolio.holdings),
                "asset_class_breakdown": [
                    ab.model_dump(mode="json") for ab in portfolio.asset_class_breakdown
                ],
            },
            "holdings": holdings_dicts,
            "client_profile": client_profile,
        }

        cross_agents = await self._run_cross_portfolio_agents(cross_portfolio_context)

        # 4. Condense for S1
        condensed = condense_for_synthesis(batch_results)

        # 5. Call master agent with mode=portfolio_review
        master = MasterAnalysisAgent(self._llm)

        # Build a synthetic intent for the master agent
        symbols = [
            h.isin_or_cin or h.instrument_name
            for h in portfolio.holdings
            if h.isin_or_cin
        ]
        intent = GovernanceIntent(
            intent_type=IntentType.RISK_REVIEW,
            source=IntentSource.HUMAN,
            initiator="pam_orchestrator",
            parameters={"mode": "portfolio_review", "review_id": review_id},
            symbols=symbols[:50],  # cap to avoid oversize
        )

        evidence_context: dict[str, Any] = {
            "mode": "portfolio_review",
            "review_id": review_id,
            "condensed_holdings": condensed,
            "cross_portfolio_analysis": {
                agent_id: out.model_dump(mode="json")
                for agent_id, out in cross_agents.items()
            },
            "portfolio_summary": cross_portfolio_context["portfolio_summary"],
            "client_profile": client_profile,
        }

        envelope = await master.run(intent, evidence_context)

        # 6. Build CPR with all 10 sections
        cpr = self._build_cpr(
            portfolio=portfolio,
            condensed=condensed,
            batch_results=batch_results,
            cross_agents=cross_agents,
            envelope=envelope,
            client_profile=client_profile,
            review_id=review_id,
        )

        # 7. Record telemetry
        decision_id = DecisionID(review_id)
        await record_pam_event(
            session=self._session,
            decision_id=decision_id,
            event_type="portfolio_review_complete",
            event_data={
                "portfolio_review_id": review_id,
                "portfolio_id": portfolio_id,
                "client_id": client_id,
                "canonical_portfolio": portfolio.model_dump(mode="json"),
                "agent_outputs": condensed,
                "cpr_sections": cpr,
                "component_versions": self._get_component_versions(),
                "data_quality_summary": portfolio.data_quality_summary.model_dump(mode="json"),
                "timestamp": get_clock().now().isoformat(),
            },
        )

        return cpr

    # ── Phase 2: Investment Suggestion Engine ────────────────────────

    async def run_phase2_ise(
        self, portfolio: CanonicalPortfolio, cpr: dict, review_id: str
    ) -> dict:
        """Phase 2: Investment Suggestion Engine.

        Steps:
          1. Calculate exit proceeds for HIGH/CRITICAL holdings
          2. Call master agent with mode=ise_generation
          3. For each suggestion: run through existing GovernancePipeline
          4. Filter: BLOCKED removed silently (logged), APPROVED/ESCALATION_REQUIRED kept
          5. Record suggestion_set_generated telemetry event
          6. Return filtered suggestion_set
        """
        from artha.governance.orchestrator.graph import GovernancePipeline
        from artha.portfolio_analysis.rebalancing.ltcg_calculator import (
            calculate_ltcg,
            load_ltcg_rates,
        )

        holdings_dicts = [h.model_dump(mode="json") for h in portfolio.holdings]

        # 1. Calculate exit proceeds for HIGH/CRITICAL holdings
        ltcg_rates = load_ltcg_rates()

        # Extract condensed risk info from CPR
        holding_risk_map = {}
        for section in cpr.get("sections", {}).values():
            if isinstance(section, dict) and "holding_assessments" in section:
                for assessment in section["holding_assessments"]:
                    hid = assessment.get("holding_id")
                    if hid:
                        holding_risk_map[hid] = assessment.get("risk_level", "medium")

        # Build minimal batch_results format for exit calculator
        synthetic_batch_results = [
            {
                "agent_id": "synthesis",
                "batch_index": 0,
                "status": "ok",
                "results": [
                    {
                        "holding_id": hid,
                        "status": "ok",
                        "output": {"risk_level": rl, "drivers": [], "flags": []},
                    }
                    for hid, rl in holding_risk_map.items()
                ],
            }
        ]

        exit_proceeds = calculate_exit_proceeds(
            holdings_dicts, synthetic_batch_results, ltcg_rates
        )

        # 2. Call master agent with mode=ise_generation
        master = MasterAnalysisAgent(self._llm)

        symbols = [
            h.isin_or_cin or h.instrument_name
            for h in portfolio.holdings
            if h.isin_or_cin
        ]
        intent = GovernanceIntent(
            intent_type=IntentType.TRADE_PROPOSAL,
            source=IntentSource.HUMAN,
            initiator="pam_orchestrator",
            parameters={"mode": "ise_generation", "review_id": review_id},
            symbols=symbols[:50],
        )

        evidence_context: dict[str, Any] = {
            "mode": "ise_generation",
            "review_id": review_id,
            "cpr": cpr,
            "exit_proceeds": exit_proceeds,
            "portfolio_summary": {
                "total_aum": portfolio.total_value_inr,
                "holdings_count": len(portfolio.holdings),
            },
        }

        envelope = await master.run(intent, evidence_context)

        # 3. For each suggestion — run through GovernancePipeline
        suggestions = self._extract_suggestions(envelope, exit_proceeds)
        pipeline = GovernancePipeline(self._session, self._llm)

        filtered_suggestions: list[dict] = []
        blocked_count = 0

        for suggestion in suggestions:
            # Create a GovernanceIntent per suggestion
            sug_intent = GovernanceIntent(
                intent_type=IntentType.TRADE_PROPOSAL,
                source=IntentSource.HUMAN,
                initiator="pam_ise",
                parameters={
                    "mode": "ise_suggestion",
                    "review_id": review_id,
                    "suggestion": suggestion,
                },
                symbols=[suggestion.get("symbol", "")],
                holdings={suggestion.get("symbol", ""): suggestion.get("target_weight", 0.0)},
            )

            try:
                state = await pipeline.run(sug_intent)
                status = state.get("status", "rejected")

                # 4. Filter
                if status == "rejected":
                    blocked_count += 1
                    logger.info(
                        "ISE suggestion BLOCKED: %s — %s",
                        suggestion.get("symbol"),
                        state.get("error", "rule violation"),
                    )
                else:
                    suggestion["governance_status"] = status
                    suggestion["decision_id"] = state.get("decision_id")
                    filtered_suggestions.append(suggestion)
            except Exception as e:
                logger.warning("Governance pipeline error for suggestion: %s", e)
                blocked_count += 1

        # 5. Record telemetry
        decision_id = DecisionID(review_id)
        suggestion_set = {
            "review_id": review_id,
            "suggestions": filtered_suggestions,
            "blocked_count": blocked_count,
            "total_redeployable_inr": exit_proceeds.get("total_redeployable_inr", 0.0),
            "exit_candidates": exit_proceeds.get("exit_candidates", []),
            "timestamp": get_clock().now().isoformat(),
        }

        await record_pam_event(
            session=self._session,
            decision_id=decision_id,
            event_type="suggestion_set_generated",
            event_data={
                "portfolio_review_id": review_id,
                "exit_candidates": exit_proceeds.get("exit_candidates", []),
                "total_redeployable_inr": exit_proceeds.get("total_redeployable_inr", 0.0),
                "suggestion_set": suggestion_set,
                "timestamp": get_clock().now().isoformat(),
            },
        )

        # 6. Return
        return suggestion_set

    # ── Private helpers ──────────────────────────────────────────────

    async def _run_cross_portfolio_agents(
        self, context: dict[str, Any]
    ) -> dict[str, AgentOutput]:
        """Run industry_business, macro, and behavioural_historical agents."""
        import asyncio

        from artha.governance.agents.analysis.behavioural_historical.agent import (
            BehaviouralHistoricalAgent,
        )
        from artha.governance.agents.analysis.industry_business.agent import (
            IndustryBusinessAgent,
        )
        from artha.governance.agents.analysis.macro.agent import MacroAnalysisAgent

        agents: dict[str, Any] = {
            "industry_business": IndustryBusinessAgent(self._llm),
            "macro": MacroAnalysisAgent(self._llm),
            "behavioural_historical": BehaviouralHistoricalAgent(self._llm),
        }

        async def _run_one(agent_id: str, agent: Any) -> tuple[str, AgentOutput]:
            try:
                output = await agent.run(context)
                return agent_id, output
            except Exception as e:
                logger.warning("Cross-portfolio agent '%s' failed: %s", agent_id, e)
                return agent_id, AgentOutput(
                    agent_id=agent_id,
                    agent_name=agent_id,
                    reasoning_summary=f"Agent failed: {e}",
                    flags=["AGENT_UNAVAILABLE"],
                    confidence=0.0,
                )

        results = await asyncio.gather(
            *[_run_one(aid, a) for aid, a in agents.items()]
        )
        return dict(results)

    def _build_cpr(
        self,
        portfolio: CanonicalPortfolio,
        condensed: list[dict],
        batch_results: list[dict],
        cross_agents: dict[str, AgentOutput],
        envelope: Any,
        client_profile: dict,
        review_id: str,
    ) -> dict:
        """Build the 10-section CPR dict."""
        # Build holding-level assessments from condensed data
        holding_assessments = []
        for c in condensed:
            holding_match = next(
                (h for h in portfolio.holdings if h.holding_id == c["holding_id"]),
                None,
            )
            assessment = {
                "holding_id": c["holding_id"],
                "instrument_name": holding_match.instrument_name if holding_match else "Unknown",
                "asset_class": holding_match.asset_class.value if holding_match else "unknown",
                "risk_level": c["risk_level"],
                "top_drivers": c["top_2_drivers"],
                "flags": c["flags"],
            }
            holding_assessments.append(assessment)

        # Count risk distribution
        risk_dist = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for c in condensed:
            rl = c.get("risk_level", "medium")
            risk_dist[rl] = risk_dist.get(rl, 0) + 1

        sections = {
            # S1: Executive Summary
            "executive_summary": {
                "review_id": review_id,
                "client_name": client_profile.get("client_name", "N/A"),
                "review_date": get_clock().now().isoformat(),
                "total_aum": portfolio.total_value_inr,
                "holdings_count": len(portfolio.holdings),
                "overall_risk_level": envelope.overall_risk_level.value,
                "overall_confidence": envelope.overall_confidence,
                "synthesis_summary": envelope.synthesis_summary,
                "key_drivers": envelope.key_drivers[:5],
            },
            # S2: Asset Allocation Analysis
            "asset_allocation": {
                "breakdown": [
                    ab.model_dump(mode="json") for ab in portfolio.asset_class_breakdown
                ],
                "concentration_flags": [
                    f for f in envelope.flags if "concentration" in f.lower()
                ],
            },
            # S3: Risk Assessment Summary
            "risk_assessment": {
                "risk_distribution": risk_dist,
                "high_risk_holdings": [
                    a for a in holding_assessments
                    if a["risk_level"] in ("high", "critical")
                ],
                "overall_risk_level": envelope.overall_risk_level.value,
            },
            # S4: Individual Holding Analysis
            "holding_analysis": {
                "holding_assessments": holding_assessments,
            },
            # S5: Industry & Business Environment
            "industry_business": self._agent_section(
                cross_agents.get("industry_business")
            ),
            # S6: Macro Environment
            "macro_environment": self._agent_section(
                cross_agents.get("macro")
            ),
            # S7: Behavioural & Historical Patterns
            "behavioural_historical": self._agent_section(
                cross_agents.get("behavioural_historical")
            ),
            # S8: Data Quality & Gaps
            "data_quality": portfolio.data_quality_summary.model_dump(mode="json"),
            # S9: Conflicts & Divergences
            "conflicts": {
                "agent_conflicts": envelope.conflicts,
                "flags": envelope.flags,
            },
            # S10: Recommended Actions
            "recommended_actions": {
                "actions": [
                    a.model_dump(mode="json") for a in envelope.recommended_actions
                ],
                "classification_reasoning": envelope.classification_reasoning,
            },
        }

        return {
            "review_id": review_id,
            "version": "1.0",
            "generated_at": get_clock().now().isoformat(),
            "sections": sections,
        }

    def _agent_section(self, output: AgentOutput | None) -> dict:
        """Convert an AgentOutput into a CPR section dict."""
        if output is None:
            return {"status": "not_available", "summary": "", "drivers": [], "flags": []}
        return {
            "status": "ok",
            "agent_id": output.agent_id,
            "agent_name": output.agent_name,
            "risk_level": output.risk_level.value,
            "confidence": output.confidence,
            "summary": output.reasoning_summary,
            "drivers": output.drivers,
            "flags": output.flags,
        }

    def _extract_suggestions(self, envelope: Any, exit_proceeds: dict) -> list[dict]:
        """Extract tradeable suggestions from the master agent's ISE output."""
        suggestions: list[dict] = []

        for action in envelope.recommended_actions:
            suggestions.append({
                "symbol": action.symbol,
                "action": action.action,
                "target_weight": action.target_weight,
                "rationale": action.rationale,
            })

        # If no actions from master, generate exit suggestions from exit candidates
        if not suggestions:
            for candidate in exit_proceeds.get("exit_candidates", []):
                suggestions.append({
                    "symbol": candidate.get("isin_or_cin") or candidate.get("instrument_name", ""),
                    "action": "sell",
                    "target_weight": 0.0,
                    "rationale": f"Exit candidate: risk_level={candidate.get('risk_level', 'high')}, "
                                 f"net_proceeds={candidate.get('net_proceeds', 0):.0f}",
                })

        return suggestions

    def _get_component_versions(self) -> dict:
        """Return version info for all PAM components used in this run."""
        return {
            "pam_orchestrator": "1.0.0",
            "spreadsheet_parser": "1.0.0",
            "ecas_parser": "1.0.0",
            "asset_class_classifier": "1.0.0",
            "batch_builder": "1.0.0",
            "parallel_executor": "1.0.0",
            "context_condenser": "1.0.0",
            "ltcg_calculator": "1.0.0",
            "exit_proceeds_calculator": "1.0.0",
        }
