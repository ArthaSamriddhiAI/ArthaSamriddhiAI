"""Concrete D0 adapters (cluster 3 chunk 3.2 onwards).

Cluster 3 chunk 3.2 ships :class:`JSONFixtureAdapter` — the
demo-stage adapter that loads instruments from a JSON fixture file or
in-memory dict. Chunks 3.3 will add macro / industry section adapters
that share the same fixture mechanism. Cluster 17 introduces the live
HTTP-backed adapters.
"""

from __future__ import annotations
