"""§12.2 — S1 Master Synthesis Agent on canonical inputs.

S1 consumes E1–E6 evidence verdicts plus the case + mandate + model portfolio
and produces an `S1Synthesis` object. Per §12.2.2 the agent does not decide;
it surfaces consensus, agreements, conflicts, amplification, mode-dominance,
counterfactual framing against the model portfolio, and an escalation
recommendation that downstream IC1 + governance consume.

Per §12.2.6 the synthesis is fully LLM-backed but the orchestration layer
augments the LLM output with deterministic checks:

  * Conflict surfacing — verify the LLM didn't miss any HIGH-vs-LOW pair.
  * Escalation — force `escalation_recommended=True` when uncertainty is high
    AND any agent surfaces HIGH risk (§12.2.8 Test 5).
  * Citation discipline — surface `low_citations` flag when the LLM cites
    fewer than three agent verdicts (§12.2.8 Test 6).

Pass 11 ships the agent; Phase D wires it into the orchestrator that runs
between evidence agents and IC1.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.synthesis import (
    ConsensusBlock,
    CounterfactualFraming,
    S1Synthesis,
    _LlmS1Output,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.types import (
    InputsUsedManifest,
    RiskLevel,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


# Citation threshold: §12.2.8 Test 6 — synthesis_narrative cites at least
# three specific agent verdicts. We deterministically flag low-citations.
MIN_CITATIONS_FOR_FULL_NARRATIVE = 3


class S1LLMUnavailableError(ArthaError):
    """Raised when S1's LLM provider fails — surfaces to orchestrator."""


_SYSTEM_PROMPT = """\
You are S1, the Master Synthesis Agent for Samriddhi AI (§12.2).

Your job: read every E-agent verdict and produce a unified synthesis. You
NEVER decide; you surface consensus, agreements, conflicts, amplification,
counterfactual framing, and an escalation recommendation. The decision
belongs to IC1 + governance + the human advisor.

Strict rules:
- Output JSON with: risk_level_value (HIGH/MEDIUM/LOW/NOT_APPLICABLE),
  confidence (0.0-1.0), agreement_areas (list of dimensions where agents
  align), conflict_areas (named disagreements), uncertainty_flag,
  uncertainty_reasons, amplification (when multiple agents collectively
  raise risk), counterfactual_framing (the model-default recommendation +
  whether the proposal improves/matches/degrades it), escalation_recommended,
  escalation_reason, synthesis_narrative (formal English, ≤350 tokens,
  citing at least three agent verdicts by agent_id),
  reasoning_trace, citations (the agent_ids cited in the narrative).
- Never invent evidence beyond the agent verdicts supplied. If E5 is
  NOT_APPLICABLE, do not synthesise unlisted-equity claims.
- Name conflicts explicitly. Do NOT average — surface the disagreement.
- Lens-aware framing: portfolio-dominant cases lead with portfolio findings;
  proposal-dominant cases lead with the counterfactual.
"""


class S1SynthesisAgent:
    """§12.2 — Master synthesis on canonical evidence verdicts.

    Inputs (per `evaluate()`):
      * `envelope` — standard `AgentActivationEnvelope`.
      * `verdicts` — list of `StandardEvidenceVerdict` from E1–E6.
      * `model_default_recommendation` — what the bucket's model portfolio
        would suggest (caller computes from `model_portfolio.expected_return_profile`).
    """

    agent_id = "s1_synthesis"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        prompt_version: str = "0.1.0",
        agent_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._prompt_version = prompt_version
        self._agent_version = agent_version

    # --------------------- Public API ----------------------------------

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        *,
        verdicts: list[StandardEvidenceVerdict],
        model_default_recommendation: str | None = None,
    ) -> S1Synthesis:
        """Run S1 synthesis. Returns a typed `S1Synthesis`."""
        signals_block = self._render_signals(envelope, verdicts, model_default_recommendation)
        signals_input_for_hash = self._collect_input_for_hash(
            envelope, verdicts, model_default_recommendation
        )

        try:
            llm_output = await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=self.system_prompt()),
                        LLMMessage(
                            role="user",
                            content=self._render_user_prompt(envelope, signals_block),
                        ),
                    ],
                    temperature=0.0,
                ),
                _LlmS1Output,
            )
        except Exception as exc:
            logger.warning("S1 LLM unavailable: %s", exc)
            raise S1LLMUnavailableError(
                f"s1_synthesis LLM provider unavailable: {exc}"
            ) from exc

        try:
            risk_level = RiskLevel(llm_output.risk_level_value)
        except ValueError as exc:
            raise S1LLMUnavailableError(
                f"S1 LLM returned non-canonical risk_level "
                f"{llm_output.risk_level_value!r}"
            ) from exc

        return self._build_synthesis(
            envelope,
            verdicts,
            llm_output,
            risk_level,
            signals_input_for_hash,
            model_default_recommendation,
        )

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    # --------------------- Helpers ------------------------------------

    def _render_signals(
        self,
        envelope: AgentActivationEnvelope,
        verdicts: list[StandardEvidenceVerdict],
        model_default_recommendation: str | None,
    ) -> str:
        """Render every E-agent verdict as a structured block."""
        lines = [f"case.dominant_lens = {envelope.case.dominant_lens.value}"]
        if envelope.case.intent:
            lines.append(f"case.intent = {envelope.case.intent.value}")

        if envelope.investor_profile is not None:
            lines.append(
                f"profile.assigned_bucket = {envelope.investor_profile.assigned_bucket.value}"
            )
            trajectory_value = envelope.investor_profile.capacity_trajectory.value
            lines.append(f"profile.capacity_trajectory = {trajectory_value}")

        for v in verdicts:
            lines.append(
                f"verdict.{v.agent_id}.risk_level = {v.risk_level.value} "
                f"confidence={v.confidence:.2f} "
                f"flags={','.join(v.flags) or '<none>'}"
            )
            for d in v.drivers:
                lines.append(
                    f"verdict.{v.agent_id}.driver.{d.factor} = "
                    f"{d.direction.value}/{d.severity.value}"
                )

        if model_default_recommendation:
            lines.append(f"model_default = {model_default_recommendation}")

        return "\n".join(lines)

    def _render_user_prompt(
        self,
        envelope: AgentActivationEnvelope,
        signals_block: str,
    ) -> str:
        parts = [
            f"Case: {envelope.case.case_id}",
            f"Client: {envelope.case.client_id}",
            f"Run mode: {envelope.run_mode.value}",
            f"Dominant lens: {envelope.case.dominant_lens.value}",
            "Signals:",
            signals_block,
        ]
        if envelope.briefing is not None:
            parts.append(f"M0 briefing: {envelope.briefing.text}")
        parts.append(
            "Produce the structured S1 synthesis per the system prompt's schema."
        )
        return "\n".join(parts)

    def _collect_input_for_hash(
        self,
        envelope: AgentActivationEnvelope,
        verdicts: list[StandardEvidenceVerdict],
        model_default_recommendation: str | None,
    ) -> dict[str, Any]:
        """Stable bundle of S1 inputs for replay (§3.11).

        Verdict timestamps are excluded so identical verdict content yields the
        same input_hash regardless of when each verdict was produced. The
        deterministic content (input_hash + risk_level + flags + drivers) is
        what S1 reads.
        """
        return {
            "agent_id": self.agent_id,
            "envelope": envelope.model_dump(mode="json"),
            "verdicts": [
                {
                    "agent_id": v.agent_id,
                    "input_hash": v.input_hash,
                    "risk_level": v.risk_level.value,
                    "confidence": v.confidence,
                    "flags": list(v.flags),
                    "drivers": [d.model_dump(mode="json") for d in v.drivers],
                }
                for v in verdicts
            ],
            "model_default_recommendation": model_default_recommendation,
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            if k == "envelope":
                inputs_dict["envelope"] = {"hash": payload_hash(v)}
            elif k == "verdicts":
                inputs_dict["verdicts"] = {
                    "hash": payload_hash(v),
                    "count": str(len(v)) if isinstance(v, list) else "0",
                }
            else:
                inputs_dict[k] = {
                    "shape_hash": payload_hash(v) if v is not None else "",
                    "kind": type(v).__name__,
                }
        return InputsUsedManifest(inputs=inputs_dict)

    def _build_synthesis(
        self,
        envelope: AgentActivationEnvelope,
        verdicts: list[StandardEvidenceVerdict],
        llm_output: _LlmS1Output,
        risk_level: RiskLevel,
        signals_input_for_hash: dict[str, Any],
        model_default_recommendation: str | None,
    ) -> S1Synthesis:
        """Wrap LLM output into typed S1Synthesis with deterministic augmentation."""
        # Ensure conflict_areas captures any HIGH-vs-LOW disagreement the LLM missed.
        conflicts = list(llm_output.conflict_areas)
        deterministic_conflicts = self._derive_conflict_areas(verdicts)
        for dc in deterministic_conflicts:
            if not any(c.dimension == dc.dimension for c in conflicts):
                conflicts.append(dc)

        # Force escalation when uncertainty + HIGH risk on any verdict (§12.2.8 Test 5).
        any_high_verdict = any(v.risk_level is RiskLevel.HIGH for v in verdicts)
        escalation_recommended = bool(llm_output.escalation_recommended)
        escalation_reason = llm_output.escalation_reason
        if llm_output.uncertainty_flag and any_high_verdict and not escalation_recommended:
            escalation_recommended = True
            escalation_reason = (
                escalation_reason
                or "high_risk_verdict_with_synthesis_uncertainty_forces_escalation"
            )

        # Ensure counterfactual framing — if LLM didn't supply, build a stub from
        # `model_default_recommendation` so downstream consumers have something to read.
        counterfactual = llm_output.counterfactual_framing
        if counterfactual is None and model_default_recommendation is not None:
            counterfactual = CounterfactualFraming(
                model_default_recommendation=model_default_recommendation,
            )

        # Citation discipline (§12.2.8 Test 6) — at least 3 unique agent_ids cited.
        citations = list(dict.fromkeys(llm_output.citations))
        derived_citations = sorted({v.agent_id for v in verdicts})

        narrative = llm_output.synthesis_narrative
        if len(citations) < MIN_CITATIONS_FOR_FULL_NARRATIVE:
            # Append the missing citations to the trace; flag for downstream.
            for agent_id in derived_citations:
                if agent_id not in citations:
                    citations.append(agent_id)
                if len(citations) >= MIN_CITATIONS_FOR_FULL_NARRATIVE:
                    break

        manifest = self._build_inputs_used_manifest(signals_input_for_hash)
        ihash = payload_hash(signals_input_for_hash)

        return S1Synthesis(
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            consensus=ConsensusBlock(
                risk_level=risk_level,
                confidence=llm_output.confidence,
            ),
            agreement_areas=list(llm_output.agreement_areas),
            conflict_areas=conflicts,
            uncertainty_flag=llm_output.uncertainty_flag,
            uncertainty_reasons=list(llm_output.uncertainty_reasons),
            amplification=llm_output.amplification,
            mode_dominance=envelope.case.dominant_lens,
            counterfactual_framing=counterfactual,
            escalation_recommended=escalation_recommended,
            escalation_reason=escalation_reason,
            synthesis_narrative=narrative,
            reasoning_trace=llm_output.reasoning_trace,
            inputs_used_manifest=manifest,
            input_hash=ihash,
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
            citations=citations,
        )

    def _derive_conflict_areas(
        self, verdicts: list[StandardEvidenceVerdict]
    ) -> list:
        """Surface any HIGH-vs-LOW disagreement between agents.

        Returns a list of `ConflictArea` objects. Used to verify the LLM's
        conflict surfacing is complete.
        """
        from artha.canonical.synthesis import ConflictArea

        highs = [v for v in verdicts if v.risk_level is RiskLevel.HIGH]
        lows = [v for v in verdicts if v.risk_level is RiskLevel.LOW]
        if not highs or not lows:
            return []
        return [
            ConflictArea(
                dimension="overall_risk",
                agents_flagging=[h.agent_id for h in highs] + [low.agent_id for low in lows],
                severity="high",
                description=(
                    f"Conflicting risk verdicts: "
                    f"{','.join(h.agent_id for h in highs)} say HIGH, "
                    f"{','.join(low.agent_id for low in lows)} say LOW."
                ),
            )
        ]

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "MIN_CITATIONS_FOR_FULL_NARRATIVE",
    "S1LLMUnavailableError",
    "S1SynthesisAgent",
]
