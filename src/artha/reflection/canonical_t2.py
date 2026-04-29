"""§13.8 — T2 Reflection Engine.

T2 closes the learning loop. It reads T1 history + outcomes + A1
accountability flags + PM1 drift records and produces a `T2ReflectionRun`
containing:

  * Findings (LLM-backed) — observations across seven categories.
  * Calibration curves (deterministic) — one per agent / component.
  * Prompt-update proposals (LLM-backed) — actionable text edits.
  * Rule-update proposals (LLM-backed) — G2 corpus updates.
  * Recommended actions (LLM-backed) — ranked priorities.

Per §13.8.6 NO prompt update deploys without explicit firm signoff. T2
emits proposals into a governance review queue (`T2RunStatus.IN_GOVERNANCE_REVIEW`).

Pass 13 ships:
  * Calibration-curve computation (deterministic) — bucketed (predicted_prob,
    observed_outcome_rate) pairs per component.
  * LLM-backed findings + proposals using a pluggable LLMProvider.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.monitoring import (
    T2CalibrationCurve,
    T2Finding,
    T2FindingCategory,
    T2PromptUpdateProposal,
    T2ReflectionRun,
    T2RuleUpdateProposal,
    T2RunStatus,
    T2RunType,
    _LlmT2Output,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.types import (
    ConfidenceField,
    InputsUsedManifest,
)
from artha.common.ulid import new_ulid
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


# Minimum sample size before T2 issues findings (per §13.8.8 Test 2).
MIN_SAMPLES_FOR_FINDING = 30
# Number of calibration buckets (deciles by default).
DEFAULT_CALIBRATION_BUCKETS = 10


class T2LLMUnavailableError(ArthaError):
    """Raised when T2's LLM provider fails."""


class CalibrationSample(BaseModel):
    """One sample for calibration: predicted probability + observed outcome.

    `outcome` is 0/1 (or 0.0/1.0). `component_id` distinguishes per-agent
    calibration so the engine can produce one curve per component.
    """

    model_config = ConfigDict(extra="forbid")

    component_id: str
    predicted_probability: ConfidenceField
    outcome: float = Field(ge=0.0, le=1.0)


class ReflectionScope(BaseModel):
    """Inputs to a single T2 run."""

    model_config = ConfigDict(extra="forbid")

    firm_id: str
    period_start_at: datetime
    period_end_at: datetime
    components: list[str] = Field(default_factory=list)
    case_types: list[str] = Field(default_factory=list)
    calibration_samples: list[CalibrationSample] = Field(default_factory=list)
    flag_firing_rates: dict[str, dict[str, float]] = Field(default_factory=dict)
    a1_flag_counts: dict[str, int] = Field(default_factory=dict)
    pm1_drift_summary: dict[str, Any] = Field(default_factory=dict)
    new_rule_corpus_versions: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You are T2, the Reflection Engine for Samriddhi AI (§13.8).

Your job: read the system's recent telemetry (calibration metrics, flag
firing rates, A1 accountability flags, PM1 drift summary, new rule corpus
versions) and produce structured findings + actionable proposals.

Strict rules:
- Output JSON with: findings, prompt_update_proposals, rule_update_proposals,
  recommended_actions, reasoning_trace.
- Findings cite at least one supporting T1 event id when available.
- Prompt-update proposals are operationally actionable: name the component,
  the prompt section, the proposed change verbatim, and the rationale.
- Rule-update proposals reference rule_id, propose specific text changes.
- Recommended actions are ranked by priority (highest first).
- T2 never deploys; it surfaces proposals into a governance review queue.
"""


class ReflectionEngine:
    """§13.8 reflection engine."""

    agent_id = "t2_reflection"

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        min_samples_for_finding: int = MIN_SAMPLES_FOR_FINDING,
        calibration_buckets: int = DEFAULT_CALIBRATION_BUCKETS,
        prompt_version: str = "0.1.0",
        agent_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._min_samples = min_samples_for_finding
        self._buckets = calibration_buckets
        self._prompt_version = prompt_version
        self._agent_version = agent_version

    # --------------------- Public API --------------------------------

    async def run(
        self,
        *,
        run_type: T2RunType = T2RunType.SCHEDULED_MONTHLY,
        scope: ReflectionScope,
    ) -> T2ReflectionRun:
        """Execute one reflection run end-to-end."""
        # 1) Deterministic: per-component calibration curves.
        curves = self._compute_calibration_curves(scope.calibration_samples)

        # 2) LLM-backed: findings + proposals (only if provider supplied AND
        # at least one component has enough samples).
        findings: list[T2Finding] = []
        prompt_proposals: list[T2PromptUpdateProposal] = []
        rule_proposals: list[T2RuleUpdateProposal] = []
        recommended_actions: list[str] = []

        eligible_for_findings = any(c.sample_size >= self._min_samples for c in curves)
        if self._provider is not None and eligible_for_findings:
            (
                findings,
                prompt_proposals,
                rule_proposals,
                recommended_actions,
            ) = await self._llm_findings(scope, curves)

        # 3) Block findings on insufficient samples (§13.8.8 Test 2).
        findings = [f for f in findings if self._finding_supported(f, curves)]

        signals_input = self._collect_input_for_hash(scope=scope, curves=curves)

        return T2ReflectionRun(
            run_id=new_ulid(),
            run_type=run_type,
            period_start_at=scope.period_start_at,
            period_end_at=scope.period_end_at,
            timestamp=self._now(),
            firm_id=scope.firm_id,
            scope_components=list(scope.components),
            scope_case_types=list(scope.case_types),
            findings=findings,
            prompt_update_proposals=prompt_proposals,
            rule_update_proposals=rule_proposals,
            calibration_curves=curves,
            recommended_actions=recommended_actions,
            status=T2RunStatus.IN_GOVERNANCE_REVIEW,
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
        )

    # --------------------- Calibration curves (deterministic) ---------

    def _compute_calibration_curves(
        self, samples: list[CalibrationSample]
    ) -> list[T2CalibrationCurve]:
        """Bucket (predicted, observed) pairs per component."""
        by_component: dict[str, list[CalibrationSample]] = {}
        for s in samples:
            by_component.setdefault(s.component_id, []).append(s)

        curves: list[T2CalibrationCurve] = []
        for component_id, comp_samples in sorted(by_component.items()):
            curve_data: list[tuple[float, float]] = []
            buckets: list[list[CalibrationSample]] = [
                [] for _ in range(self._buckets)
            ]
            for s in comp_samples:
                idx = min(int(s.predicted_probability * self._buckets), self._buckets - 1)
                buckets[idx].append(s)
            for bucket in buckets:
                if not bucket:
                    continue
                pred_mean = sum(b.predicted_probability for b in bucket) / len(bucket)
                obs_mean = sum(b.outcome for b in bucket) / len(bucket)
                curve_data.append((round(pred_mean, 6), round(obs_mean, 6)))
            curves.append(
                T2CalibrationCurve(
                    component_id=component_id,
                    sample_size=len(comp_samples),
                    curve_data=curve_data,
                    bucket_count=self._buckets,
                )
            )
        return curves

    # --------------------- LLM findings -------------------------------

    async def _llm_findings(
        self,
        scope: ReflectionScope,
        curves: list[T2CalibrationCurve],
    ) -> tuple[
        list[T2Finding],
        list[T2PromptUpdateProposal],
        list[T2RuleUpdateProposal],
        list[str],
    ]:
        signals_block = self._render_signals(scope, curves)
        user_text = (
            f"Firm: {scope.firm_id}\n"
            f"Period: {scope.period_start_at.isoformat()} → {scope.period_end_at.isoformat()}\n"
            f"Scope components: {','.join(scope.components) or '<none>'}\n"
            f"Signals:\n{signals_block}\n"
            "Produce the structured T2 findings + proposals per the system prompt."
        )

        try:
            llm_output = await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=_SYSTEM_PROMPT),
                        LLMMessage(role="user", content=user_text),
                    ],
                    temperature=0.0,
                ),
                _LlmT2Output,
            )
        except Exception as exc:
            logger.warning("T2 LLM unavailable: %s", exc)
            raise T2LLMUnavailableError(
                f"t2 LLM provider unavailable: {exc}"
            ) from exc

        return (
            list(llm_output.findings),
            list(llm_output.prompt_update_proposals),
            list(llm_output.rule_update_proposals),
            list(llm_output.recommended_actions),
        )

    def _finding_supported(
        self,
        finding: T2Finding,
        curves: list[T2CalibrationCurve],
    ) -> bool:
        """A finding is suppressed when it cites a calibration insight from
        a component below the minimum sample size."""
        if finding.category is not T2FindingCategory.CONFIDENCE_CALIBRATION:
            return True  # non-calibration findings pass through
        # Block if any calibration curve referenced is undersampled.
        for curve in curves:
            if curve.component_id in finding.observation:
                if curve.sample_size < self._min_samples:
                    return False
        return True

    # --------------------- Helpers ----------------------------------

    def _render_signals(
        self,
        scope: ReflectionScope,
        curves: list[T2CalibrationCurve],
    ) -> str:
        lines: list[str] = []
        for curve in curves:
            lines.append(
                f"calibration.{curve.component_id}.sample_size = {curve.sample_size}"
            )
            for pred, obs in curve.curve_data[:3]:
                lines.append(
                    f"calibration.{curve.component_id}.point pred={pred:.4f} obs={obs:.4f}"
                )
        for component, rates in scope.flag_firing_rates.items():
            for flag, rate in rates.items():
                lines.append(f"flag.{component}.{flag}.firing_rate = {rate:.4f}")
        for flag, count in scope.a1_flag_counts.items():
            lines.append(f"a1.{flag}.count = {count}")
        if scope.pm1_drift_summary:
            for k, v in sorted(scope.pm1_drift_summary.items()):
                lines.append(f"pm1.drift.{k} = {v}")
        for v in scope.new_rule_corpus_versions:
            lines.append(f"rule_corpus.new_version = {v}")
        return "\n".join(lines) if lines else "(no signals)"

    def _collect_input_for_hash(
        self,
        *,
        scope: ReflectionScope,
        curves: list[T2CalibrationCurve],
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "firm_id": scope.firm_id,
            "period_start_at": scope.period_start_at.isoformat(),
            "period_end_at": scope.period_end_at.isoformat(),
            "components": sorted(scope.components),
            "case_types": sorted(scope.case_types),
            "calibration_curves": [c.model_dump(mode="json") for c in curves],
            "flag_firing_rates": scope.flag_firing_rates,
            "a1_flag_counts": scope.a1_flag_counts,
            "new_rule_corpus_versions": list(scope.new_rule_corpus_versions),
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
    "DEFAULT_CALIBRATION_BUCKETS",
    "MIN_SAMPLES_FOR_FINDING",
    "CalibrationSample",
    "ReflectionEngine",
    "ReflectionScope",
    "T2LLMUnavailableError",
]
