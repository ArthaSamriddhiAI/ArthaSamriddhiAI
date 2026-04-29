"""M0 — the master agent and its sub-agents (Section 8).

Per Thesis 8.1, M0 is the system: every channel speaks to M0 first; every
piece of cross-case institutional cognition lives at M0 or under one of its
seven sub-agents (Router, PortfolioState, IndianContext, Stitcher, Librarian,
Briefer, PortfolioAnalytics).

Pass 6 ships:
  * `Router` — 8-intent classifier (§8.3)
  * `PortfolioState` — semantic data layer (§8.4)

Pass 7 will add IndianContext + Briefer + the clarification protocol.
Phase C will add Stitcher; Phase E will add Librarian.
PortfolioAnalytics shipped in Pass 5 under `artha.portfolio_analysis`.
"""

from artha.m0.briefer import M0Briefer
from artha.m0.clarification import ClarificationCapExceededError, M0ClarificationProtocol
from artha.m0.curated_knowledge import make_default_snapshot
from artha.m0.indian_context import M0IndianContext
from artha.m0.portfolio_state import M0PortfolioState
from artha.m0.router import M0Router

__all__ = [
    "ClarificationCapExceededError",
    "M0Briefer",
    "M0ClarificationProtocol",
    "M0IndianContext",
    "M0PortfolioState",
    "M0Router",
    "make_default_snapshot",
]
