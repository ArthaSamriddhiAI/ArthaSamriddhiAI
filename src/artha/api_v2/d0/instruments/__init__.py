"""D0 Instrument canonical entity (cluster 3 chunk 3.2).

The Instrument entity is the foundational catalogue item used by every
downstream consumer that touches portfolios — model portfolios in
cluster 4, holdings in cluster 4, governance in cluster 8, portfolio
analytics in cluster 10. Cluster 3 chunk 3.2 ships the schema, the
SEBI mutual-fund category mapping, and a JSON-fixture-driven adapter
for demo-stage seeding.

Submodules:

- :mod:`artha.api_v2.d0.instruments.models` — :class:`Instrument` ORM
- :mod:`artha.api_v2.d0.instruments.sebi_mapping` — SEBI 46 MF categories
  → ``(asset_class, vehicle_type)`` lookup
- :mod:`artha.api_v2.d0.instruments.schemas` — Pydantic read shapes
- :mod:`artha.api_v2.d0.instruments.service` — query helpers
- :mod:`artha.api_v2.d0.instruments.router` — ``/api/v2/admin/instruments``
"""

from __future__ import annotations
