"""M0 deterministic sub-agents (cluster 5 chunk 5.2).

Five sub-agents, all deterministic Python — no LLM calls. They handle
context-shaping concerns the M0 boss leans on:

- :mod:`.router` — picks the applicable evidence agents per case mode +
  intent (FR Entry 20.2 §3.1).
- :mod:`.portfolio_state` — assembles the portfolio state object the
  evidence + synthesis layers consume (FR Entry 20.2 §3.2).
- :mod:`.indian_context` — looks up entries in the YAML knowledge
  stores under ``config/indian_context/`` (FR Entry 20.2 §3.3).
- :mod:`.stitcher` — renders Jinja2-style templates for case detail,
  health report, briefing note (FR Entry 20.2 §3.4).
- :mod:`.portfolio_analytics` — deterministic concentration / HHI /
  liquidity computations (FR Entry 20.2 §3.5).
"""

from __future__ import annotations
