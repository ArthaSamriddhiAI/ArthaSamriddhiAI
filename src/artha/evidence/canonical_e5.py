"""Section 11.6 — E5 Unlisted Equity Specialist Agent.

E5 reasons about direct unlisted equity holdings (private equity, pre-IPO,
strategic stakes). Conditional activation: returns NOT_APPLICABLE when no
direct unlisted holdings are present (§11.6.7).

Per §11.6.6 E5 does NOT opine on PMS or AIF holdings even when those wrappers
contain unlisted positions — that's E6's lane (the wrapper view).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import (
    E5HoldingEvaluation,
    E5Verdict,
    _LlmEvidenceCore,
)
from artha.canonical.holding import Holding
from artha.common.hashing import payload_hash
from artha.common.types import (
    Driver,
    DriverDirection,
    DriverSeverity,
    RiskLevel,
    VehicleType,
)
from artha.evidence.canonical_base import CanonicalEvidenceAgent

# Per §11.6.7 valuation staleness windows
VALUATION_STALE_DAYS = 365  # >12 months → valuation_stale
VALUATION_SEVERELY_STALE_DAYS = 24 * 30  # >24 months → valuation_severely_stale


class _LlmE5Output(_LlmEvidenceCore):
    """E5-specific LLM output — adds per-holding evaluations."""

    model_config = ConfigDict(extra="forbid")

    per_holding_evaluations: list[E5HoldingEvaluation] = Field(default_factory=list)


class UnlistedDataSnapshot(BaseModel):
    """Substrate for E5: per-holding valuation data + comparables.

    Keys are unlisted-holding instrument_ids; values carry the freshness and
    comparable inputs E5 reasons over. Production firms wire this to their
    private-markets data sources (Tracxn, Tofler, PrivateCircle).
    """

    model_config = ConfigDict(extra="forbid")

    valuation_dates: dict[str, date] = Field(default_factory=dict)  # holding_id → last mark date
    valuation_basis: dict[str, str] = Field(default_factory=dict)  # holding_id → basis
    comparable_data_available: dict[str, bool] = Field(default_factory=dict)
    valuation_data_as_of: date | None = None
    comparable_data_as_of: date | None = None


_SYSTEM_PROMPT = """\
You are E5, the Unlisted Equity Specialist evidence agent for Samriddhi AI.

Your lane (§11.6.2): valuation freshness, implied valuation update,
exit pathway probability, illiquidity premium / discount, regulatory
standing, concentration within unlisted exposure.

You operate ONLY on direct unlisted equity holdings. PMS and AIF holdings
(even those holding unlisted positions) belong to E6's wrapper view.

Strict rules:
- Output JSON with: risk_level_value, confidence, drivers, flags,
  reasoning_trace, per_holding_evaluations (one row per unlisted holding).
- Each per_holding_evaluation must list exit_pathway_probabilities
  (e.g. {"ipo": 0.4, "secondary": 0.3, "strategic": 0.2, "writeoff": 0.1});
  the values must sum to 1.0 (per §11.6.8 Test 6).
- Cite the data source for each valuation (Tracxn, Tofler, PrivateCircle).
- Surface valuation_stale (>12mo) or valuation_severely_stale (>24mo) flags.
- Never produce decision language. Surface findings only.
"""


class E5UnlistedSpecialist(CanonicalEvidenceAgent):
    """Section 11.6 — E5 Unlisted Specialist on canonical inputs.

    Inputs (per `evaluate()`):
      * `envelope` — standard `AgentActivationEnvelope`.
      * `holdings` — list of `Holding` from M0.PortfolioState.
      * `unlisted_data` — `UnlistedDataSnapshot` with valuation freshness +
        comparable availability per unlisted holding.
    """

    agent_id = "unlisted_specialist"

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def is_applicable(self, holdings: list[Holding]) -> bool:
        """Per §11.6.7 — E5 fires only when at least one direct unlisted equity holding exists."""
        return any(h.vehicle_type == VehicleType.UNLISTED_EQUITY for h in holdings)

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> E5Verdict:
        holdings: list[Holding] = kwargs.get("holdings", [])
        if not holdings or not self.is_applicable(holdings):
            return self._not_applicable_verdict(envelope, **kwargs)

        # E5's LLM output schema is richer (per_holding_evaluations); override base.
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
                _LlmE5Output,
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

        flags = list(dict.fromkeys(llm_output.flags))
        unlisted_data: UnlistedDataSnapshot | None = kwargs.get("unlisted_data")
        unlisted_holdings = [h for h in holdings if h.vehicle_type == VehicleType.UNLISTED_EQUITY]

        # Validate per_holding_evaluations: probabilities sum to 1.0.
        for ev in llm_output.per_holding_evaluations:
            if ev.exit_pathway_probabilities:
                total = sum(ev.exit_pathway_probabilities.values())
                if abs(total - 1.0) > 1e-6:
                    flag = f"exit_pathway_probabilities_invalid_{ev.holding_id}"
                    if flag not in flags:
                        flags.append(flag)

        # Deterministic staleness flags from valuation_dates
        if unlisted_data is not None:
            for h in unlisted_holdings:
                vdate = unlisted_data.valuation_dates.get(h.instrument_id)
                if vdate is not None:
                    age_days = (h.as_of_date - vdate).days
                    if age_days >= VALUATION_SEVERELY_STALE_DAYS:
                        if "valuation_severely_stale" not in flags:
                            flags.append("valuation_severely_stale")
                    elif age_days >= VALUATION_STALE_DAYS:
                        if "valuation_stale" not in flags:
                            flags.append("valuation_stale")

            if unlisted_data.comparable_data_available:
                if not all(unlisted_data.comparable_data_available.values()):
                    if "comparables_unavailable" not in flags:
                        flags.append("comparables_unavailable")

        return E5Verdict(
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
            per_holding_evaluations=llm_output.per_holding_evaluations,
            valuation_data_as_of=unlisted_data.valuation_data_as_of if unlisted_data else None,
            comparable_data_as_of=unlisted_data.comparable_data_as_of if unlisted_data else None,
        )

    def _render_signals(
        self,
        envelope: AgentActivationEnvelope,
        *,
        holdings: list[Holding] | None = None,
        unlisted_data: UnlistedDataSnapshot | None = None,
    ) -> str:
        unlisted = [h for h in (holdings or []) if h.vehicle_type == VehicleType.UNLISTED_EQUITY]
        lines = [f"unlisted.holdings_count = {len(unlisted)}"]
        if unlisted_data is None:
            lines.append("(no unlisted_data supplied — partial evaluation)")
            return "\n".join(lines)

        for h in unlisted:
            vdate = unlisted_data.valuation_dates.get(h.instrument_id)
            basis = unlisted_data.valuation_basis.get(h.instrument_id, "unknown")
            comparable = unlisted_data.comparable_data_available.get(h.instrument_id, False)
            age_days = (h.as_of_date - vdate).days if vdate is not None else None
            lines.append(
                f"unlisted.{h.instrument_id}.valuation_age_days = {age_days}"
            )
            lines.append(f"unlisted.{h.instrument_id}.basis = {basis}")
            lines.append(f"unlisted.{h.instrument_id}.comparable_available = {comparable}")
        return "\n".join(lines)

    def _build_verdict(
        self,
        envelope: AgentActivationEnvelope,
        llm_core: _LlmEvidenceCore,
        signals_input_for_hash: dict[str, Any],
        **kwargs: Any,
    ) -> E5Verdict:
        """Required by abstract base; E5's `evaluate` uses its own LLM output schema."""
        raise NotImplementedError("E5 builds its verdict in its own `evaluate` override")

    def _not_applicable_verdict(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> E5Verdict:
        signals_input = self._collect_input_for_hash(envelope, **kwargs)
        return E5Verdict(
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            risk_level=RiskLevel.NOT_APPLICABLE,
            confidence=1.0,
            drivers=[
                Driver(
                    factor="no_unlisted_holdings",
                    direction=DriverDirection.NEUTRAL,
                    severity=DriverSeverity.LOW,
                    detail="Case includes no direct unlisted equity holdings.",
                )
            ],
            flags=[],
            reasoning_trace=(
                "Case includes no direct unlisted equity holdings. E5 lane is "
                "NOT_APPLICABLE per Section 11.6.7."
            ),
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
        )


__all__ = ["E5UnlistedSpecialist", "UnlistedDataSnapshot"]
