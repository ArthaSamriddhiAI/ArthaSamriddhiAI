"""T1 event-name constants for the SmartLLMRouter (FR Entry 16.0 §6 + §7).

Names are re-exported as module-level constants so callers don't pass raw
strings around (typos are caught at import time, refs are easy to grep).

Lifecycle events (one row per LLM call): ``llm_call_initiated``,
``llm_call_completed``, ``llm_call_failed``.

Configuration events: ``llm_provider_configuration_changed``,
``llm_kill_switch_activated``, ``llm_kill_switch_deactivated``.
"""

from __future__ import annotations

# ---- Per-call lifecycle (FR 16.0 §6) ----
LLM_CALL_INITIATED = "llm_call_initiated"
LLM_CALL_COMPLETED = "llm_call_completed"
LLM_CALL_FAILED = "llm_call_failed"

# ---- Config + kill-switch (FR 16.0 §6 + §7) ----
LLM_PROVIDER_CONFIGURATION_CHANGED = "llm_provider_configuration_changed"
LLM_KILL_SWITCH_ACTIVATED = "llm_kill_switch_activated"
LLM_KILL_SWITCH_DEACTIVATED = "llm_kill_switch_deactivated"
