"""Cluster 7 chunk 7.4 — agent evaluation framework.

Two layers of eval per chunk plan §4:

- :mod:`.harness` — *structural* validation harness. Runs each shim
  through canned LLM outputs and checks every semantic rule fires
  correctly (positive + negative paths). Sync / deterministic;
  produces a :class:`HarnessReport` callers can pretty-print or roll
  into CI gates.
- :mod:`.rubric` — *manual review* rubric. Defines 8 hand-curated
  cases that exercise the corner cases an analyst should sanity-check
  by reading the LLM's verdict. Output is a markdown rendering of
  the cases + scoring criteria; analysts run the cases through real
  Anthropic, score them, and append rationale in the rubric.

Cluster 7.4 will add a third layer (regression bench against the
23-case cohort with the locked-prompt LLM) once cluster 8+ ships
the upstream M0 portfolio_state outputs the M0.PRA shim depends on.
"""

from __future__ import annotations
