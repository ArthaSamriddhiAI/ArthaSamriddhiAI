"""Per-agent stub-vs-real implementation toggle (chunk 7.1 §12.3).

Cluster 5+6 ran every agent through the lookup-stub layer. Cluster 7
introduces real LLM-using implementations of two agents (E1,
M0.PortfolioRiskAnalytics) — the rest stay stubbed until clusters
8-12. To avoid burning API tokens during the demo flow + tests, the
default per-agent implementation is ``stub`` for *every* agent
including E1 + M0.PortfolioRiskAnalytics.

To opt-in to the real shim runtime:

- Tests: pass ``override_impls={"e1_listed_fundamental_equity": "real"}``
  to :func:`set_agent_impl_overrides`.
- Production: set ``ARTHA_REAL_AGENTS=e1_listed_fundamental_equity,m0_portfolio_risk_analytics``
  before app start.

Invalid values are logged but coerced back to ``stub`` so the demo
flow stays safe under misconfiguration.
"""

from __future__ import annotations

import os
from typing import Literal

AgentImpl = Literal["stub", "real"]

#: Test-only override map. Higher-priority than env var when set.
_OVERRIDES: dict[str, AgentImpl] | None = None


def set_agent_impl_overrides(overrides: dict[str, AgentImpl] | None) -> None:
    """Test helper: pin specific agent_ids to ``stub`` or ``real``.

    Pass ``None`` to clear.
    """
    global _OVERRIDES
    _OVERRIDES = dict(overrides) if overrides else None


def _env_real_set() -> set[str]:
    """Return the set of agent_ids the env var marks ``real``."""
    raw = os.environ.get("ARTHA_REAL_AGENTS", "").strip()
    if not raw:
        return set()
    return {agent_id.strip() for agent_id in raw.split(",") if agent_id.strip()}


def get_agent_impl(agent_id: str) -> AgentImpl:
    """Return ``"stub"`` (default) or ``"real"`` for ``agent_id``.

    Resolution order:
    1. Test override (highest priority).
    2. ``ARTHA_REAL_AGENTS`` env var (production opt-in).
    3. Default ``"stub"``.
    """
    if _OVERRIDES is not None and agent_id in _OVERRIDES:
        return _OVERRIDES[agent_id]
    if agent_id in _env_real_set():
        return "real"
    return "stub"


def is_real(agent_id: str) -> bool:
    """Convenience predicate."""
    return get_agent_impl(agent_id) == "real"


__all__ = [
    "AgentImpl",
    "get_agent_impl",
    "is_real",
    "set_agent_impl_overrides",
]
