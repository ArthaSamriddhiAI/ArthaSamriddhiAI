"""Cluster 1 chunk 1.3 — SmartLLMRouter package.

Implements FR Entry 16.0:

- ``models``      — :class:`LLMProviderConfig` ORM (the singleton settings row).
- ``encryption``  — Fernet wrap/unwrap for API keys at rest (FR 16.0 §4.1).
- ``providers/``  — Mistral + Claude adapters (FR 16.0 §3).
- ``router_runtime`` — :class:`SmartLLMRouter` executor (rate limit + retry +
  timeout + kill switch + telemetry, FR 16.0 §5–§7).
- ``service``     — config + kill-switch CRUD called from the FastAPI surface.
- ``router``      — REST endpoints under ``/api/v2/llm/...`` (chunk 1.3 scope).
- ``event_names`` — T1 event-name constants emitted by the router runtime.
- ``schemas``     — Pydantic request/response shapes for the surface above.
"""
