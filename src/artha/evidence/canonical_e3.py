"""Section 11.4 — E3 Macro & Policy Agent.

E3 reasons about regimes that affect every holding (rate cycle, inflation,
currency, fiscal stance, monetary regime, structural themes) and originates
WATCH-tier alerts for probabilistic future events (§10.2.3 — E3-only watch
origination in MVP).

Pass 9 ships the canonical service. Pass 14 (N0 channel) consumes
`watch_candidates` and converts them to N0 alerts at the WATCH tier.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import (
    E3Verdict,
    RegimeAssessment,
    WatchCandidate,
    _LlmEvidenceCore,
)
from artha.common.hashing import payload_hash
from artha.common.types import (
    RiskLevel,
)
from artha.evidence.canonical_base import CanonicalEvidenceAgent

# Section 10.2.3 — watches sit between must-respond and informational.
WATCH_PROBABILITY_RANGE: tuple[float, float] = (0.40, 0.70)


class _LlmE3Output(_LlmEvidenceCore):
    """E3-specific LLM output — adds regime_assessments + watch_candidates."""

    model_config = ConfigDict(extra="forbid")

    regime_assessments: list[RegimeAssessment] = Field(default_factory=list)
    watch_candidates: list[WatchCandidate] = Field(default_factory=list)


class MacroSignals(BaseModel):
    """Structured macro signals fed into E3's prompt.

    Pass 9's substrate is the firm's macro data pipelines (RBI DBIE, NSO, IIP,
    CPI). Tests pass a pre-populated `MacroSignals`; production wires this
    via Phase D macro pipeline integration.
    """

    model_config = ConfigDict(extra="forbid")

    policy_rate: float | None = None
    real_rate: float | None = None
    headline_cpi: float | None = None
    core_cpi: float | None = None
    inr_usd_rate: float | None = None
    fiscal_deficit_gdp_pct: float | None = None
    # one of: accommodative | neutral | tightening | transitioning
    monetary_regime: str | None = None
    structural_themes: list[str] = Field(default_factory=list)
    data_as_of: date | None = None


_SYSTEM_PROMPT = """\
You are E3, the Macro & Policy evidence agent for Samriddhi AI.

Your lane (§11.4.2): rate environment, inflation, currency, fiscal stance,
monetary regime, structural themes. You are the only evidence agent that
originates WATCH-tier alerts in MVP (§10.2.3).

Strict rules:
- Output JSON with: risk_level_value, confidence, drivers, flags,
  reasoning_trace (cite RBI DBIE / NSO / policy feed sources),
  regime_assessments (one per dimension), watch_candidates (zero or more).
- A watch_candidate is a regime shift you are TRACKING with probability
  in the 0.40-0.70 range. Probability above 0.70 typically means must-respond
  (no watch); below 0.40 is too speculative to track. Each watch must specify
  dimension, probability, confidence_band (one of:
  virtually_certain/high/moderate/low/uncertain), resolution_horizon_days,
  and impact_if_resolved.
- Never produce decision language. Surface findings only.
- Cite at least one named source per dimension that produced output.
"""


class E3MacroPolicy(CanonicalEvidenceAgent):
    """Section 11.4 — E3 Macro Policy on canonical inputs.

    Inputs (per `evaluate()`):
      * `envelope` — standard `AgentActivationEnvelope`.
      * `signals` — `MacroSignals` snapshot of the macro substrate.
    """

    agent_id = "macro_policy"

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def _render_signals(
        self,
        envelope: AgentActivationEnvelope,
        *,
        signals: MacroSignals | None = None,
    ) -> str:
        if signals is None:
            return "(no macro signals supplied — partial evaluation)"
        lines: list[str] = []
        if signals.policy_rate is not None:
            lines.append(f"rate.policy_rate = {signals.policy_rate:.4f}")
        if signals.real_rate is not None:
            lines.append(f"rate.real_rate = {signals.real_rate:.4f}")
        if signals.headline_cpi is not None:
            lines.append(f"inflation.headline_cpi = {signals.headline_cpi:.4f}")
        if signals.core_cpi is not None:
            lines.append(f"inflation.core_cpi = {signals.core_cpi:.4f}")
        if signals.inr_usd_rate is not None:
            lines.append(f"currency.inr_usd_rate = {signals.inr_usd_rate:.4f}")
        if signals.fiscal_deficit_gdp_pct is not None:
            lines.append(
                f"fiscal.fiscal_deficit_gdp_pct = {signals.fiscal_deficit_gdp_pct:.4f}"
            )
        if signals.monetary_regime is not None:
            lines.append(f"monetary.regime = {signals.monetary_regime}")
        if signals.structural_themes:
            lines.append(
                f"structural.themes = {', '.join(signals.structural_themes)}"
            )
        if signals.data_as_of is not None:
            lines.append(f"data_as_of = {signals.data_as_of.isoformat()}")
        return "\n".join(lines) if lines else "(no macro signals supplied)"

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> E3Verdict:
        """E3 uses a richer LLM output schema (regime_assessments + watch_candidates).

        We override the base `evaluate` to call `complete_structured` with
        `_LlmE3Output` instead of `_LlmEvidenceCore`.
        """
        signals_block = self._render_signals(envelope, **kwargs)
        signals_input_for_hash = self._collect_input_for_hash(envelope, **kwargs)

        from artha.evidence.canonical_base import EvidenceLLMUnavailableError
        from artha.llm.models import LLMMessage, LLMRequest

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
                _LlmE3Output,
            )
        except Exception as exc:
            raise EvidenceLLMUnavailableError(
                f"{self.agent_id} LLM provider unavailable: {exc}"
            ) from exc

        try:
            risk_level = RiskLevel(llm_output.risk_level_value)
        except ValueError as exc:
            raise EvidenceLLMUnavailableError(
                f"{self.agent_id} LLM returned non-canonical risk_level "
                f"{llm_output.risk_level_value!r}"
            ) from exc

        # Filter watch_candidates to those within the canonical probability range.
        # Pass 9 surfaces an out-of-range watch in flags rather than silently dropping it,
        # so calibration drift becomes visible to A1.
        valid_watches: list[WatchCandidate] = []
        flags = list(dict.fromkeys(llm_output.flags))
        for w in llm_output.watch_candidates:
            if WATCH_PROBABILITY_RANGE[0] <= w.probability <= WATCH_PROBABILITY_RANGE[1]:
                valid_watches.append(w)
            else:
                flag = f"watch_probability_out_of_range_{w.dimension.value}"
                if flag not in flags:
                    flags.append(flag)

        signals: MacroSignals | None = kwargs.get("signals")

        return E3Verdict(
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            risk_level=risk_level,
            confidence=llm_output.confidence,
            drivers=llm_output.drivers,
            flags=flags,
            reasoning_trace=llm_output.reasoning_trace,
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input_for_hash),
            input_hash=payload_hash(signals_input_for_hash),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
            regime_assessments=llm_output.regime_assessments,
            watch_candidates=valid_watches,
            data_as_of=signals.data_as_of if signals else None,
        )

    def _build_verdict(
        self,
        envelope: AgentActivationEnvelope,
        llm_core: _LlmEvidenceCore,
        signals_input_for_hash: dict[str, Any],
        **kwargs: Any,
    ) -> E3Verdict:
        """Required by the abstract base. E3's `evaluate` uses its own LLM
        output schema and bypasses the base's verdict-building path; this
        method exists to satisfy the abstract contract.
        """
        raise NotImplementedError("E3 builds its verdict in its own `evaluate` override")


__all__ = ["E3MacroPolicy", "MacroSignals", "WATCH_PROBABILITY_RANGE"]
