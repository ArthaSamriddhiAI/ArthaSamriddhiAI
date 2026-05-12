"""E2.SectorView shim — cluster 8 chunk 8.2 §3.5 + §3.6.

Implements :class:`AgentShim` for E2.SectorView.  Six semantic
validation rules (chunk 8.2 §3.5) check sector_code match, macro
regime citation, theme specificity, regulatory_environment
consistency, quantitative grounding, and verdict/cycle_stage
consistency.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e2_sector_view.schema import (
    CycleStage,
    E2SectorViewOutput,
    SectorViewVerdict,
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

_QUANT_PATTERN = re.compile(r"\b\d+(?:\.\d+)?(?:\s*(?:%|bps|pct|cr|bn|x))?\b", re.IGNORECASE)

# Verdicts incompatible with certain cycle stages (chunk 8.2 §3.5 rule 6).
_VERDICT_INCOMPATIBLE: dict[str, frozenset[str]] = {
    SectorViewVerdict.CHALLENGING.value: frozenset(
        {CycleStage.RECOVERY.value, CycleStage.EARLY_CYCLE.value}
    ),
    SectorViewVerdict.FAVOURABLE.value: frozenset({CycleStage.CONTRACTION.value}),
}

# Generic theme patterns that rule 3 should reject.
_GENERIC_THEME_PATTERNS = re.compile(
    r"^(growth opportunity|market opportunity|sector growth|"
    r"industry trend|structural trend|positive outlook|"
    r"good fundamentals?)$",
    re.IGNORECASE,
)


class E2SectorViewShim(AgentShim):
    """Cluster-8 real E2.SectorView shim."""

    agent_id = "e2_sector_view"
    skill_md_version = "2.0"
    output_model = E2SectorViewOutput

    _USER_PROMPT_TEMPLATE = (
        "Please produce sector view analysis for: {sector_code}\n"
        "\n"
        "Sector classification:\n"
        "{sector_classification_json}\n"
        "\n"
        "Current macro context (from E3.MacroView):\n"
        "{e3_macro_view_output_json}\n"
        "\n"
        "Return your verdict as a single JSON object matching schema "
        "referenced at {output_schema_ref}."
    )

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        for field in ("sector_code", "macro_regime_id", "macro_regime_name"):
            if not agent_inputs.payload.get(field):
                return ValidationResult(
                    success=False,
                    error_type="missing_field",
                    error_path=(field,),
                    error_message=f"E2.SectorView requires non-empty '{field}' input",
                )
        return ValidationResult(success=True)

    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        import json

        placeholders = {
            "sector_code": agent_inputs.payload.get("sector_code", ""),
            "sector_classification_json": json.dumps(
                {
                    "sector_code": agent_inputs.payload.get("sector_code"),
                    "macro_regime_id": agent_inputs.payload.get("macro_regime_id"),
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
            raise ValueError(f"E2.SectorView parse: {parse_err}")
        try:
            verdict = E2SectorViewOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E2.SectorView schema_violation: {exc.errors()[:3]}",
            ) from exc
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
        """Apply the 6 semantic validation rules from chunk 8.2 §3.5."""
        out = E2SectorViewOutput.model_validate(verdict.structured)

        # Rule 1: sector_code in output matches request.
        requested_sector = agent_inputs.payload.get("sector_code", "")
        if requested_sector and out.sector_code != requested_sector:
            return ValidationResult(
                success=False,
                error_type="rule_1_sector_code_mismatch",
                error_path=("sector_code",),
                error_message=(
                    f"requested sector_code={requested_sector!r}, "
                    f"got {out.sector_code!r}"
                ),
            )

        # Rule 2: macro_regime referenced in reasoning_summary.
        macro_regime_name = agent_inputs.payload.get("macro_regime_name", "")
        if macro_regime_name and macro_regime_name.lower() not in out.reasoning_summary.lower():
            return ValidationResult(
                success=False,
                error_type="rule_2_macro_regime_not_in_reasoning",
                error_path=("reasoning_summary",),
                error_message=(
                    f"macro_regime_name={macro_regime_name!r} not found "
                    f"in reasoning_summary"
                ),
            )

        # Rule 3: dominant_themes contains 2-4 specific items (not generic).
        themes = out.dominant_themes
        if len(themes) < 2 or len(themes) > 4:
            return ValidationResult(
                success=False,
                error_type="rule_3_dominant_themes_count",
                error_path=("dominant_themes",),
                error_message=(
                    f"dominant_themes must have 2-4 items; got {len(themes)}"
                ),
            )
        for theme in themes:
            if _GENERIC_THEME_PATTERNS.match(theme.strip()):
                return ValidationResult(
                    success=False,
                    error_type="rule_3_generic_theme",
                    error_path=("dominant_themes",),
                    error_message=(
                        f"dominant_theme {theme!r} is too generic; "
                        f"use specific theme descriptions"
                    ),
                )

        # Rule 4: regulatory_environment.key_considerations populated when
        # intensity is moderate or intensive.
        intensity = out.regulatory_environment.intensity.value
        considerations = out.regulatory_environment.key_considerations
        if intensity in ("moderate", "intensive") and not considerations:
            return ValidationResult(
                success=False,
                error_type="rule_4_missing_regulatory_considerations",
                error_path=("regulatory_environment", "key_considerations"),
                error_message=(
                    f"regulatory_environment.intensity={intensity!r} requires "
                    f"non-empty key_considerations"
                ),
            )

        # Rule 5: reasoning_summary has ≥2 quantitative tokens.
        quant_tokens = _QUANT_PATTERN.findall(out.reasoning_summary)
        if len(quant_tokens) < 2:
            return ValidationResult(
                success=False,
                error_type="rule_5_insufficient_quantitative_grounding",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary requires ≥2 quantitative tokens; "
                    f"found {len(quant_tokens)}"
                ),
            )

        # Rule 6: sector_view_verdict consistent with cycle_stage.
        verdict_val = out.sector_view_verdict.value
        cycle_val = out.cycle_stage.value
        incompatible = _VERDICT_INCOMPATIBLE.get(verdict_val, frozenset())
        if cycle_val in incompatible:
            return ValidationResult(
                success=False,
                error_type="rule_6_verdict_cycle_stage_inconsistency",
                error_path=("sector_view_verdict",),
                error_message=(
                    f"sector_view_verdict={verdict_val!r} is incompatible "
                    f"with cycle_stage={cycle_val!r}"
                ),
            )

        return ValidationResult(success=True)

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        sector_code = agent_inputs.payload.get("sector_code")
        macro_regime_id = agent_inputs.payload.get("macro_regime_id")
        if not sector_code or not macro_regime_id:
            return None
        sector_manual_flag_id = agent_inputs.payload.get("sector_manual_flag_id") or "null"
        return f"e2sv:{sector_code}:{macro_regime_id}:{sector_manual_flag_id}"

    @staticmethod
    def _to_stage_payload(verdict: E2SectorViewOutput) -> dict[str, Any]:
        return {
            "agent_id": "e2_sector_view",
            "sector_code": verdict.sector_code,
            "sector_view_verdict": verdict.sector_view_verdict.value,
            "cycle_stage": verdict.cycle_stage.value,
            "confidence": verdict.confidence,
            "dominant_themes": verdict.dominant_themes,
            "structured_output": verdict.model_dump(mode="json"),
            "reasoning_summary": verdict.reasoning_summary,
        }


__all__ = ["E2SectorViewShim"]
