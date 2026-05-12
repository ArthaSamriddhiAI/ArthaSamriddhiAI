"""E5.FundView shim — cluster 9 chunk 9.2 §2.5 + §2.6.

Six semantic validation rules enforce grounding against AIF disclosure data:
manager identity, IRR grounding, corpus grounding, verdict/signals consistency,
and quantitative grounding in reasoning_summary.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e5_fund_view.schema import (
    E5FundViewOutput,
    FundViewVerdict,
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

_QUANT_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?(?:\s*(?:%|pct|cr|bn|inr))?\b", re.IGNORECASE
)

# 5% relative tolerance for corpus grounding checks (rule 4).
_CORPUS_TOLERANCE_RELATIVE = 0.05

# IRR tolerance in percentage points (rule 3).
_IRR_TOLERANCE_PCT = 2.0

_USER_PROMPT_TEMPLATE = (
    "Please produce an AIF fund view analysis for: {fund_name} ({aif_id})\n"
    "\n"
    "AIF classification:\n"
    "{aif_classification_json}\n"
    "\n"
    "Recent disclosures:\n"
    "{recent_disclosures_json}\n"
    "\n"
    "E3.MacroView output:\n"
    "{e3_macro_view_output_json}\n"
    "\n"
    "Return verdict as single JSON object matching schema at {output_schema_ref}."
)


class E5FundViewShim(AgentShim):
    """Cluster-9 E5.FundView shim (chunk 9.2 §2.5)."""

    agent_id = "e5_fund_view"
    skill_md_version = "2.0"
    output_model = E5FundViewOutput

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        aif_id = agent_inputs.payload.get("aif_id", "")
        if not aif_id:
            return None
        latest_aif_disclosure_id = agent_inputs.payload.get(
            "latest_aif_disclosure_id", "no_disclosure_seeded"
        )
        fund_manual_flag_id = agent_inputs.payload.get("fund_manual_flag_id") or "null"
        return f"e5fv:{aif_id}:{latest_aif_disclosure_id}:{fund_manual_flag_id}"

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        for field in ("aif_id", "aif_category"):
            if not agent_inputs.payload.get(field):
                return ValidationResult(
                    success=False,
                    error_type="missing_field",
                    error_path=(field,),
                    error_message=f"E5.FundView requires non-empty '{field}' input",
                )
        return ValidationResult(success=True)

    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        import json

        p = agent_inputs.payload
        placeholders = {
            "aif_id": p.get("aif_id", ""),
            "fund_name": p.get("fund_name", ""),
            "aif_classification_json": json.dumps(
                {
                    "aif_id": p.get("aif_id"),
                    "aif_category": p.get("aif_category"),
                    "vintage_year": p.get("vintage_year"),
                    "target_corpus_inr_cr": p.get("target_corpus_inr_cr"),
                    "drawn_corpus_inr_cr": p.get("drawn_corpus_inr_cr"),
                },
                ensure_ascii=False,
            ),
            "recent_disclosures_json": json.dumps(
                p.get("recent_disclosures") or [],
                ensure_ascii=False,
            ),
            "e3_macro_view_output_json": json.dumps(
                p.get("e3_macro_view_output") or {},
                ensure_ascii=False,
            ),
            "output_schema_ref": skill_md_template.output_schema_ref,
        }
        user = render_user_prompt(_USER_PROMPT_TEMPLATE, placeholders=placeholders)
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
            raise ValueError(f"E5.FundView parse: {parse_err}")
        try:
            verdict = E5FundViewOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E5.FundView schema_violation: {exc.errors()[:3]}",
            ) from exc

        aif_id = agent_inputs.payload.get("aif_id")
        if aif_id and verdict.aif_id != aif_id:
            raise ValueError(
                f"E5.FundView aif_id mismatch: requested {aif_id!r}, got {verdict.aif_id!r}",
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
        """Apply the 6 semantic validation rules from chunk 9.2 §2.6."""
        out = E5FundViewOutput.model_validate(verdict.structured)

        # Rule 1: aif_id matches request.
        aif_id = agent_inputs.payload.get("aif_id", "")
        if aif_id and out.aif_id != aif_id:
            return ValidationResult(
                success=False,
                error_type="rule_1_aif_id_mismatch",
                error_path=("aif_id",),
                error_message=f"aif_id mismatch: {aif_id!r} vs {out.aif_id!r}",
            )

        # Rule 2: manager_name grounded in input current_manager_name.
        input_manager = agent_inputs.payload.get("current_manager_name", "")
        if input_manager:
            output_manager = out.manager_quality_assessment.manager_name
            in_lower = input_manager.lower()
            out_lower = output_manager.lower()
            if in_lower not in out_lower and out_lower not in in_lower:
                return ValidationResult(
                    success=False,
                    error_type="rule_2_manager_name_mismatch",
                    error_path=("manager_quality_assessment", "manager_name"),
                    error_message=(
                        f"manager_name in output {output_manager!r} does not match "
                        f"input {input_manager!r}"
                    ),
                )

        # Rule 3: irr_since_inception_pct within ±2.0 ppt of input value.
        irr_input = agent_inputs.payload.get("irr_since_inception_pct")
        if irr_input is not None:
            try:
                irr_input_val = float(irr_input)
                irr_output = out.track_record_assessment.irr_since_inception_pct
                if abs(irr_output - irr_input_val) > _IRR_TOLERANCE_PCT:
                    return ValidationResult(
                        success=False,
                        error_type="rule_3_irr_not_grounded",
                        error_path=("track_record_assessment", "irr_since_inception_pct"),
                        error_message=(
                            f"irr_since_inception_pct output={irr_output} differs from "
                            f"input={irr_input_val} by more than {_IRR_TOLERANCE_PCT} ppt"
                        ),
                    )
            except (TypeError, ValueError):
                pass

        # Rule 4: corpus figures grounded in input within 5% relative tolerance.
        target_input = agent_inputs.payload.get("target_corpus_inr_cr")
        if target_input is not None:
            try:
                target_input_val = float(target_input)
                target_output = out.capacity_assessment.target_corpus_inr_cr
                if target_input_val > 0:
                    rel_diff = abs(target_output - target_input_val) / target_input_val
                    if rel_diff > _CORPUS_TOLERANCE_RELATIVE:
                        return ValidationResult(
                            success=False,
                            error_type="rule_4_corpus_not_grounded",
                            error_path=("capacity_assessment", "target_corpus_inr_cr"),
                            error_message=(
                                f"target_corpus_inr_cr output={target_output} differs from "
                                f"input={target_input_val} by more than "
                                f"{_CORPUS_TOLERANCE_RELATIVE * 100:.0f}%"
                            ),
                        )
            except (TypeError, ValueError):
                pass

        drawn_input = agent_inputs.payload.get("drawn_corpus_inr_cr")
        if drawn_input is not None:
            try:
                drawn_input_val = float(drawn_input)
                drawn_output = out.capacity_assessment.drawn_corpus_inr_cr
                if drawn_input_val > 0:
                    rel_diff = abs(drawn_output - drawn_input_val) / drawn_input_val
                    if rel_diff > _CORPUS_TOLERANCE_RELATIVE:
                        return ValidationResult(
                            success=False,
                            error_type="rule_4_corpus_not_grounded",
                            error_path=("capacity_assessment", "drawn_corpus_inr_cr"),
                            error_message=(
                                f"drawn_corpus_inr_cr output={drawn_output} differs from "
                                f"input={drawn_input_val} by more than "
                                f"{_CORPUS_TOLERANCE_RELATIVE * 100:.0f}%"
                            ),
                        )
            except (TypeError, ValueError):
                pass

        # Rule 5: fund_view_verdict consistent with key_signals direction distribution.
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
            v = out.fund_view_verdict.value
            if v == FundViewVerdict.POSITIVE.value and pos < 0.6 * total:
                return ValidationResult(
                    success=False,
                    error_type="rule_5_verdict_signals_inconsistency",
                    error_path=("fund_view_verdict",),
                    error_message=(
                        f"fund_view_verdict=positive but only {pos}/{total} "
                        f"key_signals are positive (need >=60%)"
                    ),
                )
            if v == FundViewVerdict.AVOID.value and neg <= pos:
                return ValidationResult(
                    success=False,
                    error_type="rule_5_verdict_signals_inconsistency",
                    error_path=("fund_view_verdict",),
                    error_message=(
                        f"fund_view_verdict=avoid but positive signals ({pos}) "
                        f">= negative signals ({neg})"
                    ),
                )

        # Rule 6: reasoning_summary has >=3 quantitative tokens.
        quant_tokens = _QUANT_PATTERN.findall(out.reasoning_summary)
        if len(quant_tokens) < 3:
            return ValidationResult(
                success=False,
                error_type="rule_6_insufficient_quantitative_grounding",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary requires >=3 quantitative tokens; "
                    f"found {len(quant_tokens)}"
                ),
            )

        return ValidationResult(success=True)

    @staticmethod
    def _to_stage_payload(verdict: E5FundViewOutput) -> dict[str, Any]:
        return {
            "agent_id": "e5_fund_view",
            "aif_id": verdict.aif_id,
            "fund_view_verdict": verdict.fund_view_verdict.value,
            "confidence": verdict.confidence,
            "structured_output": verdict.model_dump(mode="json"),
            "reasoning_summary": verdict.reasoning_summary,
        }


__all__ = ["E5FundViewShim"]
