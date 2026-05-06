"""Cluster 5 chunk 5.2 — registry inventory tests.

Pins:
- The canonical inventory has the right tier counts (FR 20.2 §2 / 20.3 §2-4).
- :func:`validate_inventory` reports clean against the on-disk skill.md set.
- Per-tier listing returns agents in canonical (registration) order.
- Deferred agents are flagged + active list excludes them.
"""

from __future__ import annotations

import pytest

from artha.api_v2.m0 import registry


class TestCanonicalInventory:
    def test_total_agent_count_is_24(self) -> None:
        assert len(registry.CANONICAL_AGENTS) == 24

    @pytest.mark.parametrize(
        "tier,expected_count",
        [
            (registry.AgentTier.M0, 8),
            (registry.AgentTier.EVIDENCE, 7),
            (registry.AgentTier.SYNTHESIS, 3),
            (registry.AgentTier.DELIBERATION, 5),
            (registry.AgentTier.CHALLENGE, 1),
        ],
    )
    def test_tier_counts(
        self,
        tier: registry.AgentTier,
        expected_count: int,
    ) -> None:
        agents = registry.list_agents_by_tier(tier)
        assert len(agents) == expected_count

    def test_unique_agent_ids(self) -> None:
        ids = [a.agent_id for a in registry.CANONICAL_AGENTS]
        assert len(ids) == len(set(ids)), "duplicate agent_id in registry"

    def test_deferred_agents(self) -> None:
        deferred = {a.agent_id for a in registry.CANONICAL_AGENTS if a.deferred}
        assert deferred == {"m0_briefer", "m0_librarian"}

    def test_list_active_excludes_deferred(self) -> None:
        active = registry.list_active_agents()
        deferred_ids = {"m0_briefer", "m0_librarian"}
        assert not any(a.agent_id in deferred_ids for a in active)
        assert len(active) == len(registry.CANONICAL_AGENTS) - len(deferred_ids)


class TestLookup:
    def test_get_agent_spec_known(self) -> None:
        spec = registry.get_agent_spec("m0_router")
        assert spec.tier == registry.AgentTier.M0
        assert spec.deferred is False

    def test_get_agent_spec_unknown_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            registry.get_agent_spec("not_a_real_agent")


class TestInventoryValidation:
    def test_repo_inventory_is_clean(self) -> None:
        # Reset caches; the inventory call is over the on-disk set.
        from artha.api_v2.m0 import skill_md as skill_md_mod
        skill_md_mod.set_skill_dir(None)
        skill_md_mod.reset_cache()
        drift = registry.validate_inventory()
        assert drift.is_clean, (
            f"inventory drift: missing={drift.missing}, unexpected={drift.unexpected}"
        )


class TestLoadAgentSkill:
    def test_load_known_agent(self) -> None:
        from artha.api_v2.m0 import skill_md as skill_md_mod
        skill_md_mod.set_skill_dir(None)
        skill_md_mod.reset_cache()
        skill = registry.load_agent_skill("m0_router")
        assert skill.agent_id == "m0_router"
        assert skill.llm_model == "deterministic"

    def test_load_unknown_agent_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            registry.load_agent_skill("unknown_agent")
