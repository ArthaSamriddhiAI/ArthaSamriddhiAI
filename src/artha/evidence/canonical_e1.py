"""Section 11.2 — E1 Financial Risk Agent on canonical inputs.

E1 reads concentration / leverage / liquidity / return-quality / deployment /
cascade signals from M0.PortfolioAnalytics and the model portfolio reference,
then asks the LLM to interpret the metrics relative to bucket norms and the
proposed action (case mode) or the model portfolio (diagnostic mode).

The numeric inputs come from PortfolioAnalytics (Pass 5); E1's job is the
interpretive layer. Per §11.2.1 "the numbers come from PortfolioAnalytics; the
interpretation is E1's."

Pass 8 ships the canonical service. Pass 11+ wires it into M0 orchestration
and S1 synthesis.
"""

from __future__ import annotations

from typing import Any

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import (
    E1DimensionVerdict,
    E1Verdict,
    _LlmEvidenceCore,
)
from artha.canonical.holding import Holding
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.canonical.portfolio_analytics import (
    AnalyticsQueryResult,
)
from artha.common.hashing import payload_hash
from artha.common.types import (
    RiskLevel,
)
from artha.evidence.canonical_base import CanonicalEvidenceAgent

# ===========================================================================
# Bucket-relative concentration norms (§11.2.2)
# ===========================================================================
#
# Per §11.2.2 E1 interprets concentration relative to the bucket's expected
# concentration profile (Aggressive accepts higher concentration than
# Conservative). The model portfolio's `counterfactual.expected_concentration_profile`
# (§15.5.1) is the firm's tuning surface; these are sensible MVP defaults
# used when no per-bucket profile is supplied.
_DEFAULT_HHI_HIGH_THRESHOLD: dict[str, float] = {
    "CON_ST": 0.20, "CON_MT": 0.20, "CON_LT": 0.20,
    "MOD_ST": 0.30, "MOD_MT": 0.30, "MOD_LT": 0.30,
    "AGG_ST": 0.40, "AGG_MT": 0.40, "AGG_LT": 0.40,
}


_SYSTEM_PROMPT = """\
You are E1, the Financial Risk evidence agent for Samriddhi AI.

Your lane (§11.2.2): concentration, leverage, liquidity, return quality,
deployment, cascade modelling. You do NOT opine on industry dynamics (E2),
macro (E3), behavioural patterns (E4), unlisted equity (E5), or product
suitability (E6).

Strict rules:
- Output JSON with: risk_level_value (one of HIGH/MEDIUM/LOW/NOT_APPLICABLE),
  confidence (0.0-1.0), drivers (3-5 most material factors with severity +
  direction + detail + citations), flags (named conditions like
  concentration_breach), reasoning_trace (short formal-English narrative).
- Cite at least three named PortfolioAnalytics metrics in reasoning_trace.
- Use risk levels relative to the bucket norm (Aggressive accepts higher
  concentration than Conservative).
- Never produce decision language ("approve", "reject"). Surface findings
  only.
- Confidence calibrates the verdict, not effort. A clear-cut classification
  scores >=0.85.
"""


class E1FinancialRisk(CanonicalEvidenceAgent):
    """Section 11.2 — E1 Financial Risk on canonical inputs.

    Inputs (per `evaluate()`):
      * `envelope` — standard `AgentActivationEnvelope` from Pass 6.
      * `holdings` — list of `Holding` from M0.PortfolioState.
      * `analytics` — `AnalyticsQueryResult` from M0.PortfolioAnalytics with at
        least the deployment / liquidity / concentration / fees / tax categories
        populated.
      * `model_portfolio` — `ModelPortfolioObject` for the client's bucket.
      * `bucket_concentration_thresholds` (optional override) — per-bucket HHI
        threshold for `concentration_breach` flag.
    """

    agent_id = "financial_risk"

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def _render_signals(
        self,
        envelope: AgentActivationEnvelope,
        *,
        holdings: list[Holding] | None = None,
        analytics: AnalyticsQueryResult | None = None,
        model_portfolio: ModelPortfolioObject | None = None,
        bucket_concentration_thresholds: dict[str, float] | None = None,
    ) -> str:
        """Render concentration / liquidity / fees / cascade signals as a prompt block."""
        if analytics is None:
            return "(no PortfolioAnalytics output supplied — partial evaluation)"

        thresholds = bucket_concentration_thresholds or _DEFAULT_HHI_HIGH_THRESHOLD
        bucket = envelope.case.payload.get("bucket") if envelope.case.payload else None
        if bucket is None and model_portfolio is not None:
            bucket = model_portfolio.bucket.value

        lines: list[str] = []

        if analytics.deployment is not None:
            lines.append(
                f"deployment.total_aum_inr = {analytics.deployment.total_aum_inr:.0f}"
            )
            lines.append(
                f"deployment.cash_buffer_inr = {analytics.deployment.cash_buffer_inr:.0f}"
            )
            lines.append(
                "deployment.undeployed_investable_assets_inr = "
                f"{analytics.deployment.undeployed_investable_assets_inr:.0f}"
            )

        if analytics.concentration is not None:
            c = analytics.concentration
            lines.append(f"concentration.hhi_holding_level = {c.hhi_holding_level:.4f}")
            lines.append(f"concentration.hhi_manager_level = {c.hhi_manager_level:.4f}")
            if c.hhi_lookthrough_stock_level is not None:
                lines.append(
                    "concentration.hhi_lookthrough_stock_level = "
                    f"{c.hhi_lookthrough_stock_level:.4f}"
                )
            if isinstance(bucket, str):
                threshold = thresholds.get(bucket, 0.30)
                lines.append(
                    f"bucket.{bucket}.hhi_threshold = {threshold:.4f}"
                )

        if analytics.liquidity is not None:
            most_liquid = analytics.liquidity.liquidity_buckets
            for k, v in most_liquid.items():
                lines.append(f"liquidity.{k.value} = {v:.4f}")
            lines.append(
                f"liquidity.floor_compliance = {analytics.liquidity.liquidity_floor_compliance}"
            )

        if analytics.fees is not None:
            lines.append(f"fees.aggregate_fee_bps = {analytics.fees.aggregate_fee_bps}")
            lines.append(
                f"fees.fee_data_incomplete = {analytics.fees.flags.fee_data_incomplete}"
            )

        if analytics.tax is not None:
            lines.append(
                f"tax.tax_basis_stale_days = {analytics.tax.flags.tax_basis_stale_days}"
            )
            lines.append(
                f"tax.unrealised_gain_loss_total_inr = "
                f"{analytics.tax.unrealised_gain_loss_total_inr:.0f}"
            )

        return "\n".join(lines) if lines else "(no analytics signals available)"

    def _build_verdict(
        self,
        envelope: AgentActivationEnvelope,
        llm_core: _LlmEvidenceCore,
        signals_input_for_hash: dict[str, Any],
        *,
        holdings: list[Holding] | None = None,
        analytics: AnalyticsQueryResult | None = None,
        model_portfolio: ModelPortfolioObject | None = None,
        bucket_concentration_thresholds: dict[str, float] | None = None,
    ) -> E1Verdict:
        """Wrap the LLM core into a typed E1Verdict with deterministic flags + dimensions."""
        # Validated to be a canonical enum value in the base class
        risk_level = RiskLevel(llm_core.risk_level_value)

        # Compose flags: LLM flags + deterministic flags we know to trip
        flags = list(dict.fromkeys(llm_core.flags))  # preserve order, deduplicate
        deterministic_flags = self._derive_deterministic_flags(
            analytics=analytics,
            model_portfolio=model_portfolio,
            bucket_concentration_thresholds=bucket_concentration_thresholds,
        )
        for f in deterministic_flags:
            if f not in flags:
                flags.append(f)

        if analytics is None:
            if "partial_evaluation" not in flags:
                flags.append("partial_evaluation")

        # Per-dimension sub-verdicts (§11.2.2). The LLM emits portfolio-level;
        # for Pass 8 the per-dimension layer mirrors the headline. Pass 11+
        # may have the LLM emit per-dimension if S1 needs that granularity.
        dimensions = self._build_dimensions(risk_level, analytics)

        manifest = self._build_inputs_used_manifest(signals_input_for_hash)
        ihash = payload_hash(signals_input_for_hash)

        return E1Verdict(
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
            dimensions_evaluated=dimensions,
        )

    def _derive_deterministic_flags(
        self,
        *,
        analytics: AnalyticsQueryResult | None,
        model_portfolio: ModelPortfolioObject | None,
        bucket_concentration_thresholds: dict[str, float] | None = None,
    ) -> list[str]:
        """Compute deterministic flags from analytics signals.

        These are flags the LLM should emit but might miss; we add them
        deterministically so consumers (S1, A1) don't have to second-guess.
        """
        flags: list[str] = []
        if analytics is None:
            return flags

        # concentration_breach (§15.7.1)
        if analytics.concentration is not None and model_portfolio is not None:
            thresholds = bucket_concentration_thresholds or _DEFAULT_HHI_HIGH_THRESHOLD
            threshold = thresholds.get(model_portfolio.bucket.value, 0.30)
            if analytics.concentration.hhi_holding_level >= threshold:
                flags.append("concentration_breach")

        # liquidity_floor_proximity / fee_drag_excessive / tax_basis_stale_days
        if analytics.liquidity is not None and not analytics.liquidity.liquidity_floor_compliance:
            flags.append("liquidity_floor_proximity")

        if analytics.fees is not None and analytics.fees.aggregate_fee_bps >= 250:
            flags.append("fee_drag_excessive")

        if (
            analytics.tax is not None
            and analytics.tax.flags.tax_basis_stale_days is not None
            and analytics.tax.flags.tax_basis_stale_days > 0
        ):
            flags.append("tax_basis_stale_days")

        return flags

    def _build_dimensions(
        self,
        overall_risk: RiskLevel,
        analytics: AnalyticsQueryResult | None,
    ) -> list[E1DimensionVerdict]:
        """Roll up per-dimension sub-verdicts (§11.2.2).

        Pass 8's heuristic: each evaluable dimension inherits the overall risk
        level; future passes may have the LLM emit per-dimension separately
        for finer S1 synthesis.
        """
        if analytics is None:
            return []

        dims: list[E1DimensionVerdict] = []
        if analytics.concentration is not None:
            dims.append(
                E1DimensionVerdict(
                    dimension="concentration",
                    risk_level=overall_risk,
                    summary=(
                        f"HHI holding={analytics.concentration.hhi_holding_level:.4f}, "
                        f"manager={analytics.concentration.hhi_manager_level:.4f}"
                    ),
                )
            )
        if analytics.liquidity is not None:
            dims.append(
                E1DimensionVerdict(
                    dimension="liquidity",
                    risk_level=overall_risk,
                    summary=(
                        f"floor_compliance={analytics.liquidity.liquidity_floor_compliance}"
                    ),
                )
            )
        if analytics.fees is not None:
            dims.append(
                E1DimensionVerdict(
                    dimension="return_quality",
                    risk_level=overall_risk,
                    summary=f"aggregate_fee_bps={analytics.fees.aggregate_fee_bps}",
                )
            )
        if analytics.deployment is not None:
            dims.append(
                E1DimensionVerdict(
                    dimension="deployment",
                    risk_level=overall_risk,
                    summary=(
                        f"undeployed={analytics.deployment.undeployed_investable_assets_inr:.0f}"
                    ),
                )
            )
        return dims


__all__ = ["E1FinancialRisk"]
