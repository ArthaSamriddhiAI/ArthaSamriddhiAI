"""C0-shaped wrapper around :class:`SmartLLMRouter`.

C0's two LLM call sites — intent detection and slot extraction — both
need: (a) a templated prompt, (b) JSON-mode response, (c) parsed-and-
validated structured output, (d) a reliable failure signal so the FSM
can fall back to template mode.

This module turns those four needs into two helpers
(:func:`detect_intent`, :func:`extract_slots`) that hide the SmartLLMRouter
plumbing from the service layer.

Per FR Entry 14.0 §5:
- LLM unavailable / non-configured / kill-switched → :class:`LLMFallback`.
- LLM responds but JSON is malformed → :class:`LLMFallback` with
  ``failure_type="malformed_response"``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.c0 import prompts
from artha.api_v2.llm.providers import LLMCallRequest
from artha.api_v2.llm.router_runtime import (
    LLMCallFailedError,
    LLMKillSwitchActiveError,
    LLMNotConfiguredError,
    SmartLLMRouter,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntentDetectionResult:
    intent: str
    extracted_fields: dict[str, Any]
    llm_provider: str
    llm_latency_ms: int
    skill_version: str = prompts.SKILL_VERSION


@dataclass(frozen=True)
class SlotExtractionResult:
    extracted_fields: dict[str, Any]
    extraction_confidence: str  # "high" | "medium" | "low"
    llm_provider: str
    llm_latency_ms: int
    skill_version: str = prompts.SKILL_VERSION


@dataclass(frozen=True)
class LLMFallback:
    """Returned in place of an LLM result when the call cannot proceed.

    The service layer translates this into:

    1. A user-visible message ("Conversational understanding is temporarily
       unavailable; please respond with a single value to each question.")
    2. A ``c0_llm_failure`` T1 event.
    3. Single-field templated prompts for the remainder of the conversation.
    """

    failure_type: str  # "not_configured" | "kill_switch" | "auth" | ...
    detail: str


IntentResult = IntentDetectionResult | LLMFallback
SlotResult = SlotExtractionResult | LLMFallback


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


CALLER_INTENT = "c0_intent_detector"
CALLER_SLOT = "c0_slot_extractor"


async def detect_intent(
    *,
    db: AsyncSession,
    router: SmartLLMRouter,
    user_message: str,
) -> IntentResult:
    """Run the cluster 1 intent-detection prompt and parse the JSON reply."""
    prompt = prompts.render_intent_prompt(user_message=user_message)
    try:
        response = await router.call(
            db,
            LLMCallRequest(
                caller_id=CALLER_INTENT,
                prompt=prompt,
                response_format="json",
                temperature=0.0,
                max_tokens=512,
            ),
        )
    except LLMNotConfiguredError as exc:
        return LLMFallback(failure_type="not_configured", detail=str(exc))
    except LLMKillSwitchActiveError as exc:
        return LLMFallback(failure_type="kill_switch", detail=str(exc))
    except LLMCallFailedError as exc:
        return LLMFallback(failure_type=exc.failure_type, detail=str(exc))

    parsed = _safe_load_json(response.content)
    if parsed is None:
        return LLMFallback(
            failure_type="malformed_response",
            detail="LLM did not return valid JSON for intent detection",
        )

    intent = str(parsed.get("intent") or "general_question")
    fields = parsed.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        fields = {}

    return IntentDetectionResult(
        intent=intent,
        extracted_fields=_coerce_field_types(fields),
        llm_provider=response.provider,
        llm_latency_ms=response.latency_ms,
    )


async def extract_slots(
    *,
    db: AsyncSession,
    router: SmartLLMRouter,
    user_response: str,
    current_prompt: str,
    expected_fields: list[str],
) -> SlotResult:
    """Run the cluster 1 slot-extraction prompt and parse the JSON reply."""
    prompt = prompts.render_slot_prompt(
        user_response=user_response,
        current_prompt=current_prompt,
        expected_fields=expected_fields,
    )
    try:
        response = await router.call(
            db,
            LLMCallRequest(
                caller_id=CALLER_SLOT,
                prompt=prompt,
                response_format="json",
                temperature=0.0,
                max_tokens=512,
            ),
        )
    except LLMNotConfiguredError as exc:
        return LLMFallback(failure_type="not_configured", detail=str(exc))
    except LLMKillSwitchActiveError as exc:
        return LLMFallback(failure_type="kill_switch", detail=str(exc))
    except LLMCallFailedError as exc:
        return LLMFallback(failure_type=exc.failure_type, detail=str(exc))

    parsed = _safe_load_json(response.content)
    if parsed is None:
        return LLMFallback(
            failure_type="malformed_response",
            detail="LLM did not return valid JSON for slot extraction",
        )

    fields = parsed.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        fields = {}

    confidence = str(parsed.get("extraction_confidence") or "medium").lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    return SlotExtractionResult(
        extracted_fields=_coerce_field_types(fields),
        extraction_confidence=confidence,
        llm_provider=response.provider,
        llm_latency_ms=response.latency_ms,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_load_json(content: str) -> dict[str, Any] | None:
    """Parse ``content`` as JSON; return ``None`` on any failure.

    Handles two real-world degraded shapes:
    1. A model that wraps the JSON in markdown fences despite the system
       prompt forbidding them (Claude does this occasionally).
    2. Trailing/leading whitespace.
    """
    text = content.strip()
    if text.startswith("```"):
        # Strip a fenced block; tolerate "```json\n..." or "```\n...".
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("C0 LLM response was not valid JSON: %r", content[:200])
        return None
    return loaded if isinstance(loaded, dict) else None


def _coerce_field_types(fields: dict[str, Any]) -> dict[str, Any]:
    """Apply the obvious type coercions before handing fields to the FSM.

    The Pydantic input schema validates everything strictly later (via the
    investor-creation service); this normalisation is just so common LLM
    quirks don't need to be re-handled at every call site.
    """
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None or value == "":
            continue
        if key == "age":
            try:
                out["age"] = int(value)
            except (TypeError, ValueError):
                continue
        elif key in ("risk_appetite", "time_horizon"):
            out[key] = str(value).strip().lower().replace(" ", "_")
        elif isinstance(value, str):
            out[key] = value.strip()
        else:
            out[key] = value
    return out
