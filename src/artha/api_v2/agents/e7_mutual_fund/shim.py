"""E7 Mutual Fund shim — cluster 8 chunk 8.3 §9 + §10.

Implements :class:`AgentShim` for E7 (Mutual Fund analysis).  Seven
semantic validation rules (chunk 8.3 §9) enforce grounding against
actual disclosure data: manager identity, alpha, TER, capacity signal
consistency, verdict/key_signals majority, quantitative grounding.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e7_mutual_fund.schema import (
    CapacitySignal,
    E7MutualFundOutput,
    FundVerdict,
    SignalDirection,
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

_QUANT_PATTERN = re.compile(r"\b\d+(?:\.\d+)?(?:\s*(?:%|bps|pct|cr|bn))?\b", re.IGNORECASE)

# Category-aware capacity thresholds (chunk 8.3 §9.5).
# Each entry: (ample_threshold_cr, approaching_threshold_cr).
_CAPACITY_THRESHOLDS: dict[str, tuple[float, float]] = {
    "largecap_equity": (50_000, 80_000),
    "midcap_equity": (15_000, 25_000),
    "smallcap_equity": (5_000, 10_000),
    "debt_short_term": (30_000, 50_000),
    "balanced_advantage": (50_000, 100_000),
}

# Plausibility range for alpha (rule 3).
_ALPHA_MIN_BPS = -1000
_ALPHA_MAX_BPS = 1500

# Alpha tolerance for grounding check (rule 3).
_ALPHA_TOLERANCE_BPS = 20

# TER tolerance for grounding check (rule 4).
_TER_TOLERANCE_PCT = 0.05


class E7MutualFundShim(AgentShim):
    """Cluster-8 real E7 Mutual Fund shim."""

    agent_id = "e7_mutual_fund"
    skill_md_version = "2.0"
    output_model = E7MutualFundOutput

    _USER_PROMPT_TEMPLATE = (
        "Please produce mutual fund analysis for: {fund_name} ({fund_id})\n"
        "\n"
        "Fund classification:\n"
        "{fund_classification_json}\n"
        "\n"
        "E3.MacroView output:\n"
        "{e3_macro_view_output_json}\n"
        "\n"
        "Return verdict as single JSON object matching schema at {output_schema_ref}."
    )

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        for field in ("fund_id", "fund_name", "fund_category"):
            if not agent_inputs.payload.get(field):
                return ValidationResult(
                    success=False,
                    error_type="missing_field",
                    error_path=(field,),
                    error_message=f"E7 requires non-empty '{field}' input",
                )
        return ValidationResult(success=True)

    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        import json

        placeholders = {
            "fund_name": agent_inputs.payload.get("fund_name", ""),
            "fund_id": agent_inputs.payload.get("fund_id", ""),
            "fund_classification_json": json.dumps(
                {
                    "fund_id": agent_inputs.payload.get("fund_id"),
                    "fund_category": agent_inputs.payload.get("fund_category"),
                    "current_manager_name": agent_inputs.payload.get("current_manager_name"),
                    "ter_pct_current": agent_inputs.payload.get("ter_pct_current"),
                    "alpha_5y_bps": agent_inputs.payload.get("alpha_5y_bps_input"),
                    "current_aum_inr_cr": agent_inputs.payload.get("current_aum_inr_cr"),
                },
                ensure_ascii=False,
            ),
            "e3_macro_view_output_json": json.dumps(
                agent_inputs.payload.get("e3_macro_view_output") or {},
                ensure_ascii=False,
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
        payload, parse_err = parse_json_object(llm_response.text)
        if parse_err is not None:
            raise ValueError(f"E7 parse: {parse_err}")
        try:
            verdict = E7MutualFundOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E7 schema_violation: {exc.errors()[:3]}",
            ) from exc

        fund_id = agent_inputs.payload.get("fund_id")
        if fund_id and verdict.fund_id != fund_id:
            raise ValueError(
                f"E7 fund_id mismatch: requested {fund_id!r}, got {verdict.fund_id!r}",
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
        """Apply the 7 semantic validation rules from chunk 8.3 §9."""
        out = E7MutualFundOutput.model_validate(verdict.structured)

        # Rule 1: fund_id matches request.
        fund_id = agent_inputs.payload.get("fund_id", "")
        if fund_id and out.fund_id != fund_id:
            return ValidationResult(
                success=False,
                error_type="rule_1_fund_id_mismatch",
                error_path=("fund_id",),
                error_message=f"fund_id mismatch: {fund_id!r} vs {out.fund_id!r}",
            )

        # Rule 2: manager identity grounded in input disclosure.
        input_manager = agent_inputs.payload.get("current_manager_name", "")
        if input_manager:
            output_manager = out.manager_continuity_assessment.manager_name
            in_lower = input_manager.lower()
            out_lower = output_manager.lower()
            if in_lower not in out_lower and out_lower not in in_lower:
                return ValidationResult(
                    success=False,
                    error_type="rule_2_manager_name_mismatch",
                    error_path=("manager_continuity_assessment", "manager_name"),
                    error_message=(
                        f"manager_name in output {output_manager!r} does not match "
                        f"input {input_manager!r}"
                    ),
                )

        # Rule 3: alpha_5y_bps grounded in input + within plausibility.
        alpha_output = out.alpha_assessment.alpha_5y_bps
        if not (_ALPHA_MIN_BPS <= alpha_output <= _ALPHA_MAX_BPS):
            return ValidationResult(
                success=False,
                error_type="rule_3_alpha_outside_plausibility",
                error_path=("alpha_assessment", "alpha_5y_bps"),
                error_message=(
                    f"alpha_5y_bps={alpha_output} is outside plausibility range "
                    f"[{_ALPHA_MIN_BPS}, {_ALPHA_MAX_BPS}]"
                ),
            )
        alpha_input = agent_inputs.payload.get("alpha_5y_bps_input")
        if alpha_input is not None:
            try:
                alpha_input_val = float(alpha_input)
                if abs(alpha_output - alpha_input_val) > _ALPHA_TOLERANCE_BPS:
                    return ValidationResult(
                        success=False,
                        error_type="rule_3_alpha_not_grounded",
                        error_path=("alpha_assessment", "alpha_5y_bps"),
                        error_message=(
                            f"alpha_5y_bps output={alpha_output} differs from "
                            f"input={alpha_input_val:.0f} by more than "
                            f"{_ALPHA_TOLERANCE_BPS} bps"
                        ),
                    )
            except (TypeError, ValueError):
                pass

        # Rule 4: ter_pct matches input within tolerance.
        ter_input = agent_inputs.payload.get("ter_pct_current")
        if ter_input is not None:
            try:
                ter_input_val = float(ter_input)
                ter_output = out.fee_structure_assessment.ter_pct
                if abs(ter_output - ter_input_val) > _TER_TOLERANCE_PCT:
                    return ValidationResult(
                        success=False,
                        error_type="rule_4_ter_not_grounded",
                        error_path=("fee_structure_assessment", "ter_pct"),
                        error_message=(
                            f"ter_pct output={ter_output} differs from "
                            f"input={ter_input_val} by more than {_TER_TOLERANCE_PCT}"
                        ),
                    )
            except (TypeError, ValueError):
                pass

        # Rule 5: capacity_signal consistent with AUM and category.
        category = agent_inputs.payload.get("fund_category", "")
        aum_input = agent_inputs.payload.get("current_aum_inr_cr")
        if aum_input is not None and category in _CAPACITY_THRESHOLDS:
            try:
                aum_val = float(aum_input)
                ample_thresh, approaching_thresh = _CAPACITY_THRESHOLDS[category]
                cap_signal = out.capacity_assessment.capacity_signal.value
                if cap_signal == CapacitySignal.AMPLE.value and aum_val >= approaching_thresh:
                    return ValidationResult(
                        success=False,
                        error_type="rule_5_capacity_signal_inconsistent",
                        error_path=("capacity_assessment", "capacity_signal"),
                        error_message=(
                            f"capacity_signal=ample but AUM={aum_val:.0f} Cr "
                            f"exceeds approaching threshold {approaching_thresh:.0f} Cr "
                            f"for category={category!r}"
                        ),
                    )
            except (TypeError, ValueError):
                pass

        # Rule 6: verdict consistent with key_signals majority (≥60% positive
        # for positive verdict; majority negative for avoid).
        if out.key_signals:
            pos = sum(
                1
                for s in out.key_signals
                if s.direction == SignalDirection.POSITIVE
            )
            neg = sum(
                1
                for s in out.key_signals
                if s.direction == SignalDirection.NEGATIVE
            )
            total = len(out.key_signals)
            v = out.fund_verdict.value
            if v == FundVerdict.POSITIVE.value and pos < 0.6 * total:
                return ValidationResult(
                    success=False,
                    error_type="rule_6_verdict_signals_inconsistency",
                    error_path=("fund_verdict",),
                    error_message=(
                        f"fund_verdict=positive but only {pos}/{total} "
                        f"key_signals are positive (need ≥60%)"
                    ),
                )
            if v == FundVerdict.AVOID.value and neg <= pos:
                return ValidationResult(
                    success=False,
                    error_type="rule_6_verdict_signals_inconsistency",
                    error_path=("fund_verdict",),
                    error_message=(
                        f"fund_verdict=avoid but positive signals ({pos}) "
                        f">= negative signals ({neg})"
                    ),
                )

        # Rule 7: reasoning_summary has ≥3 quantitative tokens.
        quant_tokens = _QUANT_PATTERN.findall(out.reasoning_summary)
        if len(quant_tokens) < 3:
            return ValidationResult(
                success=False,
                error_type="rule_7_insufficient_quantitative_grounding",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary requires ≥3 quantitative tokens; "
                    f"found {len(quant_tokens)}"
                ),
            )

        return ValidationResult(success=True)

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        fund_id = agent_inputs.payload.get("fund_id")
        if not fund_id:
            return None
        disclosure_id = agent_inputs.payload.get(
            "latest_quarterly_disclosure_id", "no_disclosure_seeded",
        )
        fund_manual_flag_id = agent_inputs.payload.get("fund_manual_flag_id") or "null"
        return f"e7:{fund_id}:{disclosure_id}:{fund_manual_flag_id}"

    @staticmethod
    def _to_stage_payload(verdict: E7MutualFundOutput) -> dict[str, Any]:
        return {
            "agent_id": "e7_mutual_fund",
            "fund_id": verdict.fund_id,
            "fund_verdict": verdict.fund_verdict.value,
            "confidence": verdict.confidence,
            "structured_output": verdict.model_dump(mode="json"),
            "reasoning_summary": verdict.reasoning_summary,
        }


__all__ = ["E7MutualFundShim"]
