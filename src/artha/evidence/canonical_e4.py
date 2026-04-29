"""Section 11.5 — E4 Behavioural & Historical Agent.

E4 reasons about how the client has actually behaved (not stated). Reads T1
historical events for the client and produces a verdict on the gap between
stated and revealed risk tolerance, decision pattern stability, redemption
history, override patterns, engagement patterns, and horizon adherence.

Per §11.5.1 new clients have thinner E4 evidence; the `limited_history` flag
fires and confidence is capped at 0.5 (configurable via `LIMITED_HISTORY_THRESHOLD`).
"""

from __future__ import annotations

from typing import Any

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import (
    BehaviouralHistorySummary,
    E4Verdict,
    _LlmEvidenceCore,
)
from artha.common.hashing import payload_hash
from artha.common.types import (
    Driver,
    DriverDirection,
    DriverSeverity,
    RiskLevel,
)
from artha.evidence.canonical_base import CanonicalEvidenceAgent

# Per §11.5.1: relationship-history threshold below which `limited_history`
# fires and confidence is capped. Pass 9 ships a sensible default; firms
# may tune via T2 calibration once production data accumulates.
LIMITED_HISTORY_EVENT_THRESHOLD = 50
LIMITED_HISTORY_CONFIDENCE_CAP = 0.5

# Below this event count we have no meaningful history at all.
NO_HISTORY_EVENT_THRESHOLD = 5


_SYSTEM_PROMPT = """\
You are E4, the Behavioural & Historical evidence agent for Samriddhi AI.

Your lane (§11.5.2): stated vs revealed risk tolerance, decision pattern
stability, reaction to market events, override frequency and pattern,
engagement patterns, stated horizon adherence.

You do NOT opine on financial metrics (E1), industry dynamics (E2), macro
(E3), products (E6), or unlisted (E5). Your evidence is the client's
historical actions read from T1.

Strict rules:
- Output JSON with: risk_level_value, confidence, drivers, flags,
  reasoning_trace.
- Cite at least three specific historical events (with timestamps) for
  established-client verdicts; new-client verdicts cite the limited-history
  reason and surface the `limited_history` flag.
- New clients (no_history) confidence <= 0.0; limited_history confidence
  capped at 0.5; established clients use full calibration.
- Never produce decision language. Surface findings only.
"""


class E4BehaviouralHistorical(CanonicalEvidenceAgent):
    """Section 11.5 — E4 Behavioural / Historical on canonical inputs.

    Inputs (per `evaluate()`):
      * `envelope` — standard `AgentActivationEnvelope`.
      * `history` — `BehaviouralHistorySummary` summarising T1 events for the
        client. Pass 9's tests inject this directly; Phase D wires a
        `BehaviouralHistoryProvider` reading T1.
    """

    agent_id = "behavioural_historical"

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def is_no_history(self, history: BehaviouralHistorySummary | None) -> bool:
        return history is None or history.event_count < NO_HISTORY_EVENT_THRESHOLD

    def is_limited_history(self, history: BehaviouralHistorySummary | None) -> bool:
        return (
            history is not None
            and NO_HISTORY_EVENT_THRESHOLD <= history.event_count < LIMITED_HISTORY_EVENT_THRESHOLD
        )

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> E4Verdict:
        history: BehaviouralHistorySummary | None = kwargs.get("history")

        # No-history fast path (§11.5.7) — avoid LLM call for new clients.
        if self.is_no_history(history):
            return self._no_history_verdict(envelope, **kwargs)

        verdict = await super().evaluate(envelope, **kwargs)
        assert isinstance(verdict, E4Verdict)
        return verdict

    def _render_signals(
        self,
        envelope: AgentActivationEnvelope,
        *,
        history: BehaviouralHistorySummary | None = None,
    ) -> str:
        if history is None:
            return "(no behavioural history supplied)"
        lines = [
            f"history.window_days = {history.historical_window_days}",
            f"history.event_count = {history.event_count}",
            f"history.redemption_count_total = {history.redemption_count_total}",
            f"history.redemption_count_in_drawdowns = {history.redemption_count_in_drawdowns}",
            f"history.override_count = {history.override_count}",
            f"history.override_more_risk = {history.override_direction_more_risk}",
            f"history.override_less_risk = {history.override_direction_less_risk}",
        ]
        if history.horizon_adherence_score is not None:
            lines.append(f"history.horizon_adherence_score = {history.horizon_adherence_score:.4f}")
        if history.stated_risk_tolerance:
            lines.append(f"history.stated_risk_tolerance = {history.stated_risk_tolerance}")
        if history.revealed_risk_pattern:
            lines.append(f"history.revealed_risk_pattern = {history.revealed_risk_pattern}")
        return "\n".join(lines)

    def _build_verdict(
        self,
        envelope: AgentActivationEnvelope,
        llm_core: _LlmEvidenceCore,
        signals_input_for_hash: dict[str, Any],
        *,
        history: BehaviouralHistorySummary | None = None,
    ) -> E4Verdict:
        risk_level = RiskLevel(llm_core.risk_level_value)
        flags = list(dict.fromkeys(llm_core.flags))
        confidence = llm_core.confidence

        # Apply the limited-history cap if applicable
        if history is not None and self.is_limited_history(history):
            if "limited_history" not in flags:
                flags.append("limited_history")
            confidence = min(confidence, LIMITED_HISTORY_CONFIDENCE_CAP)

        # Deterministic redemption-volatility flag
        if (
            history is not None
            and history.redemption_count_total > 0
            and history.redemption_count_in_drawdowns
            >= max(1, history.redemption_count_total // 2)
        ):
            if "redemption_history_volatile" not in flags:
                flags.append("redemption_history_volatile")

        return E4Verdict(
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            risk_level=risk_level,
            confidence=confidence,
            drivers=llm_core.drivers,
            flags=flags,
            reasoning_trace=llm_core.reasoning_trace,
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input_for_hash),
            input_hash=payload_hash(signals_input_for_hash),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
            historical_window_evaluated_days=history.historical_window_days if history else 0,
            historical_event_count=history.event_count if history else 0,
        )

    def _no_history_verdict(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> E4Verdict:
        """§11.5.7 — new client returns LOW risk with `no_history` flag, confidence 0."""
        history: BehaviouralHistorySummary | None = kwargs.get("history")
        signals_input = self._collect_input_for_hash(envelope, **kwargs)
        return E4Verdict(
            case_id=envelope.case.case_id,
            timestamp=self._now(),
            run_mode=envelope.run_mode,
            risk_level=RiskLevel.LOW,
            confidence=0.0,
            drivers=[
                Driver(
                    factor="no_historical_record",
                    direction=DriverDirection.NEUTRAL,
                    severity=DriverSeverity.LOW,
                    detail=(
                        "Client has fewer than 5 historical events; "
                        "behavioural inference is unavailable."
                    ),
                )
            ],
            flags=["no_history"],
            reasoning_trace=(
                "New client with insufficient historical record (<5 events). "
                "E4 surfaces no_history flag and confidence 0.0; calibration "
                "will improve as T1 events accumulate."
            ),
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
            historical_window_evaluated_days=history.historical_window_days if history else 0,
            historical_event_count=history.event_count if history else 0,
        )


__all__ = ["E4BehaviouralHistorical", "LIMITED_HISTORY_EVENT_THRESHOLD"]
