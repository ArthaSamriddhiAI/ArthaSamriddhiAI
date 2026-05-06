"""Agent registry — canonical inventory of cluster-5 agents (FR 20.2 §2).

The registry is a static catalog of every ``agent_id`` that the
cluster-5 case pipeline expects to be authored. It exists for three
reasons:

1. **Discovery for the lookup-stub layer (chunk 5.4).** The stub
   dispatcher iterates the registry to confirm every expected agent
   has a stub registered.
2. **Startup self-check.** :func:`validate_inventory` compares the
   on-disk skill.md set against the canonical list and flags drift.
3. **Documentation.** A grep-able list of which agents exist + which
   tier they belong to.

Tiers mirror FR Entry 20.2 §2 (M0 + evidence agents) and FR Entry 20.3
§2 (synthesis + deliberation + challenge).

Per the cluster-5 chunk plan, three M0 sub-agents are *deferred* —
their skill.md drafts ship in cluster 5.2 but the runtime stays in
stub mode through cluster 6:

- ``m0_briefer`` — briefing-mode synthesis helper, deferred.
- ``m0_librarian`` — citation/retrieval helper, deferred.
- ``m0_execution_planner`` — deferred to cluster 13 (execution).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from artha.api_v2.m0.skill_md import (
    SkillMd,
    list_available_agent_ids,
    load_skill,
)


class AgentTier(str, Enum):
    """Pipeline tier for an agent. Ordering mirrors case-pipeline flow."""

    M0 = "m0"
    EVIDENCE = "evidence"
    SYNTHESIS = "synthesis"
    DELIBERATION = "deliberation"
    CHALLENGE = "challenge"


@dataclass(frozen=True)
class AgentSpec:
    """Static registry entry: agent_id + its tier + deferred flag.

    ``deferred=True`` agents have their skill.md drafted but their
    runtime is stub-only through later clusters — the registry still
    expects the file to exist, but downstream code skips them.
    """

    agent_id: str
    tier: AgentTier
    deferred: bool = False


# ---------------------------------------------------------------------------
# Canonical inventory (24 agents per FR 20.2 / 20.3)
# ---------------------------------------------------------------------------

#: M0 tier — boss + sub-agents. PortfolioRiskAnalytics is M0-tier but
#: also produces a per-case stage row; PortfolioAnalytics serves the
#: synthesis layer with deterministic computations. Briefer / Librarian
#: / ExecutionPlanner are deferred (slim-draft skill.md only).
_M0_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("m0_router", AgentTier.M0),
    AgentSpec("m0_portfolio_state", AgentTier.M0),
    AgentSpec("m0_indian_context", AgentTier.M0),
    AgentSpec("m0_stitcher", AgentTier.M0),
    AgentSpec("m0_portfolio_analytics", AgentTier.M0),
    AgentSpec("m0_portfolio_risk_analytics", AgentTier.M0),
    AgentSpec("m0_briefer", AgentTier.M0, deferred=True),
    AgentSpec("m0_librarian", AgentTier.M0, deferred=True),
)

#: Evidence agents — read snapshot + indian-context, write evidence
#: verdicts. 7 in the cluster-5 inventory.
_EVIDENCE_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("e1_equity_evidence", AgentTier.EVIDENCE),
    AgentSpec("e1_debt_evidence", AgentTier.EVIDENCE),
    AgentSpec("e1_alternatives_evidence", AgentTier.EVIDENCE),
    AgentSpec("e1_macro_evidence", AgentTier.EVIDENCE),
    AgentSpec("e1_sentiment_evidence", AgentTier.EVIDENCE),
    AgentSpec("e1_behavioural_evidence", AgentTier.EVIDENCE),
    AgentSpec("e1_tax_evidence", AgentTier.EVIDENCE),
)

#: Synthesis (S1) — three mode-specific drafters.
_SYNTHESIS_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("s1_case_mode", AgentTier.SYNTHESIS),
    AgentSpec("s1_diagnostic_mode", AgentTier.SYNTHESIS),
    AgentSpec("s1_briefing_mode", AgentTier.SYNTHESIS),
)

#: Deliberation — IC1 chair + member personas + governance gates G1-G3.
#: 5 agents per FR 20.3 §3.
_DELIBERATION_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("ic1_chair", AgentTier.DELIBERATION),
    AgentSpec("ic1_member_quant", AgentTier.DELIBERATION),
    AgentSpec("g1_mandate_gate", AgentTier.DELIBERATION),
    AgentSpec("g2_sebi_regulatory_gate", AgentTier.DELIBERATION),
    AgentSpec("g3_action_filter_gate", AgentTier.DELIBERATION),
)

#: Challenge — A1 advocacy / tear-down. 1 agent per FR 20.3 §4.
_CHALLENGE_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("a1_challenge", AgentTier.CHALLENGE),
)


CANONICAL_AGENTS: tuple[AgentSpec, ...] = (
    *_M0_AGENTS,
    *_EVIDENCE_AGENTS,
    *_SYNTHESIS_AGENTS,
    *_DELIBERATION_AGENTS,
    *_CHALLENGE_AGENTS,
)

#: Lookup map for O(1) agent_id resolution.
_BY_ID: dict[str, AgentSpec] = {a.agent_id: a for a in CANONICAL_AGENTS}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_agent_spec(agent_id: str) -> AgentSpec:
    """Return the static :class:`AgentSpec` for an agent_id.

    Raises :class:`KeyError` for unknown agent_ids.
    """
    return _BY_ID[agent_id]


def list_agents_by_tier(tier: AgentTier) -> list[AgentSpec]:
    """Return all agents in a tier, in canonical (registration) order."""
    return [a for a in CANONICAL_AGENTS if a.tier == tier]


def list_active_agents() -> list[AgentSpec]:
    """Return non-deferred agents (the runtime cares about these)."""
    return [a for a in CANONICAL_AGENTS if not a.deferred]


def load_agent_skill(agent_id: str) -> SkillMd:
    """Validate ``agent_id`` is in the registry, then load its skill.md."""
    if agent_id not in _BY_ID:
        raise KeyError(
            f"agent_id {agent_id!r} is not in the cluster-5 canonical "
            f"inventory.",
        )
    return load_skill(agent_id)


@dataclass(frozen=True)
class InventoryDrift:
    """Output of :func:`validate_inventory`: missing + unexpected files."""

    missing: tuple[str, ...]
    unexpected: tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        return not self.missing and not self.unexpected


def validate_inventory() -> InventoryDrift:
    """Compare on-disk skill.md set against :data:`CANONICAL_AGENTS`.

    ``missing``: agents in the registry without an on-disk skill.md.
    ``unexpected``: skill.md files on disk for agent_ids not in the
    registry. Either is a sign of drift; the application should fail
    fast at startup.
    """
    expected = {a.agent_id for a in CANONICAL_AGENTS}
    found = set(list_available_agent_ids())
    missing = tuple(sorted(expected - found))
    unexpected = tuple(sorted(found - expected))
    return InventoryDrift(missing=missing, unexpected=unexpected)


__all__ = [
    "CANONICAL_AGENTS",
    "AgentSpec",
    "AgentTier",
    "InventoryDrift",
    "get_agent_spec",
    "list_active_agents",
    "list_agents_by_tier",
    "load_agent_skill",
    "validate_inventory",
]
