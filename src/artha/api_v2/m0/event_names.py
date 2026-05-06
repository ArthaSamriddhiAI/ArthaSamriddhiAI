"""T1 event-name constants for M0 framework (cluster 5 chunk 5.2).

Per FR Entry 20.2 §10 (skill.md mechanism) + Principles §3.4.
"""

from __future__ import annotations

# Re-export the cases module's hot-reload event so M0 callers don't
# import across module boundaries for it.
from artha.api_v2.cases.event_names import SKILL_MD_HOT_RELOADED

# ---------------------------------------------------------------------------
# Skill.md lifecycle events
# ---------------------------------------------------------------------------

SKILL_MD_LOADED = "skill_md_loaded"
SKILL_MD_VALIDATION_FAILED = "skill_md_validation_failed"

# ---------------------------------------------------------------------------
# Sub-agent invocation events (deterministic sub-agents emit these)
# ---------------------------------------------------------------------------

M0_ROUTER_DISPATCHED = "m0_router_dispatched"
M0_PORTFOLIO_STATE_ASSEMBLED = "m0_portfolio_state_assembled"
M0_INDIAN_CONTEXT_LOOKUP = "m0_indian_context_lookup"
M0_STITCHER_RENDERED = "m0_stitcher_rendered"
M0_PORTFOLIO_ANALYTICS_COMPUTED = "m0_portfolio_analytics_computed"

__all__ = [
    "M0_INDIAN_CONTEXT_LOOKUP",
    "M0_PORTFOLIO_ANALYTICS_COMPUTED",
    "M0_PORTFOLIO_STATE_ASSEMBLED",
    "M0_ROUTER_DISPATCHED",
    "M0_STITCHER_RENDERED",
    "SKILL_MD_HOT_RELOADED",
    "SKILL_MD_LOADED",
    "SKILL_MD_VALIDATION_FAILED",
]
