"""Real-shim registry — cluster 7 chunk 7.1 §3.

Maps each ``agent_id`` to its :class:`AgentShim` instance. Cluster 7
ships shims for E1 + M0.PortfolioRiskAnalytics; clusters 8-12 add
the remaining 14 agents.

Stub-served agents (no entry here) keep running on the cluster-5/6
lookup-stub layer; the runtime falls through to that path when
:func:`get_shim` returns ``None``.
"""

from __future__ import annotations

from artha.api_v2.agents.e1.shim import E1Shim
from artha.api_v2.agents.e2_sector_view.shim import E2SectorViewShim
from artha.api_v2.agents.e2_stock_in_sector.shim import E2StockInSectorShim
from artha.api_v2.agents.e3_macro_view.shim import E3MacroViewShim
from artha.api_v2.agents.e3_news_scanner.shim import E3NewsScannerShim
from artha.api_v2.agents.e7_mutual_fund.shim import E7MutualFundShim
from artha.api_v2.agents.m0_pra.shim import M0PortfolioRiskAnalyticsShim
from artha.api_v2.agents.shim import AgentShim

# Singleton shims — instantiated at import. Per-call shim methods are
# pure (no mutable state) so a single instance per agent suffices.
_SHIMS: dict[str, AgentShim] = {
    # Cluster 7
    "e1_listed_fundamental_equity": E1Shim(),
    "m0_portfolio_risk_analytics": M0PortfolioRiskAnalyticsShim(),
    # Cluster 8
    "e3_macro_view": E3MacroViewShim(),
    "e2_sector_view": E2SectorViewShim(),
    "e2_stock_in_sector": E2StockInSectorShim(),
    "e7_mutual_fund": E7MutualFundShim(),
    "e3_news_scanner": E3NewsScannerShim(),
}


def get_shim(agent_id: str) -> AgentShim | None:
    """Return the registered :class:`AgentShim` for ``agent_id``, else None.

    A return value of ``None`` means the agent runs on the legacy
    lookup-stub layer (clusters 5/6).
    """
    return _SHIMS.get(agent_id)


def list_real_agent_ids() -> list[str]:
    """Return the agent_ids for which a real shim is registered."""
    return sorted(_SHIMS.keys())


def register_shim(agent_id: str, shim: AgentShim) -> None:
    """Test-only / extension-point: register a new shim at runtime.

    Production code adds shims via the import-time block above.
    """
    _SHIMS[agent_id] = shim


def unregister_shim(agent_id: str) -> None:
    """Test helper: drop a shim registration."""
    _SHIMS.pop(agent_id, None)


__all__ = [
    "get_shim",
    "list_real_agent_ids",
    "register_shim",
    "unregister_shim",
]
