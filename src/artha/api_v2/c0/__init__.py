"""Cluster 1 chunk 1.2 — C0 Conversational Orchestrator package.

Implements FR Entry 14.0:

- ``models``         — :class:`Conversation` + :class:`Message` ORM rows.
- ``state_machine``  — pure-Python FSM driving the investor_onboarding flow
  (FR 14.0 §2.4); no LLM in transitions, only at extraction points.
- ``prompts``        — loader for the skill.md prompt templates (intent +
  slot extraction; FR 14.0 §2.3).
- ``llm_client``     — wraps :class:`SmartLLMRouter` with C0-shaped helpers
  (intent detection, slot extraction, JSON parsing, fallback signals).
- ``service``        — turn-level entrypoints (start, post_message, get,
  list, abandon-stale) called from the FastAPI surface.
- ``router``         — REST endpoints under ``/api/v2/conversations/...``.
- ``schemas``        — Pydantic request/response shapes.
- ``event_names``    — T1 event-name constants (FR 14.0 §6).
"""
