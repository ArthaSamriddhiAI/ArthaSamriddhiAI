"""D0 Snapshot machinery (cluster 3 chunk 3.4 — FR Entry 10.4).

A Snapshot captures the full canonical-entity state at one point in
time as a single content-hashed JSON payload. Audit replay (cluster 15)
will reconstruct any prior state from these rows. Verification
re-serialises the payload and compares hashes — drift between
``content_hash`` and the recomputed hash flips ``verified_status`` to
``verification_failed`` and emits a T1 event.

Submodules:

- :mod:`artha.api_v2.d0.snapshot.service` — create + list + verify + diff
- :mod:`artha.api_v2.d0.snapshot.schemas` — Pydantic read shapes
- :mod:`artha.api_v2.d0.snapshot.router` — ``/api/v2/admin/snapshots``
"""

from __future__ import annotations
