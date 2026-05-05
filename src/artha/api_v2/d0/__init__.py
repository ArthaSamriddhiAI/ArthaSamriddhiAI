"""Cluster 3 — D0 Data Foundation package.

Implements FR Entries 10.0 through 10.5:

- ``adapter_base``  — :class:`D0Adapter` ABC + :class:`AdapterRunResult`
  + :class:`AdapterHealth` (FR 10.1 §2).
- ``registry``      — process-wide adapter registry; lookup by source id.
- ``models``        — :class:`StagingRecord` + :class:`Snapshot` ORM rows
  (FR 10.2 §2.1, FR 10.4 §2.3).
- ``freshness``     — pure-function freshness status computation +
  threshold lookup (FR 10.5 §2).
- ``event_names``   — D0 T1 event-name constants.
- ``schemas``       — Pydantic shapes for admin endpoints.
- ``service``       — admin-endpoint service helpers (adapter run trigger,
  staging queries).
- ``router``        — REST endpoints under ``/api/v2/admin/...`` for the
  audit role (chunk 3.1 surface; chunks 3.4 add the snapshot UI).

Cluster 3 chunks:
- 3.1 ships the framework: adapter ABC, registry, staging+snapshot tables,
  freshness infrastructure, mandate cash-band revision migration, audit
  admin endpoints (skeleton).
- 3.2 ships the JSONFixtureAdapter loading instruments.
- 3.3 ships the macro+industry context loaders.
- 3.4 ships the snapshot full functionality + freshness UI + demo tool.
"""
