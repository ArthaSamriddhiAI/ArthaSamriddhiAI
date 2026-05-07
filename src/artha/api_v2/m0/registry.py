"""Agent registry — canonical inventory (FR 20.2 §2 + FR 20.3 cluster 6 revision).

The registry is a static catalog of every ``agent_id`` that the
case pipeline expects to be authored. It exists for three reasons:

1. **Discovery for the lookup-stub layer.** The stub dispatcher
   iterates the registry to confirm every expected agent has a stub
   registered.
2. **Startup self-check.** :func:`validate_inventory` compares the
   on-disk skill.md set against the canonical list and flags drift.
3. **Documentation.** A grep-able list of which agents exist + which
   tier they belong to.

Cluster 6 architectural changes (per FR 20.3 cluster 6 revision §3):

- E1 reframed to per-stock listed/fundamental equity; portfolio-level
  financial risk extracted to ``m0_portfolio_risk_analytics``.
- Evidence agents renumbered: e1-e7 are now distinct numbered agents
  (E1 listed equity, E2 industry/business, E3 macro/policy/news,
  E4 behavioural/historical, E5 unlisted equity, E6 PMS/AIF/SIF, E7 MF).
  Cluster 5's ``e1_*`` family (debt / alternatives / sentiment / tax) is
  superseded.
- IC1 expanded from 2 sub-agents (chair + member_quant) to 5
  (chair + devils_advocate + risk_assessor + minutes_recorder +
  counterfactual_engine) per FR 20.1 §6.
- ``m0_boss`` added (was a Python class in cluster 5; now also an LLM
  agent with skill.md per FR 20.2 §3.1).
- Governance gates (G1/G2/G3) remain in registry but are deterministic
  Python checks — no skill.md drafts in cluster 6 inventory.
- Removed: ``m0_briefer`` / ``m0_librarian`` / ``m0_portfolio_state`` /
  ``m0_portfolio_analytics`` / ``ic1_member_quant`` / cluster-5
  ``e1_*`` family. Deterministic sub-agents (portfolio_state +
  portfolio_analytics) live in :mod:`artha.api_v2.m0.sub_agents` as
  Python classes; they don't need skill.md.
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

#: M0 tier — boss + LLM-using sub-agents. Cluster 6 introduces
#: ``m0_boss`` as its own LLM agent (was a Python class in cluster 5);
#: ``m0_portfolio_state`` + ``m0_portfolio_analytics`` are deterministic
#: Python sub-agents and intentionally absent from this list (no
#: skill.md needed).
_M0_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("m0_boss", AgentTier.M0),
    AgentSpec("m0_router", AgentTier.M0),
    AgentSpec("m0_indian_context", AgentTier.M0),
    AgentSpec("m0_stitcher", AgentTier.M0),
    AgentSpec("m0_portfolio_risk_analytics", AgentTier.M0),
)

#: Evidence agents — read snapshot + indian-context, write evidence
#: verdicts. 7 in the cluster-6 inventory per FR 20.3 cluster 6
#: revision §3 (corrected numbering vs cluster 5).
_EVIDENCE_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("e1_listed_fundamental_equity", AgentTier.EVIDENCE),
    AgentSpec("e2_industry_business", AgentTier.EVIDENCE),
    AgentSpec("e3_macro_policy_news", AgentTier.EVIDENCE),
    AgentSpec("e4_behavioural_historical", AgentTier.EVIDENCE),
    AgentSpec("e5_unlisted_equity", AgentTier.EVIDENCE),
    AgentSpec("e6_pms_aif_sif", AgentTier.EVIDENCE),
    AgentSpec("e7_mutual_fund", AgentTier.EVIDENCE),
)

#: Synthesis (S1) — three mode-specific drafters.
_SYNTHESIS_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("s1_case_mode", AgentTier.SYNTHESIS),
    AgentSpec("s1_diagnostic_mode", AgentTier.SYNTHESIS),
    AgentSpec("s1_briefing_mode", AgentTier.SYNTHESIS),
)

#: Deliberation — IC1 has 5 sub-roles per FR 20.1 §6 cluster 6
#: revision. Governance gates G1/G2/G3 are deterministic Python
#: checks (no skill.md), tracked here as ``deferred=True`` so the
#: registry knows they exist for stub-layer dispatch but the loader
#: doesn't expect on-disk skill.md files.
_DELIBERATION_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("ic1_chair", AgentTier.DELIBERATION),
    AgentSpec("ic1_devils_advocate", AgentTier.DELIBERATION),
    AgentSpec("ic1_risk_assessor", AgentTier.DELIBERATION),
    AgentSpec("ic1_minutes_recorder", AgentTier.DELIBERATION),
    AgentSpec("ic1_counterfactual_engine", AgentTier.DELIBERATION),
    AgentSpec("g1_mandate_gate", AgentTier.DELIBERATION, deferred=True),
    AgentSpec("g2_sebi_regulatory_gate", AgentTier.DELIBERATION, deferred=True),
    AgentSpec("g3_action_filter_gate", AgentTier.DELIBERATION, deferred=True),
)

#: Challenge — A1 advocacy / tear-down.
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

    Deferred agents (governance gates G1/G2/G3 in cluster 6) are
    excluded from ``missing`` because they're deterministic Python
    checks and have no skill.md drafts. They DO still belong in the
    registry so the dispatcher knows about them.

    ``missing``: non-deferred agents in the registry without an on-disk
    skill.md.
    ``unexpected``: skill.md files on disk for agent_ids not in the
    registry.
    """
    expected = {a.agent_id for a in CANONICAL_AGENTS if not a.deferred}
    deferred_ids = {a.agent_id for a in CANONICAL_AGENTS if a.deferred}
    found = set(list_available_agent_ids())
    missing = tuple(sorted(expected - found))
    # Don't count deferred agents as "unexpected" — they may or may not
    # have skill.md files on disk, but either way they're known.
    unexpected = tuple(sorted(found - expected - deferred_ids))
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
