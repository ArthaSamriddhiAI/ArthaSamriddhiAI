"""Section 11.3 — E2 Industry & Business Model Agent on canonical inputs.

E2 reasons about the businesses behind the holdings: sectoral exposure,
moat assessment, industry lifecycle, five-forces aggregate, sector regulatory
context, quality aggregation. Per §11.3.7 E2 returns NOT_APPLICABLE on pure-
debt portfolios.

Pass 8 ships the canonical service. The full SAMRIDDHI Industry Database
integration (sector classification + moat data + lifecycle + five-forces)
is firm-managed substrate; Pass 8's E2 consumes whatever sector data the
caller provides and emits a structured per-sector + portfolio-level verdict.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import (
    E2PortfolioQualityVerdict,
    E2SectorEvaluation,
    E2Verdict,
    _LlmEvidenceCore,
)
from artha.canonical.holding import Holding
from artha.common.hashing import payload_hash
from artha.common.types import (
    AssetClass,
    Driver,
    DriverDirection,
    DriverSeverity,
    PercentageField,
    RiskLevel,
)
from artha.evidence.canonical_base import CanonicalEvidenceAgent

# Default thresholds per §11.3.7
DEFAULT_LOW_FIELD_COVERAGE_THRESHOLD = 0.6
DEFAULT_SECTOR_CONCENTRATION_BREACH = 0.35  # share of portfolio in single sector


_SYSTEM_PROMPT = """\
You are E2, the Industry & Business Model evidence agent for Samriddhi AI.

Your lane (§11.3.2): sectoral concentration, moat assessment, industry
lifecycle, five-forces aggregate, sector regulatory context, quality
aggregation. You operate on listed equity exposure (direct + look-through
from MFs / PMS / AIF Cat III). You do NOT opine on debt holdings, commodities,
REITs, unlisted equity (E5's lane), or economy-wide macro (E3's lane).

Strict rules:
- Output JSON with: risk_level_value (one of HIGH/MEDIUM/LOW/NOT_APPLICABLE),
  confidence (0.0-1.0), drivers (sector + moat + lifecycle factors with
  severity + detail + citations), flags (named conditions like
  sector_weakening_concentration), reasoning_trace.
- Cite sector data sources and moat / lifecycle / five-forces classifications.
- Pure-debt or pure-cash portfolios produce NOT_APPLICABLE.
- Low field coverage (<60%) sets `low_field_coverage` flag with reduced
  confidence; surface missing fields in reasoning_trace.
- Never produce decision language. Surface findings only.
"""


class E2IndustryAnalyst(CanonicalEvidenceAgent):
    """Section 11.3 — E2 Industry Analyst on canonical inputs.

    Inputs (per `evaluate()`):
      * `envelope` — standard `AgentActivationEnvelope`.
      * `holdings` — list of `Holding` from M0.PortfolioState.
      * `sector_weights` — dict of sector → portfolio fraction (look-through-
        aware; pre-computed by caller using `compute_concentration` or upstream).
      * `sector_evaluations` — optional list of `E2SectorEvaluation` with
        moat / lifecycle / five-forces from the firm's industry database.
        Pass 8 accepts these as a parameter; Phase D integrates with E2's
        upstream substrate.
      * `data_as_of` — when the sector data was last refreshed (for staleness).
      * `field_coverage_pct` — 0.0–1.0 fraction of holdings with sector data.
    """

    agent_id = "industry_analyst"

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def is_applicable(self, holdings: list[Holding]) -> bool:
        """Per §11.3.7: E2 is NOT_APPLICABLE on pure-debt or pure-cash portfolios."""
        return any(
            h.asset_class == AssetClass.EQUITY for h in holdings
        )

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> E2Verdict:
        """E2-specific override: short-circuit to NOT_APPLICABLE on non-equity portfolios."""
        holdings: list[Holding] = kwargs.get("holdings", [])
        if holdings and not self.is_applicable(holdings):
            return self._not_applicable_verdict(envelope, **kwargs)

        verdict = await super().evaluate(envelope, **kwargs)
        # `evaluate` from base returns a StandardEvidenceVerdict typed as
        # whatever the subclass's `_build_verdict` returns — cast for clarity.
        assert isinstance(verdict, E2Verdict)
        return verdict

    def _render_signals(
        self,
        envelope: AgentActivationEnvelope,
        *,
        holdings: list[Holding] | None = None,
        sector_weights: dict[str, PercentageField] | None = None,
        sector_evaluations: list[E2SectorEvaluation] | None = None,
        data_as_of: date | None = None,
        field_coverage_pct: PercentageField = 1.0,
    ) -> str:
        """Render sector / moat / lifecycle signals into the prompt."""
        lines: list[str] = []
        if sector_weights:
            for sector, weight in sorted(sector_weights.items(), key=lambda kv: -kv[1]):
                lines.append(f"sector.{sector}.weight = {weight:.4f}")
        else:
            lines.append("(no sector_weights supplied — partial evaluation)")

        if sector_evaluations:
            for ev in sector_evaluations:
                if ev.moat is not None:
                    lines.append(
                        f"sector.{ev.sector}.moat = {ev.moat.classification}"
                    )
                if ev.lifecycle is not None:
                    lines.append(
                        f"sector.{ev.sector}.lifecycle = {ev.lifecycle.stage}"
                    )

        lines.append(f"field_coverage_pct = {field_coverage_pct:.2f}")
        if data_as_of is not None:
            lines.append(f"data_as_of = {data_as_of.isoformat()}")
        return "\n".join(lines)

    def _build_verdict(
        self,
        envelope: AgentActivationEnvelope,
        llm_core: _LlmEvidenceCore,
        signals_input_for_hash: dict[str, Any],
        *,
        holdings: list[Holding] | None = None,
        sector_weights: dict[str, PercentageField] | None = None,
        sector_evaluations: list[E2SectorEvaluation] | None = None,
        data_as_of: date | None = None,
        field_coverage_pct: PercentageField = 1.0,
    ) -> E2Verdict:
        risk_level = RiskLevel(llm_core.risk_level_value)

        # Deterministic flags
        flags = list(dict.fromkeys(llm_core.flags))
        deterministic = self._derive_deterministic_flags(
            sector_weights=sector_weights,
            field_coverage_pct=field_coverage_pct,
        )
        for f in deterministic:
            if f not in flags:
                flags.append(f)

        # Portfolio quality verdict — roll-up at the headline level
        portfolio_quality = E2PortfolioQualityVerdict(
            overall_risk_level=risk_level,
            overall_confidence=llm_core.confidence,
            drivers=llm_core.drivers,
        )

        manifest = self._build_inputs_used_manifest(signals_input_for_hash)
        ihash = payload_hash(signals_input_for_hash)

        return E2Verdict(
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            risk_level=risk_level,
            confidence=llm_core.confidence,
            drivers=llm_core.drivers,
            flags=flags,
            reasoning_trace=llm_core.reasoning_trace,
            inputs_used_manifest=manifest,
            input_hash=ihash,
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
            sector_evaluations=sector_evaluations or [],
            portfolio_quality_verdict=portfolio_quality,
            field_coverage_pct=field_coverage_pct,
            data_as_of=data_as_of,
        )

    def _derive_deterministic_flags(
        self,
        *,
        sector_weights: dict[str, PercentageField] | None,
        field_coverage_pct: PercentageField,
    ) -> list[str]:
        flags: list[str] = []
        if field_coverage_pct < DEFAULT_LOW_FIELD_COVERAGE_THRESHOLD:
            flags.append("low_field_coverage")
        if sector_weights:
            top_sector_weight = max(sector_weights.values())
            if top_sector_weight >= DEFAULT_SECTOR_CONCENTRATION_BREACH:
                flags.append("sector_weakening_concentration")
        return flags

    def _not_applicable_verdict(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> E2Verdict:
        """Per §11.3.7: pure-debt portfolio → NOT_APPLICABLE without LLM call."""
        signals_input = self._collect_input_for_hash(envelope, **kwargs)
        manifest = self._build_inputs_used_manifest(signals_input)
        ihash = payload_hash(signals_input)
        return E2Verdict(
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            risk_level=RiskLevel.NOT_APPLICABLE,
            confidence=1.0,
            drivers=[
                Driver(
                    factor="non_equity_portfolio",
                    direction=DriverDirection.NEUTRAL,
                    severity=DriverSeverity.LOW,
                    detail="Portfolio contains no listed equity holdings; E2 lane does not apply.",
                )
            ],
            flags=[],
            reasoning_trace=(
                "Portfolio contains no listed equity holdings (no asset_class=equity entries). "
                "E2 lane is NOT_APPLICABLE per Section 11.3.7."
            ),
            inputs_used_manifest=manifest,
            input_hash=ihash,
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
        )


__all__ = ["E2IndustryAnalyst"]
