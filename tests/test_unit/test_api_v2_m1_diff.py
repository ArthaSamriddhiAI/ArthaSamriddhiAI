"""Cluster 2 chunk 2.3 — diff + impact-analysis pure-function tests.

Covers FR Entry 12.2 §4.2 + §4.3 — the diff-computation contract that
the CIO's amendment-review surface depends on.
"""

from __future__ import annotations

from datetime import datetime, timezone

from artha.api_v2.m1 import diff as diff_lib
from artha.api_v2.m1.schemas import MandateVersionRead


def _version(**overrides) -> MandateVersionRead:
    base = {
        "version_id": "01ABCVERSIONIDFAKEXX1",
        "mandate_id": "01ABCMANDATEFAKEXX1",
        "version_number": 1,
        "status": "active",
        "equity_min_pct": 50,
        "equity_max_pct": 70,
        "debt_min_pct": 20,
        "debt_max_pct": 40,
        "alternatives_min_pct": 5,
        "alternatives_max_pct": 15,
        "single_position_max_pct": 5,
        "liquidity_floor_pct": 20,
        "sector_max_pct": 25,
        "prohibited_instruments": [],
        "created_at": datetime.now(timezone.utc),
        "created_by": "advisor1",
        "created_via": "form",
        "parent_version_id": None,
        "proposed_at": None,
        "proposed_by": None,
        "approved_at": None,
        "approved_by": None,
        "rejected_at": None,
        "rejected_by": None,
        "rejection_reason": None,
        "approval_comments": None,
        "changes_requested_at": None,
        "changes_requested_by": None,
        "changes_requested_comments": None,
        "activated_at": datetime.now(timezone.utc),
        "archived_at": None,
    }
    base.update(overrides)
    return MandateVersionRead.model_validate(base)


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


class TestComputeDiff:
    def test_identical_versions_produce_empty_diff(self):
        a = _version()
        b = _version()
        d = diff_lib.compute_diff(active=a, proposed=b)
        assert d.is_empty is True
        assert d.numeric_changes == ()
        assert d.prohibited_change.added == ()
        assert d.prohibited_change.removed == ()

    def test_numeric_change_captured(self):
        a = _version()
        b = _version(equity_max_pct=75)
        d = diff_lib.compute_diff(active=a, proposed=b)
        assert d.is_empty is False
        assert len(d.numeric_changes) == 1
        change = d.numeric_changes[0]
        assert change.field == "equity_max_pct"
        assert change.old_value == 70
        assert change.new_value == 75

    def test_multiple_numeric_changes(self):
        a = _version()
        b = _version(equity_max_pct=75, single_position_max_pct=7)
        d = diff_lib.compute_diff(active=a, proposed=b)
        fields = {c.field for c in d.numeric_changes}
        assert fields == {"equity_max_pct", "single_position_max_pct"}

    def test_prohibited_added(self):
        a = _version()
        b = _version(prohibited_instruments=["tobacco stocks"])
        d = diff_lib.compute_diff(active=a, proposed=b)
        assert d.prohibited_change.added == ("tobacco stocks",)
        assert d.prohibited_change.removed == ()

    def test_prohibited_removed(self):
        a = _version(prohibited_instruments=["XYZ Corp"])
        b = _version()
        d = diff_lib.compute_diff(active=a, proposed=b)
        assert d.prohibited_change.removed == ("XYZ Corp",)
        assert d.prohibited_change.added == ()

    def test_prohibited_added_and_removed(self):
        a = _version(prohibited_instruments=["XYZ Corp", "kept"])
        b = _version(prohibited_instruments=["kept", "tobacco stocks"])
        d = diff_lib.compute_diff(active=a, proposed=b)
        assert d.prohibited_change.added == ("tobacco stocks",)
        assert d.prohibited_change.removed == ("XYZ Corp",)


# ---------------------------------------------------------------------------
# Plain-language summary
# ---------------------------------------------------------------------------


class TestSummariseDiff:
    def test_empty_diff_summarises_as_no_changes(self):
        a = _version()
        b = _version()
        diff = diff_lib.compute_diff(active=a, proposed=b)
        assert diff_lib.summarise_diff(diff) == ["No changes"]

    def test_numeric_change_summary_includes_old_and_new(self):
        a = _version()
        b = _version(equity_max_pct=75)
        diff = diff_lib.compute_diff(active=a, proposed=b)
        lines = diff_lib.summarise_diff(diff)
        assert any("70" in line and "75" in line for line in lines)
        assert any("Equity max" in line for line in lines)

    def test_prohibited_added_in_summary(self):
        a = _version()
        b = _version(prohibited_instruments=["tobacco stocks"])
        diff = diff_lib.compute_diff(active=a, proposed=b)
        lines = diff_lib.summarise_diff(diff)
        assert any("tobacco stocks" in line and "Adding" in line for line in lines)

    def test_prohibited_removed_in_summary(self):
        a = _version(prohibited_instruments=["XYZ Corp"])
        b = _version()
        diff = diff_lib.compute_diff(active=a, proposed=b)
        lines = diff_lib.summarise_diff(diff)
        assert any("XYZ Corp" in line and "Removing" in line for line in lines)


# ---------------------------------------------------------------------------
# Impact analysis
# ---------------------------------------------------------------------------


class TestImpactAnalysis:
    def test_empty_diff_yields_empty_structural(self):
        a = _version()
        b = _version()
        diff = diff_lib.compute_diff(active=a, proposed=b)
        impact = diff_lib.build_impact_analysis(diff=diff, proposed=b, active=a)
        assert impact.structural == ()
        assert "version" in impact.activation_summary.lower()

    def test_numeric_change_explained_with_direction(self):
        a = _version()
        b = _version(equity_max_pct=75)  # increasing by 5
        diff = diff_lib.compute_diff(active=a, proposed=b)
        impact = diff_lib.build_impact_analysis(diff=diff, proposed=b, active=a)
        assert any(
            "70%" in s.label and "75%" in s.label and "Equity max" in s.label
            for s in impact.structural
        )
        assert any("increasing" in s.explanation for s in impact.structural)

    def test_decreasing_change_uses_decreasing_word(self):
        a = _version()
        b = _version(equity_max_pct=65)
        diff = diff_lib.compute_diff(active=a, proposed=b)
        impact = diff_lib.build_impact_analysis(diff=diff, proposed=b, active=a)
        assert any("decreasing" in s.explanation for s in impact.structural)

    def test_portfolio_implications_is_cluster_4_placeholder(self):
        a = _version()
        b = _version(equity_max_pct=75)
        diff = diff_lib.compute_diff(active=a, proposed=b)
        impact = diff_lib.build_impact_analysis(diff=diff, proposed=b, active=a)
        assert impact.portfolio_implications.status == "cluster_4_placeholder"
        assert "cluster 4" in impact.portfolio_implications.message

    def test_activation_summary_mentions_proposed_and_active_version_numbers(self):
        a = _version(version_number=2)
        b = _version(version_number=3, equity_max_pct=75)
        diff = diff_lib.compute_diff(active=a, proposed=b)
        impact = diff_lib.build_impact_analysis(diff=diff, proposed=b, active=a)
        assert "version 3" in impact.activation_summary
        assert "version 2" in impact.activation_summary

    def test_prohibited_added_appears_in_structural(self):
        a = _version()
        b = _version(prohibited_instruments=["tobacco stocks"])
        diff = diff_lib.compute_diff(active=a, proposed=b)
        impact = diff_lib.build_impact_analysis(diff=diff, proposed=b, active=a)
        assert any(
            "tobacco stocks" in s.label and "Add" in s.label
            for s in impact.structural
        )

    def test_prohibited_removed_appears_in_structural(self):
        a = _version(prohibited_instruments=["XYZ Corp"])
        b = _version()
        diff = diff_lib.compute_diff(active=a, proposed=b)
        impact = diff_lib.build_impact_analysis(diff=diff, proposed=b, active=a)
        assert any(
            "XYZ Corp" in s.label and "Remove" in s.label
            for s in impact.structural
        )
