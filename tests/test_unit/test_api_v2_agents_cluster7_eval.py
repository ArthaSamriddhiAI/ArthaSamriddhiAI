"""Cluster 7 chunk 7.4 — structural eval harness + rubric tests.

Pins:

- :func:`harness.run_structural_eval` reports every canonical case
  passed (regression net for the per-rule unit tests).
- :func:`harness.format_report` renders a multi-line summary.
- The rubric ships exactly 8 cases, half per agent, four criteria
  each (160-point total).
- :func:`rubric.render_rubric_markdown` is well-formed (every case
  surfaces a section + a criteria table).
"""

from __future__ import annotations

import pytest

from artha.api_v2.agents.eval.harness import (
    STRUCTURAL_CASES,
    HarnessExpectation,
    StructuralCase,
    format_report,
    run_structural_eval,
)
from artha.api_v2.agents.eval.rubric import (
    RUBRIC_CASES,
    render_rubric_markdown,
)


class TestHarness:
    def test_canonical_cases_all_pass(self) -> None:
        report = run_structural_eval()
        assert report.all_passed, (
            "Canonical structural cases regressed: "
            f"{[(o.case_id, o.actual_outcome, o.actual_error_type) for o in report.failures]}"
        )

    def test_minimum_case_coverage(self) -> None:
        # At least 11 canonical cases (chunk 7.4 §1.2: cover every
        # cluster-7 rule + a couple of schema regressions).
        assert len(STRUCTURAL_CASES) >= 11

    def test_each_rule_has_at_least_one_failure_case(self) -> None:
        # Every error_type the harness expects to fire must be exercised.
        expected_errors = {
            c.expected.expected_error_type
            for c in STRUCTURAL_CASES
            if c.expected.expected_error_type
        }
        # Spot-check: a representative E1 + M0.PRA failure each.
        assert any("rule_1" in e for e in expected_errors)
        assert any("rule_3" in e for e in expected_errors)
        assert any("rule_5" in e for e in expected_errors)

    def test_format_report_mentions_pass_count(self) -> None:
        report = run_structural_eval()
        text = format_report(report)
        assert f"{report.passed_count}/{report.total} passed" in text
        assert "PASS" in text

    def test_run_with_explicit_cases_subset(self) -> None:
        # Pass a single case explicitly — the runner must respect the
        # narrow input (used for CI bisection on regressions).
        single = (STRUCTURAL_CASES[0],)
        report = run_structural_eval(cases=single)
        assert report.total == 1

    def test_failure_in_explicit_case_surfaces(self) -> None:
        # Build a deliberately-broken expectation and verify the runner
        # tags it as a failure (defensive).
        broken = StructuralCase(
            case_id="broken_pin",
            description="claims pass but rule 4 will fire",
            shim=STRUCTURAL_CASES[0].shim,  # E1Shim
            inputs=STRUCTURAL_CASES[0].inputs,
            llm_output=STRUCTURAL_CASES[4].llm_output,  # rule 4 trip
            expected=HarnessExpectation(outcome="pass"),
        )
        report = run_structural_eval(cases=(broken,))
        assert not report.all_passed
        assert report.failures[0].case_id == "broken_pin"


class TestRubric:
    def test_eight_cases(self) -> None:
        assert len(RUBRIC_CASES) == 8

    def test_balanced_per_agent(self) -> None:
        from collections import Counter

        agents = Counter(c.agent_id for c in RUBRIC_CASES)
        assert agents["e1_listed_fundamental_equity"] == 4
        assert agents["m0_portfolio_risk_analytics"] == 4

    def test_four_criteria_each(self) -> None:
        assert all(len(c.review_criteria) == 4 for c in RUBRIC_CASES)

    def test_unique_case_ids(self) -> None:
        ids = [c.case_id for c in RUBRIC_CASES]
        assert len(ids) == len(set(ids))

    def test_markdown_round_trip_includes_all_cases(self) -> None:
        md = render_rubric_markdown()
        for case in RUBRIC_CASES:
            assert case.case_id in md
            assert case.expected_verdict_summary in md
            for crit in case.review_criteria:
                assert crit.label in md
        # Final scoring scaffold present.
        assert "**Grand total /160**" in md
        assert "Reviewer name + date:" in md

    @pytest.mark.parametrize(
        "expected_substring",
        [
            "rubric_e1_quality_compounder",
            "rubric_e1_audit_qualification_red_flag",
            "rubric_m0_concentration_breach",
            "rubric_m0_liquidity_floor_breach",
        ],
    )
    def test_markdown_includes_signature_cases(
        self, expected_substring: str,
    ) -> None:
        md = render_rubric_markdown()
        assert expected_substring in md
