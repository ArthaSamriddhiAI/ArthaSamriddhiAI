"""M0.PortfolioRiskAnalytics — cluster 7 chunk 7.3.

Real LLM-using interpretation of cluster 4 PortfolioAnalytics
deterministic outputs into a structured portfolio-level risk verdict.
Per principles §3.8 + cluster 6 chunk 6.5A reframe: this agent owns
the portfolio-level financial-risk rollup; E1 is per-stock only.

No caching (per cluster 7 ideation locked decision): each case carries
unique pre/post-action metric pairs + mandate context, so cache hit
rate would be ~0 and overhead would dominate.

Submodules:
- :mod:`.schema` — :class:`M0PRAOutput` Pydantic model
- :mod:`.shim` — :class:`M0PortfolioRiskAnalyticsShim` implementation
"""

from __future__ import annotations
