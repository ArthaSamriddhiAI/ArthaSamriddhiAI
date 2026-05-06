"""M2 Model Portfolio (cluster 4).

The model portfolio is the firm-level template that defines which
instruments are appropriate for which client profiles (the *tagging*
layer) and which specific instruments the firm prefers to deploy as
default recommendations (the *preferred portfolio* layer).

Two layers, different scopes:

- **Tagging (FR Entry 13.1)** — every Instrument carries one or more
  cell-identifier tags from the 9-element ``(risk_profile, horizon)``
  enum. Tagging is exhaustive: 1300+ instruments all tagged.
- **Preferred portfolio (FR Entry 13.2)** — a curated short list per
  cell, structured as ``PreferredPortfolioEntry`` rows with
  ``core / satellite / optional`` roles plus rank ordering. Cluster 4's
  default ships ~60-100 entries across 9 cells.

Submodules:

- :mod:`artha.api_v2.m2.cells` — the 9-cell enum + (risk_profile,
  horizon) ↔ cell-identifier helpers
- :mod:`artha.api_v2.m2.default_tags` — default tag rules per SEBI
  category, vehicle type, market cap rank
- :mod:`artha.api_v2.m2.default_loader` — startup loader that applies
  default tags + loads the JSON fixture's preferred portfolio entries
- :mod:`artha.api_v2.m2.models` — :class:`PreferredPortfolioEntry` ORM
- :mod:`artha.api_v2.m2.schemas` — Pydantic read shapes
- :mod:`artha.api_v2.m2.service` — query + write helpers
- :mod:`artha.api_v2.m2.router` — ``/api/v2/model-portfolio/...``
"""

from __future__ import annotations
