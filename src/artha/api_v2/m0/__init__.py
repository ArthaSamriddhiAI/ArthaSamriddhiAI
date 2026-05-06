"""M0 framework — cluster 5 chunk 5.2.

M0 is the *reasoning manager*: the boss agent that orchestrates the case
pipeline, plus a small set of deterministic sub-agents that own
context-shaping concerns (routing, portfolio state assembly, Indian
context lookup, stitching, deterministic analytics).

Submodules:

- :mod:`artha.api_v2.m0.skill_md` — skill.md front-matter parser +
  loader + validator + hot-reloader. Per FR Entry 20.2 §10.3, every
  agent's prompt + invocation parameters live in a markdown file under
  ``config/skills/`` with YAML front-matter. The application reads
  them at startup; dev mode hot-reload bumps the cache and emits a
  :data:`artha.api_v2.cases.event_names.SKILL_MD_HOT_RELOADED` event.
- :mod:`artha.api_v2.m0.event_names` — m0-specific T1 event constants.
- :mod:`artha.api_v2.m0.registry` — agent registry: SkillMD lookup +
  invocation policy (model, tokens, temperature) per ``agent_id``.
- :mod:`artha.api_v2.m0.boss` — M0 orchestrator stub. Cluster 5.2
  ships the lookup-driven shell; cluster 7+ wires it to the real
  evidence + synthesis agents.
- :mod:`artha.api_v2.m0.sub_agents` — deterministic sub-agents:
  router, portfolio_state, indian_context, stitcher,
  portfolio_analytics.

Cluster 5.2 ships everything as a *deterministic shell* — the LLM
plumbing exists but every call resolves through the lookup-stub layer
(chunk 5.4) until cluster 7 swaps in real model calls. The sub-agents
that don't need an LLM (router, portfolio_state, indian_context,
stitcher, portfolio_analytics) are real today.
"""

from __future__ import annotations
