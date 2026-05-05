"""D0 MacroSnapshot canonical entity (cluster 3 chunk 3.3).

A MacroSnapshot is a point-in-time capture of macroeconomic indicators
(GDP, CPI, repo rate, 10y yield, FX) for one country in one period.
Cluster 3 ships an India-focused indicator set; future clusters can
extend the schema to cover regional / global indicators per consumer
needs.

Submodules:

- :mod:`artha.api_v2.d0.macro.models` — :class:`MacroSnapshot` ORM
- :mod:`artha.api_v2.d0.macro.schemas` — Pydantic read shapes
- :mod:`artha.api_v2.d0.macro.service` — query + upsert helpers
- :mod:`artha.api_v2.d0.macro.router` — ``/api/v2/admin/macro-snapshots``
"""

from __future__ import annotations
