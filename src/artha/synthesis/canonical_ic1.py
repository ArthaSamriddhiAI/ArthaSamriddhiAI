"""§12.3 — IC1 Investment Committee Agent.

IC1 has two parts:

  1. `IC1MaterialityGate` — deterministic gate (§12.3.2). It fires on
     case-pipeline cases when materiality conditions trip (ticket size
     threshold, product complexity, S1 amplification/conflict flag, advisor
     request, firm policy); fires on nearly all construction-pipeline cases.

  2. `IC1Agent` — when the gate fires, run four LLM-backed sub-roles
     (chair, devil's advocate, risk assessor, minutes recorder) over the
     S1 synthesis + case bundle, producing an `IC1Deliberation`.

Per §12.3.6, `escalation_to_human=True` is always emitted — IC1 never
produces an autonomous decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.case import CaseObject
from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.synthesis import (
    CommitteePosition,
    DissentPoint,
    IC1Deliberation,
    IC1SubRole,
    MaterialityGateBlock,
    S1Synthesis,
    SubRoleContribution,
    _LlmIC1SubRoleOutput,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.types import (
    InputsUsedManifest,
    INRAmountField,
    MaterialityGateResult,
    Recommendation,
    RunMode,
    VehicleType,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


# ===========================================================================
# Defaults — firms can override per §12.3.2
# ===========================================================================

# Ticket-size threshold above which IC1 fires by default (₹50L).
DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR: float = 5_000_000.0

# Vehicle types whose structural complexity warrants IC1 by default.
_COMPLEX_VEHICLES_FOR_IC1: frozenset[VehicleType] = frozenset(
    {
        VehicleType.AIF_CAT_1,
        VehicleType.AIF_CAT_2,
        VehicleType.AIF_CAT_3,
        VehicleType.SIF,
        VehicleType.UNLISTED_EQUITY,
        VehicleType.PMS,
    }
)


class IC1LLMUnavailableError(ArthaError):
    """Raised when an IC1 sub-role's LLM provider fails."""


# ===========================================================================
# IC1MaterialityGate
# ===========================================================================


class MaterialityInputs(BaseModel):
    """§12.3.2 — explicit inputs the materiality gate reads.

    Pulled from S1 synthesis + case + firm policy. Pass 11 carries an
    in-process container; Phase D wires this through the orchestration layer.
    """

    model_config = ConfigDict(extra="forbid")

    advisor_requested: bool = False
    firm_policy_force_convene: bool = False
    ticket_size_inr: INRAmountField | None = None
    proposed_vehicle_type: VehicleType | None = None
    s1_amplification_present: bool = False
    s1_conflict_present: bool = False
    s1_escalation_recommended: bool = False
    s1_uncertainty_flag: bool = False


@dataclass(frozen=True)
class MaterialityDecision:
    """Result of the deterministic gate."""

    fired: MaterialityGateResult
    signals: list[str] = field(default_factory=list)
    rationale: str = ""


class IC1MaterialityGate:
    """§12.3.2 — deterministic gate that decides whether IC1 deliberates.

    Construction:
      * `ticket_threshold_inr` — firm-overridable ticket-size cutoff.
      * `complex_vehicles` — firm-overridable set of vehicles.
      * `force_convene_in_construction` — convene on construction-pipeline cases by default.
    """

    def __init__(
        self,
        *,
        ticket_threshold_inr: float = DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR,
        complex_vehicles: frozenset[VehicleType] | None = None,
        force_convene_in_construction: bool = True,
    ) -> None:
        self._ticket_threshold = ticket_threshold_inr
        self._complex_vehicles = complex_vehicles or _COMPLEX_VEHICLES_FOR_IC1
        self._force_convene_in_construction = force_convene_in_construction

    def evaluate(
        self,
        *,
        run_mode: RunMode,
        inputs: MaterialityInputs,
    ) -> MaterialityDecision:
        signals: list[str] = []

        if (
            self._force_convene_in_construction
            and run_mode is RunMode.CONSTRUCTION
        ):
            signals.append("construction_pipeline")

        if inputs.advisor_requested:
            signals.append("advisor_requested")

        if inputs.firm_policy_force_convene:
            signals.append("firm_policy_force_convene")

        if (
            inputs.ticket_size_inr is not None
            and inputs.ticket_size_inr >= self._ticket_threshold
        ):
            signals.append("ticket_size_above_threshold")

        if (
            inputs.proposed_vehicle_type is not None
            and inputs.proposed_vehicle_type in self._complex_vehicles
        ):
            signals.append("complex_vehicle_proposal")

        if inputs.s1_amplification_present:
            signals.append("s1_amplification_present")

        if inputs.s1_conflict_present:
            signals.append("s1_conflict_present")

        if inputs.s1_escalation_recommended:
            signals.append("s1_escalation_recommended")

        if inputs.s1_uncertainty_flag:
            signals.append("s1_uncertainty_flag")

        if signals:
            return MaterialityDecision(
                fired=MaterialityGateResult.CONVENE,
                signals=signals,
                rationale=f"Materiality gate convenes IC1 on signals: {', '.join(signals)}.",
            )
        return MaterialityDecision(
            fired=MaterialityGateResult.SKIP,
            signals=[],
            rationale="No materiality signals tripped; IC1 skipped.",
        )


# ===========================================================================
# IC1Agent — convenes when the gate fires
# ===========================================================================


_CHAIR_PROMPT = """\
You are the IC1 Chair (§12.3.4) for Samriddhi AI.

Your job: frame the deliberation. Read the S1 synthesis + evidence verdicts
and produce a one-paragraph framing of the decision question, what's at
stake, and which dimensions the committee must adjudicate.

Output JSON: contribution (your framing, ≤200 tokens), citations (agent_ids
you cite), proposed_recommendation (proceed | modify | do_not_proceed |
defer — your initial leaning), proposed_conditions (if modify), dissent_point
(null — you are not the dissenter).

Cite evidence verdicts; do not invent claims.
"""

_DEVILS_ADVOCATE_PROMPT = """\
You are the IC1 Devil's Advocate (§12.3.4).

Your job: argue against the prevailing synthesis. Find at least one
concrete dissent point that would change the recommendation, even if you
don't believe it. Per §12.3.9 Test 2, dissent must surface in ≥95% of
fired cases.

Output JSON: contribution (your dissent, ≤200 tokens), citations,
proposed_recommendation (your alternative), proposed_conditions,
dissent_point (the structured dissent — required, must be non-null).

Cite specific risk drivers; never argue against evidence by inventing
counter-evidence.
"""

_RISK_ASSESSOR_PROMPT = """\
You are the IC1 Risk Assessor (§12.3.4).

Your job: aggregate the risk perspectives. Identify the most material risks
and how they aggregate against the case's mandate. Surface any structural
risk the synthesis layer missed.

Output JSON: contribution (≤200 tokens), citations, proposed_recommendation,
proposed_conditions (concrete risk-mitigation conditions if recommendation
is modify), dissent_point (null or your specific risk-based dissent).
"""

_MINUTES_RECORDER_PROMPT = """\
You are the IC1 Minutes Recorder (§12.3.4).

Your job: capture the deliberation. Read the chair, devil's advocate, and
risk assessor contributions and produce a faithful summary of what each
contributed and the committee's converged position.

Output JSON: contribution (the minutes, ≤300 tokens), citations
(agent_ids referenced in the minutes), proposed_recommendation (the
committee's converged recommendation), proposed_conditions (the final
condition list when modify), dissent_point (null — you are not the
dissenter).

Never embellish. Capture verbatim; replay must reconstruct the meeting.
"""


# Each sub-role's (prompt, role-enum) pairing.
_SUB_ROLE_PROMPTS: dict[IC1SubRole, str] = {
    IC1SubRole.CHAIR: _CHAIR_PROMPT,
    IC1SubRole.DEVILS_ADVOCATE: _DEVILS_ADVOCATE_PROMPT,
    IC1SubRole.RISK_ASSESSOR: _RISK_ASSESSOR_PROMPT,
    IC1SubRole.MINUTES_RECORDER: _MINUTES_RECORDER_PROMPT,
}


class IC1Agent:
    """§12.3 — IC1 deliberation agent.

    Construction:
      * `provider` — LLM provider for sub-role activations.
      * `gate` — defaults to `IC1MaterialityGate()`; inject for tests.

    Inputs to `evaluate()`:
      * `envelope` — `AgentActivationEnvelope`.
      * `s1_synthesis` — the upstream S1 output.
      * `verdicts` — list of `StandardEvidenceVerdict` (E1–E6).
      * `materiality_inputs` — populated by the orchestrator from S1 +
        case + firm policy.
    """

    agent_id = "ic1_deliberation"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        gate: IC1MaterialityGate | None = None,
        prompt_version: str = "0.1.0",
        agent_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._gate = gate or IC1MaterialityGate()
        self._prompt_version = prompt_version
        self._agent_version = agent_version

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        *,
        s1_synthesis: S1Synthesis,
        verdicts: list[StandardEvidenceVerdict],
        materiality_inputs: MaterialityInputs | None = None,
    ) -> IC1Deliberation:
        """Run the gate then (if convened) the four sub-roles."""
        materiality_inputs = materiality_inputs or self._derive_materiality_inputs(
            envelope.case, s1_synthesis
        )
        gate_decision = self._gate.evaluate(
            run_mode=envelope.run_mode, inputs=materiality_inputs
        )

        signals_input_for_hash = self._collect_input_for_hash(
            envelope, s1_synthesis, verdicts, materiality_inputs, gate_decision
        )
        manifest = self._build_inputs_used_manifest(signals_input_for_hash)
        ihash = payload_hash(signals_input_for_hash)

        if gate_decision.fired is MaterialityGateResult.SKIP:
            # Return a SKIP-tier IC1 with no deliberation; recommendation comes
            # from S1 indirectly (Pass 11 leaves this as DEFER until M0.Stitcher
            # reconciles; per §12.3.6 IC1 never decides anyway).
            return IC1Deliberation(
                case_id=envelope.case.case_id,
                timestamp=self._now(),
                run_mode=envelope.run_mode,
                materiality_gate_result=MaterialityGateBlock(
                    fired=MaterialityGateResult.SKIP,
                    signals=[],
                    rationale=gate_decision.rationale,
                ),
                committee_position=CommitteePosition.CONSENSUS,
                recommendation=Recommendation.PROCEED,
                dissent_recorded=[],
                conditions=[],
                minutes=[],
                escalation_to_human=True,
                reasoning_trace=(
                    "Materiality gate skipped IC1; the case proceeds without a "
                    "convened committee. Human advisor still owns the final decision."
                ),
                inputs_used_manifest=manifest,
                input_hash=ihash,
                prompt_version=self._prompt_version,
                agent_version=self._agent_version,
            )

        # Gate fired → run four sub-roles sequentially (the minutes recorder
        # reads earlier sub-roles' output).
        contributions: list[SubRoleContribution] = []
        sub_outputs: dict[IC1SubRole, _LlmIC1SubRoleOutput] = {}

        for sub_role in (
            IC1SubRole.CHAIR,
            IC1SubRole.DEVILS_ADVOCATE,
            IC1SubRole.RISK_ASSESSOR,
            IC1SubRole.MINUTES_RECORDER,
        ):
            try:
                output = await self._run_sub_role(
                    envelope, s1_synthesis, verdicts, sub_role, sub_outputs
                )
            except Exception as exc:
                logger.warning("IC1 sub-role %s failed: %s", sub_role.value, exc)
                raise IC1LLMUnavailableError(
                    f"IC1 sub-role {sub_role.value} unavailable: {exc}"
                ) from exc

            sub_outputs[sub_role] = output
            contributions.append(
                SubRoleContribution(
                    sub_role=sub_role,
                    contribution=output.contribution,
                    citations=list(output.citations),
                )
            )

        # Aggregate dissent from chair / devil's advocate / risk assessor (the
        # minutes recorder is summary-only).
        dissent_recorded: list[DissentPoint] = []
        for role in (IC1SubRole.CHAIR, IC1SubRole.DEVILS_ADVOCATE, IC1SubRole.RISK_ASSESSOR):
            sub = sub_outputs.get(role)
            if sub is not None and sub.dissent_point:
                dissent_recorded.append(
                    DissentPoint(
                        dissent_point=sub.dissent_point,
                        source_role=role,
                        reasoning=sub.contribution[:500],
                    )
                )

        # Recommendation comes from the minutes recorder (the committee's
        # converged position). Fall back to chair's leaning, then DEFER.
        minutes_recorder_output = sub_outputs.get(IC1SubRole.MINUTES_RECORDER)
        chair_output = sub_outputs.get(IC1SubRole.CHAIR)
        recommendation = self._resolve_recommendation(
            minutes_recorder_output, chair_output
        )
        conditions_source = (
            minutes_recorder_output
            or chair_output
            or sub_outputs[IC1SubRole.RISK_ASSESSOR]
        )
        conditions = list(conditions_source.proposed_conditions)
        if recommendation is not Recommendation.MODIFY:
            conditions = []  # conditions only meaningful on MODIFY

        # Committee position: split if any sub-role's proposed_recommendation
        # differs from the converged recommendation.
        position = CommitteePosition.CONSENSUS
        for sub in sub_outputs.values():
            if (
                sub.proposed_recommendation
                and sub.proposed_recommendation != recommendation.value
            ):
                position = CommitteePosition.SPLIT
                break

        # Compose reasoning_trace from each sub-role's contribution.
        trace = "\n\n".join(
            f"[{c.sub_role.value}] {c.contribution}" for c in contributions
        )

        return IC1Deliberation(
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            materiality_gate_result=MaterialityGateBlock(
                fired=MaterialityGateResult.CONVENE,
                signals=list(gate_decision.signals),
                rationale=gate_decision.rationale,
            ),
            committee_position=position,
            recommendation=recommendation,
            dissent_recorded=dissent_recorded,
            conditions=conditions,
            minutes=contributions,
            escalation_to_human=True,
            reasoning_trace=trace,
            inputs_used_manifest=manifest,
            input_hash=ihash,
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
        )

    # --------------------- Helpers ----------------------------------

    def _derive_materiality_inputs(
        self,
        case: CaseObject,
        s1_synthesis: S1Synthesis,
    ) -> MaterialityInputs:
        """Build a `MaterialityInputs` from case + S1 if caller didn't supply one."""
        proposed_vt: VehicleType | None = None
        ticket_size: float | None = None
        if case.proposed_action is not None:
            ticket_size = case.proposed_action.ticket_size_inr
            if case.proposed_action.structure:
                try:
                    proposed_vt = VehicleType(case.proposed_action.structure)
                except ValueError:
                    proposed_vt = None

        return MaterialityInputs(
            ticket_size_inr=ticket_size,
            proposed_vehicle_type=proposed_vt,
            s1_amplification_present=(
                s1_synthesis.amplification is not None
                and s1_synthesis.amplification.present
            ),
            s1_conflict_present=bool(s1_synthesis.conflict_areas),
            s1_escalation_recommended=s1_synthesis.escalation_recommended,
            s1_uncertainty_flag=s1_synthesis.uncertainty_flag,
        )

    async def _run_sub_role(
        self,
        envelope: AgentActivationEnvelope,
        s1_synthesis: S1Synthesis,
        verdicts: list[StandardEvidenceVerdict],
        sub_role: IC1SubRole,
        prior_outputs: dict[IC1SubRole, _LlmIC1SubRoleOutput],
    ) -> _LlmIC1SubRoleOutput:
        """Activate one sub-role's LLM and parse the structured output."""
        prompt = _SUB_ROLE_PROMPTS[sub_role]
        signals_block = self._render_signals(s1_synthesis, verdicts, prior_outputs)
        user_text = self._render_user_prompt(envelope, sub_role, signals_block)

        return await self._provider.complete_structured(
            LLMRequest(
                messages=[
                    LLMMessage(role="system", content=prompt),
                    LLMMessage(role="user", content=user_text),
                ],
                temperature=0.0,
            ),
            _LlmIC1SubRoleOutput,
        )

    def _render_signals(
        self,
        s1_synthesis: S1Synthesis,
        verdicts: list[StandardEvidenceVerdict],
        prior_outputs: dict[IC1SubRole, _LlmIC1SubRoleOutput],
    ) -> str:
        lines: list[str] = []
        lines.append(
            f"s1.consensus.risk_level = {s1_synthesis.consensus.risk_level.value} "
            f"confidence={s1_synthesis.consensus.confidence:.2f}"
        )
        lines.append(
            f"s1.escalation_recommended = {s1_synthesis.escalation_recommended}"
        )
        lines.append(
            f"s1.uncertainty_flag = {s1_synthesis.uncertainty_flag}"
        )
        for c in s1_synthesis.conflict_areas:
            lines.append(
                f"s1.conflict.{c.dimension} = severity={c.severity} "
                f"agents={','.join(c.agents_flagging)}"
            )
        for v in verdicts:
            lines.append(
                f"verdict.{v.agent_id}.risk_level = {v.risk_level.value} "
                f"flags={','.join(v.flags) or '<none>'}"
            )

        # Show prior sub-role contributions for downstream sub-roles.
        for role, out in prior_outputs.items():
            lines.append(f"prior.{role.value}.contribution = {out.contribution[:200]}")
            if out.dissent_point:
                lines.append(f"prior.{role.value}.dissent = {out.dissent_point[:200]}")
            if out.proposed_recommendation:
                lines.append(
                    f"prior.{role.value}.proposed_recommendation = "
                    f"{out.proposed_recommendation}"
                )

        return "\n".join(lines)

    def _render_user_prompt(
        self,
        envelope: AgentActivationEnvelope,
        sub_role: IC1SubRole,
        signals_block: str,
    ) -> str:
        return "\n".join(
            [
                f"Case: {envelope.case.case_id}",
                f"Client: {envelope.case.client_id}",
                f"Sub-role: {sub_role.value}",
                f"Run mode: {envelope.run_mode.value}",
                f"Dominant lens: {envelope.case.dominant_lens.value}",
                "Signals:",
                signals_block,
                "Produce the structured sub-role contribution per the system prompt's schema.",
            ]
        )

    def _resolve_recommendation(
        self,
        minutes_output: _LlmIC1SubRoleOutput | None,
        chair_output: _LlmIC1SubRoleOutput | None,
    ) -> Recommendation:
        """Pick the converged recommendation from minutes; fall back to chair."""
        for src in (minutes_output, chair_output):
            if src is not None and src.proposed_recommendation:
                try:
                    return Recommendation(src.proposed_recommendation)
                except ValueError:
                    continue
        return Recommendation.DEFER

    def _collect_input_for_hash(
        self,
        envelope: AgentActivationEnvelope,
        s1_synthesis: S1Synthesis,
        verdicts: list[StandardEvidenceVerdict],
        materiality_inputs: MaterialityInputs,
        gate_decision: MaterialityDecision,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "envelope": envelope.model_dump(mode="json"),
            "s1_synthesis_input_hash": s1_synthesis.input_hash,
            "verdict_input_hashes": sorted(v.input_hash for v in verdicts),
            "materiality_inputs": materiality_inputs.model_dump(mode="json"),
            "gate_signals": list(gate_decision.signals),
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            if k == "envelope":
                inputs_dict["envelope"] = {"hash": payload_hash(v)}
            else:
                inputs_dict[k] = {"shape_hash": payload_hash(v)}
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "DEFAULT_MATERIALITY_TICKET_THRESHOLD_INR",
    "IC1Agent",
    "IC1LLMUnavailableError",
    "IC1MaterialityGate",
    "MaterialityDecision",
    "MaterialityInputs",
]
