"""Cluster 8 structural eval harness + rubric tests.

Pins:
- run_cluster8_structural_eval() reports all canonical C8 cases passed.
- STRUCTURAL_CASES_CLUSTER8 has ≥12 cases.
- RUBRIC_CASES_CLUSTER8 has exactly 10 cases (2 per agent).
- render_rubric_cluster8_markdown is well-formed.
"""

from __future__ import annotations

from collections import Counter

import pytest

from artha.api_v2.agents.eval.harness import (
    STRUCTURAL_CASES_CLUSTER8,
    HarnessExpectation,
    StructuralCase,
    format_report,
    run_cluster8_structural_eval,
    run_structural_eval,
)
from artha.api_v2.agents.eval.rubric import (
    RUBRIC_CASES_CLUSTER8,
    render_rubric_cluster8_markdown,
)

# ---------------------------------------------------------------------------
# TestCluster8Harness
# ---------------------------------------------------------------------------


class TestCluster8Harness:
    def test_canonical_cases_all_pass(self) -> None:
        report = run_cluster8_structural_eval()
        assert report.all_passed, (
            "Cluster-8 structural cases regressed: "
            + str(
                [
                    (o.case_id, o.actual_outcome, o.actual_error_type)
                    for o in report.failures
                ]
            )
        )

    def test_minimum_case_coverage(self) -> None:
        assert len(STRUCTURAL_CASES_CLUSTER8) >= 12

    def test_each_rule_has_failure_case(self) -> None:
        # Spot-check: confirm error types from each of the 5 shims are present.
        error_types = {
            c.expected.expected_error_type
            for c in STRUCTURAL_CASES_CLUSTER8
            if c.expected.expected_error_type
        }
        # E3.MacroView
        assert any(
            "regime_name" in e or "quantitative_grounding" in e
            for e in error_types
        )
        # E2.SectorView
        assert any("verdict_cycle_stage" in e for e in error_types)
        # E2.StockInSector
        assert any(
            "generic_ranking_framework" in e or "quartile_mismatch" in e
            for e in error_types
        )
        # E7.MutualFund
        assert any(
            "capacity_signal" in e or "verdict_signals" in e
            for e in error_types
        )
        # E3.NewsScanner
        assert any("high_materiality" in e for e in error_types)

    def test_format_report_mentions_pass_count(self) -> None:
        report = run_cluster8_structural_eval()
        text = format_report(report)
        # format_report uses the cluster-7 header string; just verify structure
        assert str(report.passed_count) in text
        assert str(report.total) in text

    def test_run_with_explicit_cases_subset(self) -> None:
        single = (STRUCTURAL_CASES_CLUSTER8[0],)
        report = run_cluster8_structural_eval(cases=single)
        assert report.total == 1

    def test_failure_surfaces_correctly(self) -> None:
        # Take a known-pass case and flip the expectation to "fail" →
        # the runner should report it as not passed.
        pass_case = next(
            c
            for c in STRUCTURAL_CASES_CLUSTER8
            if c.expected.outcome == "pass"
        )
        broken = StructuralCase(
            case_id="broken_c8_pin",
            description="wrong expectation to confirm failure detection",
            shim=pass_case.shim,
            inputs=pass_case.inputs,
            llm_output=pass_case.llm_output,
            expected=HarnessExpectation(
                outcome="fail",
                expected_error_type="rule_99_nonexistent",
            ),
        )
        report = run_cluster8_structural_eval(cases=(broken,))
        assert not report.all_passed
        assert len(report.failures) == 1

    def test_cluster8_cases_do_not_interfere_with_cluster7(self) -> None:
        # Cluster-7 harness should still pass unchanged after adding C8
        report = run_structural_eval()
        assert report.all_passed, (
            "Cluster-7 cases regressed after C8 additions: "
            + str(
                [
                    (o.case_id, o.actual_outcome, o.actual_error_type)
                    for o in report.failures
                ]
            )
        )

    def test_all_c8_cases_have_unique_case_ids(self) -> None:
        ids = [c.case_id for c in STRUCTURAL_CASES_CLUSTER8]
        assert len(ids) == len(set(ids))

    def test_pass_and_fail_cases_both_present(self) -> None:
        outcomes = {c.expected.outcome for c in STRUCTURAL_CASES_CLUSTER8}
        assert "pass" in outcomes
        assert "fail" in outcomes


# ---------------------------------------------------------------------------
# TestCluster8Rubric
# ---------------------------------------------------------------------------

# The 5 expected C8 agent IDs (must appear in exactly 2 cases each).
_C8_AGENTS = {
    "e3_macro_view",
    "e2_sector_view",
    "e2_stock_in_sector",
    "e7_mutual_fund",
    "e3_news_scanner",
}


class TestCluster8Rubric:
    def test_ten_cases(self) -> None:
        assert len(RUBRIC_CASES_CLUSTER8) == 10

    def test_balanced_per_agent(self) -> None:
        counts = Counter(c.agent_id for c in RUBRIC_CASES_CLUSTER8)
        for agent in _C8_AGENTS:
            assert counts[agent] == 2, (
                f"Expected 2 cases for {agent}, got {counts[agent]}"
            )

    def test_four_criteria_each(self) -> None:
        for case in RUBRIC_CASES_CLUSTER8:
            assert len(case.review_criteria) == 4, (
                f"Case {case.case_id} has {len(case.review_criteria)} "
                f"criteria (expected 4)"
            )

    def test_unique_case_ids(self) -> None:
        ids = [c.case_id for c in RUBRIC_CASES_CLUSTER8]
        assert len(ids) == len(set(ids))

    def test_markdown_round_trip_includes_all_cases(self) -> None:
        md = render_rubric_cluster8_markdown()
        for case in RUBRIC_CASES_CLUSTER8:
            assert case.case_id in md, (
                f"case_id {case.case_id!r} not found in rendered markdown"
            )

    def test_markdown_grand_total_200(self) -> None:
        md = render_rubric_cluster8_markdown()
        assert "**Grand total /200**" in md

    def test_markdown_has_criteria_tables(self) -> None:
        md = render_rubric_cluster8_markdown()
        # Each case should have a criteria table header
        assert md.count("| # | Label | Description") == 10

    def test_markdown_has_subtotal_lines(self) -> None:
        md = render_rubric_cluster8_markdown()
        assert md.count("**Subtotal /20**") == 10

    def test_all_criteria_labels_unique_within_agent(self) -> None:
        # Within each case, criterion labels must be unique
        for case in RUBRIC_CASES_CLUSTER8:
            labels = [c.label for c in case.review_criteria]
            assert len(labels) == len(set(labels)), (
                f"Duplicate criterion labels in case {case.case_id}"
            )

    def test_each_criterion_has_non_empty_description(self) -> None:
        for case in RUBRIC_CASES_CLUSTER8:
            for crit in case.review_criteria:
                assert crit.description.strip(), (
                    f"Empty description for criterion {crit.label!r} "
                    f"in case {case.case_id}"
                )

    @pytest.mark.parametrize(
        "agent_id",
        sorted(_C8_AGENTS),
    )
    def test_parametrized_each_agent_has_two_cases(
        self, agent_id: str
    ) -> None:
        matching = [
            c for c in RUBRIC_CASES_CLUSTER8 if c.agent_id == agent_id
        ]
        assert len(matching) == 2, (
            f"Expected 2 rubric cases for {agent_id}, got {len(matching)}"
        )

    def test_cluster8_rubric_does_not_collide_with_cluster7(self) -> None:
        from artha.api_v2.agents.eval.rubric import RUBRIC_CASES

        c7_ids = {c.case_id for c in RUBRIC_CASES}
        c8_ids = {c.case_id for c in RUBRIC_CASES_CLUSTER8}
        assert not c7_ids & c8_ids, (
            f"Collision between C7 and C8 case IDs: {c7_ids & c8_ids}"
        )
