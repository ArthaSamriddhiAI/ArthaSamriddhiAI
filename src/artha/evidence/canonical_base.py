"""Shared base for canonical evidence agents (E1–E6).

Section 11.1 — every evidence agent has a strictly isolated lane and produces
a structured verdict conforming to `StandardEvidenceVerdict`. Sections 11.2,
11.3, etc. specialise per-lane. The shared activation logic lives here:

  * Build the LLM request from the activation envelope + agent-specific
    prompt + structured signals.
  * Call `complete_structured` with the internal `_LlmEvidenceCore` shape.
  * Validate the LLM's risk-level string against the canonical enum.
  * Compute `input_hash` over the canonicalised input bundle for replay (§3.11).
  * Wrap the LLM output into the agent's typed verdict subclass.

Per-agent classes override `system_prompt`, `_render_signals`, `_build_verdict`,
and the structured output type. The base class handles the LLM mechanics, hash
computation, and replay-stable serialisation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, TypeVar

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import (
    StandardEvidenceVerdict,
    _LlmEvidenceCore,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.types import (
    InputsUsedManifest,
    RiskLevel,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


T = TypeVar("T", bound=StandardEvidenceVerdict)


class EvidenceLLMUnavailableError(ArthaError):
    """Raised when the agent's LLM provider fails and no fallback is available.

    Per §11.2.7 / §3.13 the EX1 contract for evidence agents is to surface a
    fallback verdict (HIGH risk, low confidence, "agent timeout" flag); the
    agent service does not invent a verdict on its own, so this exception is
    propagated up to whatever orchestrator wired the agent.
    """


class CanonicalEvidenceAgent(ABC):
    """Base class for canonical evidence agents.

    Subclasses must implement:
      * `agent_id` — class attribute, e.g. "financial_risk".
      * `system_prompt()` — system-prompt text.
      * `_render_signals(envelope, **kwargs)` — agent-specific structured-signal
        block included in the user prompt.
      * `_build_verdict(envelope, llm_core, signals_input_for_hash)` — wrap
        the LLM core into the typed verdict subclass.

    The shared `evaluate()` orchestration handles LLM mechanics + hashing + manifest.
    """

    agent_id: str  # subclasses override

    def __init__(
        self,
        provider: LLMProvider,
        *,
        prompt_version: str = "0.1.0",
        agent_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._prompt_version = prompt_version
        self._agent_version = agent_version

    # --------------------- Abstract slots ----------------------------------

    @abstractmethod
    def system_prompt(self) -> str:
        """The agent-specific system prompt enforcing its lane and discipline."""

    @abstractmethod
    def _render_signals(self, envelope: AgentActivationEnvelope, **kwargs: Any) -> str:
        """Render agent-specific structured signals into the user prompt."""

    @abstractmethod
    def _build_verdict(
        self,
        envelope: AgentActivationEnvelope,
        llm_core: _LlmEvidenceCore,
        signals_input_for_hash: dict[str, Any],
        **kwargs: Any,
    ) -> StandardEvidenceVerdict:
        """Wrap the LLM core output into the typed verdict subclass."""

    # --------------------- Shared orchestration ----------------------------

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> StandardEvidenceVerdict:
        """Activate the agent on the given envelope. Returns a typed verdict.

        Per-agent additional inputs (holdings, analytics, sector data, etc.)
        come through `**kwargs` to keep the base agnostic. Subclasses define
        their input contract.
        """
        signals_block = self._render_signals(envelope, **kwargs)
        signals_input_for_hash = self._collect_input_for_hash(envelope, **kwargs)

        try:
            llm_core = await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=self.system_prompt()),
                        LLMMessage(
                            role="user", content=self._render_user_prompt(envelope, signals_block)
                        ),
                    ],
                    temperature=0.0,
                ),
                _LlmEvidenceCore,
            )
        except Exception as exc:
            logger.warning("%s LLM unavailable: %s", self.agent_id, exc)
            raise EvidenceLLMUnavailableError(
                f"{self.agent_id} LLM provider unavailable: {exc}"
            ) from exc

        # Validate the LLM's risk_level string against the canonical enum.
        try:
            _ = RiskLevel(llm_core.risk_level_value)
        except ValueError as exc:
            raise EvidenceLLMUnavailableError(
                f"{self.agent_id} LLM returned non-canonical risk_level "
                f"{llm_core.risk_level_value!r}"
            ) from exc

        return self._build_verdict(envelope, llm_core, signals_input_for_hash, **kwargs)

    # --------------------- Helpers (shared) -------------------------------

    def _render_user_prompt(
        self,
        envelope: AgentActivationEnvelope,
        signals_block: str,
    ) -> str:
        """Render the standard user prompt: case context + signals + briefing."""
        parts = [
            f"Case: {envelope.case.case_id}",
            f"Client: {envelope.case.client_id}",
            f"Run mode: {envelope.run_mode.value}",
            f"Intent: {envelope.case.intent.value}",
            "Signals:",
            signals_block,
        ]
        if envelope.briefing is not None:
            parts.append(f"M0 briefing: {envelope.briefing.text}")
        if envelope.clarification is not None and envelope.clarification.response_text:
            parts.append(
                f"Clarification response: {envelope.clarification.response_text}"
            )
        parts.append(
            "Produce the structured evidence verdict per the system prompt's schema."
        )
        return "\n".join(parts)

    def _collect_input_for_hash(
        self,
        envelope: AgentActivationEnvelope,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build a stable dict of the verdict's inputs for `input_hash` and manifest.

        The hash discipline (§3.11): two activations with identical input bundles
        produce identical hashes. Pydantic models serialise via `model_dump(mode="json")`.
        """
        bundle: dict[str, Any] = {
            "agent_id": self.agent_id,
            "envelope": envelope.model_dump(mode="json"),
        }
        for k, v in kwargs.items():
            if hasattr(v, "model_dump"):
                bundle[k] = v.model_dump(mode="json")
            elif isinstance(v, list) and v and hasattr(v[0], "model_dump"):
                bundle[k] = [item.model_dump(mode="json") for item in v]
            else:
                bundle[k] = v
        return bundle

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        """Build the InputsUsedManifest for replay traceability."""
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            if k == "envelope":
                inputs_dict["envelope"] = {"hash": payload_hash(v)}
            else:
                inputs_dict[k] = {
                    "shape_hash": payload_hash(v),
                    "kind": type(v).__name__ if not isinstance(v, dict) else "dict",
                }
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "CanonicalEvidenceAgent",
    "EvidenceLLMUnavailableError",
]
