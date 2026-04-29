"""Section 8.8 — M0.Briefer: disciplined natural-language briefings.

Per Section 8.8.1 the Briefer writes 100-300 token briefings to downstream
agents when the structured context packet under-conveys the case. The
discipline (Section 8.8.2):

  * No conclusions, no risk-level assertions, no recommendations, no
    verdict-anticipating language.
  * 2-4 sentences, 100-300 tokens.
  * Format: 1-2 sentences naming what context the structured packet under-
    conveys, 1-2 sentences providing the missing context, optionally 1
    sentence flagging what to be aware of without telling the agent what
    to conclude.
  * Returns null when M0 cannot articulate non-redundant context.

The lint check uses Pass 1's `briefing_violates_discipline()` which catches
verdict-anticipating language. On lint failure Pass 7 returns null with a
skip_reason; future passes may add an LLM retry-with-tighter-discipline path.
"""

from __future__ import annotations

import logging
import re

from artha.canonical.m0_briefer import (
    BriefingTrigger,
    M0BrieferInput,
    M0BrieferMetadata,
    M0BrieferOutput,
)
from artha.common.clock import get_clock
from artha.common.standards import (
    BRIEFING_TOKEN_MAX,
    BRIEFING_TOKEN_MIN,
    briefing_violates_discipline,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are M0.Briefer for Samriddhi AI. Your job is to write a disciplined briefing
to a downstream agent activating on a case.

Strict rules:
- 2 to 4 sentences. 100 to 300 tokens total.
- Surface context the structured input does not carry. Do not restate the
  structured fields.
- Do NOT state conclusions. Do NOT assign risk levels. Do NOT make
  recommendations. Do NOT use language that anticipates the agent's verdict.
- Format: (1) one or two sentences naming what context is missing from the
  structured packet, (2) one or two sentences supplying that context.
- If you cannot articulate non-redundant context, return the literal string
  SKIP and nothing else.

Tone: formal English. The agent will read your briefing alongside the
structured packet; the briefing is captured verbatim in T1 and audited by A1.
"""


def _approx_token_count(text: str) -> int:
    """Rough token count approximation (whitespace-split + punctuation-aware).

    Production uses the LLM provider's tokenizer; for Pass 7 lint we use a cheap
    word-count proxy. The 100-300 token budget is forgiving enough that ±10%
    accuracy is fine.
    """
    return len(re.findall(r"\b\w+\b", text)) if text else 0


def _build_user_prompt(input: M0BrieferInput) -> str:
    """Render the trigger + case context into a brief prompt."""
    parts = [
        f"Target agent: {input.target_agent}",
        f"Trigger: {input.trigger_flag.value}",
    ]
    if input.additional_emphasis:
        parts.append(f"Advisor emphasis: {input.additional_emphasis}")
    # case_bundle is permissive; we keep the prompt small by summarising shape only.
    case_keys = sorted(input.case_bundle.keys()) if input.case_bundle else []
    if case_keys:
        parts.append(f"Case bundle includes: {', '.join(case_keys)}")
    parts.append(
        "Write the briefing per the rules in the system prompt, or output SKIP."
    )
    return "\n".join(parts)


class M0Briefer:
    """Section 8.8 — disciplined briefing generator.

    Inject any LLMProvider; tests use MockProvider.set_response('Trigger:', '...').
    Production uses the configured Anthropic / OpenAI provider via
    `artha.llm.smart_router`.

    `generate()` returns:
      * M0BrieferOutput with briefing_text + metadata when the LLM produced a
        compliant briefing.
      * M0BrieferOutput with briefing_text=None and skip_reason populated when
        the LLM emitted SKIP, the text fell outside the length budget, or the
        text failed lint.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        briefer_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._briefer_version = briefer_version

    async def generate(self, input: M0BrieferInput) -> M0BrieferOutput:
        """Run the LLM, lint the output, return a structured `M0BrieferOutput`."""
        try:
            response = await self._provider.complete(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=_SYSTEM_PROMPT),
                        LLMMessage(role="user", content=_build_user_prompt(input)),
                    ],
                    temperature=0.0,
                )
            )
        except Exception as exc:
            logger.warning("M0.Briefer LLM unavailable: %s", exc)
            return M0BrieferOutput(
                briefing_text=None,
                skip_reason=f"llm_unavailable: {exc}",
            )

        text = response.content.strip()

        # Skip path
        if text.upper() == "SKIP":
            return M0BrieferOutput(
                briefing_text=None,
                skip_reason="llm_emitted_skip",
            )

        # Length lint
        token_count = _approx_token_count(text)
        if token_count < BRIEFING_TOKEN_MIN or token_count > BRIEFING_TOKEN_MAX:
            return M0BrieferOutput(
                briefing_text=None,
                skip_reason=(
                    f"length_violation: {token_count} tokens "
                    f"outside [{BRIEFING_TOKEN_MIN}, {BRIEFING_TOKEN_MAX}]"
                ),
            )

        # Discipline lint (no verdict anticipation)
        violates, reasons = briefing_violates_discipline(text)
        if violates:
            return M0BrieferOutput(
                briefing_text=None,
                skip_reason=f"lint_violation: {'; '.join(reasons)}",
                briefing_metadata=M0BrieferMetadata(
                    token_count=token_count,
                    generation_timestamp=get_clock().now(),
                    briefer_version=self._briefer_version,
                    trigger_flag=input.trigger_flag,
                    target_agent=input.target_agent,
                    lint_violations=reasons,
                ),
            )

        return M0BrieferOutput(
            briefing_text=text,
            briefing_metadata=M0BrieferMetadata(
                token_count=token_count,
                generation_timestamp=get_clock().now(),
                briefer_version=self._briefer_version,
                trigger_flag=input.trigger_flag,
                target_agent=input.target_agent,
            ),
        )


__all__ = [
    "M0Briefer",
    "BriefingTrigger",
    "M0BrieferInput",
    "M0BrieferOutput",
]
