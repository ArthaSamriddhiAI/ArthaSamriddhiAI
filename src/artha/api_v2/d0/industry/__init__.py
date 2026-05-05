"""D0 IndustryReport canonical entity (cluster 3 chunk 3.3).

An IndustryReport is a structured snapshot of analyst commentary on an
industry sector for a given reporting period. Cluster 3 ships the core
schema (outlook + summary + drivers + risks + themes) used by future
clusters' case orchestration (cluster 5+) and governance gate
(cluster 8) for sector-cap context.

Submodules:

- :mod:`artha.api_v2.d0.industry.models` — :class:`IndustryReport` ORM
- :mod:`artha.api_v2.d0.industry.schemas` — Pydantic read shapes
- :mod:`artha.api_v2.d0.industry.service` — query + upsert helpers
- :mod:`artha.api_v2.d0.industry.router` — ``/api/v2/admin/industry-reports``
"""

from __future__ import annotations
