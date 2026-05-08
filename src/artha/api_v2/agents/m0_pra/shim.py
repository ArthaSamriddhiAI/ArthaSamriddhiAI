"""M0.PortfolioRiskAnalytics shim — cluster 7 chunk 7.3 §3 + §5.

Real LLM-using shim for portfolio-level risk-rollup interpretation.
Six semantic validation rules (chunk 7.3 §5) enforce the boundary
discipline (interpret-not-recompute) and quantitative grounding.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.llm_client import LLMResponse
from artha.api_v2.agents.m0_pra.schema import (
    M0PRAOutput,
    M0RiskLevel,
    VerdictTag,
)
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

_PA_MODES: frozenset[str] = frozenset({"proposed_action", "scenario"})


class M0PortfolioRiskAnalyticsShim(AgentShim):
    """Cluster-7 real M0.PortfolioRiskAnalytics shim."""

    agent_id = "m0_portfolio_risk_analytics"
    skill_md_version = "1.1"
    output_model = M0PRAOutput

    # Per-call user prompt template per chunk 7.3 §3.1.
    _USER_PROMPT_TEMPLATE = (
        "Please interpret the following portfolio-level metrics into a "
        "structured risk verdict.\n\n"
        "Case context:\n"
        "{case_context_json}\n\n"
        "Active mandate:\n"
        "{mandate_json}\n\n"
        "Pre-action portfolio metrics (from PortfolioAnalytics):\n"
        "{portfolio_analytics_pre_action_json}\n\n"
        "Post-action portfolio metrics (if applicable; for PA and SCENARIO "
        "modes):\n"
        "{portfolio_analytics_post_action_json}\n\n"
        "Available evidence context (informational; from agents that have "
        "produced verdicts in this case lifecycle so far):\n"
        "{evidence_summaries_json}\n\n"
        "Return your verdict as a single JSON object matching the schema "
        "referenced at {output_schema_ref}. Do not return any text outside "
        "the JSON object.\n\n"
        "Specific reminders:\n"
        "- Interpret the deterministic metrics; do not recompute them.\n"
        "- Use mandate values as the binding reference for ceilings and "
        "floors.\n"
        "- For PA and SCENARIO modes, comment on the pre-to-post-action "
        "delta in each per-dimension assessment.\n"
        "- Cascade implications: identify downstream constraints the "
        "action triggers (capital call timing, reserved liquidity).\n"
        "- Risk verdict (low/moderate/high/critical) reflects synthesised "
        "reading across all dimensions, not single-dimension breach."
    )

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        for required in ("portfolio_analytics_pre_action", "mandate"):
            if not agent_inputs.payload.get(required):
                return ValidationResult(
                    success=False,
                    error_type="missing_field",
                    error_path=(required,),
                    error_message=(
                        f"M0.PortfolioRiskAnalytics requires "
                        f"non-empty {required!r} input"
                    ),
                )
        if agent_inputs.case_mode in _PA_MODES:
            if not agent_inputs.payload.get("portfolio_analytics_post_action"):
                return ValidationResult(
                    success=False,
                    error_type="missing_field",
                    error_path=("portfolio_analytics_post_action",),
                    error_message=(
                        f"case_mode={agent_inputs.case_mode!r} requires "
                        f"portfolio_analytics_post_action input"
                    ),
                )
        return ValidationResult(success=True)

    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        is_pa = agent_inputs.case_mode in _PA_MODES
        post_action = (
            json.dumps(agent_inputs.payload.get("portfolio_analytics_post_action") or {})
            if is_pa
            else "Not applicable for this case mode."
        )
        case_context = {
            "case_id": agent_inputs.case_id,
            "case_mode": agent_inputs.case_mode,
            "case_intent": agent_inputs.case_intent,
            "dominant_lens": agent_inputs.payload.get("dominant_lens"),
            "proposed_action_summary": agent_inputs.payload.get(
                "proposed_action_summary",
            ),
        }
        placeholders = {
            "case_context_json": json.dumps(case_context),
            "mandate_json": json.dumps(agent_inputs.payload["mandate"]),
            "portfolio_analytics_pre_action_json": json.dumps(
                agent_inputs.payload["portfolio_analytics_pre_action"],
            ),
            "portfolio_analytics_post_action_json": post_action,
            "evidence_summaries_json": json.dumps(
                agent_inputs.payload.get("evidence_summaries", []),
            ),
            "output_schema_ref": skill_md_template.output_schema_ref,
        }
        user = render_user_prompt(
            self._USER_PROMPT_TEMPLATE, placeholders=placeholders,
        )
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
            raise ValueError(f"M0.PRA parse: {parse_err}")
        try:
            verdict = M0PRAOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"M0.PRA schema_violation: {exc.errors()[:3]}",
            ) from exc

        return ParsedVerdict(
            agent_id=self.agent_id,
            structured=verdict.model_dump(mode="json"),
            stage_payload=self._to_stage_payload(verdict),
            raw_text=llm_response.text,
        )

    def validate_output(
        self,
        verdict: ParsedVerdict,
        agent_inputs: AgentInputs,
    ) -> ValidationResult:
        out = M0PRAOutput.model_validate(verdict.structured)
        mandate = agent_inputs.payload.get("mandate") or {}
        pre = agent_inputs.payload.get("portfolio_analytics_pre_action") or {}

        # Rule 1: mandate-aware verdict consistency (§5.1).
        rule1 = self._check_mandate_breach(out, mandate, pre)
        if rule1 is not None:
            return rule1

        # Rule 2: required dimension coverage non-empty (§5.2).
        for dim_name, dim in out.per_dimension_assessment.model_dump().items():
            if not str(dim.get("reading", "")).strip():
                return ValidationResult(
                    success=False,
                    error_type="rule_2_empty_dimension_reading",
                    error_path=("per_dimension_assessment", dim_name, "reading"),
                    error_message=f"empty reading on dimension {dim_name!r}",
                )

        # Rule 3: PA/SCENARIO requires delta_post_action on every dim (§5.3).
        if agent_inputs.case_mode in _PA_MODES:
            for dim_name, dim in out.per_dimension_assessment.model_dump().items():
                delta = dim.get("delta_post_action")
                if not delta or not str(delta).strip():
                    return ValidationResult(
                        success=False,
                        error_type="rule_3_missing_delta_on_pa",
                        error_path=(
                            "per_dimension_assessment",
                            dim_name,
                            "delta_post_action",
                        ),
                        error_message=(
                            f"case_mode={agent_inputs.case_mode!r} requires "
                            f"non-empty delta_post_action on every dimension; "
                            f"dimension {dim_name!r} missing"
                        ),
                    )

        # Rule 4: reasoning_summary quantitative grounding — at least 3
        # numeric tokens (§5.4).
        numeric_count = len(re.findall(r"\d+(?:\.\d+)?", out.reasoning_summary))
        if numeric_count < 3:
            return ValidationResult(
                success=False,
                error_type="rule_4_under_quantified_reasoning",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary needs >=3 numeric references; "
                    f"got {numeric_count}"
                ),
            )

        # Rule 5: confidence calibration on critical (§5.5).
        if out.overall_risk_level == M0RiskLevel.CRITICAL:
            if out.confidence < 0.75:
                return ValidationResult(
                    success=False,
                    error_type="rule_5_critical_underconfident",
                    error_path=("overall_risk_level", "confidence"),
                    error_message=(
                        f"overall_risk_level=critical requires "
                        f"confidence>=0.75; got {out.confidence:.2f}"
                    ),
                )

        return ValidationResult(success=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_mandate_breach(
        out: M0PRAOutput,
        mandate: dict[str, Any],
        pre: dict[str, Any],
    ) -> ValidationResult | None:
        """Cross-check mandate ceilings/floors against the pre-action
        metrics and flag any disagreement with the verdict_tag."""
        metrics = pre.get("metrics") or {}

        # Concentration breach: HHI > mandate concentration ceiling.
        hhi = (metrics.get("concentration") or {}).get("hhi_at_holding")
        ceiling_hhi = (mandate.get("concentration_ceiling") or {}).get(
            "hhi_at_holding",
        )
        if (
            hhi is not None
            and ceiling_hhi is not None
            and hhi > ceiling_hhi
            and out.per_dimension_assessment.concentration.verdict_tag
            != VerdictTag.BREACH
        ):
            return ValidationResult(
                success=False,
                error_type="rule_1_concentration_breach_unflagged",
                error_path=(
                    "per_dimension_assessment",
                    "concentration",
                    "verdict_tag",
                ),
                error_message=(
                    f"hhi_at_holding={hhi} exceeds mandate ceiling "
                    f"{ceiling_hhi} but verdict_tag is "
                    f"{out.per_dimension_assessment.concentration.verdict_tag.value!r}"
                ),
            )

        # Leverage breach.
        leverage = (metrics.get("leverage") or {}).get("leverage_ratio")
        ceiling_lev = mandate.get("leverage_ceiling")
        if (
            leverage is not None
            and ceiling_lev is not None
            and leverage > ceiling_lev
            and out.per_dimension_assessment.leverage.verdict_tag
            != VerdictTag.BREACH
        ):
            return ValidationResult(
                success=False,
                error_type="rule_1_leverage_breach_unflagged",
                error_path=(
                    "per_dimension_assessment",
                    "leverage",
                    "verdict_tag",
                ),
                error_message=(
                    f"leverage_ratio={leverage} exceeds mandate ceiling "
                    f"{ceiling_lev} but verdict_tag is "
                    f"{out.per_dimension_assessment.leverage.verdict_tag.value!r}"
                ),
            )

        # Liquidity floor breach: T+0..30 sum below mandate floor.
        buckets = (metrics.get("liquidity") or {}).get("buckets") or {}
        liquidity_short = (
            float(buckets.get("T+0_to_T+3", 0))
            + float(buckets.get("T+3_to_T+30", 0))
        )
        floor = (mandate.get("liquidity_floor") or {}).get("T+0_to_T+30")
        if (
            floor is not None
            and liquidity_short < floor
            and out.per_dimension_assessment.liquidity.verdict_tag
            != VerdictTag.BREACH
        ):
            return ValidationResult(
                success=False,
                error_type="rule_1_liquidity_floor_unflagged",
                error_path=(
                    "per_dimension_assessment",
                    "liquidity",
                    "verdict_tag",
                ),
                error_message=(
                    f"T+0_to_T+30 liquidity={liquidity_short} below "
                    f"mandate floor {floor}"
                ),
            )

        # Fee drag breach.
        fee_bps = (metrics.get("fee_drag") or {}).get("aggregate_bps")
        ceiling_fee = mandate.get("fee_drag_ceiling_bps")
        if (
            fee_bps is not None
            and ceiling_fee is not None
            and fee_bps > ceiling_fee
            and out.per_dimension_assessment.fee_drag.verdict_tag
            != VerdictTag.BREACH
        ):
            return ValidationResult(
                success=False,
                error_type="rule_1_fee_drag_breach_unflagged",
                error_path=(
                    "per_dimension_assessment",
                    "fee_drag",
                    "verdict_tag",
                ),
                error_message=(
                    f"fee_drag_aggregate_bps={fee_bps} exceeds mandate "
                    f"ceiling {ceiling_fee}"
                ),
            )

        # Mandate-aware: when overall verdict is "low" but any breach
        # is flagged, escalate.
        if out.overall_risk_level == M0RiskLevel.LOW:
            for dim_name, dim in out.per_dimension_assessment.model_dump().items():
                if dim.get("verdict_tag") == VerdictTag.BREACH.value:
                    return ValidationResult(
                        success=False,
                        error_type="rule_1_overall_low_with_breach",
                        error_path=("overall_risk_level",),
                        error_message=(
                            f"overall_risk_level=low incompatible with "
                            f"per-dimension breach on {dim_name!r}"
                        ),
                    )

        return None

    @staticmethod
    def _to_stage_payload(verdict: M0PRAOutput) -> dict[str, Any]:
        """Map :class:`M0PRAOutput` → the
        :class:`PortfolioRiskAnalyticsOutput` stage row payload."""
        per_dim = verdict.per_dimension_assessment.model_dump(mode="json")
        return {
            "concentration_assessment": per_dim["concentration"],
            "leverage_assessment": per_dim["leverage"],
            "liquidity_assessment": per_dim["liquidity"],
            "return_quality_assessment": per_dim["return_quality"],
            "deployment_assessment": per_dim["deployment"],
            "cascade_assessment": {
                "implications": [
                    c.model_dump(mode="json") for c in verdict.cascade_implications
                ],
                "flagged_proximity": [
                    p.model_dump(mode="json") for p in verdict.flagged_proximity
                ],
            },
            "overall_risk_level": _coarse_risk(verdict.overall_risk_level),
            "overall_confidence": verdict.confidence,
            "drivers": {
                "key_risk_drivers": [
                    d.model_dump(mode="json") for d in verdict.key_risk_drivers
                ],
            },
            "flags": {},
            "reasoning_summary": verdict.reasoning_summary,
        }


def _coarse_risk(level: M0RiskLevel) -> str:
    """Map M0.PRA risk level to the cluster-5 RiskLevel column enum
    (low / medium / high / critical). Cluster 7 introduces ``moderate``
    in the M0 schema; coerce it to ``medium`` for the stage row."""
    if level == M0RiskLevel.LOW:
        return "low"
    if level == M0RiskLevel.MODERATE:
        return "medium"
    if level == M0RiskLevel.HIGH:
        return "high"
    return "critical"


__all__ = ["M0PortfolioRiskAnalyticsShim"]
