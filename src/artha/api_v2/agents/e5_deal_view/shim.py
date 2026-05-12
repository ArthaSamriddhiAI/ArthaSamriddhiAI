"""E5.DealView shim — cluster 9 chunk 9.2 §3.5 + §3.6.

Five semantic validation rules enforce grounding against deal and company
data: deal_id identity, stage match, valuation grounding, co-investor
grounding, and quantitative grounding in reasoning_summary.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e5_deal_view.schema import (
    DealStage,
    E5DealViewOutput,
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

# 5% relative tolerance for valuation grounding check (rule 3).
_VALUATION_TOLERANCE_RELATIVE = 0.05

_USER_PROMPT_TEMPLATE = (
    "Please produce a deal view analysis for deal: {deal_id}\n"
    "\n"
    "Deal metadata:\n"
    "{deal_metadata_json}\n"
    "\n"
    "Company metadata:\n"
    "{company_metadata_json}\n"
    "\n"
    "Recent MCA filings:\n"
    "{recent_mca_filings_json}\n"
    "\n"
    "E5.FundView output:\n"
    "{e5_fund_view_output_json}\n"
    "\n"
    "E3.MacroView output:\n"
    "{e3_macro_view_output_json}\n"
    "\n"
    "Return verdict as single JSON object matching schema at {output_schema_ref}."
)


class E5DealViewShim(AgentShim):
    """Cluster-9 E5.DealView shim (chunk 9.2 §3.5)."""

    agent_id = "e5_deal_view"
    skill_md_version = "2.0"
    output_model = E5DealViewOutput

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        deal_id = agent_inputs.payload.get("deal_id", "")
        if not deal_id:
            return None
        fund_or_firm_id = agent_inputs.payload.get("fund_or_firm_id") or "direct"
        latest_mca_filing_id = agent_inputs.payload.get(
            "latest_mca_filing_id", "no_filing_seeded"
        )
        deal_manual_flag_id = agent_inputs.payload.get("deal_manual_flag_id") or "null"
        return f"e5dv:{deal_id}:{fund_or_firm_id}:{latest_mca_filing_id}:{deal_manual_flag_id}"

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        for field in ("deal_id", "cin_or_internal"):
            if not agent_inputs.payload.get(field):
                return ValidationResult(
                    success=False,
                    error_type="missing_field",
                    error_path=(field,),
                    error_message=f"E5.DealView requires non-empty '{field}' input",
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
            "deal_id": p.get("deal_id", ""),
            "deal_metadata_json": json.dumps(
                p.get("deal_metadata") or {},
                ensure_ascii=False,
            ),
            "company_metadata_json": json.dumps(
                p.get("company_metadata") or {},
                ensure_ascii=False,
            ),
            "recent_mca_filings_json": json.dumps(
                p.get("recent_mca_filings") or [],
                ensure_ascii=False,
            ),
            "e5_fund_view_output_json": json.dumps(
                p.get("e5_fund_view_output") or {},
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
            raise ValueError(f"E5.DealView parse: {parse_err}")
        try:
            verdict = E5DealViewOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E5.DealView schema_violation: {exc.errors()[:3]}",
            ) from exc

        deal_id = agent_inputs.payload.get("deal_id")
        if deal_id and verdict.deal_id != deal_id:
            raise ValueError(
                f"E5.DealView deal_id mismatch: requested {deal_id!r}, got {verdict.deal_id!r}",
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
        """Apply the 5 semantic validation rules from chunk 9.2 §3.6."""
        out = E5DealViewOutput.model_validate(verdict.structured)

        # Rule 1: deal_id matches request.
        deal_id = agent_inputs.payload.get("deal_id", "")
        if deal_id and out.deal_id != deal_id:
            return ValidationResult(
                success=False,
                error_type="rule_1_deal_id_mismatch",
                error_path=("deal_id",),
                error_message=f"deal_id mismatch: {deal_id!r} vs {out.deal_id!r}",
            )

        # Rule 2: stage_assessment.current_stage matches company_stage input if provided.
        company_stage = agent_inputs.payload.get("company_stage")
        if company_stage:
            try:
                expected_stage = DealStage(company_stage)
                if out.stage_assessment.current_stage != expected_stage:
                    return ValidationResult(
                        success=False,
                        error_type="rule_2_stage_mismatch",
                        error_path=("stage_assessment", "current_stage"),
                        error_message=(
                            f"current_stage output={out.stage_assessment.current_stage.value!r} "
                            f"does not match input company_stage={company_stage!r}"
                        ),
                    )
            except ValueError:
                pass  # Unrecognised input stage value — skip check

        # Rule 3: post_money_inr_cr within 5% relative of input valuation if provided.
        valuation_input = agent_inputs.payload.get("valuation_post_money_inr_cr")
        if valuation_input is not None:
            try:
                val_input_val = float(valuation_input)
                val_output = out.valuation_assessment.post_money_inr_cr
                if val_input_val > 0:
                    rel_diff = abs(val_output - val_input_val) / val_input_val
                    if rel_diff > _VALUATION_TOLERANCE_RELATIVE:
                        return ValidationResult(
                            success=False,
                            error_type="rule_3_valuation_not_grounded",
                            error_path=("valuation_assessment", "post_money_inr_cr"),
                            error_message=(
                                f"post_money_inr_cr output={val_output} differs from "
                                f"input={val_input_val} by more than "
                                f"{_VALUATION_TOLERANCE_RELATIVE * 100:.0f}%"
                            ),
                        )
            except (TypeError, ValueError):
                pass

        # Rule 4: co_investor_quality.lead_investor grounded in input lead_investor.
        input_lead = agent_inputs.payload.get("lead_investor", "")
        if input_lead:
            output_lead = out.co_investor_quality.lead_investor
            if output_lead:
                in_lower = input_lead.lower()
                out_lower = output_lead.lower()
                if in_lower not in out_lower and out_lower not in in_lower:
                    return ValidationResult(
                        success=False,
                        error_type="rule_4_co_investor_not_grounded",
                        error_path=("co_investor_quality", "lead_investor"),
                        error_message=(
                            f"lead_investor output={output_lead!r} does not match "
                            f"input {input_lead!r}"
                        ),
                    )

        # Rule 5: reasoning_summary has >=3 quantitative tokens.
        quant_tokens = _QUANT_PATTERN.findall(out.reasoning_summary)
        if len(quant_tokens) < 3:
            return ValidationResult(
                success=False,
                error_type="rule_5_insufficient_quantitative_grounding",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary requires >=3 quantitative tokens; "
                    f"found {len(quant_tokens)}"
                ),
            )

        return ValidationResult(success=True)

    @staticmethod
    def _to_stage_payload(verdict: E5DealViewOutput) -> dict[str, Any]:
        return {
            "agent_id": "e5_deal_view",
            "deal_id": verdict.deal_id,
            "deal_view_verdict": verdict.deal_view_verdict.value,
            "confidence": verdict.confidence,
            "structured_output": verdict.model_dump(mode="json"),
            "reasoning_summary": verdict.reasoning_summary,
        }


__all__ = ["E5DealViewShim"]
