"""Cluster 2 — M1 Mandate Management package.

Implements FR Entries 12.0 (overview), 12.1 (constraint specification), and
12.2 (amendment workflow):

- ``models``       — :class:`Mandate` + :class:`MandateVersion` ORM rows.
- ``i0_defaults``  — pure-function mapping of investor enrichment to suggested
  constraint values (FR 12.1 §2.4 + §4.4).
- ``validation``   — cross-constraint hard rules + soft-warning generation
  (FR 12.1 §2.3, §3.3, §4.3, §5.3, §6.3).
- ``service``      — mandate-lifecycle entrypoints: create, read, list,
  amend (chunk 2.3), approve (chunk 2.3).
- ``router``       — REST endpoints under ``/api/v2/...`` (mandate creation +
  read paths in chunks 2.1 / 2.4; amendment paths in chunk 2.3).
- ``schemas``      — Pydantic request/response shapes.
- ``event_names``  — T1 event-name constants (FR 12.0 §6).
"""
