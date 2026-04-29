"""§11.7.3–11.7.6 — E6 product-specific sub-agents (LLM-backed).

Each sub-agent has its own lane and prompt:

  * `PmsSubAgent` (§11.7.3) — manager quality, strategy consistency, fee
    structure, operational risk on PMS holdings/proposals.
  * `AifCat1SubAgent` (§11.7.4) — vintage, deployment, infrastructure-style
    risk for Cat I AIFs.
  * `AifCat2SubAgent` (§11.7.4) — long-lock private credit / private equity:
    cascade modelling, deployment, J-curve, liquidity collision.
  * `AifCat3SubAgent` (§11.7.4) — long-short / hedge-style strategies:
    leverage, drawdown profile, gross exposure, manager pedigree.
  * `SifSubAgent` (§11.7.5) — SIF (Specialised Investment Fund) lane.
  * `MutualFundSubAgent` (§11.7.6) — manager continuity, expense ratio,
    style drift, liquidity profile for MF holdings/proposals.

Each sub-agent emits a `StandardEvidenceVerdict` whose `agent_id` identifies
the sub-lane (e.g. "e6.pms_subagent"). The orchestrator (Pass 10) aggregates
them into the final `E6Verdict`.

The base class `E6ProductSubAgent` shares LLM mechanics + hash + manifest
with the rest of the evidence layer. Each subclass overrides `system_prompt`,
the agent_id, and the signal-rendering routine. This keeps the
product-specific prompts tightly scoped while leaving the orchestration
logic centralised.
"""

from __future__ import annotations

import logging
from typing import Any

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import (
    StandardEvidenceVerdict,
    _LlmEvidenceCore,
)
from artha.canonical.holding import Holding
from artha.canonical.l4_manifest import FundUniverseL4Entry
from artha.common.hashing import payload_hash
from artha.common.types import RiskLevel, VehicleType
from artha.evidence.canonical_base import (
    CanonicalEvidenceAgent,
    EvidenceLLMUnavailableError,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


# ===========================================================================
# Base class
# ===========================================================================


class E6ProductSubAgent(CanonicalEvidenceAgent):
    """Base for E6 product-specific sub-agents.

    Subclasses set:
      * `agent_id` — e.g. "e6.pms_subagent".
      * `vehicle_types` — frozenset of canonical VehicleTypes this sub-agent owns.
      * `system_prompt()` — product-specific lane definition.
      * `_render_product_signals()` — per-holding / per-product signal block.

    The shared `evaluate()` filters holdings to the sub-agent's vehicle types,
    short-circuits NOT_APPLICABLE if none are present, otherwise delegates to
    the LLM via the standard `CanonicalEvidenceAgent` machinery.
    """

    vehicle_types: frozenset[VehicleType] = frozenset()

    def __init__(
        self,
        provider: LLMProvider,
        *,
        prompt_version: str = "0.1.0",
        agent_version: str = "0.1.0",
    ) -> None:
        super().__init__(
            provider, prompt_version=prompt_version, agent_version=agent_version
        )

    # --------------------- Applicability ----------------------------------

    def is_applicable(
        self,
        envelope: AgentActivationEnvelope,
        holdings: list[Holding] | None = None,
    ) -> bool:
        """Sub-agent fires when at least one matching holding OR a matching
        proposed_action is present."""
        if holdings:
            for h in holdings:
                if h.vehicle_type in self.vehicle_types:
                    return True

        proposed = envelope.case.proposed_action
        if proposed is not None and proposed.structure:
            try:
                vt = VehicleType(proposed.structure)
                if vt in self.vehicle_types:
                    return True
            except ValueError:
                pass

        return False

    # --------------------- Evaluate ----------------------------------------

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> StandardEvidenceVerdict:
        holdings: list[Holding] = kwargs.get("holdings") or []
        if not self.is_applicable(envelope, holdings):
            return self._not_applicable_verdict(envelope, **kwargs)

        signals_block = self._render_signals(envelope, **kwargs)
        signals_input_for_hash = self._collect_input_for_hash(envelope, **kwargs)

        try:
            llm_core = await self._provider.complete_structured(
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
                _LlmEvidenceCore,
            )
        except Exception as exc:
            logger.warning("%s LLM unavailable: %s", self.agent_id, exc)
            raise EvidenceLLMUnavailableError(
                f"{self.agent_id} LLM provider unavailable: {exc}"
            ) from exc

        try:
            RiskLevel(llm_core.risk_level_value)
        except ValueError as exc:
            raise EvidenceLLMUnavailableError(
                f"{self.agent_id} LLM returned non-canonical risk_level "
                f"{llm_core.risk_level_value!r}"
            ) from exc

        return self._build_verdict(envelope, llm_core, signals_input_for_hash, **kwargs)

    # --------------------- Hooks ----------------------------------------

    def _build_verdict(
        self,
        envelope: AgentActivationEnvelope,
        llm_core: _LlmEvidenceCore,
        signals_input_for_hash: dict[str, Any],
        **kwargs: Any,
    ) -> StandardEvidenceVerdict:
        return StandardEvidenceVerdict(
            agent_id=self.agent_id,
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            risk_level=RiskLevel(llm_core.risk_level_value),
            confidence=llm_core.confidence,
            drivers=llm_core.drivers,
            flags=list(dict.fromkeys(llm_core.flags)),
            reasoning_trace=llm_core.reasoning_trace,
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input_for_hash),
            input_hash=payload_hash(signals_input_for_hash),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
        )

    def _not_applicable_verdict(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> StandardEvidenceVerdict:
        signals_input = self._collect_input_for_hash(envelope, **kwargs)
        return StandardEvidenceVerdict(
            agent_id=self.agent_id,
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            risk_level=RiskLevel.NOT_APPLICABLE,
            confidence=1.0,
            drivers=[],
            flags=[],
            reasoning_trace=(
                f"{self.agent_id} lane has no applicable holdings or proposal "
                "in this case."
            ),
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
        )

    def _render_signals(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> str:
        """Default signal block: matched holdings + proposed action + L4 entry summary.

        Subclasses extend (not replace) by composing additional product-specific
        signals on top of the base block.
        """
        holdings: list[Holding] = kwargs.get("holdings") or []
        l4_entry: FundUniverseL4Entry | None = kwargs.get("l4_entry")
        matched = [h for h in holdings if h.vehicle_type in self.vehicle_types]

        lines = [f"sub_agent.matched_holdings_count = {len(matched)}"]
        for h in matched:
            lines.append(
                f"holding.{h.instrument_id}.vehicle = {h.vehicle_type.value} "
                f"market_value={h.market_value:.0f}"
            )

        proposed = envelope.case.proposed_action
        if proposed is not None and proposed.structure:
            try:
                vt = VehicleType(proposed.structure)
                if vt in self.vehicle_types:
                    lines.append(
                        f"proposed.target_product = {proposed.target_product}"
                    )
                    lines.append(f"proposed.structure = {proposed.structure}")
                    if proposed.ticket_size_inr is not None:
                        lines.append(
                            f"proposed.ticket_size_inr = {proposed.ticket_size_inr:.0f}"
                        )
            except ValueError:
                pass

        if l4_entry is not None:
            lines.append(
                f"l4.instrument_id = {l4_entry.instrument_id} "
                f"sub_asset_class={l4_entry.sub_asset_class}"
            )
            lines.append(
                f"l4.amc_or_issuer = {l4_entry.amc_or_issuer} "
                f"minimum_aum_tier={l4_entry.minimum_aum_tier.value}"
            )
            lines.append(
                "l4.fee_schedule.management_fee_bps = "
                f"{l4_entry.fee_schedule.management_fee_bps}"
            )
            lines.append(
                "l4.fee_schedule.performance_fee_bps = "
                f"{l4_entry.fee_schedule.performance_fee_bps}"
            )
            lines.append(
                f"l4.look_through_published = {l4_entry.look_through_published}"
            )
            if l4_entry.lock_in_iso_duration:
                lines.append(
                    f"l4.lock_in_iso_duration = {l4_entry.lock_in_iso_duration}"
                )

        return "\n".join(lines)


# ===========================================================================
# §11.7.3 — PMS sub-agent
# ===========================================================================


_PMS_PROMPT = """\
You are E6.PMS sub-agent for Samriddhi AI.

Your lane (§11.7.3): manager quality, strategy consistency, fee structure
reasonableness, operational risk for Portfolio Management Service holdings.

Strict rules:
- Output JSON with: risk_level_value (HIGH/MEDIUM/LOW/NOT_APPLICABLE),
  confidence (0.0-1.0), drivers (3-5 most material), flags, reasoning_trace.
- Cite specific PMS attributes (manager tenure, AUM, strategy turnover,
  expense pass-through) in reasoning_trace.
- Surface tax_collision_fy27 if PMS direct-equity churn looks tax-inefficient
  under FY26-27 LTCG/STCG.
- Never produce decision language. Findings only.
"""


class PmsSubAgent(E6ProductSubAgent):
    """§11.7.3 — PMS-specific sub-agent."""

    agent_id = "e6.pms_subagent"
    vehicle_types = frozenset({VehicleType.PMS})

    def system_prompt(self) -> str:
        return _PMS_PROMPT


# ===========================================================================
# §11.7.4 — AIF Category I / II / III sub-agents
# ===========================================================================


_AIF_CAT1_PROMPT = """\
You are E6.AIF-Cat-I sub-agent for Samriddhi AI.

Your lane (§11.7.4): vintage diversification, deployment pacing,
infrastructure / venture-style risk for AIF Category I funds (infrastructure,
venture, social impact, SME).

Strict rules:
- Output JSON with: risk_level_value, confidence, drivers, flags,
  reasoning_trace.
- Cite vintage year, deployment status, sector exposure, regulatory regime.
- Surface look_through_unavailable when underlying portfolio data is missing.
- Never produce decision language. Findings only.
"""


class AifCat1SubAgent(E6ProductSubAgent):
    """§11.7.4 — AIF Category I sub-agent."""

    agent_id = "e6.aif_cat1_subagent"
    vehicle_types = frozenset({VehicleType.AIF_CAT_1})

    def system_prompt(self) -> str:
        return _AIF_CAT1_PROMPT


_AIF_CAT2_PROMPT = """\
You are E6.AIF-Cat-II sub-agent for Samriddhi AI.

Your lane (§11.7.4): private credit / private equity-style funds with
long lock-up. Evaluate cascade exposure (capital calls + distributions),
J-curve sensitivity, liquidity collisions, fee-drag-vs-counterfactual.

Strict rules:
- Output JSON with: risk_level_value, confidence, drivers, flags,
  reasoning_trace.
- Cite uncalled commitment, expected distribution timeline, fee structure.
- Surface fund_level_tax_drag and look_through_unavailable when applicable.
- Never produce decision language. Findings only.
"""


class AifCat2SubAgent(E6ProductSubAgent):
    """§11.7.4 — AIF Category II sub-agent."""

    agent_id = "e6.aif_cat2_subagent"
    vehicle_types = frozenset({VehicleType.AIF_CAT_2})

    def system_prompt(self) -> str:
        return _AIF_CAT2_PROMPT


_AIF_CAT3_PROMPT = """\
You are E6.AIF-Cat-III sub-agent for Samriddhi AI.

Your lane (§11.7.4): long-short / hedge-style AIF Cat III. Evaluate leverage,
drawdown profile, gross/net exposure, manager pedigree, fund-level tax drag,
behavioural fit with bucket.

Strict rules:
- Output JSON with: risk_level_value, confidence, drivers, flags,
  reasoning_trace.
- Cite leverage ratio, max-drawdown history, peer-group context.
- Surface leverage_elevated when gross > 1.5x or strategy is materially
  long-short.
- Never produce decision language. Findings only.
"""


class AifCat3SubAgent(E6ProductSubAgent):
    """§11.7.4 — AIF Category III sub-agent."""

    agent_id = "e6.aif_cat3_subagent"
    vehicle_types = frozenset({VehicleType.AIF_CAT_3})

    def system_prompt(self) -> str:
        return _AIF_CAT3_PROMPT


# ===========================================================================
# §11.7.5 — SIF sub-agent
# ===========================================================================


_SIF_PROMPT = """\
You are E6.SIF sub-agent for Samriddhi AI.

Your lane (§11.7.5): Specialised Investment Fund. Evaluate strategy
specialisation, mandate alignment, liquidity profile, tax classification,
fee normalisation against peer SIFs.

Strict rules:
- Output JSON with: risk_level_value, confidence, drivers, flags,
  reasoning_trace.
- Cite specialisation theme, expense ratio, look-through availability.
- Never produce decision language. Findings only.
"""


class SifSubAgent(E6ProductSubAgent):
    """§11.7.5 — SIF sub-agent."""

    agent_id = "e6.sif_subagent"
    vehicle_types = frozenset({VehicleType.SIF})

    def system_prompt(self) -> str:
        return _SIF_PROMPT


# ===========================================================================
# §11.7.6 — Mutual Fund sub-agent
# ===========================================================================


_MF_PROMPT = """\
You are E6.MF sub-agent for Samriddhi AI.

Your lane (§11.7.6): mutual fund manager continuity, expense ratio reasonableness,
style drift, sector concentration vs benchmark, liquidity profile.

Strict rules:
- Output JSON with: risk_level_value, confidence, drivers, flags,
  reasoning_trace.
- Cite manager tenure, AUM, expense ratio, peer-quartile context.
- Never produce decision language. Findings only.
"""


class MutualFundSubAgent(E6ProductSubAgent):
    """§11.7.6 — Mutual Fund sub-agent."""

    agent_id = "e6.mf_subagent"
    vehicle_types = frozenset({VehicleType.MUTUAL_FUND})

    def system_prompt(self) -> str:
        return _MF_PROMPT


# ===========================================================================
# Registry — orchestrator routes by VehicleType
# ===========================================================================


PRODUCT_SUBAGENT_REGISTRY: dict[VehicleType, type[E6ProductSubAgent]] = {
    VehicleType.PMS: PmsSubAgent,
    VehicleType.AIF_CAT_1: AifCat1SubAgent,
    VehicleType.AIF_CAT_2: AifCat2SubAgent,
    VehicleType.AIF_CAT_3: AifCat3SubAgent,
    VehicleType.SIF: SifSubAgent,
    VehicleType.MUTUAL_FUND: MutualFundSubAgent,
}


__all__ = [
    "AifCat1SubAgent",
    "AifCat2SubAgent",
    "AifCat3SubAgent",
    "E6ProductSubAgent",
    "MutualFundSubAgent",
    "PmsSubAgent",
    "PRODUCT_SUBAGENT_REGISTRY",
    "SifSubAgent",
]
