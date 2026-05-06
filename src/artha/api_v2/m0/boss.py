"""M0 boss — orchestrator façade over sub-agents + skill.md registry.

The boss is the *one place* the case-pipeline code (chunks 5.3 / 5.4 /
5.5) calls when it needs:

- the skill.md for an agent (model + prompt + invocation params)
- routing decisions (which evidence agents apply to a case)
- the canonical portfolio-state object
- deterministic concentration analytics
- Indian-context lookups
- stitched markdown for case detail / health report / briefing note

Cluster 5.2 ships the deterministic façade. Cluster 5.4 wires the
stub-layer dispatcher to it (so evidence + synthesis stage outputs
flow through the boss). Cluster 7+ replaces the stub dispatcher with
real LLM calls — the boss surface stays the same.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from artha.api_v2.cases.state_machine import (
    CaseIntent,
    CaseMode,
    DominantLens,
)
from artha.api_v2.m0.registry import (
    AgentSpec,
    AgentTier,
    InventoryDrift,
    get_agent_spec,
    list_active_agents,
    list_agents_by_tier,
    load_agent_skill,
    validate_inventory,
)
from artha.api_v2.m0.skill_md import SkillMd
from artha.api_v2.m0.sub_agents import (
    indian_context as indian_context_mod,
)
from artha.api_v2.m0.sub_agents import (
    portfolio_analytics as analytics_mod,
)
from artha.api_v2.m0.sub_agents import (
    portfolio_state as portfolio_state_mod,
)
from artha.api_v2.m0.sub_agents import (
    router as router_mod,
)
from artha.api_v2.m0.sub_agents import (
    stitcher as stitcher_mod,
)


@dataclass(frozen=True)
class CaseRoutingInput:
    """The minimal subset of a Case row that the router needs.

    Lifted to its own type so chunk 5.3 can construct it from a
    request payload before the Case ORM row exists, and chunk 5.5 can
    construct it from a hydrated Case row.
    """

    case_mode: CaseMode | str
    case_intent: CaseIntent | str | None = None
    dominant_lens: DominantLens | str | None = None
    manual_override: tuple[str, ...] | None = None


class M0Boss:
    """Façade over the M0 sub-agents + skill.md registry."""

    # ------------------------------------------------------------------
    # Skill.md / registry
    # ------------------------------------------------------------------

    def load_skill(self, agent_id: str) -> SkillMd:
        """Return the parsed :class:`SkillMd` for an agent."""
        return load_agent_skill(agent_id)

    def get_agent_spec(self, agent_id: str) -> AgentSpec:
        """Return the static :class:`AgentSpec` for an agent."""
        return get_agent_spec(agent_id)

    def list_agents_by_tier(self, tier: AgentTier) -> list[AgentSpec]:
        """Return every agent in a given tier."""
        return list_agents_by_tier(tier)

    def list_active_agents(self) -> list[AgentSpec]:
        """Return non-deferred agents (the runtime cares about these)."""
        return list_active_agents()

    def validate_inventory(self) -> InventoryDrift:
        """Compare on-disk skill.md set against the registry."""
        return validate_inventory()

    # ------------------------------------------------------------------
    # Sub-agent dispatchers (deterministic)
    # ------------------------------------------------------------------

    def route_evidence_agents(
        self,
        case: CaseRoutingInput,
    ) -> router_mod.RouterDecision:
        """Pick the applicable evidence agents for a case."""
        return router_mod.route(
            case_mode=case.case_mode,
            case_intent=case.case_intent,
            dominant_lens=case.dominant_lens,
            manual_override=case.manual_override,
        )

    def compose_state(
        self,
        holdings: list[portfolio_state_mod.HoldingInput],
        *,
        top_n: int = 10,
    ) -> portfolio_state_mod.PortfolioState:
        """Reduce holdings into the canonical portfolio-state object."""
        return portfolio_state_mod.assemble_state(holdings, top_n=top_n)

    def compute_analytics(
        self,
        state: portfolio_state_mod.PortfolioState,
        *,
        top_n: int = 5,
    ) -> analytics_mod.ConcentrationMetrics:
        """Compute deterministic concentration metrics."""
        return analytics_mod.compute_concentration(state, top_n=top_n)

    def compute_drift_vs_target(
        self,
        state: portfolio_state_mod.PortfolioState,
        targets: dict[str, Decimal],
    ) -> tuple[analytics_mod.AssetClassDeviation, ...]:
        """Per-asset-class deviation from a target allocation."""
        return analytics_mod.compute_drift_vs_target(state, targets)

    def lookup_indian_context(
        self,
        store: str,
        *path_keys: str,
        default: Any = None,
    ) -> Any:
        """Walk into a YAML knowledge store; return value or default."""
        return indian_context_mod.lookup(store, *path_keys, default=default)

    def render_template(self, name: str, context: dict[str, Any]) -> str:
        """Render a stitcher template by short name."""
        return stitcher_mod.render(name, context)


#: Process-wide singleton (cheap; sub-agents are stateless apart from
#: the small load caches they own).
boss = M0Boss()


__all__ = ["CaseRoutingInput", "M0Boss", "boss"]
