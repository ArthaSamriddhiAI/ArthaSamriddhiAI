"""E3.MacroView shim — cluster 8 chunk 8.1 §7 + §8.

Implements :class:`AgentShim` for E3.MacroView.  Six semantic validation
rules (chunk 8.1 §7) catch outputs that pass schema but are internally
inconsistent — regime_name not in characterisation, incomplete forward
expectations, insufficient sector coverage, cycle/regime mismatch,
missing quantitative grounding, missing FX view.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e3_macro_view.schema import (
    CyclePositioning,
    E3MacroViewOutput,
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The 5 required sector codes per chunk 8.1 §7.3.
_REQUIRED_SECTORS: frozenset[str] = frozenset(
    {
        "banking_financial_services",
        "information_technology",
        "fast_moving_consumer_goods",
        "pharma_healthcare",
        "energy",
    }
)

#: Regex that matches any numeric token (integer or decimal, optionally
#: with % or "bps" suffix).  Used for quantitative grounding check.
_QUANT_PATTERN = re.compile(r"\b\d+(?:\.\d+)?(?:\s*(?:%|bps|pct|cr|bn))?\b", re.IGNORECASE)

#: Accommodative → valid cycle_positioning values.
_ACCOMMODATIVE_CYCLES: frozenset[str] = frozenset(
    {CyclePositioning.EARLY_CUTTING, CyclePositioning.ACTIVE_CUTTING}
)
#: Transition → valid cycle_positioning values.
_TRANSITION_CYCLES: frozenset[str] = frozenset(
    {
        CyclePositioning.LATE_CUTTING_EARLY_PAUSE,
        CyclePositioning.LATE_TIGHTENING_EARLY_CUTTING,
    }
)
#: Tightening → valid cycle_positioning values.
_TIGHTENING_CYCLES: frozenset[str] = frozenset(
    {CyclePositioning.EARLY_TIGHTENING, CyclePositioning.ACTIVE_TIGHTENING}
)


class E3MacroViewShim(AgentShim):
    """Cluster-8 real E3.MacroView shim."""

    agent_id = "e3_macro_view"
    skill_md_version = "2.0"
    output_model = E3MacroViewOutput

    _USER_PROMPT_TEMPLATE = (
        "Please produce the current macro view assessment.\n"
        "\n"
        "Active macro regime:\n"
        "{macro_regime_json}\n"
        "\n"
        "Recent material rate policy events (last 6 months):\n"
        "{recent_material_events_json}\n"
        "\n"
        "Return your assessment as a single JSON object matching the schema "
        "referenced at {output_schema_ref}. Do not return any text outside "
        "the JSON object."
    )

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        for field in ("macro_regime_id", "macro_regime_name", "regime_category"):
            if not agent_inputs.payload.get(field):
                return ValidationResult(
                    success=False,
                    error_type="missing_field",
                    error_path=(field,),
                    error_message=f"E3.MacroView requires non-empty '{field}' input",
                )
        return ValidationResult(success=True)

    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        import json

        macro_regime_json = json.dumps(
            {
                "regime_id": agent_inputs.payload.get("macro_regime_id"),
                "regime_name": agent_inputs.payload.get("macro_regime_name"),
                "regime_category": agent_inputs.payload.get("regime_category"),
                "started_at": agent_inputs.payload.get("regime_started_at", ""),
                "rationale_text": agent_inputs.payload.get("regime_rationale", ""),
            },
            ensure_ascii=False,
        )
        events = agent_inputs.payload.get("recent_material_events") or []
        placeholders = {
            "macro_regime_json": macro_regime_json,
            "recent_material_events_json": json.dumps(events, ensure_ascii=False),
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
            raise ValueError(f"E3.MacroView parse: {parse_err}")
        try:
            verdict = E3MacroViewOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E3.MacroView schema_violation: {exc.errors()[:3]}",
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
        """Apply the 6 semantic validation rules from chunk 8.1 §7."""
        out = E3MacroViewOutput.model_validate(verdict.structured)

        # Rule 1: regime_name appears in rate_environment.regime_characterisation.
        regime_name = agent_inputs.payload.get("macro_regime_name", "")
        characterisation_lower = out.rate_environment.regime_characterisation.lower()
        if regime_name and regime_name.lower() not in characterisation_lower:
            return ValidationResult(
                success=False,
                error_type="rule_1_regime_name_missing_from_characterisation",
                error_path=("rate_environment", "regime_characterisation"),
                error_message=(
                    f"regime_name={regime_name!r} not found in "
                    f"rate_environment.regime_characterisation"
                ),
            )

        # Rule 2: forward_expectations has all three horizons non-empty.
        fe = out.forward_expectations
        for horizon_name, horizon_val in (
            ("next_3m", fe.next_3m),
            ("next_6m", fe.next_6m),
            ("next_12m", fe.next_12m),
        ):
            if not horizon_val.strip():
                return ValidationResult(
                    success=False,
                    error_type="rule_2_forward_expectations_incomplete",
                    error_path=("forward_expectations", horizon_name),
                    error_message=f"forward_expectations.{horizon_name} is empty",
                )

        # Rule 3: sector_macro_implications ≥5 entries covering required sectors.
        present_sectors = {s.sector_code for s in out.sector_macro_implications}
        if len(present_sectors) < 5:
            return ValidationResult(
                success=False,
                error_type="rule_3_insufficient_sector_coverage",
                error_path=("sector_macro_implications",),
                error_message=(
                    f"sector_macro_implications must have ≥5 distinct sector_codes; "
                    f"got {len(present_sectors)}"
                ),
            )
        missing_required = _REQUIRED_SECTORS - present_sectors
        if missing_required:
            return ValidationResult(
                success=False,
                error_type="rule_3_missing_required_sectors",
                error_path=("sector_macro_implications",),
                error_message=(
                    f"sector_macro_implications missing required sectors: "
                    f"{sorted(missing_required)}"
                ),
            )

        # Rule 4: cycle_positioning matches regime_category.
        regime_category = agent_inputs.payload.get("regime_category", "")
        cycle = out.cycle_positioning.value
        if regime_category == "accommodative" and cycle not in {
            c.value for c in _ACCOMMODATIVE_CYCLES
        }:
            return ValidationResult(
                success=False,
                error_type="rule_4_cycle_regime_mismatch",
                error_path=("cycle_positioning",),
                error_message=(
                    f"regime_category=accommodative but cycle_positioning={cycle!r}; "
                    f"expected one of {[c.value for c in _ACCOMMODATIVE_CYCLES]}"
                ),
            )
        if regime_category == "tightening" and cycle not in {
            c.value for c in _TIGHTENING_CYCLES
        }:
            return ValidationResult(
                success=False,
                error_type="rule_4_cycle_regime_mismatch",
                error_path=("cycle_positioning",),
                error_message=(
                    f"regime_category=tightening but cycle_positioning={cycle!r}; "
                    f"expected one of {[c.value for c in _TIGHTENING_CYCLES]}"
                ),
            )
        if regime_category == "transition" and cycle not in {
            c.value for c in _TRANSITION_CYCLES
        }:
            return ValidationResult(
                success=False,
                error_type="rule_4_cycle_regime_mismatch",
                error_path=("cycle_positioning",),
                error_message=(
                    f"regime_category=transition but cycle_positioning={cycle!r}; "
                    f"expected one of {[c.value for c in _TRANSITION_CYCLES]}"
                ),
            )

        # Rule 5: reasoning_summary has ≥3 quantitative tokens.
        quant_tokens = _QUANT_PATTERN.findall(out.reasoning_summary)
        if len(quant_tokens) < 3:
            return ValidationResult(
                success=False,
                error_type="rule_5_insufficient_quantitative_grounding",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary requires ≥3 quantitative tokens; "
                    f"found {len(quant_tokens)}"
                ),
            )

        # Rule 6: fx_view.inr_outlook is non-empty (Pydantic already enforces min_length=1).
        if not out.fx_view.inr_outlook.strip():
            return ValidationResult(
                success=False,
                error_type="rule_6_inr_outlook_missing",
                error_path=("fx_view", "inr_outlook"),
                error_message="fx_view.inr_outlook must be non-empty",
            )

        return ValidationResult(success=True)

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        macro_regime_id = agent_inputs.payload.get("macro_regime_id")
        if not macro_regime_id:
            return None
        latest_event_id = agent_inputs.payload.get(
            "latest_material_event_id", "no_material_event_seeded",
        )
        return f"e3mv:{macro_regime_id}:{latest_event_id}"

    # ------------------------------------------------------------------
    # Stage payload
    # ------------------------------------------------------------------

    @staticmethod
    def _to_stage_payload(verdict: E3MacroViewOutput) -> dict[str, Any]:
        return {
            "agent_id": "e3_macro_view",
            "cycle_positioning": verdict.cycle_positioning.value,
            "confidence": verdict.confidence,
            "sector_implications": [
                {
                    "sector_code": s.sector_code,
                    "directional_signal": s.directional_signal.value,
                }
                for s in verdict.sector_macro_implications
            ],
            "structured_output": verdict.model_dump(mode="json"),
            "reasoning_summary": verdict.reasoning_summary,
        }


__all__ = ["E3MacroViewShim"]
