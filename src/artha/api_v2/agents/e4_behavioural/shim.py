"""E4 Behavioural shim — cluster 9 chunk 9.3 §9.

Six semantic validation rules enforce grounding against investor case history
and communication data: investor_id identity, panic verdict consistency,
bias evidence grounding, history-based verdict consistency, communication
preferences completeness, and historical reference grounding in
reasoning_summary.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e4_behavioural.schema import (
    BehaviouralVerdict,
    E4BehaviouralOutput,
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

_HISTORICAL_REF_PATTERN = re.compile(
    r"\b(?:case_\w+|20\d{2}[-/]\d{2}[-/]\d{2}|\d+\s*(?:trades?|cases?|messages?))\b",
    re.IGNORECASE,
)

_USER_PROMPT_TEMPLATE = (
    "Please produce a behavioural profile for investor: {investor_name} ({investor_id})\n"
    "\n"
    "Investor profile:\n"
    "{investor_profile_json}\n"
    "\n"
    "Case history:\n"
    "{case_history_json}\n"
    "\n"
    "Communication patterns:\n"
    "{communication_patterns_json}\n"
    "\n"
    "Trading log:\n"
    "{trading_log_json}\n"
    "\n"
    "Mandate:\n"
    "{mandate_json}\n"
    "\n"
    "Case context:\n"
    "{case_context_json}\n"
    "\n"
    "Behavioural manual flag:\n"
    "{behavioural_manual_flag_json}\n"
    "\n"
    "Return verdict as single JSON object matching schema at {output_schema_ref}."
)


def derive_window_id(case_opened_at: datetime) -> str:
    """Derive 30-day window bucket ID from case open timestamp."""
    year = case_opened_at.year
    day_of_year = case_opened_at.timetuple().tm_yday
    bucket_num = ((day_of_year - 1) // 30) + 1
    return f"e4_w_{year}_{bucket_num:02d}"


class E4BehaviouralShim(AgentShim):
    """Cluster-9 E4 Behavioural shim (chunk 9.3 §9)."""

    agent_id = "e4_behavioural"
    skill_md_version = "2.0"
    output_model = E4BehaviouralOutput

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        investor_id = agent_inputs.payload.get("investor_id", "")
        if not investor_id:
            return None

        window_id = agent_inputs.payload.get("window_id")
        if not window_id:
            case_opened_at_raw = agent_inputs.payload.get("case_opened_at")
            if case_opened_at_raw:
                try:
                    case_opened_at = datetime.fromisoformat(str(case_opened_at_raw))
                    window_id = derive_window_id(case_opened_at)
                except (ValueError, TypeError):
                    window_id = "no_window_seeded"
            else:
                window_id = "no_window_seeded"

        behavioural_manual_flag_id = (
            agent_inputs.payload.get("behavioural_manual_flag_id") or "null"
        )
        return f"e4:{investor_id}:{window_id}:{behavioural_manual_flag_id}"

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        if not agent_inputs.payload.get("investor_id"):
            return ValidationResult(
                success=False,
                error_type="missing_field",
                error_path=("investor_id",),
                error_message="E4 Behavioural requires non-empty 'investor_id' input",
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
            "investor_id": p.get("investor_id", ""),
            "investor_name": p.get("investor_name", ""),
            "investor_profile_json": json.dumps(
                p.get("investor_profile") or {},
                ensure_ascii=False,
            ),
            "case_history_json": json.dumps(
                p.get("case_history") or [],
                ensure_ascii=False,
            ),
            "communication_patterns_json": json.dumps(
                p.get("communication_patterns") or {},
                ensure_ascii=False,
            ),
            "trading_log_json": json.dumps(
                p.get("trading_log") or [],
                ensure_ascii=False,
            ),
            "mandate_json": json.dumps(
                p.get("mandate") or {},
                ensure_ascii=False,
            ),
            "case_context_json": json.dumps(
                p.get("case_context") or {},
                ensure_ascii=False,
            ),
            "behavioural_manual_flag_json": json.dumps(
                p.get("behavioural_manual_flag") or {},
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
            raise ValueError(f"E4 Behavioural parse: {parse_err}")
        try:
            verdict = E4BehaviouralOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E4 Behavioural schema_violation: {exc.errors()[:3]}",
            ) from exc

        investor_id = agent_inputs.payload.get("investor_id")
        if investor_id and verdict.investor_id != investor_id:
            raise ValueError(
                f"E4 Behavioural investor_id mismatch: "
                f"requested {investor_id!r}, got {verdict.investor_id!r}",
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
        """Apply the 6 semantic validation rules from chunk 9.3 §9."""
        out = E4BehaviouralOutput.model_validate(verdict.structured)

        # Rule 1: investor_id matches request.
        investor_id = agent_inputs.payload.get("investor_id", "")
        if investor_id and out.investor_id != investor_id:
            return ValidationResult(
                success=False,
                error_type="rule_1_investor_id_mismatch",
                error_path=("investor_id",),
                error_message=f"investor_id mismatch: {investor_id!r} vs {out.investor_id!r}",
            )

        # Rule 2: panic_indicators consistency with behavioural_verdict.
        bv = out.behavioural_verdict
        panic_verdicts = {BehaviouralVerdict.REACTIVE, BehaviouralVerdict.PANIC_PRONE}
        if bv in panic_verdicts and not out.panic_indicators:
            return ValidationResult(
                success=False,
                error_type="rule_2_panic_indicators_required_for_verdict",
                error_path=("panic_indicators",),
                error_message=(
                    f"behavioural_verdict={bv.value} requires at least one panic_indicator, "
                    f"but panic_indicators is empty"
                ),
            )
        if bv == BehaviouralVerdict.UNTESTED and out.panic_indicators:
            return ValidationResult(
                success=False,
                error_type="rule_2_panic_indicators_present_for_untested",
                error_path=("panic_indicators",),
                error_message=(
                    f"behavioural_verdict=untested should have no panic_indicators, "
                    f"but {len(out.panic_indicators)} found"
                ),
            )

        # Rule 3: each bias_signal.evidence must be >= 20 chars (specific grounding).
        for idx, bs in enumerate(out.bias_signals):
            if len(bs.evidence) < 20:
                return ValidationResult(
                    success=False,
                    error_type="rule_3_bias_evidence_not_grounded",
                    error_path=("bias_signals", str(idx), "evidence"),
                    error_message=(
                        f"bias_signals[{idx}].evidence has {len(bs.evidence)} chars; "
                        f"requires >= 20 for specific grounding"
                    ),
                )

        # Rule 4: verdict consistency with case_history panic proxies.
        case_history = agent_inputs.payload.get("case_history") or []
        panic_proxy_decisions = {"accepted_with_modification", "rejected"}
        panic_proxies = sum(
            1
            for entry in case_history
            if isinstance(entry, dict)
            and entry.get("investor_decision") in panic_proxy_decisions
        )
        if panic_proxies >= 2 and bv == BehaviouralVerdict.DISCIPLINED:
            return ValidationResult(
                success=False,
                error_type="rule_4_verdict_inconsistent_with_history",
                error_path=("behavioural_verdict",),
                error_message=(
                    f"behavioural_verdict=disciplined but case_history has "
                    f"{panic_proxies} panic-proxy decisions (accepted_with_modification "
                    f"or rejected)"
                ),
            )
        if (
            len(case_history) >= 5
            and panic_proxies == 0
            and bv == BehaviouralVerdict.PANIC_PRONE
        ):
            return ValidationResult(
                success=False,
                error_type="rule_4_verdict_inconsistent_with_history",
                error_path=("behavioural_verdict",),
                error_message=(
                    f"behavioural_verdict=panic_prone but case_history has "
                    f"{len(case_history)} entries and zero panic-proxy decisions"
                ),
            )

        # Rule 5: communication_preferences must be populated (guard for None).
        if out.communication_preferences is None:
            return ValidationResult(
                success=False,
                error_type="rule_5_communication_preferences_missing",
                error_path=("communication_preferences",),
                error_message="communication_preferences is None; must be a populated object",
            )
        if out.communication_preferences.preferred_channel is None:
            return ValidationResult(
                success=False,
                error_type="rule_5_communication_preferences_missing",
                error_path=("communication_preferences", "preferred_channel"),
                error_message="communication_preferences.preferred_channel is not set",
            )

        # Rule 6: reasoning_summary has >=2 specific historical references.
        historical_refs = _HISTORICAL_REF_PATTERN.findall(out.reasoning_summary)
        if len(historical_refs) < 2:
            return ValidationResult(
                success=False,
                error_type="rule_6_insufficient_historical_grounding",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary requires >=2 historical reference tokens "
                    f"(case_ids, dates, or trade/case counts); "
                    f"found {len(historical_refs)}"
                ),
            )

        return ValidationResult(success=True)

    @staticmethod
    def _to_stage_payload(verdict: E4BehaviouralOutput) -> dict[str, Any]:
        return {
            "agent_id": "e4_behavioural",
            "investor_id": verdict.investor_id,
            "behavioural_verdict": verdict.behavioural_verdict.value,
            "confidence": verdict.confidence,
            "structured_output": verdict.model_dump(mode="json"),
            "reasoning_summary": verdict.reasoning_summary,
        }


__all__ = ["E4BehaviouralShim", "derive_window_id"]
