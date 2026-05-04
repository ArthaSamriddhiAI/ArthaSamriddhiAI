"""T1 event-name constants for C0 conversations (FR Entry 14.0 §6).

Each name is a module-level constant so callers don't pass raw strings
around (typos are caught at import time, refs are easy to grep).
"""

from __future__ import annotations

C0_CONVERSATION_STARTED = "c0_conversation_started"
C0_INTENT_DETECTED = "c0_intent_detected"
C0_SLOT_EXTRACTED = "c0_slot_extracted"
C0_STATE_TRANSITIONED = "c0_state_transitioned"
C0_CONVERSATION_COMPLETED = "c0_conversation_completed"
C0_CONVERSATION_ABANDONED = "c0_conversation_abandoned"
C0_LLM_FAILURE = "c0_llm_failure"
