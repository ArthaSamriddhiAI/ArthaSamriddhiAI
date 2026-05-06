"""Cluster 5 chunk 5.2 — M0 boss façade tests.

Pins:
- Boss exposes the right surface (load_skill, route, compose_state,
  compute_analytics, lookup_indian_context, render_template).
- Each method delegates to the underlying sub-agent / registry.
- Singleton ``boss`` is importable.
"""

from __future__ import annotations

from decimal import Decimal

from artha.api_v2.cases.state_machine import CaseMode
from artha.api_v2.m0 import boss as boss_mod
from artha.api_v2.m0.registry import AgentTier
from artha.api_v2.m0.sub_agents.portfolio_state import HoldingInput


class TestM0Boss:
    def test_singleton_importable(self) -> None:
        assert isinstance(boss_mod.boss, boss_mod.M0Boss)

    def test_load_skill_via_boss(self) -> None:
        from artha.api_v2.m0 import skill_md
        skill_md.set_skill_dir(None)
        skill_md.reset_cache()
        skill = boss_mod.boss.load_skill("m0_router")
        assert skill.agent_id == "m0_router"

    def test_get_agent_spec(self) -> None:
        spec = boss_mod.boss.get_agent_spec("a1_challenge")
        assert spec.tier == AgentTier.CHALLENGE

    def test_list_agents_by_tier(self) -> None:
        m0_agents = boss_mod.boss.list_agents_by_tier(AgentTier.M0)
        ids = {a.agent_id for a in m0_agents}
        assert "m0_router" in ids and "m0_briefer" in ids

    def test_route_evidence_agents(self) -> None:
        decision = boss_mod.boss.route_evidence_agents(
            boss_mod.CaseRoutingInput(case_mode=CaseMode.PROPOSED_ACTION),
        )
        assert decision.applicable_evidence_agents
        assert decision.reason == "mode=proposed_action"

    def test_compose_state(self) -> None:
        holdings = [
            HoldingInput(
                instrument_id="X",
                asset_class="equity",
                sector="IT",
                market_value_inr=Decimal("100"),
                allocation_pct=Decimal("100"),
            ),
        ]
        state = boss_mod.boss.compose_state(holdings)
        assert state.total_value_inr == Decimal("100")
        assert state.holding_count == 1

    def test_compute_analytics(self) -> None:
        holdings = [
            HoldingInput(
                instrument_id="X",
                asset_class="equity",
                sector="IT",
                market_value_inr=Decimal("100"),
                allocation_pct=Decimal("100"),
            ),
        ]
        state = boss_mod.boss.compose_state(holdings)
        metrics = boss_mod.boss.compute_analytics(state)
        assert metrics.hhi == Decimal("10000")

    def test_lookup_indian_context(self) -> None:
        from artha.api_v2.m0.sub_agents import indian_context
        indian_context.set_context_dir(None)
        indian_context.reset_cache()
        rate = boss_mod.boss.lookup_indian_context(
            "tax_matrix", "asset_classes", "equity_listed", "ltcg_rate_pct",
        )
        assert rate == 12.5

    def test_validate_inventory(self) -> None:
        from artha.api_v2.m0 import skill_md
        skill_md.set_skill_dir(None)
        skill_md.reset_cache()
        drift = boss_mod.boss.validate_inventory()
        assert drift.is_clean

    def test_render_template(self) -> None:
        from artha.api_v2.m0.sub_agents import stitcher
        stitcher.set_stitcher_dir(None)
        stitcher.reset_cache()
        # Use the briefing_note template — small enough that we can sanity-check.
        out = boss_mod.boss.render_template(
            "briefing_note",
            {
                "investor": {"name": "Test Inv"},
                "advisor_name": "Adv",
                "meeting_date": "2026-05-01",
                "case": {"case_id": "abc"},
                "briefing": {
                    "headline": "All good.",
                    "talking_points": [],
                    "recent_changes": [],
                    "client_concerns_to_address": [],
                    "recommended_questions_to_ask": [],
                },
                "portfolio_state": {
                    "total_value_inr": "100",
                    "top_positions": [{"instrument_id": "X", "allocation_pct": "100"}],
                },
            },
        )
        assert "Test Inv" in out
        assert "All good." in out
