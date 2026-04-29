"""Section 8.3 — M0.Router: the canonical 8-intent classifier.

Behaviour per §8.3:

  * If the inbound channel pre-tagged the event with high confidence
    (`pre_tag_confidence >= HIGH_PRE_TAG_CONFIDENCE`), the Router confirms
    without an LLM call.
  * Otherwise the Router classifies via the LLM provider with a disciplined
    prompt that surfaces the 8-type taxonomy and the inbound payload. It
    requests a structured `M0RouterClassification` response.
  * If the LLM-emitted confidence is below `LOW_CONFIDENCE_THRESHOLD`, the
    Router emits `clarification_required=True` so the channel can surface
    a clarifying prompt.
  * If the LLM service is unavailable, the Router falls back to the channel
    pre-tag with reduced confidence (Section 8.3.7); if no pre-tag, it
    surfaces clarification.

Outputs are structured `M0RouterOutput` per Section 15.6.2 carrying
`run_mode` (Thesis 4.2 plumbing) and `routing_metadata` for downstream consumers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from artha.canonical.m0_router import (
    M0RouterClassification,
    M0RouterInput,
    M0RouterOutput,
)
from artha.common.types import CaseIntent, RunMode
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

# Pre-tag confidence at or above this is treated as canonical and confirmed
# without an LLM call. Lower pre-tags or missing pre-tags trigger LLM classification.
HIGH_PRE_TAG_CONFIDENCE = 0.85

# LLM-emitted confidence below this triggers a clarification request.
LOW_CONFIDENCE_THRESHOLD = 0.50

# Reduced confidence applied when falling back to channel pre-tag because LLM
# service is unavailable (Section 8.3.7).
LLM_UNAVAILABLE_CONFIDENCE_DOWNGRADE = 0.7

logger = logging.getLogger(__name__)


_INTENT_DESCRIPTIONS: dict[CaseIntent, str] = {
    CaseIntent.CASE: (
        "A proposal or question requiring full case-pipeline activation "
        "(e.g. 'evaluate adding this AIF')."
    ),
    CaseIntent.DIAGNOSTIC: "An explicit portfolio health check.",
    CaseIntent.BRIEFING: "Meeting prep — 'I'm meeting Sharma tomorrow, brief me'.",
    CaseIntent.MONITORING_RESPONSE: "Advisor engaging with an existing N0 alert.",
    CaseIntent.KNOWLEDGE_QUERY: "Factual question answerable without case pipeline.",
    CaseIntent.PROFILE_UPDATE: "Advisor adding or correcting client data.",
    CaseIntent.REBALANCE_TRIGGER: "Scheduled or drift-triggered rebalance.",
    CaseIntent.MANDATE_REVIEW: "Scheduled or ad-hoc IPS review.",
}


_SYSTEM_PROMPT_TEMPLATE = """\
You are M0.Router, the canonical intent classifier for Samriddhi AI.

Your job: classify the inbound event into exactly one of the eight canonical
intent types below. Do not invent new types. If the payload is genuinely
ambiguous between two intents, return your best guess with reduced confidence;
the calling layer will surface clarification.

Eight intent types:
{taxonomy}

Disciplined output:
- Output JSON with exactly three fields: `intent_type_value` (one of:
  {intent_values}), `confidence` (float 0.0-1.0), `reasoning` (short string,
  optional).
- Confidence calibrates the certainty of the verdict, not the analysis effort.
  A clear-cut classification scores >=0.85; a genuinely ambiguous one scores
  0.4-0.6.
- Never output any intent type not in the list above.
"""


def _build_system_prompt() -> str:
    taxonomy_lines = "\n".join(
        f"  - {intent.value}: {desc}" for intent, desc in _INTENT_DESCRIPTIONS.items()
    )
    intent_values = ", ".join(intent.value for intent in CaseIntent)
    return _SYSTEM_PROMPT_TEMPLATE.format(taxonomy=taxonomy_lines, intent_values=intent_values)


def _build_user_prompt(input: M0RouterInput) -> str:
    """Render the inbound event for the LLM."""
    pre_tag_line = (
        f"Channel's pre-tag: {input.pre_tag.value} (confidence {input.pre_tag_confidence:.2f})"
        if input.pre_tag is not None and input.pre_tag_confidence is not None
        else "Channel's pre-tag: none"
    )
    lines = [
        f"Channel: {input.channel.value}",
        pre_tag_line,
        f"Payload: {json.dumps(input.payload, default=str)}",
    ]
    if input.context:
        lines.append(f"Session context: {json.dumps(input.context, default=str)}")
    lines.append("Classify the intent and emit JSON per the schema.")
    return "\n".join(lines)


class M0Router:
    """Section 8.3 — canonical Router service.

    Inject any `LLMProvider` (use `MockProvider` for tests, `AnthropicProvider`
    or similar in production via `artha.llm.smart_router`). The Router is async
    because the LLM provider protocol is async; the deterministic pre-tag-confirm
    path returns immediately without awaiting.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        high_pre_tag_threshold: float = HIGH_PRE_TAG_CONFIDENCE,
        low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        prompt_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._high_pre_tag_threshold = high_pre_tag_threshold
        self._low_confidence_threshold = low_confidence_threshold
        self._prompt_version = prompt_version

    async def classify(self, input: M0RouterInput) -> M0RouterOutput:
        """Classify an inbound event into the canonical intent taxonomy."""
        # Path 1 — confirm a high-confidence pre-tag without an LLM call (Section 8.3.2)
        if (
            input.pre_tag is not None
            and input.pre_tag_confidence is not None
            and input.pre_tag_confidence >= self._high_pre_tag_threshold
        ):
            return M0RouterOutput(
                intent_type=input.pre_tag,
                intent_confidence=input.pre_tag_confidence,
                routing_metadata=self._extract_routing_metadata(input.pre_tag, input),
                run_mode=self._derive_run_mode(input.pre_tag),
            )

        # Path 2 — LLM-backed classification
        try:
            classification = await self._classify_with_llm(input)
        except Exception as exc:
            logger.warning("M0.Router LLM unavailable: %s", exc)
            return self._fallback_on_llm_failure(input)

        # Validate the LLM's intent string against the canonical enum.
        try:
            intent = CaseIntent(classification.intent_type_value)
        except ValueError:
            logger.warning(
                "M0.Router LLM returned non-canonical intent %r; emitting clarification",
                classification.intent_type_value,
            )
            return M0RouterOutput(
                intent_type=input.pre_tag or CaseIntent.CASE,
                intent_confidence=0.0,
                routing_metadata={"path": "llm_invalid_intent"},
                clarification_required=True,
                clarification_payload={
                    "reason": "LLM returned a non-canonical intent",
                    "raw": classification.intent_type_value,
                },
            )

        # Path 3 — low confidence triggers clarification
        if classification.confidence < self._low_confidence_threshold:
            return M0RouterOutput(
                intent_type=intent,
                intent_confidence=classification.confidence,
                routing_metadata={"path": "llm_low_confidence"},
                clarification_required=True,
                clarification_payload={
                    "reason": classification.reasoning or "Low confidence classification",
                    "candidate_intents": [intent.value],
                },
                run_mode=self._derive_run_mode(intent),
            )

        return M0RouterOutput(
            intent_type=intent,
            intent_confidence=classification.confidence,
            routing_metadata=self._extract_routing_metadata(intent, input),
            run_mode=self._derive_run_mode(intent),
        )

    async def _classify_with_llm(self, input: M0RouterInput) -> M0RouterClassification:
        """Invoke the LLM provider with the disciplined classification prompt."""
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=_build_system_prompt()),
                LLMMessage(role="user", content=_build_user_prompt(input)),
            ],
            temperature=0.0,
        )
        return await self._provider.complete_structured(request, M0RouterClassification)

    def _fallback_on_llm_failure(self, input: M0RouterInput) -> M0RouterOutput:
        """Section 8.3.7 — fall back to channel pre-tag if available; else escalate."""
        if input.pre_tag is not None:
            confidence = (input.pre_tag_confidence or 0.5) * LLM_UNAVAILABLE_CONFIDENCE_DOWNGRADE
            return M0RouterOutput(
                intent_type=input.pre_tag,
                intent_confidence=confidence,
                routing_metadata={"path": "llm_unavailable_pre_tag_fallback"},
                run_mode=self._derive_run_mode(input.pre_tag),
            )
        # No pre-tag and no LLM — escalate via clarification
        return M0RouterOutput(
            intent_type=CaseIntent.CASE,  # most permissive default
            intent_confidence=0.0,
            routing_metadata={"path": "llm_unavailable_no_pre_tag"},
            clarification_required=True,
            clarification_payload={
                "reason": "LLM service unavailable and no channel pre-tag provided"
            },
        )

    def _derive_run_mode(self, intent: CaseIntent) -> RunMode:
        """Most case-pipeline intents run in CASE mode; the construction pipeline
        sets RunMode.CONSTRUCTION outside the Router (the construction workflow
        instantiates the envelope directly per §4.2). DIAGNOSTIC intents run
        in DIAGNOSTIC mode so PortfolioAnalytics knows the substrate is the
        primary view per §12.2.2.
        """
        if intent == CaseIntent.DIAGNOSTIC:
            return RunMode.DIAGNOSTIC
        if intent == CaseIntent.BRIEFING:
            return RunMode.BRIEFING
        return RunMode.CASE

    def _extract_routing_metadata(self, intent: CaseIntent, input: M0RouterInput) -> dict[str, Any]:
        """Pull intent-specific routing fields from the payload (best effort).

        Pass 6 keeps this simple — we surface any `client_id`, `case_topic`, or
        `alert_id` we can find. Phase E (channels) tightens the per-intent
        contract.
        """
        meta: dict[str, Any] = {"path": "pre_tag_confirmed"}
        for key in ("client_id", "case_topic", "alert_id", "trigger_source"):
            if key in input.payload:
                meta[key] = input.payload[key]
        meta["intent_type"] = intent.value
        return meta
