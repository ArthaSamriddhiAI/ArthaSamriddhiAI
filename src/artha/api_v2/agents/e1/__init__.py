"""E1 (per-stock listed/fundamental equity) — cluster 7 chunks 7.1 + 7.2.

Real LLM-using implementation of the E1 evidence agent. Per principles
§3.8 + cluster 6 chunk 6.5A reframe: E1 is per-stock fundamental
analysis only; portfolio-level financial-risk rollup lives in
:mod:`artha.api_v2.agents.m0_pra` (M0.PortfolioRiskAnalytics).

Cluster 7.1 ships the shim + Pydantic output schema + 5 semantic
validation rules. Cluster 7.2 wires the cache layer (e1_verdict_cache
table + earnings + manual flag invalidation).

Submodules:

- :mod:`.schema` — :class:`E1Output` Pydantic model + sub-models
- :mod:`.shim` — :class:`E1Shim` implementing
  :class:`AgentShim` for cluster 7
"""

from __future__ import annotations
