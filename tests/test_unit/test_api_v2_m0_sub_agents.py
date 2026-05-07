"""Cluster 5 chunk 5.2 — M0 sub-agent unit tests.

Coverage: router, portfolio_state, indian_context, stitcher,
portfolio_analytics. Each is deterministic and exercised through pure
inputs.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from artha.api_v2.cases.state_machine import CaseIntent, CaseMode, DominantLens
from artha.api_v2.m0.sub_agents import (
    indian_context,
    portfolio_analytics,
    portfolio_state,
    router,
    stitcher,
)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class TestRouter:
    def test_proposed_action_default(self) -> None:
        decision = router.route(case_mode=CaseMode.PROPOSED_ACTION)
        assert decision.applicable_evidence_agents[0] == "e1_listed_fundamental_equity"
        # All 7 evidence agents in proposed_action mode.
        assert len(decision.applicable_evidence_agents) == 7
        assert decision.reason == "mode=proposed_action"

    def test_diagnostic_drops_alternatives_and_tax(self) -> None:
        decision = router.route(case_mode=CaseMode.DIAGNOSTIC)
        assert "e6_pms_aif_sif" not in decision.applicable_evidence_agents
        assert "e7_mutual_fund" not in decision.applicable_evidence_agents

    def test_briefing_minimal_set(self) -> None:
        # Cluster 6 reframe: briefing runs the lightest evidence layer
        # (E3 macro/policy/news + E4 behavioural/historical) per FR 20.3
        # cluster 6 revision; briefing is operational meeting prep.
        decision = router.route(case_mode=CaseMode.BRIEFING)
        assert decision.applicable_evidence_agents == (
            "e3_macro_policy_news",
            "e4_behavioural_historical",
        )

    def test_intent_overlay_adds_tax(self) -> None:
        decision = router.route(
            case_mode=CaseMode.DIAGNOSTIC,
            case_intent=CaseIntent.TAX_LOSS_HARVESTING,
        )
        assert "e7_mutual_fund" in decision.applicable_evidence_agents
        assert "intent=tax_loss_harvesting" in decision.reason

    def test_lens_overlay_dedupes(self) -> None:
        decision = router.route(
            case_mode=CaseMode.PROPOSED_ACTION,
            dominant_lens=DominantLens.PORTFOLIO_SHIFT,
        )
        # behavioural already in proposed_action default, must not duplicate.
        count = decision.applicable_evidence_agents.count("e4_behavioural_historical")
        assert count == 1

    def test_manual_override(self) -> None:
        decision = router.route(
            case_mode=CaseMode.PROPOSED_ACTION,
            manual_override=("e1_listed_fundamental_equity", "e7_mutual_fund"),
        )
        assert decision.applicable_evidence_agents == (
            "e1_listed_fundamental_equity",
            "e7_mutual_fund",
        )
        assert decision.reason == "manual_override"

    def test_string_inputs_accepted(self) -> None:
        decision = router.route(
            case_mode="proposed_action",
            case_intent="tax_loss_harvesting",
        )
        assert "e7_mutual_fund" in decision.applicable_evidence_agents


# ---------------------------------------------------------------------------
# Portfolio state
# ---------------------------------------------------------------------------


def _holding(
    instrument_id: str,
    asset_class: str,
    sector: str | None,
    value: str,
    pct: str,
) -> portfolio_state.HoldingInput:
    return portfolio_state.HoldingInput(
        instrument_id=instrument_id,
        asset_class=asset_class,
        sector=sector,
        market_value_inr=Decimal(value),
        allocation_pct=Decimal(pct),
    )


class TestPortfolioState:
    def test_empty_holdings(self) -> None:
        state = portfolio_state.assemble_state([])
        assert state.total_value_inr == Decimal("0")
        assert state.holding_count == 0
        assert state.asset_class_slices == ()
        assert state.top_positions == ()

    def test_aggregation_basic(self) -> None:
        holdings = [
            _holding("INF", "equity", "IT", "1000000", "40"),
            _holding("HDFC", "equity", "Banking", "500000", "20"),
            _holding("GSEC10Y", "debt", None, "1000000", "40"),
        ]
        state = portfolio_state.assemble_state(holdings)
        assert state.total_value_inr == Decimal("2500000")
        assert state.holding_count == 3
        # equity slice = 60% > debt 40%
        assert state.asset_class_slices[0].asset_class == "equity"
        assert state.asset_class_slices[0].allocation_pct == Decimal("60")
        # Sector slice excludes None.
        sectors = [s.sector for s in state.sector_slices]
        assert "IT" in sectors and "Banking" in sectors and None not in sectors

    def test_top_positions_sorted_desc(self) -> None:
        holdings = [
            _holding("A", "equity", "X", "100", "5"),
            _holding("B", "equity", "X", "1000", "50"),
            _holding("C", "equity", "X", "500", "30"),
        ]
        state = portfolio_state.assemble_state(holdings, top_n=2)
        assert [p.instrument_id for p in state.top_positions] == ["B", "C"]

    def test_unknown_asset_class_buckets_to_other(self) -> None:
        state = portfolio_state.assemble_state(
            [_holding("X", "weird_class", None, "100", "100")],
        )
        assert state.asset_class_slices[0].asset_class == "other"


# ---------------------------------------------------------------------------
# Portfolio analytics
# ---------------------------------------------------------------------------


class TestPortfolioAnalytics:
    def test_concentration_empty(self) -> None:
        state = portfolio_state.assemble_state([])
        metrics = portfolio_analytics.compute_concentration(state)
        assert metrics.hhi == Decimal("0")
        assert metrics.top_n_share_pct == Decimal("0")

    def test_concentration_single_position(self) -> None:
        state = portfolio_state.assemble_state(
            [_holding("X", "equity", "IT", "100", "100")],
        )
        metrics = portfolio_analytics.compute_concentration(state)
        # HHI = 100^2 = 10000
        assert metrics.hhi == Decimal("10000")
        assert metrics.max_single_position_pct == Decimal("100")

    def test_drift_vs_target(self) -> None:
        holdings = [
            _holding("A", "equity", None, "100", "70"),
            _holding("B", "debt", None, "100", "30"),
        ]
        state = portfolio_state.assemble_state(holdings)
        targets = {"equity": Decimal("60"), "debt": Decimal("40")}
        deviations = portfolio_analytics.compute_drift_vs_target(state, targets)
        eq_dev = next(d for d in deviations if d.asset_class == "equity")
        db_dev = next(d for d in deviations if d.asset_class == "debt")
        assert eq_dev.deviation_pct == Decimal("10")
        assert db_dev.deviation_pct == Decimal("-10")

    def test_cumulative_share(self) -> None:
        result = portfolio_analytics.cumulative_share(
            [Decimal("10"), Decimal("20"), Decimal("30")],
        )
        assert result == (Decimal("10"), Decimal("30"), Decimal("60"))


# ---------------------------------------------------------------------------
# Indian context
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_indian_context_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    indian_context.set_context_dir(tmp_path)
    yield tmp_path
    indian_context.set_context_dir(None)


class TestIndianContext:
    def test_load_known_store(self, tmp_indian_context_dir: Path) -> None:
        (tmp_indian_context_dir / "tax_matrix.yaml").write_text(
            "asset_classes:\n  equity_listed:\n    ltcg_rate_pct: 12.5\n",
            encoding="utf-8",
        )
        store = indian_context.load_knowledge_store("tax_matrix")
        assert store.payload["asset_classes"]["equity_listed"]["ltcg_rate_pct"] == 12.5

    def test_unknown_store_raises(self) -> None:
        with pytest.raises(indian_context.IndianContextError):
            indian_context.load_knowledge_store("not_a_real_store")

    def test_missing_file_raises(self, tmp_indian_context_dir: Path) -> None:
        with pytest.raises(indian_context.IndianContextMissingError):
            indian_context.load_knowledge_store("tax_matrix")

    def test_lookup_dot_traversal(self, tmp_indian_context_dir: Path) -> None:
        (tmp_indian_context_dir / "tax_matrix.yaml").write_text(
            "asset_classes:\n  equity_listed:\n    ltcg_rate_pct: 12.5\n",
            encoding="utf-8",
        )
        rate = indian_context.lookup(
            "tax_matrix", "asset_classes", "equity_listed", "ltcg_rate_pct",
        )
        assert rate == 12.5

    def test_lookup_missing_returns_default(
        self,
        tmp_indian_context_dir: Path,
    ) -> None:
        (tmp_indian_context_dir / "tax_matrix.yaml").write_text(
            "asset_classes: {}\n",
            encoding="utf-8",
        )
        v = indian_context.lookup(
            "tax_matrix", "missing", "key", default="fallback",
        )
        assert v == "fallback"

    def test_repo_stores_load(self) -> None:
        indian_context.set_context_dir(None)
        indian_context.reset_cache()
        try:
            for name in indian_context.KNOWN_KNOWLEDGE_STORES:
                store = indian_context.load_knowledge_store(name)
                assert store.payload, f"{name} payload empty"
        finally:
            indian_context.reset_cache()


# ---------------------------------------------------------------------------
# Stitcher
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_stitcher_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    stitcher.set_stitcher_dir(tmp_path)
    yield tmp_path
    stitcher.set_stitcher_dir(None)


class TestStitcher:
    def test_simple_var_substitution(self, tmp_stitcher_dir: Path) -> None:
        (tmp_stitcher_dir / "case_detail.md").write_text(
            "Hello, {{ name }}!", encoding="utf-8",
        )
        out = stitcher.render("case_detail", {"name": "world"})
        assert out == "Hello, world!"

    def test_dot_traversal(self, tmp_stitcher_dir: Path) -> None:
        (tmp_stitcher_dir / "health_report.md").write_text(
            "{{ a.b.c }}", encoding="utf-8",
        )
        out = stitcher.render("health_report", {"a": {"b": {"c": "x"}}})
        assert out == "x"

    def test_missing_key_marker(self, tmp_stitcher_dir: Path) -> None:
        (tmp_stitcher_dir / "briefing_note.md").write_text(
            "{{ absent }}", encoding="utf-8",
        )
        out = stitcher.render("briefing_note", {})
        assert out == "[unknown:absent]"

    def test_for_loop(self, tmp_stitcher_dir: Path) -> None:
        (tmp_stitcher_dir / "case_detail.md").write_text(
            "{% for x in xs %}- {{ x.name }}\n{% endfor %}",
            encoding="utf-8",
        )
        out = stitcher.render(
            "case_detail",
            {"xs": [{"name": "a"}, {"name": "b"}]},
        )
        assert "- a" in out and "- b" in out

    def test_unknown_template_raises(self) -> None:
        with pytest.raises(stitcher.StitcherError):
            stitcher.render("not_a_template", {})

    def test_missing_template_raises(self, tmp_stitcher_dir: Path) -> None:
        with pytest.raises(stitcher.StitcherTemplateMissingError):
            stitcher.render("case_detail", {})

    def test_repo_templates_load(self) -> None:
        stitcher.set_stitcher_dir(None)
        stitcher.reset_cache()
        try:
            for name in stitcher.KNOWN_TEMPLATES:
                tpl = stitcher.load_template(name)
                assert tpl.body, f"{name} body empty"
        finally:
            stitcher.reset_cache()
