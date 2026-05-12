"""E3.NewsScanner shim — cluster 8 chunk 8.4 §8 + §9.

Implements :class:`AgentShim` for E3.NewsScanner (uncached per-case
sub-agent).  Seven semantic validation rules (chunk 8.4 §8) enforce
case_id match, full ticker coverage, news_id grounding, push
consistency, high/low materiality invariants, and rationale presence.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from artha.api_v2.agents.e3_news_scanner.schema import (
    E3NewsScannerOutput,
    EntityType,
    MaterialityLevel,
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


class E3NewsScannerShim(AgentShim):
    """Cluster-8 real E3.NewsScanner shim (uncached)."""

    agent_id = "e3_news_scanner"
    skill_md_version = "2.0"
    output_model = E3NewsScannerOutput

    _USER_PROMPT_TEMPLATE = (
        "Please scan recent news for material events affecting holdings "
        "in this case.\n"
        "\n"
        "Case context:\n"
        "{case_context_json}\n"
        "\n"
        "Stock list (tickers in this case after look-through resolution):\n"
        "{stock_list_json}\n"
        "\n"
        "Recent news events (last 90 days; filtered to relevant tickers):\n"
        "{recent_news_events_json}\n"
        "\n"
        "Return verdict as single JSON object matching schema at "
        "{output_schema_ref}."
    )

    def validate_input(self, agent_inputs: AgentInputs) -> ValidationResult:
        case_id = agent_inputs.payload.get("case_id")
        if not case_id:
            return ValidationResult(
                success=False,
                error_type="missing_field",
                error_path=("case_id",),
                error_message="E3.NewsScanner requires non-empty 'case_id' input",
            )
        tickers = agent_inputs.payload.get("tickers") or []
        if not isinstance(tickers, list):
            return ValidationResult(
                success=False,
                error_type="invalid_field",
                error_path=("tickers",),
                error_message="E3.NewsScanner 'tickers' must be a list",
            )
        return ValidationResult(success=True)

    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        import json

        tickers = agent_inputs.payload.get("tickers") or []
        placeholders = {
            "case_context_json": json.dumps(
                {
                    "case_id": agent_inputs.payload.get("case_id"),
                    "case_mode": agent_inputs.case_mode,
                },
                ensure_ascii=False,
            ),
            "stock_list_json": json.dumps(
                {"tickers": [{"ticker": t} for t in tickers]},
                ensure_ascii=False,
            ),
            "recent_news_events_json": json.dumps(
                agent_inputs.payload.get("recent_news_events") or [],
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
            raise ValueError(f"E3.NewsScanner parse: {parse_err}")
        try:
            verdict = E3NewsScannerOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"E3.NewsScanner schema_violation: {exc.errors()[:3]}",
            ) from exc

        case_id = agent_inputs.payload.get("case_id")
        if case_id and verdict.case_id != case_id:
            raise ValueError(
                f"E3.NewsScanner case_id mismatch: requested {case_id!r}, "
                f"got {verdict.case_id!r}",
            )

        structured = verdict.model_dump(mode="json", by_alias=True)
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
        """Apply the 9 semantic validation rules (chunks 8.4 §8, 9.4 §2)."""
        # Re-validate with by_alias because scan_period uses "from" alias.
        out = E3NewsScannerOutput.model_validate(verdict.structured)

        # Rule 1: case_id matches request.
        case_id = agent_inputs.payload.get("case_id", "")
        if case_id and out.case_id != case_id:
            return ValidationResult(
                success=False,
                error_type="rule_1_case_id_mismatch",
                error_path=("case_id",),
                error_message=f"case_id mismatch: {case_id!r} vs {out.case_id!r}",
            )

        # Rule 2: per_ticker_signals covers exactly all input tickers.
        input_tickers = set(agent_inputs.payload.get("tickers") or [])
        output_tickers = {pts.ticker for pts in out.per_ticker_signals}
        missing = input_tickers - output_tickers
        extra = output_tickers - input_tickers
        if missing:
            return ValidationResult(
                success=False,
                error_type="rule_2_missing_ticker_coverage",
                error_path=("per_ticker_signals",),
                error_message=f"per_ticker_signals missing tickers: {sorted(missing)}",
            )
        if extra:
            return ValidationResult(
                success=False,
                error_type="rule_2_extra_ticker_in_signals",
                error_path=("per_ticker_signals",),
                error_message=(
                    f"per_ticker_signals contains tickers not in input: {sorted(extra)}"
                ),
            )

        # Rule 3: every news_id in events references actual input news_ids.
        valid_news_ids = set(agent_inputs.payload.get("available_news_ids") or [])
        if valid_news_ids:
            for pts in out.per_ticker_signals:
                for event in pts.events:
                    if event.news_id not in valid_news_ids:
                        return ValidationResult(
                            success=False,
                            error_type="rule_3_hallucinated_news_id",
                            error_path=("per_ticker_signals", "events", "news_id"),
                            error_message=(
                                f"news_id {event.news_id!r} does not appear "
                                f"in input available_news_ids"
                            ),
                        )

        # Build index: (ticker, news_id) → warrants_cache_invalidation.
        warrants_map: dict[tuple[str, str], bool] = {}
        for pts in out.per_ticker_signals:
            for event in pts.events:
                warrants_map[(pts.ticker, event.news_id)] = event.warrants_cache_invalidation

        # Rule 4: cache_invalidation_pushes consistency.
        # Only applies to ticker-type pushes (non-ticker entities do not
        # appear in per_ticker_signals).
        for push in out.cache_invalidation_pushes:
            if push.entity_type != EntityType.TICKER:
                continue  # non-ticker push — skip per_ticker_signals check
            key = (push.ticker, push.news_id)
            warrants = warrants_map.get(key, False)
            if not warrants:
                return ValidationResult(
                    success=False,
                    error_type="rule_4_push_without_warrant",
                    error_path=("cache_invalidation_pushes",),
                    error_message=(
                        f"cache_invalidation_pushes entry for "
                        f"({push.ticker}, {push.news_id}) but the corresponding "
                        f"event has warrants_cache_invalidation=False"
                    ),
                )

        # Rules 5 & 6: high materiality → always invalidate; low → never.
        for pts in out.per_ticker_signals:
            for event in pts.events:
                high = event.materiality_level == MaterialityLevel.HIGH
                if high and not event.warrants_cache_invalidation:
                    return ValidationResult(
                        success=False,
                        error_type="rule_5_high_materiality_not_invalidating",
                        error_path=("per_ticker_signals", "events"),
                        error_message=(
                            f"event news_id={event.news_id!r} has "
                            f"materiality_level=high but "
                            f"warrants_cache_invalidation=False"
                        ),
                    )
                low = event.materiality_level == MaterialityLevel.LOW
                if low and event.warrants_cache_invalidation:
                    return ValidationResult(
                        success=False,
                        error_type="rule_6_low_materiality_invalidating",
                        error_path=("per_ticker_signals", "events"),
                        error_message=(
                            f"event news_id={event.news_id!r} has "
                            f"materiality_level=low but "
                            f"warrants_cache_invalidation=True"
                        ),
                    )

        # Rule 7: every event's rationale is non-empty.
        for pts in out.per_ticker_signals:
            for event in pts.events:
                if not event.rationale.strip():
                    return ValidationResult(
                        success=False,
                        error_type="rule_7_empty_rationale",
                        error_path=(
                            "per_ticker_signals", "events", "rationale",
                        ),
                        error_message=(
                            f"event news_id={event.news_id!r} has empty rationale"
                        ),
                    )

        # ------------------------------------------------------------------
        # Rules 8–9: cluster 9 chunk 9.4 extensions.
        # ------------------------------------------------------------------

        # Rule 8: entity_id must be non-empty for non-ticker entity types;
        # ticker must be non-empty for ticker-type pushes.
        for push in out.cache_invalidation_pushes:
            if push.entity_type == EntityType.TICKER:
                if not push.ticker.strip():
                    return ValidationResult(
                        success=False,
                        error_type="rule_8_ticker_missing_for_ticker_push",
                        error_path=("cache_invalidation_pushes", "ticker"),
                        error_message=(
                            f"push news_id={push.news_id!r}: entity_type='ticker' "
                            f"but ticker is empty"
                        ),
                    )
            else:
                if not push.entity_id.strip():
                    return ValidationResult(
                        success=False,
                        error_type="rule_8_entity_id_empty",
                        error_path=(
                            "cache_invalidation_pushes", "entity_id",
                        ),
                        error_message=(
                            f"push news_id={push.news_id!r}: entity_type="
                            f"{push.entity_type.value!r} but entity_id is empty"
                        ),
                    )

        # Rule 9: flag-set consistency with entity_type.
        entity_flag_map = {
            EntityType.TICKER: ("invalidates_e1", "invalidates_e2sis"),
            EntityType.AIF: ("invalidates_e5fv",),
            EntityType.DEAL: ("invalidates_e5dv",),
        }
        for push in out.cache_invalidation_pushes:
            expected_flags = entity_flag_map.get(push.entity_type)
            if expected_flags is None:
                # EntityType.INVESTOR — no direct cache invalidation.
                continue
            if not any(getattr(push, f, False) for f in expected_flags):
                return ValidationResult(
                    success=False,
                    error_type="rule_9_flag_set_inconsistency",
                    error_path=("cache_invalidation_pushes",),
                    error_message=(
                        f"push news_id={push.news_id!r}: entity_type="
                        f"{push.entity_type.value!r} requires at least one of "
                        f"{expected_flags} to be True"
                    ),
                )

        return ValidationResult(success=True)

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        """E3.NewsScanner is not cached (per-case context dominant)."""
        return None

    @staticmethod
    def _to_stage_payload(verdict: E3NewsScannerOutput) -> dict[str, Any]:
        material_tickers = [
            pts.ticker
            for pts in verdict.per_ticker_signals
            if pts.has_material_events
        ]
        return {
            "agent_id": "e3_news_scanner",
            "case_id": verdict.case_id,
            "material_tickers": material_tickers,
            "cache_invalidation_push_count": len(verdict.cache_invalidation_pushes),
            "confidence": verdict.confidence,
            "structured_output": verdict.model_dump(mode="json", by_alias=True),
            "reasoning_summary": verdict.reasoning_summary,
        }


__all__ = ["E3NewsScannerShim"]
