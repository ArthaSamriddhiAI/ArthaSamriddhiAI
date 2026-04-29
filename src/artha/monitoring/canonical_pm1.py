"""§13.6 — PM1 Portfolio Monitoring Agent.

PM1 has four event types (§13.6.2):

  * `drift` — deterministic L1/L2/L3 drift detection (uses `model_portfolio.tolerance`).
  * `benchmark_divergence` — deterministic rolling-window return delta vs benchmark.
  * `threshold_breach` — deterministic risk-threshold check against `MandateObject`
    (concentration, liquidity, fee drag).
  * `thesis_validity` — LLM-backed: reads case `reasoning_trace` against realised
    outcomes and labels validated / partially_validated / contradicted / indeterminate.

PM1 emits structured `PM1Event` records and (when material) corresponding
`N0Alert` notifications. Cadence (§13.6.3): daily for drift+benchmark+thresholds,
monthly for thesis validity. The agent itself doesn't schedule — the orchestrator
calls it on the appropriate cadence.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.case import CaseObject
from artha.canonical.mandate import MandateObject
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.canonical.monitoring import (
    M1BreachType,
    N0Alert,
    N0AlertCategory,
    N0Originator,
    PM1BenchmarkDivergenceDetail,
    PM1DriftDetail,
    PM1Event,
    PM1EventType,
    PM1ThesisValidityDetail,
    PM1ThresholdBreachDetail,
    ThesisValidityStatus,
    _LlmPM1ThesisOutput,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.types import (
    AlertTier,
    InputsUsedManifest,
    RunMode,
)
from artha.common.ulid import new_ulid
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest
from artha.model_portfolio.tolerance import (
    DriftDimension,
    DriftSeverity,
    PortfolioAllocationSnapshot,
    detect_drift_events,
)

logger = logging.getLogger(__name__)


# Default benchmark divergence threshold (§13.6.2): 200bps over a rolling window.
DEFAULT_BENCHMARK_DIVERGENCE_THRESHOLD = 0.02


class ThesisValidityLLMUnavailableError(ArthaError):
    """Raised when PM1's thesis-validity LLM provider fails."""


_THESIS_PROMPT = """\
You are PM1's thesis-validity scorer (§13.6.2).

Your job: given a case's reasoning_trace from S1 + the realised outcome at the
evaluation horizon, label the thesis as one of:

  * validated — outcome lines up with the thesis.
  * partially_validated — major dimensions hold; minor dimensions don't.
  * contradicted — outcome diverges from the thesis materially.
  * indeterminate — outcome window too short or too noisy to judge.

Output JSON: status (one of the four), rationale (≤200 tokens), confidence
(0.0-1.0).

Cite specific dimensions of the thesis. Never produce decision language.
"""


class PM1ThesisValidityInputs(BaseModel):
    """Inputs PM1's thesis-validity sub-agent reads."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    thesis_text: str
    realised_return: float | None = None
    realised_observations: list[str] = Field(default_factory=list)
    horizon_days: int = 0


# ===========================================================================
# Agent
# ===========================================================================


class PortfolioMonitoringAgent:
    """§13.6 — PM1 portfolio monitoring agent.

    Construction:
      * `provider` — LLM provider for thesis-validity.
      * `benchmark_divergence_threshold` — fraction (default 0.02 = 200bps).
    """

    agent_id = "portfolio_monitoring"

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        benchmark_divergence_threshold: float = DEFAULT_BENCHMARK_DIVERGENCE_THRESHOLD,
        agent_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._benchmark_divergence_threshold = benchmark_divergence_threshold
        self._agent_version = agent_version

    # --------------------- Drift detection -------------------------------

    def detect_drift_events(
        self,
        *,
        client_id: str,
        firm_id: str,
        model: ModelPortfolioObject,
        snapshot: PortfolioAllocationSnapshot,
        run_mode: RunMode = RunMode.CASE,
    ) -> list[PM1Event]:
        """Daily drift sweep — emits one PM1Event per breached cell.

        Wraps `model_portfolio.tolerance.detect_drift_events` (deterministic)
        and folds each `DriftEvent` into the canonical PM1Event shape.
        """
        drift_events = detect_drift_events(model, snapshot)

        events: list[PM1Event] = []
        for d in drift_events:
            detail = PM1DriftDetail(
                dimension=d.dimension.value,
                cell_key=d.cell_key,
                expected_value=d.target,
                observed_value=d.actual,
                drift_magnitude=d.drift_magnitude,
                threshold_band=d.tolerance_band,
            )

            n0_alert: N0Alert | None = None
            if d.severity is DriftSeverity.ACTION_REQUIRED:
                n0_alert = self._build_drift_n0_alert(
                    client_id=client_id, firm_id=firm_id, drift=d
                )

            input_bundle = self._collect_drift_input(
                client_id=client_id, firm_id=firm_id, dimension=d.dimension, cell=d.cell_key,
                target=d.target, actual=d.actual, band=d.tolerance_band,
            )

            events.append(
                PM1Event(
                    event_id=new_ulid(),
                    case_id=None,
                    client_id=client_id,
                    firm_id=firm_id,
                    timestamp=self._now(),
                    run_mode=run_mode,
                    event_type=PM1EventType.DRIFT,
                    drift_detail=detail,
                    originating_n0_alert_id=n0_alert.alert_id if n0_alert else None,
                    inputs_used_manifest=self._build_inputs_used_manifest(input_bundle),
                    input_hash=payload_hash(input_bundle),
                    agent_version=self._agent_version,
                )
            )
        return events

    def _build_drift_n0_alert(
        self,
        *,
        client_id: str,
        firm_id: str,
        drift: Any,  # DriftEvent
    ) -> N0Alert:
        return N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.PM1,
            tier=AlertTier.SHOULD_RESPOND,
            category=N0AlertCategory.DRIFT,
            client_id=client_id,
            firm_id=firm_id,
            created_at=self._now(),
            title=f"Drift breach at {drift.dimension.value}: {drift.cell_key}",
            body=(
                f"Portfolio cell {drift.cell_key} actual={drift.actual:.4f} vs "
                f"target={drift.target:.4f} (band {drift.tolerance_band:.4f}). "
                f"Magnitude {drift.drift_magnitude:+.4f}."
            ),
            expected_action="Review and rebalance per advisor judgement.",
            related_constraint_id=f"drift:{drift.dimension.value}:{drift.cell_key}",
        )

    # --------------------- Benchmark divergence --------------------------

    def detect_benchmark_divergence(
        self,
        *,
        client_id: str,
        firm_id: str,
        benchmark_id: str,
        portfolio_return_period: float,
        benchmark_return_period: float,
        rolling_window_days: int,
        run_mode: RunMode = RunMode.CASE,
    ) -> PM1Event | None:
        """Emit one PM1Event when |portfolio - benchmark| ≥ threshold.

        Returns None when divergence is within the threshold.
        """
        divergence = portfolio_return_period - benchmark_return_period
        if abs(divergence) < self._benchmark_divergence_threshold:
            return None

        detail = PM1BenchmarkDivergenceDetail(
            benchmark_id=benchmark_id,
            portfolio_return_period=portfolio_return_period,
            benchmark_return_period=benchmark_return_period,
            divergence_magnitude=divergence,
            rolling_window_days=rolling_window_days,
        )

        n0_alert = N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.PM1,
            tier=AlertTier.SHOULD_RESPOND,
            category=N0AlertCategory.BENCHMARK_DIVERGENCE,
            client_id=client_id,
            firm_id=firm_id,
            created_at=self._now(),
            title=f"Benchmark divergence vs {benchmark_id}",
            body=(
                f"Portfolio {portfolio_return_period:+.4f} vs "
                f"{benchmark_id} {benchmark_return_period:+.4f} over "
                f"{rolling_window_days}d window; divergence {divergence:+.4f}."
            ),
            expected_action="Review allocation drivers.",
        )

        input_bundle = {
            "agent_id": self.agent_id,
            "client_id": client_id,
            "benchmark_id": benchmark_id,
            "rolling_window_days": rolling_window_days,
            "portfolio_return": round(portfolio_return_period, 6),
            "benchmark_return": round(benchmark_return_period, 6),
            "threshold": self._benchmark_divergence_threshold,
        }

        return PM1Event(
            event_id=new_ulid(),
            client_id=client_id,
            firm_id=firm_id,
            timestamp=self._now(),
            run_mode=run_mode,
            event_type=PM1EventType.BENCHMARK_DIVERGENCE,
            benchmark_divergence_detail=detail,
            originating_n0_alert_id=n0_alert.alert_id,
            inputs_used_manifest=self._build_inputs_used_manifest(input_bundle),
            input_hash=payload_hash(input_bundle),
            agent_version=self._agent_version,
        )

    # --------------------- Risk threshold breach -------------------------

    def detect_threshold_breach(
        self,
        *,
        client_id: str,
        firm_id: str,
        mandate: MandateObject,
        threshold_rule_id: str,
        observed_value: float,
        limit_value: float,
        breach_type: M1BreachType,
        run_mode: RunMode = RunMode.CASE,
    ) -> PM1Event | None:
        """Emit a PM1Event when a continuous monitoring threshold trips.

        Returns None when no breach is present (caller can skip emission).
        """
        breach_magnitude = observed_value - limit_value
        if breach_magnitude <= 0 and breach_type not in (
            M1BreachType.LIQUIDITY_FLOOR,
            M1BreachType.ASSET_CLASS_FLOOR,
        ):
            return None  # observed under cap → no breach
        if breach_type in (M1BreachType.LIQUIDITY_FLOOR, M1BreachType.ASSET_CLASS_FLOOR):
            # For floors, breach is observed < limit
            breach_magnitude = limit_value - observed_value
            if breach_magnitude <= 0:
                return None

        detail = PM1ThresholdBreachDetail(
            threshold_rule_id=threshold_rule_id,
            observed_value=observed_value,
            breach_magnitude=breach_magnitude,
            mandate_implication=(
                f"mandate {mandate.mandate_id} v{mandate.version} "
                f"{breach_type.value} threshold breached"
            ),
        )

        n0_alert = N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.PM1,
            tier=AlertTier.MUST_RESPOND,
            category=N0AlertCategory.THRESHOLD_BREACH,
            client_id=client_id,
            firm_id=firm_id,
            created_at=self._now(),
            title=f"Threshold breach: {threshold_rule_id}",
            body=(
                f"observed={observed_value:.4f} vs limit={limit_value:.4f} "
                f"({breach_type.value}); magnitude {breach_magnitude:+.4f}."
            ),
            expected_action="Rebalance, amend mandate, or escalate.",
            related_constraint_id=threshold_rule_id,
        )

        input_bundle = {
            "agent_id": self.agent_id,
            "client_id": client_id,
            "threshold_rule_id": threshold_rule_id,
            "observed_value": round(observed_value, 6),
            "limit_value": round(limit_value, 6),
            "breach_type": breach_type.value,
            "mandate_version": mandate.version,
        }

        return PM1Event(
            event_id=new_ulid(),
            client_id=client_id,
            firm_id=firm_id,
            timestamp=self._now(),
            run_mode=run_mode,
            event_type=PM1EventType.THRESHOLD_BREACH,
            threshold_breach_detail=detail,
            originating_n0_alert_id=n0_alert.alert_id,
            inputs_used_manifest=self._build_inputs_used_manifest(input_bundle),
            input_hash=payload_hash(input_bundle),
            agent_version=self._agent_version,
        )

    # --------------------- Thesis validity (LLM-backed) ------------------

    async def evaluate_thesis_validity(
        self,
        *,
        case: CaseObject,
        inputs: PM1ThesisValidityInputs,
        run_mode: RunMode = RunMode.CASE,
    ) -> PM1Event:
        """Monthly LLM-backed thesis-validity evaluation.

        Raises `ThesisValidityLLMUnavailableError` on LLM failure.
        """
        if self._provider is None:
            raise ThesisValidityLLMUnavailableError(
                "PM1.evaluate_thesis_validity requires an LLM provider"
            )

        signals_block = self._render_thesis_signals(inputs)
        user_text = (
            f"Case: {case.case_id}\n"
            f"Client: {case.client_id}\n"
            f"Run mode: {run_mode.value}\n"
            f"Thesis text: {inputs.thesis_text}\n"
            f"Signals:\n{signals_block}\n"
            "Produce the structured thesis-validity output per the system prompt."
        )

        try:
            llm_output = await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=_THESIS_PROMPT),
                        LLMMessage(role="user", content=user_text),
                    ],
                    temperature=0.0,
                ),
                _LlmPM1ThesisOutput,
            )
        except Exception as exc:
            logger.warning("PM1 thesis-validity LLM unavailable: %s", exc)
            raise ThesisValidityLLMUnavailableError(
                f"thesis-validity LLM unavailable: {exc}"
            ) from exc

        detail = PM1ThesisValidityDetail(
            case_id=case.case_id,
            thesis_dimension="overall",
            status=llm_output.status,
            rationale=llm_output.rationale,
            confidence=llm_output.confidence,
        )

        # Surface to N0 only on contradicted (informational tier).
        n0_alert: N0Alert | None = None
        if llm_output.status is ThesisValidityStatus.CONTRADICTED:
            n0_alert = N0Alert(
                alert_id=new_ulid(),
                originator=N0Originator.PM1,
                tier=AlertTier.INFORMATIONAL,
                category=N0AlertCategory.THESIS_VALIDITY,
                case_id=case.case_id,
                client_id=case.client_id,
                firm_id=case.firm_id,
                created_at=self._now(),
                title=f"Thesis contradicted: case {case.case_id}",
                body=llm_output.rationale[:400],
                expected_action="Review thesis against realised outcome.",
            )

        input_bundle = {
            "agent_id": self.agent_id,
            "case_id": case.case_id,
            "thesis_text": inputs.thesis_text,
            "horizon_days": inputs.horizon_days,
            "realised_return": (
                round(inputs.realised_return, 6) if inputs.realised_return is not None else None
            ),
            "realised_observations": list(inputs.realised_observations),
        }

        return PM1Event(
            event_id=new_ulid(),
            case_id=case.case_id,
            client_id=case.client_id,
            firm_id=case.firm_id,
            timestamp=self._now(),
            run_mode=run_mode,
            event_type=PM1EventType.THESIS_VALIDITY,
            thesis_validity_detail=detail,
            originating_n0_alert_id=n0_alert.alert_id if n0_alert else None,
            inputs_used_manifest=self._build_inputs_used_manifest(input_bundle),
            input_hash=payload_hash(input_bundle),
            agent_version=self._agent_version,
        )

    # --------------------- Helpers ----------------------------------

    def _render_thesis_signals(self, inputs: PM1ThesisValidityInputs) -> str:
        lines = [
            f"horizon_days = {inputs.horizon_days}",
        ]
        if inputs.realised_return is not None:
            lines.append(f"realised_return = {inputs.realised_return:+.4f}")
        for obs in inputs.realised_observations:
            lines.append(f"observation: {obs}")
        return "\n".join(lines)

    def _collect_drift_input(
        self,
        *,
        client_id: str,
        firm_id: str,
        dimension: DriftDimension,
        cell: str,
        target: float,
        actual: float,
        band: float,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "client_id": client_id,
            "firm_id": firm_id,
            "dimension": dimension.value,
            "cell_key": cell,
            "target": round(target, 6),
            "actual": round(actual, 6),
            "tolerance_band": round(band, 6),
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "DEFAULT_BENCHMARK_DIVERGENCE_THRESHOLD",
    "PM1ThesisValidityInputs",
    "PortfolioAllocationSnapshot",
    "PortfolioMonitoringAgent",
    "ThesisValidityLLMUnavailableError",
]
