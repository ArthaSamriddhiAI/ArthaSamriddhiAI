"""E2.StockInSector shim — cluster 8 chunk 8.2 §4.5 + §4.6.

Implements :class:`AgentShim` for E2.StockInSector.  Five semantic
validation rules (chunk 8.2 §4.5) check ticker + sector_code match,
verdict/quartile consistency, ranking framework specificity,
reasoning references sector context, and sector_relative_signals
are sector-relative (not fundamentals-only).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e2_stock_in_sector.schema import (
    E2StockInSectorOutput,
    SectorQuartile,
    StockInSectorVerdict,
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

# Verdicts that imply specific quartiles (rule 2).
_VERDICT_TO_QUARTILE: dict[str, str] = {
    StockInSectorVerdict.BEST_IN_CLASS.value: SectorQuartile.TOP.value,
    StockInSectorVerdict.CHALLENGED_POSITION.value: SectorQuartile.BOTTOM.value,
}

# Generic ranking framework patterns that rule 3 should reject.
_GENERIC_FRAMEWORK_PATTERN = re.compile(
    r"^(fundamental analysis|sector analysis|standard analysis|"
    r"overall assessment|general framework|qualitative assessment)$",
    re.IGNORECASE,
)

# E1 fundamentals-only terms that should NOT exclusively fill sector signals
# (rule 5 — sector_relative should be sector-relative, not per-stock financials).
_PURE_FUNDAMENTALS_TERMS = frozenset(
    {
        "roce", "return on capital", "debt equity", "pe ratio", "p/e",
        "earnings quality", "promoter pledge", "audit qualification",
    }
)


class E2StockInSectorShim(AgentShim):
    """Cluster-8 real E2.StockInSector shim."""

    agent_id = "e2_stock_in_sector"
    skill_md_version = "2.0"
    output_model = E2StockInSectorOutput

    _USER_PROMPT_TEMPLATE = (
        "Please produce stock-in-sector positioning analysis for: {ticker}\n"
        "\n"
        "Sector classification for ticker:\n"
        "{sector_classification_json}\n"
        "\n"
        "E2.SectorView output for this sector:\n"
        "{e2_sector_view_output_json}\n"
        "\n"
        "E3.MacroView output:\n"
        "{e3_macro_view_output_json}\n"
        "\n"
        "Return your verdict as a single JSON object matching schema "
        "referenced at {output_schema_ref}."
    )

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        for field in ("ticker", "sector_code"):
            if not agent_inputs.payload.get(field):
                return ValidationResult(
                    success=False,
                    error_type="missing_field",
                    error_path=(field,),
                    error_message=(
                        f"E2.StockInSector requires non-empty '{field}' input"
                    ),
                )
        return ValidationResult(success=True)

    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        import json

        placeholders = {
            "ticker": agent_inputs.payload.get("ticker", ""),
            "sector_classification_json": json.dumps(
                {
                    "ticker": agent_inputs.payload.get("ticker"),
                    "sector_code": agent_inputs.payload.get("sector_code"),
                },
                ensure_ascii=False,
            ),
            "e2_sector_view_output_json": json.dumps(
                agent_inputs.payload.get("sector_view_output") or {},
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
            raise ValueError(f"E2.StockInSector parse: {parse_err}")
        try:
            verdict = E2StockInSectorOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E2.StockInSector schema_violation: {exc.errors()[:3]}",
            ) from exc

        # Ticker / sector_code match check.
        ticker = agent_inputs.payload.get("ticker")
        sector_code = agent_inputs.payload.get("sector_code")
        if ticker and verdict.ticker != ticker:
            raise ValueError(
                f"E2.StockInSector ticker mismatch: requested {ticker!r}, "
                f"got {verdict.ticker!r}",
            )
        if sector_code and verdict.sector_code != sector_code:
            raise ValueError(
                f"E2.StockInSector sector_code mismatch: requested "
                f"{sector_code!r}, got {verdict.sector_code!r}",
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
        """Apply the 5 semantic validation rules from chunk 8.2 §4.5."""
        out = E2StockInSectorOutput.model_validate(verdict.structured)

        # Rule 1: ticker + sector_code match (enforced in parse_output too; belt+braces).
        requested_ticker = agent_inputs.payload.get("ticker", "")
        requested_sector = agent_inputs.payload.get("sector_code", "")
        if requested_ticker and out.ticker != requested_ticker:
            return ValidationResult(
                success=False,
                error_type="rule_1_ticker_mismatch",
                error_path=("ticker",),
                error_message=(
                    f"ticker mismatch: requested {requested_ticker!r}, "
                    f"got {out.ticker!r}"
                ),
            )
        if requested_sector and out.sector_code != requested_sector:
            return ValidationResult(
                success=False,
                error_type="rule_1_sector_code_mismatch",
                error_path=("sector_code",),
                error_message=(
                    f"sector_code mismatch: requested {requested_sector!r}, "
                    f"got {out.sector_code!r}"
                ),
            )

        # Rule 2: stock_in_sector_verdict consistent with sector_quartile.
        verdict_val = out.stock_in_sector_verdict.value
        quartile_val = out.positioning_within_sector.sector_quartile.value
        required_quartile = _VERDICT_TO_QUARTILE.get(verdict_val)
        if required_quartile is not None and quartile_val != required_quartile:
            return ValidationResult(
                success=False,
                error_type="rule_2_verdict_quartile_mismatch",
                error_path=("stock_in_sector_verdict",),
                error_message=(
                    f"stock_in_sector_verdict={verdict_val!r} requires "
                    f"sector_quartile={required_quartile!r}; got {quartile_val!r}"
                ),
            )

        # Rule 3: ranking_framework is non-generic.
        framework = out.positioning_within_sector.ranking_framework
        if _GENERIC_FRAMEWORK_PATTERN.match(framework.strip()):
            return ValidationResult(
                success=False,
                error_type="rule_3_generic_ranking_framework",
                error_path=("positioning_within_sector", "ranking_framework"),
                error_message=(
                    f"ranking_framework {framework!r} is too generic; "
                    f"specify concrete dimensions"
                ),
            )

        # Rule 4: reasoning_summary references sector context (from SectorView output).
        sector_view = agent_inputs.payload.get("sector_view_output") or {}
        cycle_stage = sector_view.get("cycle_stage") or ""
        if cycle_stage and cycle_stage.lower() not in out.reasoning_summary.lower():
            return ValidationResult(
                success=True,  # warning, not failure
                error_type="rule_4_sector_context_not_in_reasoning_warn",
                error_path=("reasoning_summary",),
                error_message=(
                    f"reasoning_summary does not reference sector cycle_stage "
                    f"{cycle_stage!r} from SectorView (sector-context warning)"
                ),
            )

        # Rule 5: sector_relative_signals are not exclusively E1 fundamentals terms.
        if out.sector_relative_signals:
            signals_lower = {s.signal.lower() for s in out.sector_relative_signals}
            pure_fundamentals_count = sum(
                1
                for term in _PURE_FUNDAMENTALS_TERMS
                if any(term in sig for sig in signals_lower)
            )
            if pure_fundamentals_count == len(out.sector_relative_signals):
                return ValidationResult(
                    success=False,
                    error_type="rule_5_signals_are_fundamentals_only",
                    error_path=("sector_relative_signals",),
                    error_message=(
                        "sector_relative_signals appear to be E1 fundamentals "
                        "signals; E2.StockInSector should supply sector-relative "
                        "positioning signals"
                    ),
                )

        return ValidationResult(success=True)

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        ticker = agent_inputs.payload.get("ticker")
        sector_code = agent_inputs.payload.get("sector_code")
        if not ticker or not sector_code:
            return None
        earnings_id = agent_inputs.payload.get("latest_earnings_id") or "no_earnings_seeded"
        stock_manual_flag_id = agent_inputs.payload.get("stock_manual_flag_id") or "null"
        return f"e2sis:{ticker}:{sector_code}:{earnings_id}:{stock_manual_flag_id}"

    @staticmethod
    def _to_stage_payload(verdict: E2StockInSectorOutput) -> dict[str, Any]:
        return {
            "agent_id": "e2_stock_in_sector",
            "ticker": verdict.ticker,
            "sector_code": verdict.sector_code,
            "stock_in_sector_verdict": verdict.stock_in_sector_verdict.value,
            "sector_quartile": verdict.positioning_within_sector.sector_quartile.value,
            "confidence": verdict.confidence,
            "structured_output": verdict.model_dump(mode="json"),
            "reasoning_summary": verdict.reasoning_summary,
        }


__all__ = ["E2StockInSectorShim"]
