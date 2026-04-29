"""§10 — channel layer: C0 (conversational) + N0 (notification).

Public surface:
  * `ConversationalChannel` (C0, §10.1) — LLM-backed inbound parser.
  * `NotificationChannel` (N0, §10.2) — deterministic alert lifecycle.
  * `ClientDirectory` — minimal in-memory protocol C0 calls for entity resolution.
"""

from artha.channels.canonical_c0 import (
    C0LLMUnavailableError,
    ClientDirectory,
    ConversationalChannel,
    InMemoryClientDirectory,
)
from artha.channels.canonical_n0 import NotificationChannel

__all__ = [
    "C0LLMUnavailableError",
    "ClientDirectory",
    "ConversationalChannel",
    "InMemoryClientDirectory",
    "NotificationChannel",
]
