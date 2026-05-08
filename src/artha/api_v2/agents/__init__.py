"""Real LLM-using agent runtime — cluster 7 onward (FR Entry 20.3 §4.2).

Cluster 5 + 6 ran every agent through the lookup-stub layer (cluster 6
seeded enriched content; cluster 5 placeholder content for non-seeded
cases). Cluster 7 introduces the substrate for *real* LLM-using
implementations: a per-agent shim framework, a prompt template loader,
an LLM client wrapper (with mock support for CI), and Pydantic output
schemas for structural validation.

The first two real agents land in cluster 7:

- E1 (per-stock listed/fundamental equity) — chunks 7.1 + 7.2
- M0.PortfolioRiskAnalytics — chunk 7.3

The remaining 14 stub-served agents (E2-E7, S1, IC1, A1, etc.) keep
running on cluster 6 enriched seed content until their per-agent
clusters land (8-12).

Submodules:

- :mod:`.shim` — :class:`AgentShim` ABC + base classes + lifecycle hooks
- :mod:`.prompt_loader` — skill.md body extraction + placeholder
  substitution
- :mod:`.llm_client` — Anthropic SDK wrapper with retry policy + mock
  client for tests
- :mod:`.schema_validation` — JSON-shape validation (Pydantic-backed)
- :mod:`.config` — per-agent stub/real toggle (defaults to all-stub so
  the demo flow stays fast/free)
- :mod:`.event_names` — 5 cluster-7 T1 event constants
- :mod:`.e1` — E1 listed-fundamental-equity shim + Pydantic schema
- :mod:`.m0_pra` — M0.PortfolioRiskAnalytics shim + Pydantic schema

Cluster 7.2 will add cache persistence (e1_verdict_cache table, manual
flag service); cluster 7.4 adds the eval harness. This stage 1 ships
the substrate + the two shims with no caching (default mode is
``stub`` for all agents — flipping to ``real`` is opt-in via config).
"""

from __future__ import annotations
