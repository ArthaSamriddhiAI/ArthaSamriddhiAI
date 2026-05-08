"""Structural eval harness — cluster 7 chunk 7.4 §1.

Walks every cluster-7 shim through a battery of canned LLM outputs
and checks the rule machinery does what the chunk-7.1/7.3 spec
prescribes. The harness is deterministic + offline (no Anthropic
calls); it's the safety net under the per-rule unit tests so that an
accidental rule regression surfaces in CI as a single failed harness
run rather than a diffuse cluster of unit-test failures.

Each entry in :data:`STRUCTURAL_CASES` declares:

- ``case_id`` — short slug for reporting.
- ``shim`` — :class:`AgentShim` instance under test.
- ``input`` — :class:`AgentInputs` to feed.
- ``llm_output`` — canned JSON string the mock client returns.
- ``expected`` — :class:`HarnessExpectation`: pass / fail-with-error-type /
  warning-with-error-type.

Run the harness:

>>> report = run_structural_eval()
>>> report.all_passed
True
>>> report.failures
()
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from artha.api_v2.agents.e1.shim import E1Shim
from artha.api_v2.agents.llm_client import LLMResponse
from artha.api_v2.agents.m0_pra.shim import M0PortfolioRiskAnalyticsShim
from artha.api_v2.agents.shim import AgentInputs, AgentShim

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HarnessExpectation:
    """What the harness expects to observe for one canned input.

    Three flavours:

    - ``outcome="pass"`` — schema valid, semantic validation passes.
    - ``outcome="fail"`` — schema valid, semantic validation fails with
      ``expected_error_type``.
    - ``outcome="warn"`` — schema valid, semantic validation succeeds
      but emits a warning with ``expected_error_type``.
    - ``outcome="parse_error"`` — schema validation fails (malformed
      JSON or wrong shape).
    """

    outcome: str
    expected_error_type: str | None = None


@dataclass(frozen=True)
class StructuralCase:
    """One harness case."""

    case_id: str
    description: str
    shim: AgentShim
    inputs: AgentInputs
    llm_output: str
    expected: HarnessExpectation


@dataclass(frozen=True)
class HarnessOutcome:
    """Result of running one :class:`StructuralCase`."""

    case_id: str
    description: str
    expected_outcome: str
    expected_error_type: str | None
    actual_outcome: str
    actual_error_type: str | None
    passed: bool


@dataclass(frozen=True)
class HarnessReport:
    """Aggregate result of running all cases."""

    cases: tuple[HarnessOutcome, ...] = ()

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.cases)

    @property
    def failures(self) -> tuple[HarnessOutcome, ...]:
        return tuple(c for c in self.cases if not c.passed)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.cases if c.passed)


# ---------------------------------------------------------------------------
# Shared payload builders
# ---------------------------------------------------------------------------


def _e1_inputs(ticker: str = "RELIANCE") -> AgentInputs:
    return AgentInputs(
        case_id="harness_case",
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


def _e1_payload(
    *,
    ticker: str = "RELIANCE",
    verdict: str = "positive",
    confidence: float = 0.7,
    risk_signals: list[str] | None = None,
    reasoning_words: int = 240,
    axis_value: str = "consumer/IT large-cap value-quality blend",
) -> dict[str, Any]:
    reasoning = f"{ticker} " + " ".join(
        [f"word{i}" for i in range(reasoning_words)],
    )
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
        "key_drivers": [{"driver": "x", "weight": "high"}],
    }


def _m0_pra_inputs(case_mode: str = "proposed_action") -> AgentInputs:
    return AgentInputs(
        case_id="harness_case",
        case_mode=case_mode,
        case_intent="invest_top_up",
        payload={
            "mandate": {
                "concentration_ceiling": {"hhi_at_holding": 0.25},
                "leverage_ceiling": 1.5,
                "liquidity_floor": {"T+0_to_T+30": 0.05},
                "fee_drag_ceiling_bps": 100,
            },
            "portfolio_analytics_pre_action": {
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
            "portfolio_analytics_post_action": {
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
            "evidence_summaries": [],
        },
    )


def _m0_pra_payload(
    *,
    overall: str = "moderate",
    confidence: float = 0.7,
    include_delta: bool = True,
    concentration_tag: str = "clean",
) -> dict[str, Any]:
    delta = "improves -8% post-action" if include_delta else None

    def _dim(reading: str, tag: str = "clean") -> dict[str, Any]:
        d: dict[str, Any] = {"reading": reading, "verdict_tag": tag}
        if delta is not None:
            d["delta_post_action"] = delta
        return d

    return {
        "overall_risk_level": overall,
        "confidence": confidence,
        "per_dimension_assessment": {
            "concentration": _dim("HHI 0.18 within band", concentration_tag),
            "leverage": _dim("leverage 1.1x"),
            "liquidity": _dim("T+0..30 = 12%"),
            "return_quality": _dim("Sharpe 1.4"),
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
            "HHI 0.18 (below ceiling 0.25), leverage 1.1x (below 1.5x), "
            "fee drag 65 bps (below 100). Post-action delta tightens "
            "liquidity by 4 percentage points and trims fee drag 8 bps "
            "across all six dimensions; overall stable verdict."
        ),
        "key_risk_drivers": [{"driver": "x", "weight": "high"}],
    }


# ---------------------------------------------------------------------------
# Canonical case set
# ---------------------------------------------------------------------------


def _build_structural_cases() -> tuple[StructuralCase, ...]:
    e1 = E1Shim()
    m0 = M0PortfolioRiskAnalyticsShim()

    cases: list[StructuralCase] = []

    # ------------------------------------------------------------------
    # E1 — Rule 1 (verdict-risk consistency)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_rule1_clean_positive",
            description="positive verdict with no high-severity signals passes",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(_e1_payload()),
            expected=HarnessExpectation(outcome="pass"),
        ),
    )
    cases.append(
        StructuralCase(
            case_id="e1_rule1_positive_with_promoter_pledge",
            description="positive + promoter pledge fails rule 1",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(
                _e1_payload(
                    risk_signals=["promoter pledge near covenant"],
                ),
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_1_verdict_risk_mismatch",
            ),
        ),
    )

    # ------------------------------------------------------------------
    # E1 — Rule 2 (confidence calibration)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_rule2_high_conf_short_reasoning",
            description="confidence>=0.85 with short reasoning fails rule 2",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(
                _e1_payload(confidence=0.92, reasoning_words=210),
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_2_confidence_underjustified",
            ),
        ),
    )
    cases.append(
        StructuralCase(
            case_id="e1_rule2_high_conf_long_reasoning_ok",
            description="confidence>=0.85 with >=300 words passes",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(
                _e1_payload(confidence=0.9, reasoning_words=320),
            ),
            expected=HarnessExpectation(outcome="pass"),
        ),
    )

    # ------------------------------------------------------------------
    # E1 — Rule 4 (framework axis presence on positive)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_rule4_positive_missing_axis_value",
            description="positive verdict with empty axis_value fails rule 4",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output=json.dumps(_e1_payload(axis_value="")),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_4_missing_framework_axis_value",
            ),
        ),
    )

    # ------------------------------------------------------------------
    # E1 — Rule 5 (ticker mention warning)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_rule5_ticker_missing_warning",
            description="reasoning omits ticker — warning, not failure",
            shim=e1,
            inputs=_e1_inputs("INFY"),
            llm_output=json.dumps(
                {
                    **_e1_payload(),
                    "ticker": "INFY",  # honest ticker
                    "reasoning_summary": " ".join(
                        ["word" for _ in range(220)],
                    ),  # no ticker mention
                },
            ),
            expected=HarnessExpectation(
                outcome="warn",
                expected_error_type="rule_5_ticker_not_in_reasoning_warn",
            ),
        ),
    )

    # ------------------------------------------------------------------
    # M0.PRA — Rule 1 (mandate breach flagging)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="m0_rule1_clean",
            description="metrics in-band, verdict tags clean → pass",
            shim=m0,
            inputs=_m0_pra_inputs(),
            llm_output=json.dumps(_m0_pra_payload()),
            expected=HarnessExpectation(outcome="pass"),
        ),
    )

    # ------------------------------------------------------------------
    # M0.PRA — Rule 3 (PA delta requirement)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="m0_rule3_pa_missing_delta",
            description="proposed_action mode + missing deltas → fail rule 3",
            shim=m0,
            inputs=_m0_pra_inputs(case_mode="proposed_action"),
            llm_output=json.dumps(
                _m0_pra_payload(include_delta=False),
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_3_missing_delta_on_pa",
            ),
        ),
    )
    cases.append(
        StructuralCase(
            case_id="m0_rule3_diagnostic_no_delta_ok",
            description="diagnostic mode → no delta requirement → pass",
            shim=m0,
            inputs=_m0_pra_inputs(case_mode="diagnostic"),
            llm_output=json.dumps(
                _m0_pra_payload(include_delta=False),
            ),
            expected=HarnessExpectation(outcome="pass"),
        ),
    )

    # ------------------------------------------------------------------
    # M0.PRA — Rule 5 (critical confidence calibration)
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="m0_rule5_critical_underconfident",
            description="critical verdict with confidence<0.75 fails rule 5",
            shim=m0,
            inputs=_m0_pra_inputs(),
            llm_output=json.dumps(
                _m0_pra_payload(overall="critical", confidence=0.6),
            ),
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_5_critical_underconfident",
            ),
        ),
    )

    # ------------------------------------------------------------------
    # Schema — malformed JSON
    # ------------------------------------------------------------------
    cases.append(
        StructuralCase(
            case_id="e1_schema_garbage",
            description="non-JSON output → schema parse error",
            shim=e1,
            inputs=_e1_inputs(),
            llm_output="totally not json output",
            expected=HarnessExpectation(outcome="parse_error"),
        ),
    )

    return tuple(cases)


#: Canonical case set the harness exercises. Tests in
#: :mod:`tests.test_unit.test_api_v2_agents_cluster7_eval` pin this.
STRUCTURAL_CASES: tuple[StructuralCase, ...] = _build_structural_cases()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_structural_eval(
    cases: tuple[StructuralCase, ...] | None = None,
) -> HarnessReport:
    """Run every structural case and return a :class:`HarnessReport`.

    Pure / sync; no LLM calls — the canned ``llm_output`` strings are
    handed straight to each shim's :meth:`AgentShim.parse_output` +
    :meth:`AgentShim.validate_output` hooks.
    """
    target = cases if cases is not None else STRUCTURAL_CASES
    outcomes: list[HarnessOutcome] = []
    for c in target:
        outcomes.append(_run_one(c))
    return HarnessReport(cases=tuple(outcomes))


def _run_one(case: StructuralCase) -> HarnessOutcome:
    shim = case.shim

    # Pre-flight input validation — if it fails, record as parse_error
    # (it bubbles up the same place the dispatcher would).
    pre = shim.validate_input(case.inputs)
    if not pre.success:
        actual_outcome = "parse_error"
        actual_error: str | None = pre.error_type
    else:
        try:
            verdict = shim.parse_output(
                LLMResponse(text=case.llm_output),
                case.inputs,
            )
        except Exception:  # noqa: BLE001 — schema / parse failure
            actual_outcome = "parse_error"
            actual_error = None
        else:
            sem = shim.validate_output(verdict, case.inputs)
            if sem.success and sem.error_type is None:
                actual_outcome = "pass"
                actual_error = None
            elif sem.success and sem.error_type is not None:
                actual_outcome = "warn"
                actual_error = sem.error_type
            else:
                actual_outcome = "fail"
                actual_error = sem.error_type

    passed = actual_outcome == case.expected.outcome and (
        case.expected.expected_error_type is None
        or actual_error == case.expected.expected_error_type
    )
    return HarnessOutcome(
        case_id=case.case_id,
        description=case.description,
        expected_outcome=case.expected.outcome,
        expected_error_type=case.expected.expected_error_type,
        actual_outcome=actual_outcome,
        actual_error_type=actual_error,
        passed=passed,
    )


def format_report(report: HarnessReport) -> str:
    """Render a :class:`HarnessReport` as a multi-line string for CLI."""
    lines: list[str] = []
    lines.append(
        f"Cluster 7 structural eval — {report.passed_count}/{report.total} "
        f"passed",
    )
    lines.append("=" * 60)
    for o in report.cases:
        marker = "PASS" if o.passed else "FAIL"
        line = (
            f"{marker:4s}  {o.case_id:42s}  "
            f"expected={o.expected_outcome:10s} "
            f"actual={o.actual_outcome}"
        )
        if o.expected_error_type:
            line += f"  expected_err={o.expected_error_type}"
        if o.actual_error_type and o.actual_error_type != o.expected_error_type:
            line += f"  actual_err={o.actual_error_type}"
        lines.append(line)
    return "\n".join(lines)


__all__ = [
    "STRUCTURAL_CASES",
    "HarnessExpectation",
    "HarnessOutcome",
    "HarnessReport",
    "StructuralCase",
    "format_report",
    "run_structural_eval",
]
