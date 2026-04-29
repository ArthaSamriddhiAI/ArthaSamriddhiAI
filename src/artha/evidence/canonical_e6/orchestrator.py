"""§11.7.7–11.7.8 — E6 orchestrator + final RecommendationSynthesis.

The orchestrator coordinates the E6 sub-agent network end-to-end:

  1. Run the deterministic structural-flag gate (§11.7.1).
  2. Identify which product sub-agents to fire from the proposed action and
     existing holdings.
  3. Run product sub-agents in parallel (LLM-backed).
  4. Run shared sub-agents (FeeNormalisation / CascadeEngine / LiquidityManager
     — deterministic helpers).
  5. Hand the structured roll-up to the LLM-backed `RecommendationSynthesis`
     so it produces the final E6Verdict (drivers / flags / reasoning_trace).

If the gate is HARD_BLOCK or SOFT_BLOCK, the orchestrator can short-circuit
the product sub-agent stage (§11.7.1: gate-only verdicts are valid). The
shared sub-agents still run because they are inputs to the synthesis layer
that consumers (S1, A1) read independently.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import (
    CascadeAssessment,
    E6Verdict,
    FundRiskScore,
    FundRiskScores,
    LiquidityManagerOutput,
    NormalisedReturns,
    StandardEvidenceVerdict,
    SuitabilityCondition,
    TaxYearProjection,
    _LlmEvidenceCore,
)
from artha.canonical.holding import CascadeEvent, Holding
from artha.canonical.l4_manifest import FeeSchedule, FundUniverseL4Entry
from artha.common.hashing import payload_hash
from artha.common.types import (
    Driver,
    DriverDirection,
    DriverSeverity,
    GateResult,
    RiskLevel,
    VehicleType,
)
from artha.evidence.canonical_base import (
    CanonicalEvidenceAgent,
    EvidenceLLMUnavailableError,
)
from artha.evidence.canonical_e6.gate import E6Gate, GateDecision
from artha.evidence.canonical_e6.product_subagents import (
    PRODUCT_SUBAGENT_REGISTRY,
    E6ProductSubAgent,
)
from artha.evidence.canonical_e6.shared_subagents import (
    compute_cascade_assessment,
    compute_liquidity_manager_output,
    compute_normalised_returns,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest
from artha.portfolio_analysis.canonical_metrics import HoldingCommitment

logger = logging.getLogger(__name__)


# ===========================================================================
# Synthesis input bundle
# ===========================================================================


class E6OrchestratorInputs(BaseModel):
    """Optional inputs for E6's deterministic helpers + synthesis prompt.

    The orchestrator's `evaluate()` accepts this bundle as kwargs (or builds
    one internally from defaults). Keeping it as a BaseModel makes the
    contract explicit and gives consumers a stable type for tests.
    """

    model_config = ConfigDict(extra="forbid")

    holdings: list[Holding] = Field(default_factory=list)
    holding_commitments: dict[str, HoldingCommitment] = Field(default_factory=dict)
    proposed_l4_entry: FundUniverseL4Entry | None = None
    proposed_fee_schedule: FeeSchedule | None = None
    proposed_gross_return: float | None = None
    proposed_tax_rate: float = 0.0
    counterfactual_model_portfolio_return: float | None = None
    cash_flow_schedule: list[CascadeEvent] = Field(default_factory=list)
    deployment_modelling: dict[str, float] = Field(default_factory=dict)
    most_liquid_bucket_share: float = 0.0
    mandate_liquidity_floor: float = 0.0
    proposed_uncalled_inr: float = 0.0
    forcing_function_disclosures: list[str] = Field(default_factory=list)


# ===========================================================================
# Synthesis LLM output schema
# ===========================================================================


class _LlmSynthesisOutput(_LlmEvidenceCore):
    """Synthesis adds: fund-risk scores, suitability conditions, tax projection."""

    model_config = ConfigDict(extra="forbid")

    fund_risk_scores: FundRiskScores | None = None
    suitability_conditions: list[SuitabilityCondition] = Field(default_factory=list)
    tax_year_projection: list[TaxYearProjection] = Field(default_factory=list)


# ===========================================================================
# RecommendationSynthesis — LLM-backed final aggregator
# ===========================================================================


_SYNTHESIS_PROMPT = """\
You are E6.RecommendationSynthesis for Samriddhi AI (§11.7.8).

Your job: aggregate the structural-gate decision, product sub-agent verdicts,
and deterministic shared-sub-agent outputs (fee normalisation, cascade,
liquidity) into a single E6 verdict.

Strict rules:
- Output JSON with: risk_level_value (HIGH/MEDIUM/LOW/NOT_APPLICABLE),
  confidence (0.0-1.0), drivers (3-5 most material), flags, reasoning_trace,
  fund_risk_scores (manager_quality / strategy_consistency /
  fee_reasonableness / operational_risk / liquidity_risk; values are one of
  strong/sound/caution/elevated/low), suitability_conditions (each a
  condition + follow_through_check + evidence_required), tax_year_projection
  (per-FY estimated tax INR + notes).
- If the gate is HARD_BLOCK or SOFT_BLOCK, your risk_level must reflect that
  and `gate_risk` must appear in flags. Do NOT override the gate.
- If a sub-agent verdict carries `sub_agent_unavailable` or
  `look_through_unavailable`, propagate that flag.
- Cite the counterfactual model-portfolio return when present.
- Never produce decision language ("approve", "reject"). Findings only.
"""


class RecommendationSynthesis(CanonicalEvidenceAgent):
    """§11.7.8 — LLM-backed final aggregator.

    Inputs: gate decision, product sub-agent verdicts, fee/cascade/liquidity
    helper outputs, the orchestrator inputs bundle. Output: a typed
    `_LlmSynthesisOutput` that the orchestrator wraps into `E6Verdict`.
    """

    agent_id = "e6.synthesis"

    def system_prompt(self) -> str:
        return _SYNTHESIS_PROMPT

    def _render_signals(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> str:
        gate_decision: GateDecision | None = kwargs.get("gate_decision")
        sub_verdicts: list[StandardEvidenceVerdict] = kwargs.get("sub_verdicts") or []
        normalised: NormalisedReturns | None = kwargs.get("normalised_returns")
        cascade: CascadeAssessment | None = kwargs.get("cascade_assessment")
        liquidity: LiquidityManagerOutput | None = kwargs.get("liquidity_manager_output")

        lines: list[str] = []
        if gate_decision is not None:
            lines.append(f"gate.result = {gate_decision.result.value}")
            lines.append(f"gate.reasons = {','.join(gate_decision.reasons) or '<none>'}")
            if gate_decision.override_path:
                lines.append(f"gate.override_path = {gate_decision.override_path}")

        for v in sub_verdicts:
            lines.append(
                f"sub_agent.{v.agent_id}.risk_level = {v.risk_level.value} "
                f"confidence={v.confidence:.2f} "
                f"flags={','.join(v.flags) or '<none>'}"
            )

        if normalised is not None:
            if normalised.gross_return is not None:
                lines.append(f"normalised.gross_return = {normalised.gross_return:.4f}")
            if normalised.net_of_costs_return is not None:
                lines.append(
                    f"normalised.net_of_costs_return = {normalised.net_of_costs_return:.4f}"
                )
            if normalised.net_of_costs_and_taxes_return is not None:
                lines.append(
                    "normalised.net_of_all_return = "
                    f"{normalised.net_of_costs_and_taxes_return:.4f}"
                )
            if normalised.counterfactual_model_portfolio_return is not None:
                lines.append(
                    "normalised.counterfactual_model_return = "
                    f"{normalised.counterfactual_model_portfolio_return:.4f}"
                )
            if normalised.counterfactual_delta is not None:
                lines.append(
                    f"normalised.counterfactual_delta = {normalised.counterfactual_delta:.4f}"
                )

        if cascade is not None:
            lines.append(
                "cascade.expected_distribution_inr = "
                f"{cascade.expected_distribution_inr:.0f}"
            )
            lines.append(
                "cascade.expected_capital_calls_inr = "
                f"{cascade.expected_capital_calls_inr:.0f}"
            )
            lines.append(f"cascade.event_count = {len(cascade.cash_flow_schedule)}")

        if liquidity is not None:
            lines.append(
                "liquidity.cumulative_unfunded_commitment_inr = "
                f"{liquidity.cumulative_unfunded_commitment_inr:.0f}"
            )
            lines.append(
                f"liquidity.floor_check_result = {liquidity.liquidity_floor_check_result}"
            )
            lines.append(
                f"liquidity.most_liquid_bucket_share = {liquidity.most_liquid_bucket_share:.4f}"
            )

        return "\n".join(lines) if lines else "(no synthesis signals)"

    def _build_verdict(
        self,
        envelope: AgentActivationEnvelope,
        llm_core: _LlmEvidenceCore,
        signals_input_for_hash: dict[str, Any],
        **kwargs: Any,
    ) -> StandardEvidenceVerdict:
        """Required by base; synthesis builds its own typed output via run()."""
        raise NotImplementedError(
            "RecommendationSynthesis returns _LlmSynthesisOutput via `run()`"
        )

    async def run(
        self,
        envelope: AgentActivationEnvelope,
        *,
        gate_decision: GateDecision,
        sub_verdicts: list[StandardEvidenceVerdict],
        normalised_returns: NormalisedReturns | None,
        cascade_assessment: CascadeAssessment | None,
        liquidity_manager_output: LiquidityManagerOutput | None,
    ) -> tuple[_LlmSynthesisOutput, dict[str, Any]]:
        """Run synthesis. Returns the LLM output + the input bundle for hashing."""
        kwargs: dict[str, Any] = {
            "gate_decision": gate_decision,
            "sub_verdicts": sub_verdicts,
            "normalised_returns": normalised_returns,
            "cascade_assessment": cascade_assessment,
            "liquidity_manager_output": liquidity_manager_output,
        }
        signals_block = self._render_signals(envelope, **kwargs)

        # Build hash input: serialise pydantic objects, leave gate_decision as a
        # dict (it's a frozen dataclass, not pydantic). Strip wall-clock timestamps
        # from sub-verdicts so identical inputs produce identical hashes — the
        # deterministic content is in `input_hash` + the structured fields.
        signals_input_for_hash: dict[str, Any] = {
            "agent_id": self.agent_id,
            "envelope": envelope.model_dump(mode="json"),
            "gate_decision": {
                "result": gate_decision.result.value,
                "reasons": list(gate_decision.reasons),
                "override_path": gate_decision.override_path,
            },
            "sub_verdicts": [
                {
                    "agent_id": v.agent_id,
                    "input_hash": v.input_hash,
                    "risk_level": v.risk_level.value,
                    "confidence": v.confidence,
                    "flags": list(v.flags),
                    "drivers": [d.model_dump(mode="json") for d in v.drivers],
                }
                for v in sub_verdicts
            ],
        }
        if normalised_returns is not None:
            signals_input_for_hash["normalised_returns"] = normalised_returns.model_dump(
                mode="json"
            )
        if cascade_assessment is not None:
            signals_input_for_hash["cascade_assessment"] = cascade_assessment.model_dump(
                mode="json"
            )
        if liquidity_manager_output is not None:
            signals_input_for_hash["liquidity_manager_output"] = (
                liquidity_manager_output.model_dump(mode="json")
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
                _LlmSynthesisOutput,
            )
        except Exception as exc:
            logger.warning("e6.synthesis LLM unavailable: %s", exc)
            raise EvidenceLLMUnavailableError(
                f"e6.synthesis LLM provider unavailable: {exc}"
            ) from exc

        try:
            _ = RiskLevel(llm_output.risk_level_value)
        except ValueError as exc:
            raise EvidenceLLMUnavailableError(
                f"e6.synthesis LLM returned non-canonical risk_level "
                f"{llm_output.risk_level_value!r}"
            ) from exc

        return llm_output, signals_input_for_hash


# ===========================================================================
# E6Orchestrator
# ===========================================================================


class E6Orchestrator:
    """§11.7.7 — orchestrate gate + sub-agents + synthesis into a single E6Verdict.

    Construction:
      * `provider` — shared LLM provider for product sub-agents + synthesis.
      * `gate` — defaults to E6Gate(); inject for tests.
      * `subagent_registry` — defaults to PRODUCT_SUBAGENT_REGISTRY; inject for tests.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        gate: E6Gate | None = None,
        subagent_registry: dict[VehicleType, type[E6ProductSubAgent]] | None = None,
        synthesis: RecommendationSynthesis | None = None,
        prompt_version: str = "0.1.0",
        agent_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._gate = gate or E6Gate()
        self._registry = subagent_registry or PRODUCT_SUBAGENT_REGISTRY
        self._synthesis = synthesis or RecommendationSynthesis(
            provider, prompt_version=prompt_version, agent_version=agent_version
        )
        self._prompt_version = prompt_version
        self._agent_version = agent_version

    # --------------------- Routing ----------------------------------------

    def _vehicles_to_evaluate(
        self,
        envelope: AgentActivationEnvelope,
        holdings: list[Holding],
    ) -> list[VehicleType]:
        """Determine which product sub-agents must fire (§11.7.7).

        Sub-agents fire when:
          * a matching holding exists in the portfolio, OR
          * the proposed action's structure maps to that vehicle.
        """
        vehicles: set[VehicleType] = set()
        for h in holdings:
            if h.vehicle_type in self._registry:
                vehicles.add(h.vehicle_type)

        proposed = envelope.case.proposed_action
        if proposed is not None and proposed.structure:
            try:
                vt = VehicleType(proposed.structure)
                if vt in self._registry:
                    vehicles.add(vt)
            except ValueError:
                pass

        return sorted(vehicles, key=lambda v: v.value)

    # --------------------- Public API ------------------------------------

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        *,
        inputs: E6OrchestratorInputs | None = None,
        proposed_vehicle_type: VehicleType | None = None,
    ) -> E6Verdict:
        """Run the full E6 pipeline. Returns a typed `E6Verdict`.

        `proposed_vehicle_type` overrides the structure parsed from
        `case.proposed_action.structure` when callers want explicit control
        (the gate uses this to know which vehicle to gate on).
        """
        inputs = inputs or E6OrchestratorInputs()
        if envelope.investor_profile is None:
            raise ValueError(
                "E6Orchestrator requires envelope.investor_profile for the structural gate"
            )
        profile = envelope.investor_profile

        # ----- Vehicle for gate -----
        vehicle_for_gate = proposed_vehicle_type
        if vehicle_for_gate is None:
            proposed = envelope.case.proposed_action
            if proposed is not None and proposed.structure:
                try:
                    vehicle_for_gate = VehicleType(proposed.structure)
                except ValueError:
                    vehicle_for_gate = None

        # If no proposed vehicle, gate against the most-complex existing holding
        # so existing portfolio risk still trips the gate when applicable.
        if vehicle_for_gate is None:
            for h in inputs.holdings:
                if h.vehicle_type in self._registry:
                    vehicle_for_gate = h.vehicle_type
                    break

        if vehicle_for_gate is None:
            # No products in scope → mutual fund acts as the benign default for
            # the gate (gate rules only fire on AIF / SIF / unlisted).
            vehicle_for_gate = VehicleType.MUTUAL_FUND

        gate_decision = self._gate.evaluate(profile, vehicle_for_gate)

        # ----- Shared deterministic sub-agents -----
        normalised: NormalisedReturns | None = None
        if (
            inputs.proposed_gross_return is not None
            or inputs.proposed_fee_schedule is not None
        ):
            normalised = compute_normalised_returns(
                gross_return=inputs.proposed_gross_return or 0.0,
                fee_schedule=inputs.proposed_fee_schedule,
                tax_rate=inputs.proposed_tax_rate,
                counterfactual_model_portfolio_return=(
                    inputs.counterfactual_model_portfolio_return
                ),
            )

        cascade = compute_cascade_assessment(
            inputs.cash_flow_schedule or None,
            deployment_modelling=inputs.deployment_modelling or None,
        )

        liquidity = compute_liquidity_manager_output(
            holding_commitments=inputs.holding_commitments,
            most_liquid_bucket_share=inputs.most_liquid_bucket_share,
            mandate_liquidity_floor=inputs.mandate_liquidity_floor,
            proposed_uncalled_inr=inputs.proposed_uncalled_inr,
        )

        # ----- Product sub-agents -----
        sub_verdicts: list[StandardEvidenceVerdict] = []
        if gate_decision.result != GateResult.HARD_BLOCK:
            vehicles = self._vehicles_to_evaluate(envelope, inputs.holdings)
            sub_verdicts = await self._run_product_subagents(
                envelope, inputs, vehicles
            )

        # ----- Synthesis -----
        return await self._build_e6_verdict(
            envelope=envelope,
            inputs=inputs,
            gate_decision=gate_decision,
            sub_verdicts=sub_verdicts,
            normalised=normalised,
            cascade=cascade,
            liquidity=liquidity,
        )

    # --------------------- Internals -------------------------------------

    async def _run_product_subagents(
        self,
        envelope: AgentActivationEnvelope,
        inputs: E6OrchestratorInputs,
        vehicles: list[VehicleType],
    ) -> list[StandardEvidenceVerdict]:
        """Run all in-scope product sub-agents in parallel.

        Each sub-agent owns its own LLM activation; on failure it raises
        `EvidenceLLMUnavailableError`. We catch per-sub-agent failures so a
        single failure surfaces a `sub_agent_unavailable` verdict but doesn't
        kill the whole E6 evaluation.
        """
        sub_agents: list[E6ProductSubAgent] = [
            self._registry[v](
                self._provider,
                prompt_version=self._prompt_version,
                agent_version=self._agent_version,
            )
            for v in vehicles
        ]

        async def _run_one(sa: E6ProductSubAgent) -> StandardEvidenceVerdict:
            try:
                return await sa.evaluate(
                    envelope,
                    holdings=inputs.holdings,
                    l4_entry=inputs.proposed_l4_entry,
                )
            except EvidenceLLMUnavailableError as exc:
                logger.warning("Sub-agent %s unavailable: %s", sa.agent_id, exc)
                return self._sub_agent_unavailable_verdict(envelope, sa.agent_id)

        return list(await asyncio.gather(*(_run_one(sa) for sa in sub_agents)))

    def _sub_agent_unavailable_verdict(
        self,
        envelope: AgentActivationEnvelope,
        agent_id: str,
    ) -> StandardEvidenceVerdict:
        """Per §11.7.7 / §3.13 — fallback verdict when a sub-agent fails.

        HIGH risk + low confidence + `sub_agent_unavailable` flag, so S1
        synthesis can see the gap rather than silently dropping a lane.
        """
        signals_input = {
            "agent_id": agent_id,
            "envelope": envelope.model_dump(mode="json"),
            "fallback": "sub_agent_unavailable",
        }
        return StandardEvidenceVerdict(
            agent_id=agent_id,
            case_id=envelope.case.case_id,
            timestamp=self._synthesis._now(),
            run_mode=envelope.run_mode,
            risk_level=RiskLevel.HIGH,
            confidence=0.0,
            drivers=[],
            flags=["sub_agent_unavailable"],
            reasoning_trace=(
                f"{agent_id} LLM provider unavailable; emitting fallback verdict per §11.7.7."
            ),
            inputs_used_manifest=self._synthesis._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
        )

    async def _build_e6_verdict(
        self,
        *,
        envelope: AgentActivationEnvelope,
        inputs: E6OrchestratorInputs,
        gate_decision: GateDecision,
        sub_verdicts: list[StandardEvidenceVerdict],
        normalised: NormalisedReturns | None,
        cascade: CascadeAssessment,
        liquidity: LiquidityManagerOutput,
    ) -> E6Verdict:
        """Run synthesis and assemble the final E6Verdict.

        On synthesis-LLM failure: produce a HARD_BLOCK-aware fallback so the
        layer doesn't disappear from S1's view.
        """
        try:
            llm_output, signals_input_for_hash = await self._synthesis.run(
                envelope,
                gate_decision=gate_decision,
                sub_verdicts=sub_verdicts,
                normalised_returns=normalised,
                cascade_assessment=cascade,
                liquidity_manager_output=liquidity,
            )
        except EvidenceLLMUnavailableError:
            return self._fallback_verdict(
                envelope=envelope,
                inputs=inputs,
                gate_decision=gate_decision,
                sub_verdicts=sub_verdicts,
                normalised=normalised,
                cascade=cascade,
                liquidity=liquidity,
            )

        risk_level = RiskLevel(llm_output.risk_level_value)

        # Compose flags: LLM flags + deterministic flags from gate / sub-agents.
        flags = list(dict.fromkeys(llm_output.flags))
        if gate_decision.result in (GateResult.SOFT_BLOCK, GateResult.HARD_BLOCK):
            if "gate_risk" not in flags:
                flags.append("gate_risk")
        # Propagate sub-agent unavailability and look-through gaps.
        for sv in sub_verdicts:
            for f in ("sub_agent_unavailable", "look_through_unavailable"):
                if f in sv.flags and f not in flags:
                    flags.append(f)

        # Liquidity floor + uncalled commitments — surface as flags.
        if not liquidity.liquidity_floor_check_result:
            if "liquidity_floor_proximity" not in flags:
                flags.append("liquidity_floor_proximity")

        # Suitability conditions emitted → mark them pending until follow-through.
        suitability_conditions = list(llm_output.suitability_conditions)
        if suitability_conditions and "suitability_conditions_pending" not in flags:
            flags.append("suitability_conditions_pending")

        # Default fund_risk_scores when LLM omits — every score "sound" so
        # downstream consumers always see a populated structure.
        fund_risk_scores = llm_output.fund_risk_scores or FundRiskScores(
            manager_quality=FundRiskScore.SOUND,
            strategy_consistency=FundRiskScore.SOUND,
            fee_reasonableness=FundRiskScore.SOUND,
            operational_risk=FundRiskScore.SOUND,
            liquidity_risk=FundRiskScore.SOUND,
        )

        manifest = self._synthesis._build_inputs_used_manifest(signals_input_for_hash)
        ihash = payload_hash(signals_input_for_hash)

        return E6Verdict(
            case_id=envelope.case.case_id,
            timestamp=self._synthesis._now(),
            run_mode=envelope.run_mode,
            risk_level=risk_level,
            confidence=llm_output.confidence,
            drivers=llm_output.drivers,
            flags=flags,
            reasoning_trace=llm_output.reasoning_trace,
            inputs_used_manifest=manifest,
            input_hash=ihash,
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
            fund_risk_scores=fund_risk_scores,
            sub_agent_verdicts=sub_verdicts,
            normalised_returns=normalised,
            cascade_assessment=cascade,
            tax_year_projection=llm_output.tax_year_projection,
            liquidity_manager_output=liquidity,
            forcing_function_disclosures=list(inputs.forcing_function_disclosures),
            suitability_conditions=suitability_conditions,
            gate_result=gate_decision.result,
        )

    def _fallback_verdict(
        self,
        *,
        envelope: AgentActivationEnvelope,
        inputs: E6OrchestratorInputs,
        gate_decision: GateDecision,
        sub_verdicts: list[StandardEvidenceVerdict],
        normalised: NormalisedReturns | None,
        cascade: CascadeAssessment,
        liquidity: LiquidityManagerOutput,
    ) -> E6Verdict:
        """Emit a deterministic E6Verdict when synthesis LLM fails (§11.7.7 / §3.13)."""
        signals_input = {
            "agent_id": "e6.synthesis",
            "envelope": envelope.model_dump(mode="json"),
            "fallback": "synthesis_unavailable",
        }
        flags = ["sub_agent_unavailable"]
        if gate_decision.result in (GateResult.SOFT_BLOCK, GateResult.HARD_BLOCK):
            flags.append("gate_risk")
        if not liquidity.liquidity_floor_check_result:
            flags.append("liquidity_floor_proximity")

        return E6Verdict(
            case_id=envelope.case.case_id,
            timestamp=self._synthesis._now(),
            run_mode=envelope.run_mode,
            risk_level=RiskLevel.HIGH,
            confidence=0.0,
            drivers=[
                Driver(
                    factor="e6_synthesis_unavailable",
                    direction=DriverDirection.NEUTRAL,
                    severity=DriverSeverity.HIGH,
                    detail="E6 synthesis LLM unavailable; surfacing fallback verdict.",
                )
            ],
            flags=flags,
            reasoning_trace=(
                "E6 synthesis LLM unavailable; emitting fallback verdict per §11.7.7. "
                "Gate result, sub-agent verdicts, and shared sub-agent outputs are "
                "preserved for downstream synthesis."
            ),
            inputs_used_manifest=self._synthesis._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
            fund_risk_scores=None,
            sub_agent_verdicts=sub_verdicts,
            normalised_returns=normalised,
            cascade_assessment=cascade,
            tax_year_projection=[],
            liquidity_manager_output=liquidity,
            forcing_function_disclosures=list(inputs.forcing_function_disclosures),
            suitability_conditions=[],
            gate_result=gate_decision.result,
        )


__all__ = [
    "E6Orchestrator",
    "E6OrchestratorInputs",
    "RecommendationSynthesis",
]
