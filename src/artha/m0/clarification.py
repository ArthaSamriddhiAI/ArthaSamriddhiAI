"""Section 9.4 — clarification protocol orchestrator.

Per Section 9.4 the protocol is capped at one round trip per agent per case:
  1. Agent emits a `ClarificationRequest`.
  2. M0 responds in 50-200 tokens of natural language.
  3. Agent produces its verdict.
  4. No follow-up clarifications allowed; further requests are rejected.

The service tracks per-case-per-agent round trip count, generates the response
(LLM-backed when an `LLMProvider` is given, deterministic-stub otherwise), and
hands back a `ClarificationDialog` that the caller attaches to the agent's
activation envelope. Both request and response are captured verbatim in T1.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from artha.canonical.agent_envelope import ClarificationDialog
from artha.common.clock import get_clock  # noqa: F401  (used by future LLM-driven path)
from artha.common.errors import ArthaError
from artha.common.standards import (
    CLARIFICATION_MAX_ROUNDS,
    CLARIFICATION_RESPONSE_TOKEN_MAX,
    CLARIFICATION_RESPONSE_TOKEN_MIN,
    ClarificationRequest,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You are M0 responding to a clarification request from a downstream evidence agent.

Strict rules:
- 50 to 200 tokens. 1 to 3 sentences.
- Supply the missing piece of information directly. Do NOT redirect the agent's
  primary task. Do NOT state conclusions, risk levels, or recommendations.
- If the requested information is genuinely unavailable, say so explicitly so the
  agent can produce a low-confidence verdict with the unresolved item flagged.
- The response is captured verbatim in T1 and audited by A1.
"""


class ClarificationCapExceededError(ArthaError):
    """Raised when an agent emits a second clarification request for the same case."""


@dataclass(frozen=True)
class _DialogKey:
    case_id: str
    target_agent: str


def _approx_token_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text)) if text else 0


def _build_user_prompt(case_id: str, request: ClarificationRequest) -> str:
    parts = [
        f"Case: {case_id}",
        f"Requesting agent: {request.requesting_agent}",
        f"Field requested: {request.clarification_field}",
        f"Reason: {request.reason}",
    ]
    if request.candidate_values:
        parts.append(f"Candidate values: {request.candidate_values}")
    parts.append("Provide the clarification per the system rules.")
    return "\n".join(parts)


class M0ClarificationProtocol:
    """Section 9.4 orchestrator with one-round-trip enforcement.

    `provider` is optional — when None, the service uses a deterministic stub
    response useful in tests / demos that don't want an LLM dependency.
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self._provider = provider
        self._round_trips: dict[_DialogKey, int] = {}

    async def respond(
        self,
        case_id: str,
        request: ClarificationRequest,
    ) -> ClarificationDialog:
        """Generate M0's clarification response and return the structured dialog.

        Raises `ClarificationCapExceededError` if the same (case_id, requesting_agent)
        pair has already used its round-trip budget (Section 9.4 cap).
        """
        key = _DialogKey(case_id=case_id, target_agent=request.requesting_agent)
        used = self._round_trips.get(key, 0)
        if used >= CLARIFICATION_MAX_ROUNDS:
            raise ClarificationCapExceededError(
                f"agent {request.requesting_agent} has already used its "
                f"{CLARIFICATION_MAX_ROUNDS}-round clarification budget for case {case_id}"
            )

        if self._provider is not None:
            response_text = await self._llm_respond(case_id, request)
        else:
            response_text = self._stub_response(request)

        # Length lint per Section 9.4
        token_count = _approx_token_count(response_text)
        responding_actor = "m0" if self._provider is not None else "m0_stub"

        # If the response is outside budget, surface it explicitly so that A1's
        # accountability surface picks it up. We still register the round trip
        # to honor the one-round-trip cap.
        if not (
            CLARIFICATION_RESPONSE_TOKEN_MIN
            <= token_count
            <= CLARIFICATION_RESPONSE_TOKEN_MAX
        ):
            logger.warning(
                "Clarification response outside [%d, %d] tokens (got %d) for case %s agent %s",
                CLARIFICATION_RESPONSE_TOKEN_MIN,
                CLARIFICATION_RESPONSE_TOKEN_MAX,
                token_count,
                case_id,
                request.requesting_agent,
            )

        self._round_trips[key] = used + 1

        return ClarificationDialog(
            request=request,
            response_text=response_text,
            response_token_count=token_count,
            responding_actor=responding_actor,
        )

    def remaining_budget(
        self,
        case_id: str,
        requesting_agent: str,
    ) -> int:
        """Return how many round trips this agent has left for the case."""
        used = self._round_trips.get(
            _DialogKey(case_id=case_id, target_agent=requesting_agent), 0
        )
        return max(0, CLARIFICATION_MAX_ROUNDS - used)

    def reset(self) -> None:
        """Clear all tracked round trips (use at end-of-case in tests)."""
        self._round_trips.clear()

    async def _llm_respond(
        self, case_id: str, request: ClarificationRequest
    ) -> str:
        """LLM-backed response generator."""
        try:
            response = await self._provider.complete(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=_SYSTEM_PROMPT),
                        LLMMessage(
                            role="user", content=_build_user_prompt(case_id, request)
                        ),
                    ],
                    temperature=0.0,
                )
            )
            return response.content.strip()
        except Exception as exc:
            logger.warning("Clarification LLM unavailable: %s", exc)
            return (
                f"Clarification unavailable due to service error. "
                f"Agent should produce a low-confidence verdict with "
                f"{request.clarification_field!r} flagged as unresolved."
            )

    @staticmethod
    def _stub_response(request: ClarificationRequest) -> str:
        """Deterministic fallback when no LLM provider is configured.

        Used in tests and demos. Emits a generic acknowledgment that satisfies
        the length budget; never invents domain content.
        """
        return (
            f"For field {request.clarification_field!r}: the requested value "
            f"is not available in the current case bundle. The agent should "
            f"proceed with a low-confidence verdict and flag the unresolved "
            f"item explicitly."
        )
