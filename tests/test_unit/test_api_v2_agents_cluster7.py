"""Cluster 7 chunk 7.1 — agent framework tests.

Pins:

- :class:`AgentDispatcher` retry policy (3 retries, then
  :class:`AgentDispatchError`) — case_arch08_b pattern.
- :class:`E1Shim`'s 5 semantic rules (verdict-risk consistency,
  confidence calibration, metric coverage, framework-axis presence,
  ticker-mention warning).
- :class:`M0PortfolioRiskAnalyticsShim`'s 5 semantic rules (mandate
  breach flagging, dimension non-empty, PA delta requirement,
  quantitative grounding, critical confidence calibration).
- ``prompt_loader.render_user_prompt`` placeholder substitution +
  missing-placeholder detection.
- ``MockLLMClient`` queue + error injection.
- ``agents.config`` stub/real toggle (env + override priority).
- ``agents.runtime.dispatch_real_agent`` shim execution path.
- ``cases.dispatch.dispatch_agent`` routing between stub + real.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from artha.api_v2.agents import config as agents_config
from artha.api_v2.agents import registry as agents_registry
from artha.api_v2.agents import runtime as agents_runtime
from artha.api_v2.agents.e1.schema import (
    E1DriverWeight,
    E1Framework,
    E1FrameworkAxis,
    E1KeyDriver,
    E1Metric,
    E1MetricEvaluations,
    E1Output,
    E1Verdict,
)
from artha.api_v2.agents.e1.shim import E1Shim
from artha.api_v2.agents.llm_client import (
    LLMCallError,
    LLMResponse,
    MockLLMClient,
)
from artha.api_v2.agents.m0_pra.schema import (
    CascadeHorizon,
    CascadeImplication,
    CascadeSeverity,
    DimensionAssessment,
    DriverWeight,
    KeyRiskDriver,
    M0PRAOutput,
    M0RiskLevel,
    PerDimensionAssessment,
    VerdictTag,
)
from artha.api_v2.agents.m0_pra.shim import M0PortfolioRiskAnalyticsShim
from artha.api_v2.agents.prompt_loader import (
    MissingPlaceholderError,
    PromptPayload,
    PromptTemplate,
    render_user_prompt,
)
from artha.api_v2.agents.shim import (
    AgentDispatcher,
    AgentDispatchError,
    AgentInputs,
    DispatchPolicy,
    parse_json_object,
)
from artha.api_v2.cases import dispatch as cases_dispatch
from artha.api_v2.cases.state_machine import ProducedVia

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _e1_valid_payload(
    *,
    ticker: str = "RELIANCE",
    verdict: str = "positive",
    confidence: float = 0.7,
    reasoning_words: int = 240,
    risk_signals: list[str] | None = None,
    axis_value: str = "consumer/IT large-cap value-quality blend",
) -> dict[str, Any]:
    """Build a JSON payload that round-trips through :class:`E1Output`."""
    reasoning = " ".join([f"word{i}" for i in range(reasoning_words)])
    # Ensure ticker is mentioned (rule 5 warning) when not specifically suppressed.
    if ticker:
        reasoning = f"{ticker} " + reasoning
    return {
        "ticker": ticker,
        "verdict": verdict,
        "confidence": confidence,
        "metric_evaluations": {
            "roce": {"reading": "in-range"},
            "leverage": {"reading": "low"},
            "earnings_quality": {"reading": "high"},
            "valuation": {"reading": "fair"},
            "growth": {"reading": "moderate"},
            "margins": {"reading": "stable"},
        },
        "per_stock_framework": {
            "framework_axis": "quality_maturity_best_in_class",
            "axis_value": axis_value,
        },
        "risk_signals": risk_signals or [],
        "reasoning_summary": reasoning,
        "key_drivers": [
            {"driver": "cashflow_stability", "weight": "high"},
        ],
    }


def _e1_inputs(ticker: str = "RELIANCE") -> AgentInputs:
    return AgentInputs(
        case_id="case_test",
        case_mode="proposed_action",
        case_intent="invest_top_up",
        payload={
            "ticker": ticker,
            "snapshot_excerpt": "snapshot",
            "mandate_excerpt": "mandate",
            "macro_context": "macro",
            "latest_earnings_id": "no_earnings_seeded",
            "manual_flag_id": "null",
        },
    )


def _m0_pra_valid_payload(
    *,
    overall: str = "moderate",
    confidence: float = 0.7,
    flag_concentration_breach: bool = False,
    include_delta: bool = True,
) -> dict[str, Any]:
    """Build a payload that round-trips through :class:`M0PRAOutput`."""
    delta = "improves -8% post-action" if include_delta else None

    def _dim(reading: str, tag: str = "clean") -> dict[str, Any]:
        d = {"reading": reading, "verdict_tag": tag}
        if delta is not None:
            d["delta_post_action"] = delta
        return d

    return {
        "overall_risk_level": overall,
        "confidence": confidence,
        "per_dimension_assessment": {
            "concentration": _dim(
                "HHI 0.18 (within band)",
                "breach" if flag_concentration_breach else "clean",
            ),
            "leverage": _dim("leverage 1.1x (well below ceiling)"),
            "liquidity": _dim("T+0..30 = 12% (above floor)"),
            "return_quality": _dim("Sharpe 1.4 / max drawdown 9%"),
            "fee_drag": _dim("aggregate 65 bps"),
            "deployment": _dim("82% deployed"),
        },
        "cascade_implications": [
            {
                "implication": "capital call timing T+45",
                "horizon": "near_term",
                "severity": "low",
            },
        ],
        "flagged_proximity": [],
        "reasoning_summary": (
            "Concentration HHI 0.18 (well below the mandate ceiling of "
            "0.25), leverage 1.1x (well below ceiling 1.5x), fee drag "
            "65 bps (below ceiling 100 bps); post-action delta improves "
            "liquidity by 4 percentage points and trims fee drag by 8 "
            "bps. No breach observed across the six mandate-aware "
            "dimensions; deployment 82%, return quality Sharpe 1.4, "
            "and overall risk verdict synthesised from interpretation "
            "of the deterministic PortfolioAnalytics metrics."
        ),
        "key_risk_drivers": [
            {"driver": "concentration_within_band", "weight": "high"},
        ],
    }


def _m0_pra_inputs(
    *,
    case_mode: str = "proposed_action",
    mandate: dict[str, Any] | None = None,
    pre_metrics: dict[str, Any] | None = None,
    post_metrics: dict[str, Any] | None = None,
) -> AgentInputs:
    return AgentInputs(
        case_id="case_test",
        case_mode=case_mode,
        case_intent="invest_top_up",
        payload={
            "mandate": mandate or {
                "concentration_ceiling": {"hhi_at_holding": 0.25},
                "leverage_ceiling": 1.5,
                "liquidity_floor": {"T+0_to_T+30": 0.05},
                "fee_drag_ceiling_bps": 100,
            },
            "portfolio_analytics_pre_action": pre_metrics or {
                "metrics": {
                    "concentration": {"hhi_at_holding": 0.18},
                    "leverage": {"leverage_ratio": 1.1},
                    "liquidity": {
                        "buckets": {
                            "T+0_to_T+3": 0.04,
                            "T+3_to_T+30": 0.08,
                        },
                    },
                    "fee_drag": {"aggregate_bps": 65},
                },
            },
            "portfolio_analytics_post_action": post_metrics or {
                "metrics": {
                    "concentration": {"hhi_at_holding": 0.17},
                    "leverage": {"leverage_ratio": 1.05},
                    "liquidity": {
                        "buckets": {
                            "T+0_to_T+3": 0.04,
                            "T+3_to_T+30": 0.10,
                        },
                    },
                    "fee_drag": {"aggregate_bps": 57},
                },
            },
            "proposed_action_summary": "top up 5L of mid-cap blend",
            "dominant_lens": "growth",
            "evidence_summaries": [],
        },
    )


def _skill_template(
    agent_id: str = "e1_listed_fundamental_equity",
    *,
    body: str = "You are agent X.",
) -> PromptTemplate:
    return PromptTemplate(
        agent_id=agent_id,
        skill_md_version="1.1",
        system_body=body,
        llm_model="claude-sonnet-4-5",
        max_tokens=4096,
        temperature=0.2,
        output_schema_ref="../schemas/x.json",
    )


# ---------------------------------------------------------------------------
# parse_json_object helper
# ---------------------------------------------------------------------------


class TestParseJsonObject:
    def test_plain_object(self) -> None:
        payload, err = parse_json_object('{"a": 1}')
        assert err is None
        assert payload == {"a": 1}

    def test_code_fenced_json(self) -> None:
        payload, err = parse_json_object('```json\n{"x": "y"}\n```')
        assert err is None
        assert payload == {"x": "y"}

    def test_prose_around_object(self) -> None:
        text = 'Here you go:\n{"k": 2}\nThanks.'
        payload, err = parse_json_object(text)
        assert err is None
        assert payload == {"k": 2}

    def test_unbalanced_braces(self) -> None:
        _, err = parse_json_object('{"a": 1')
        assert err is not None

    def test_no_object_found(self) -> None:
        _, err = parse_json_object("just prose, no JSON here")
        assert err == "no_json_object_found"


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------


class TestRenderUserPrompt:
    def test_substitution(self) -> None:
        out = render_user_prompt(
            "ticker={ticker}; intent={intent}",
            placeholders={"ticker": "RELIANCE", "intent": "review"},
        )
        assert out == "ticker=RELIANCE; intent=review"

    def test_missing_placeholder_raises(self) -> None:
        with pytest.raises(MissingPlaceholderError):
            render_user_prompt(
                "ticker={ticker}; missing={extra}",
                placeholders={"ticker": "RELIANCE"},
            )

    def test_extra_placeholders_ignored(self) -> None:
        # Placeholders supplied beyond what the template uses are tolerated.
        out = render_user_prompt(
            "x={x}",
            placeholders={"x": "1", "y": "2"},
        )
        assert out == "x=1"


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------


class TestMockLLMClient:
    def _payload(self) -> PromptPayload:
        return PromptPayload(
            system="sys", user="usr", llm_model="m", max_tokens=10, temperature=0.0,
        )

    def test_returns_queued_response(self) -> None:
        client = MockLLMClient(responses=["hello"])
        resp = client.complete(self._payload())
        assert isinstance(resp, LLMResponse)
        assert resp.text == "hello"

    def test_logs_calls(self) -> None:
        client = MockLLMClient(responses=["a", "b"])
        client.complete(self._payload())
        client.complete(self._payload())
        assert len(client.call_log) == 2

    def test_error_queue_raises(self) -> None:
        client = MockLLMClient(
            responses=["ok"],
            error_queue=[LLMCallError("transient")],
        )
        with pytest.raises(LLMCallError):
            client.complete(self._payload())

    def test_error_queue_with_none_passes_through(self) -> None:
        client = MockLLMClient(
            responses=["only_one"],
            error_queue=[None],  # consume None, then take from responses
        )
        resp = client.complete(self._payload())
        assert resp.text == "only_one"

    def test_exhausted_queue_raises(self) -> None:
        client = MockLLMClient(responses=[])
        with pytest.raises(LLMCallError):
            client.complete(self._payload())


# ---------------------------------------------------------------------------
# AgentDispatcher
# ---------------------------------------------------------------------------


class TestAgentDispatcher:
    def test_happy_path_returns_verdict(self) -> None:
        body = json.dumps(_e1_valid_payload())
        client = MockLLMClient(responses=[body])
        dispatcher = AgentDispatcher(llm_client=client)
        out = dispatcher.run(
            shim=E1Shim(),
            skill_md_template=_skill_template(),
            agent_inputs=_e1_inputs(),
        )
        assert out.retry_count == 0
        assert out.verdict.structured["verdict"] == "positive"

    def test_transient_error_then_success(self) -> None:
        body = json.dumps(_e1_valid_payload())
        client = MockLLMClient(
            responses=[body],
            error_queue=[LLMCallError("timeout"), None],
        )
        dispatcher = AgentDispatcher(llm_client=client)
        out = dispatcher.run(
            shim=E1Shim(),
            skill_md_template=_skill_template(),
            agent_inputs=_e1_inputs(),
        )
        # 1st call raised, 2nd call succeeded → retry_count is the
        # final iteration index (1).
        assert out.retry_count == 1

    def test_retries_exhausted_raises(self) -> None:
        client = MockLLMClient(
            error_queue=[
                LLMCallError("timeout"),
                LLMCallError("timeout"),
                LLMCallError("timeout"),
            ],
        )
        dispatcher = AgentDispatcher(
            llm_client=client,
            policy=DispatchPolicy(max_retries=3),
        )
        with pytest.raises(AgentDispatchError) as excinfo:
            dispatcher.run(
                shim=E1Shim(),
                skill_md_template=_skill_template(),
                agent_inputs=_e1_inputs(),
            )
        assert excinfo.value.retry_count == 3

    def test_input_validation_fails_fast(self) -> None:
        client = MockLLMClient(responses=[])
        dispatcher = AgentDispatcher(llm_client=client)
        bad = AgentInputs(
            case_id="x", case_mode="proposed_action",
            case_intent=None, payload={},  # no ticker
        )
        with pytest.raises(AgentDispatchError):
            dispatcher.run(
                shim=E1Shim(),
                skill_md_template=_skill_template(),
                agent_inputs=bad,
            )
        # No LLM call should have been issued.
        assert client.call_log == []

    def test_parse_failure_retries(self) -> None:
        good = json.dumps(_e1_valid_payload())
        client = MockLLMClient(responses=["totally not json", good])
        dispatcher = AgentDispatcher(
            llm_client=client,
            policy=DispatchPolicy(max_retries=3),
        )
        out = dispatcher.run(
            shim=E1Shim(),
            skill_md_template=_skill_template(),
            agent_inputs=_e1_inputs(),
        )
        assert out.retry_count == 1


# ---------------------------------------------------------------------------
# E1Shim semantic rules
# ---------------------------------------------------------------------------


class TestE1ShimRules:
    def _round_trip(self, payload: dict[str, Any]) -> Any:
        # Build a ParsedVerdict-equivalent by running parse_output.
        shim = E1Shim()
        body = json.dumps(payload)
        return shim.parse_output(
            llm_response=LLMResponse(text=body),
            agent_inputs=_e1_inputs(payload["ticker"]),
        )

    def test_rule_1_positive_with_high_severity_signal_fails(self) -> None:
        payload = _e1_valid_payload(
            risk_signals=["promoter pledge near covenant trigger"],
        )
        verdict = self._round_trip(payload)
        result = E1Shim().validate_output(verdict, _e1_inputs())
        assert not result.success
        assert result.error_type == "rule_1_verdict_risk_mismatch"

    def test_rule_2_high_confidence_underjustified(self) -> None:
        payload = _e1_valid_payload(confidence=0.9, reasoning_words=210)
        verdict = self._round_trip(payload)
        result = E1Shim().validate_output(verdict, _e1_inputs())
        assert not result.success
        assert result.error_type == "rule_2_confidence_underjustified"

    def test_rule_2_low_confidence_short_reasoning_ok(self) -> None:
        # Schema enforces a minimum of 200 words; below 300 is fine when
        # confidence < 0.85.
        payload = _e1_valid_payload(confidence=0.6, reasoning_words=220)
        verdict = self._round_trip(payload)
        result = E1Shim().validate_output(verdict, _e1_inputs())
        assert result.success

    def test_rule_4_positive_requires_axis_value(self) -> None:
        payload = _e1_valid_payload(axis_value="")
        verdict = self._round_trip(payload)
        result = E1Shim().validate_output(verdict, _e1_inputs())
        assert not result.success
        assert result.error_type == "rule_4_missing_framework_axis_value"

    def test_rule_5_ticker_missing_is_warning_not_failure(self) -> None:
        # Build reasoning that does NOT mention the ticker.
        payload = _e1_valid_payload()
        # Strip any leading mention of the ticker.
        payload["reasoning_summary"] = " ".join(
            ["word" for _ in range(220)],
        )
        verdict = self._round_trip(payload)
        result = E1Shim().validate_output(verdict, _e1_inputs())
        # Warning surfaces error_type but success stays True per cluster
        # 7 §8.5.
        assert result.success
        assert result.error_type == "rule_5_ticker_not_in_reasoning_warn"

    def test_compute_cache_key_format(self) -> None:
        key = E1Shim().compute_cache_key(_e1_inputs("INFY"))
        assert key == "e1:INFY:no_earnings_seeded:null"

    def test_compute_cache_key_no_ticker(self) -> None:
        key = E1Shim().compute_cache_key(
            AgentInputs(
                case_id="x", case_mode="proposed_action",
                case_intent=None, payload={},
            ),
        )
        assert key is None


# ---------------------------------------------------------------------------
# M0PortfolioRiskAnalyticsShim semantic rules
# ---------------------------------------------------------------------------


class TestM0PRAShim:
    def _round_trip(self, payload: dict[str, Any]) -> Any:
        shim = M0PortfolioRiskAnalyticsShim()
        body = json.dumps(payload)
        return shim.parse_output(
            llm_response=LLMResponse(text=body),
            agent_inputs=_m0_pra_inputs(),
        )

    def test_happy_path_passes(self) -> None:
        payload = _m0_pra_valid_payload()
        verdict = self._round_trip(payload)
        result = M0PortfolioRiskAnalyticsShim().validate_output(
            verdict, _m0_pra_inputs(),
        )
        assert result.success

    def test_rule_1_concentration_breach_unflagged(self) -> None:
        # Pre metrics show HHI 0.30 > ceiling 0.25, but verdict_tag clean.
        pre = {
            "metrics": {
                "concentration": {"hhi_at_holding": 0.30},
                "leverage": {"leverage_ratio": 1.1},
                "liquidity": {
                    "buckets": {
                        "T+0_to_T+3": 0.04,
                        "T+3_to_T+30": 0.08,
                    },
                },
                "fee_drag": {"aggregate_bps": 65},
            },
        }
        inputs = _m0_pra_inputs(pre_metrics=pre)
        payload = _m0_pra_valid_payload()  # concentration tag = clean
        verdict = self._round_trip(payload)
        result = M0PortfolioRiskAnalyticsShim().validate_output(verdict, inputs)
        assert not result.success
        assert result.error_type == "rule_1_concentration_breach_unflagged"

    def test_rule_3_pa_missing_delta_fails(self) -> None:
        payload = _m0_pra_valid_payload(include_delta=False)
        verdict = self._round_trip(payload)
        # PA mode requires deltas on every dimension.
        result = M0PortfolioRiskAnalyticsShim().validate_output(
            verdict, _m0_pra_inputs(case_mode="proposed_action"),
        )
        assert not result.success
        assert result.error_type == "rule_3_missing_delta_on_pa"

    def test_rule_3_diagnostic_no_delta_ok(self) -> None:
        # Diagnostic mode: no PA so delta isn't required.
        payload = _m0_pra_valid_payload(include_delta=False)
        verdict = self._round_trip(payload)
        result = M0PortfolioRiskAnalyticsShim().validate_output(
            verdict, _m0_pra_inputs(case_mode="diagnostic"),
        )
        assert result.success

    def test_rule_4_under_quantified_reasoning_fails(self) -> None:
        payload = _m0_pra_valid_payload()
        # Strip numeric tokens to under 3 references but keep length
        # >=200 chars so schema passes.
        payload["reasoning_summary"] = (
            "Concentration interpreted as comfortably within band, "
            "leverage well below the ceiling, liquidity adequate "
            "across the near-term and medium-term buckets, and fee "
            "drag healthy versus the cap. No breach across the six "
            "mandate-aware dimensions, with deployment normal under "
            "the dominant lens. Verdict reflects a synthesised reading."
        )
        verdict = self._round_trip(payload)
        result = M0PortfolioRiskAnalyticsShim().validate_output(
            verdict, _m0_pra_inputs(),
        )
        assert not result.success
        assert result.error_type == "rule_4_under_quantified_reasoning"

    def test_rule_5_critical_underconfident_fails(self) -> None:
        payload = _m0_pra_valid_payload(overall="critical", confidence=0.6)
        verdict = self._round_trip(payload)
        result = M0PortfolioRiskAnalyticsShim().validate_output(
            verdict, _m0_pra_inputs(),
        )
        assert not result.success
        assert result.error_type == "rule_5_critical_underconfident"

    def test_validate_input_requires_mandate(self) -> None:
        # Provide pre_action so we hit the mandate-missing branch; the
        # shim checks pre_action first.
        bad = AgentInputs(
            case_id="x", case_mode="proposed_action",
            case_intent=None,
            payload={"portfolio_analytics_pre_action": {"metrics": {}}},
        )
        result = M0PortfolioRiskAnalyticsShim().validate_input(bad)
        assert not result.success
        assert result.error_path == ("mandate",)

    def test_validate_input_pa_requires_post_action(self) -> None:
        bad = AgentInputs(
            case_id="x", case_mode="proposed_action",
            case_intent=None,
            payload={
                "mandate": {"x": 1},
                "portfolio_analytics_pre_action": {"metrics": {}},
                # post_action missing
            },
        )
        result = M0PortfolioRiskAnalyticsShim().validate_input(bad)
        assert not result.success
        assert result.error_path == ("portfolio_analytics_post_action",)

    def test_stage_payload_shape(self) -> None:
        payload = _m0_pra_valid_payload()
        verdict = self._round_trip(payload)
        keys = set(verdict.stage_payload.keys())
        assert {
            "concentration_assessment",
            "leverage_assessment",
            "liquidity_assessment",
            "return_quality_assessment",
            "deployment_assessment",
            "cascade_assessment",
            "overall_risk_level",
            "overall_confidence",
        } <= keys


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------


class TestSchemaModels:
    def test_e1_output_round_trips(self) -> None:
        payload = _e1_valid_payload()
        out = E1Output.model_validate(payload)
        assert isinstance(out.verdict, E1Verdict)
        assert isinstance(out.metric_evaluations, E1MetricEvaluations)
        assert isinstance(out.per_stock_framework, E1Framework)
        assert isinstance(out.per_stock_framework.framework_axis, E1FrameworkAxis)
        assert isinstance(out.metric_evaluations.roce, E1Metric)
        kd = out.key_drivers[0]
        assert isinstance(kd, E1KeyDriver)
        assert isinstance(kd.weight, E1DriverWeight)

    def test_e1_output_rejects_unknown_fields(self) -> None:
        payload = _e1_valid_payload()
        payload["bogus"] = 1
        with pytest.raises(Exception):
            E1Output.model_validate(payload)

    def test_m0_pra_output_round_trips(self) -> None:
        payload = _m0_pra_valid_payload()
        out = M0PRAOutput.model_validate(payload)
        assert isinstance(out.overall_risk_level, M0RiskLevel)
        assert isinstance(out.per_dimension_assessment, PerDimensionAssessment)
        dim: DimensionAssessment = out.per_dimension_assessment.concentration
        assert isinstance(dim.verdict_tag, VerdictTag)
        ci: CascadeImplication = out.cascade_implications[0]
        assert isinstance(ci.horizon, CascadeHorizon)
        assert isinstance(ci.severity, CascadeSeverity)
        kd: KeyRiskDriver = out.key_risk_drivers[0]
        assert isinstance(kd.weight, DriverWeight)


# ---------------------------------------------------------------------------
# agents.config
# ---------------------------------------------------------------------------


class TestAgentsConfig:
    def teardown_method(self) -> None:
        agents_config.set_agent_impl_overrides(None)

    def test_default_is_stub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARTHA_REAL_AGENTS", raising=False)
        agents_config.set_agent_impl_overrides(None)
        assert agents_config.get_agent_impl("e1_listed_fundamental_equity") == "stub"
        assert not agents_config.is_real("e1_listed_fundamental_equity")

    def test_env_var_promotes_to_real(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "ARTHA_REAL_AGENTS",
            "e1_listed_fundamental_equity,m0_portfolio_risk_analytics",
        )
        agents_config.set_agent_impl_overrides(None)
        assert agents_config.is_real("e1_listed_fundamental_equity")
        assert agents_config.is_real("m0_portfolio_risk_analytics")
        assert not agents_config.is_real("e2_industry_business")

    def test_test_override_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "ARTHA_REAL_AGENTS",
            "e1_listed_fundamental_equity",
        )
        agents_config.set_agent_impl_overrides(
            {"e1_listed_fundamental_equity": "stub"},
        )
        assert not agents_config.is_real("e1_listed_fundamental_equity")


# ---------------------------------------------------------------------------
# agents.runtime + cases.dispatch routing
# ---------------------------------------------------------------------------


class _FakeCase:
    """Duck-typed case for routing tests (matches the Case ORM surface)."""

    def __init__(
        self,
        *,
        case_id: str = "01HQZTEST00000000000000001",
        case_mode: str = "proposed_action",
        case_intent: str | None = "invest_top_up",
        proposed_action_products: list[str] | None = None,
        proposed_action: str | None = "top up 5L mid-cap",
        dominant_lens: str | None = "growth",
        investor_id: str = "01HQZINV0000000000000000001",
        is_seed_data: bool = False,
        seed_archetype_id: str | None = None,
        applicable_evidence_agents: list[str] | None = None,
    ) -> None:
        self.case_id = case_id
        self.case_mode = case_mode
        self.case_intent = case_intent
        self.proposed_action_products = proposed_action_products or ["RELIANCE"]
        self.proposed_action = proposed_action
        self.dominant_lens = dominant_lens
        self.investor_id = investor_id
        self.is_seed_data = is_seed_data
        self.seed_archetype_id = seed_archetype_id
        self.applicable_evidence_agents = applicable_evidence_agents or []


class TestAgentRuntime:
    def teardown_method(self) -> None:
        agents_runtime.reset_runtime()
        agents_config.set_agent_impl_overrides(None)

    @pytest.mark.asyncio
    async def test_dispatch_real_agent_e1_happy_path(self) -> None:
        body = json.dumps(_e1_valid_payload(ticker="RELIANCE"))
        agents_runtime.set_llm_client(MockLLMClient(responses=[body]))
        out = await agents_runtime.dispatch_real_agent(
            case=_FakeCase(),
            agent_id="e1_listed_fundamental_equity",
            upstream={},
            seed_payload={},
            skill_template_override=_skill_template(
                "e1_listed_fundamental_equity",
            ),
        )
        assert out.agent_id == "e1_listed_fundamental_equity"
        assert out.parsed.structured["ticker"] == "RELIANCE"
        assert out.prompt_version == "e1_listed_fundamental_equity@1.1"

    @pytest.mark.asyncio
    async def test_dispatch_real_agent_no_llm_client_raises(self) -> None:
        agents_runtime.set_llm_client(None)
        with pytest.raises(agents_runtime.RealAgentRuntimeError):
            await agents_runtime.dispatch_real_agent(
                case=_FakeCase(),
                agent_id="e1_listed_fundamental_equity",
                skill_template_override=_skill_template(),
            )

    @pytest.mark.asyncio
    async def test_dispatch_real_agent_unknown_shim(self) -> None:
        agents_runtime.set_llm_client(MockLLMClient(responses=["x"]))
        with pytest.raises(agents_runtime.RealAgentRuntimeError):
            await agents_runtime.dispatch_real_agent(
                case=_FakeCase(),
                agent_id="not_a_real_shim",
                skill_template_override=_skill_template(),
            )

    @pytest.mark.asyncio
    async def test_input_builder_e1_extracts_ticker(self) -> None:
        # The builder is private; exercise via dispatch_real_agent and
        # peek at the call_log.
        client = MockLLMClient(
            responses=[json.dumps(_e1_valid_payload(ticker="HDFCBANK"))],
        )
        agents_runtime.set_llm_client(client)
        await agents_runtime.dispatch_real_agent(
            case=_FakeCase(proposed_action_products=["HDFCBANK"]),
            agent_id="e1_listed_fundamental_equity",
            skill_template_override=_skill_template(
                "e1_listed_fundamental_equity",
            ),
        )
        # Prompt user message should mention the ticker.
        assert "HDFCBANK" in client.call_log[0].user


class TestDispatchAgentRouting:
    def teardown_method(self) -> None:
        agents_runtime.reset_runtime()
        agents_config.set_agent_impl_overrides(None)

    @pytest.mark.asyncio
    async def test_stub_path_when_config_says_stub(self) -> None:
        agents_config.set_agent_impl_overrides(None)
        case = _FakeCase()
        result, telemetry = await cases_dispatch.dispatch_agent(
            case=case,
            agent_id="e1_listed_fundamental_equity",
        )
        assert telemetry is None
        assert result.produced_via != ProducedVia.REAL_AGENT

    @pytest.mark.asyncio
    async def test_real_path_when_config_says_real(self) -> None:
        body = json.dumps(_e1_valid_payload())
        agents_runtime.set_llm_client(MockLLMClient(responses=[body]))
        agents_config.set_agent_impl_overrides(
            {"e1_listed_fundamental_equity": "real"},
        )
        # Override the prompt template loader so we don't need an
        # on-disk skill.md file in the test repo.
        from artha.api_v2.agents import prompt_loader

        def _fake_loader(agent_id: str) -> PromptTemplate:
            return _skill_template(agent_id)

        original = prompt_loader.load_prompt_template
        prompt_loader.load_prompt_template = _fake_loader  # type: ignore[assignment]
        # Also patch the symbol that runtime.py imported at module load.
        agents_runtime.load_prompt_template = _fake_loader  # type: ignore[attr-defined]
        try:
            result, telemetry = await cases_dispatch.dispatch_agent(
                case=_FakeCase(),
                agent_id="e1_listed_fundamental_equity",
            )
        finally:
            prompt_loader.load_prompt_template = original  # type: ignore[assignment]
            agents_runtime.load_prompt_template = original  # type: ignore[attr-defined]

        assert telemetry is not None
        assert telemetry.input_tokens >= 0
        assert result.produced_via == ProducedVia.REAL_AGENT
        # E1 shim's stage payload carries the EvidenceVerdict shape.
        assert "structured_output" in result.payload
        assert "reasoning_summary" in result.payload

    @pytest.mark.asyncio
    async def test_real_path_falls_back_when_no_shim(self) -> None:
        # Config says real but no shim registered → dispatch_agent
        # must fall through to the stub path (safe-rollout guard).
        agents_config.set_agent_impl_overrides(
            {"e2_industry_business": "real"},
        )
        result, telemetry = await cases_dispatch.dispatch_agent(
            case=_FakeCase(),
            agent_id="e2_industry_business",
        )
        assert telemetry is None
        assert result.produced_via != ProducedVia.REAL_AGENT


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_known_shims(self) -> None:
        assert agents_registry.get_shim("e1_listed_fundamental_equity") is not None
        assert agents_registry.get_shim("m0_portfolio_risk_analytics") is not None

    def test_unknown_returns_none(self) -> None:
        assert agents_registry.get_shim("does_not_exist") is None

    def test_list_real_agent_ids(self) -> None:
        ids = agents_registry.list_real_agent_ids()
        assert "e1_listed_fundamental_equity" in ids
        assert "m0_portfolio_risk_analytics" in ids
