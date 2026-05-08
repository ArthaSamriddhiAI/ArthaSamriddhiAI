"""E1 shim — cluster 7 chunk 7.1 §6 + §8.

Implements :class:`AgentShim` for E1 listed-fundamental-equity. Five
semantic validation rules (chunk 7.1 §8) catch outputs that pass
schema but are internally inconsistent — verdict + risk-signal
mismatches, under-justified high-confidence verdicts, missing metric
families, etc.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e1.schema import (
    E1FrameworkAxis,
    E1Output,
    E1Verdict,
)
from artha.api_v2.agents.llm_client import LLMResponse
from artha.api_v2.agents.prompt_loader import (
    PromptPayload,
    PromptTemplate,
    render_user_prompt,
)
from artha.api_v2.agents.shim import (
    AgentInputs,
    AgentShim,
    ParsedVerdict,
    ValidationResult,
    parse_json_object,
)

#: Verdict values that require an explicit per-stock framework axis
#: (chunk 7.1 §8.4).
_POSITIVE_VERDICTS: frozenset[str] = frozenset(
    {
        E1Verdict.POSITIVE.value,
        E1Verdict.POSITIVE_WITH_VALUATION_CAUTION.value,
    },
)

#: Risk signals whose presence is incompatible with a
#: ``positive`` verdict (chunk 7.1 §8.1). Substring match is
#: sufficient — the cluster-6 enriched skill.md doesn't pin an enum.
_HIGH_SEVERITY_SIGNALS: tuple[str, ...] = (
    "promoter pledge",
    "audit qualification",
    "regulatory action pending",
    "regulatory action",
    "fraud allegation",
    "going concern",
    "litigation material",
)


class E1Shim(AgentShim):
    """Cluster-7 real E1 shim."""

    agent_id = "e1_listed_fundamental_equity"
    skill_md_version = "1.1"
    output_model = E1Output

    # Per-call user prompt template — the system prompt comes from the
    # skill.md body. Cluster 7.1 §6.1 specifies this layout.
    _USER_PROMPT_TEMPLATE = (
        "Please perform per-stock fundamental analysis for the following:\n"
        "\n"
        "Ticker: {ticker}\n"
        "Snapshot context (relevant excerpt):\n"
        "{snapshot_excerpt}\n"
        "\n"
        "Investor mandate context:\n"
        "{mandate_excerpt}\n"
        "\n"
        "Macro context (from E3 if dispatched in this case):\n"
        "{macro_context}\n"
        "\n"
        "Return your verdict as a single JSON object matching the schema "
        "referenced at {output_schema_ref}. Do not return any text outside "
        "the JSON object."
    )

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        ticker = agent_inputs.payload.get("ticker")
        if not ticker or not isinstance(ticker, str):
            return ValidationResult(
                success=False,
                error_type="missing_field",
                error_path=("ticker",),
                error_message="E1 requires a non-empty 'ticker' input",
            )
        return ValidationResult(success=True)

    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        placeholders = {
            "ticker": agent_inputs.payload["ticker"],
            "snapshot_excerpt": agent_inputs.payload.get(
                "snapshot_excerpt",
                "No snapshot excerpt available.",
            ),
            "mandate_excerpt": agent_inputs.payload.get(
                "mandate_excerpt",
                "No mandate context available.",
            ),
            "macro_context": agent_inputs.payload.get(
                "macro_context",
                "Not dispatched in this case",
            ),
            "output_schema_ref": skill_md_template.output_schema_ref,
        }
        user = render_user_prompt(self._USER_PROMPT_TEMPLATE, placeholders=placeholders)
        return PromptPayload(
            system=skill_md_template.system_body,
            user=user,
            llm_model=skill_md_template.llm_model,
            max_tokens=skill_md_template.max_tokens,
            temperature=skill_md_template.temperature,
        )

    def parse_output(
        self,
        llm_response: LLMResponse,
        agent_inputs: AgentInputs,
    ) -> ParsedVerdict:
        """Parse the LLM response text into an :class:`E1Output`.

        Schema validation happens here via Pydantic; semantic
        validation (cross-field) is :meth:`validate_output`.
        """
        payload, parse_err = parse_json_object(llm_response.text)
        if parse_err is not None:
            raise ValueError(f"E1 parse: {parse_err}")
        try:
            verdict = E1Output.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E1 schema_violation: {exc.errors()[:3]}",
            ) from exc

        ticker = agent_inputs.payload.get("ticker")
        if ticker and verdict.ticker != ticker:
            raise ValueError(
                f"E1 ticker mismatch: requested {ticker!r}, got "
                f"{verdict.ticker!r}",
            )

        structured = verdict.model_dump(mode="json")
        stage_payload = self._to_stage_payload(verdict)
        return ParsedVerdict(
            agent_id=self.agent_id,
            structured=structured,
            stage_payload=stage_payload,
            raw_text=llm_response.text,
        )

    def validate_output(
        self,
        verdict: ParsedVerdict,
        agent_inputs: AgentInputs,
    ) -> ValidationResult:
        """Apply the 5 semantic validation rules from chunk 7.1 §8."""
        out = E1Output.model_validate(verdict.structured)

        # Rule 1: verdict consistency with risk_signals (§8.1).
        if out.verdict == E1Verdict.POSITIVE:
            for signal in out.risk_signals:
                low = signal.lower()
                for high_sev in _HIGH_SEVERITY_SIGNALS:
                    if high_sev in low:
                        return ValidationResult(
                            success=False,
                            error_type="rule_1_verdict_risk_mismatch",
                            error_path=("verdict",),
                            error_message=(
                                f"verdict=positive incompatible with "
                                f"high-severity risk_signal "
                                f"{signal!r}"
                            ),
                        )

        # Rule 2: confidence calibration (§8.2). Word-count proxy.
        if out.confidence >= 0.85:
            words = len(out.reasoning_summary.split())
            if words < 300:
                return ValidationResult(
                    success=False,
                    error_type="rule_2_confidence_underjustified",
                    error_path=("confidence", "reasoning_summary"),
                    error_message=(
                        f"confidence={out.confidence:.2f} requires "
                        f">=300 word reasoning_summary; got {words}"
                    ),
                )

        # Rule 3: required metric coverage (§8.3) — Pydantic enforces
        # already. Re-verify defensively in case schema loosens later.
        required = {"roce", "leverage", "earnings_quality", "valuation", "growth", "margins"}
        actual = set(out.metric_evaluations.model_dump(mode="json").keys())
        missing = required - actual
        if missing:
            return ValidationResult(
                success=False,
                error_type="rule_3_missing_metric_family",
                error_path=("metric_evaluations",),
                error_message=f"missing metric families: {sorted(missing)}",
            )

        # Rule 4: per-stock framework axis presence on positive verdicts
        # (§8.4).
        if out.verdict.value in _POSITIVE_VERDICTS:
            if not out.per_stock_framework.axis_value.strip():
                return ValidationResult(
                    success=False,
                    error_type="rule_4_missing_framework_axis_value",
                    error_path=("per_stock_framework", "axis_value"),
                    error_message=(
                        f"verdict={out.verdict.value} requires non-empty "
                        f"per_stock_framework.axis_value"
                    ),
                )

        # Rule 5: reasoning_summary mentions the ticker (§8.5).
        # Warning, not failure — captured in error_message but
        # success=True so the dispatcher doesn't retry. Cluster 7
        # spec calls this "flag for review".
        ticker = agent_inputs.payload.get("ticker", "")
        if ticker and ticker.lower() not in out.reasoning_summary.lower():
            return ValidationResult(
                success=True,  # warning, not failure
                error_type="rule_5_ticker_not_in_reasoning_warn",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary does not reference ticker {ticker!r} "
                    f"(generic-analysis warning; not retried)"
                ),
            )

        return ValidationResult(success=True)

    # ------------------------------------------------------------------
    # Cache key (chunk 7.2 wires the actual lookup)
    # ------------------------------------------------------------------

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        ticker = agent_inputs.payload.get("ticker")
        if not ticker:
            return None
        # Cluster 7.2 will substitute real earnings_id + manual_flag_id;
        # stage 1 leaves them as sentinels so the format is stable.
        earnings_id = agent_inputs.payload.get(
            "latest_earnings_id", "no_earnings_seeded",
        )
        manual_flag_id = agent_inputs.payload.get("manual_flag_id", "null")
        return f"e1:{ticker}:{earnings_id}:{manual_flag_id}"

    # ------------------------------------------------------------------
    # Stage payload mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _to_stage_payload(verdict: E1Output) -> dict[str, Any]:
        """Map :class:`E1Output` → the EvidenceVerdict stage row payload.

        The pipeline writes this dict via
        :func:`repository.insert_evidence_verdict`. Field names mirror
        the cluster-5 stage table; the rich E1 verdict travels in
        ``structured_output``.
        """
        risk_level = _map_verdict_to_risk_level(verdict.verdict)
        drivers = {
            "key_drivers": [
                {"driver": d.driver, "weight": d.weight.value}
                for d in verdict.key_drivers
            ],
        }
        flags: dict[str, Any] = {}
        if verdict.risk_signals:
            flags["risk_signals"] = verdict.risk_signals
        return {
            "agent_id": "e1_listed_fundamental_equity",
            "risk_level": risk_level,
            "confidence": verdict.confidence,
            "drivers": drivers,
            "flags": flags,
            "structured_output": verdict.model_dump(mode="json"),
            "reasoning_summary": verdict.reasoning_summary,
        }


def _map_verdict_to_risk_level(verdict: E1Verdict) -> str:
    """Coarse risk_level mapping for the EvidenceVerdict stage row."""
    if verdict in {E1Verdict.POSITIVE}:
        return "low"
    if verdict in {E1Verdict.POSITIVE_WITH_VALUATION_CAUTION}:
        return "medium"
    if verdict in {E1Verdict.HOLD_WITH_ATTENTION, E1Verdict.SPECIAL_SITUATION}:
        return "medium"
    if verdict in {E1Verdict.NEGATIVE}:
        return "high"
    return "medium"


_ = E1FrameworkAxis  # re-export through schema module


__all__ = ["E1Shim"]
