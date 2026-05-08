"""Per-agent shim framework (cluster 7 chunk 7.1 §2).

The :class:`AgentShim` ABC is the substrate every real LLM-using agent
implements. Cluster 7 ships two concrete shims (E1 + M0.PortfolioRisk
Analytics); clusters 8-12 ship the rest (E2-E7, S1, IC1, A1) by
sub-classing :class:`AgentShim`.

Lifecycle (chunk 7.1 §2.2):

    [DISPATCHER] receive_inputs
    [SHIM]       validate_input
    [SHIM]       compute_cache_key (default: None)
    [DISPATCHER] check_cache (when key non-null) — chunk 7.2
                 ├── HIT  → return cached verdict
                 └── MISS → proceed
    [SHIM]       format_prompt
    [DISPATCHER] llm_call (with retry policy)
    [SHIM]       parse_output
    [DISPATCHER] schema_validate
    [SHIM]       validate_output (semantic)
    [DISPATCHER] write_cache (when key non-null) — chunk 7.2
    [DISPATCHER] emit_t1_events
    [DISPATCHER] return_verdict

The ABC owns the four validation hooks; the dispatcher
(:class:`AgentDispatcher`) owns the orchestration. Tests inject a mock
LLM client so we don't burn API tokens / introduce non-determinism.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from artha.api_v2.agents.llm_client import (
    LLMCallError,
    LLMClient,
    LLMResponse,
)
from artha.api_v2.agents.prompt_loader import (
    PromptPayload,
    PromptTemplate,
)

# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """Output of a shim's validate_input / validate_output hook."""

    success: bool
    error_type: str | None = None  # e.g. "missing_field", "schema_violation"
    error_path: tuple[str, ...] = ()
    error_message: str = ""

    @property
    def ok(self) -> bool:  # backward-compat sugar
        return self.success


@dataclass
class ParsedVerdict:
    """Structured verdict produced by the shim's parse_output hook.

    ``structured`` is the parsed agent-specific verdict (e.g. an E1Output
    Pydantic model dump). ``stage_payload`` is the dict the case
    pipeline writes into the corresponding stage table (EvidenceVerdict /
    PortfolioRiskAnalyticsOutput / etc.).
    """

    agent_id: str
    structured: dict[str, Any]
    stage_payload: dict[str, Any]
    raw_text: str = ""


@dataclass(frozen=True)
class AgentInputs:
    """The bag of per-call inputs the dispatcher hands to the shim.

    For E1 this carries the ``ticker`` + per-ticker context. For
    M0.PortfolioRiskAnalytics it carries the full PortfolioAnalytics
    output + mandate snapshot. Shims declare the keys they need;
    ``validate_input`` checks them.
    """

    case_id: str
    case_mode: str
    case_intent: str | None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DispatchResult:
    """End-to-end output of :meth:`AgentDispatcher.run` per call."""

    verdict: ParsedVerdict
    llm_response: LLMResponse
    retry_count: int
    cache_hit: bool = False


# ---------------------------------------------------------------------------
# AgentShim ABC
# ---------------------------------------------------------------------------


class AgentShim(ABC):
    """Per-agent execution shim (chunk 7.1 §2.1)."""

    #: Stable identifier (matches registry + skill.md filename).
    agent_id: str = ""

    #: Cluster-6 enriched skill.md version (e.g. ``"1.1"``).
    skill_md_version: str = "1.1"

    #: Pydantic model used for output schema validation. Subclasses
    #: declare a concrete ``BaseModel`` subclass.
    output_model: type | None = None

    @abstractmethod
    def validate_input(
        self,
        agent_inputs: AgentInputs,
    ) -> ValidationResult:
        """Pre-call validation. Catches missing inputs early."""

    @abstractmethod
    def format_prompt(
        self,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> PromptPayload:
        """Render the skill.md body + per-call inputs into an LLM prompt."""

    @abstractmethod
    def parse_output(
        self,
        llm_response: LLMResponse,
        agent_inputs: AgentInputs,
    ) -> ParsedVerdict:
        """Parse the LLM response text into a structured verdict.

        Implementations typically expect a single JSON object in the
        response and use the shim's :attr:`output_model` to validate.
        """

    @abstractmethod
    def validate_output(
        self,
        verdict: ParsedVerdict,
        agent_inputs: AgentInputs,
    ) -> ValidationResult:
        """Semantic validation beyond the schema (e.g. E1 rule 1:
        verdict=positive incompatible with high-severity risk signals)."""

    def compute_cache_key(self, agent_inputs: AgentInputs) -> str | None:
        """Return a cache key when the agent supports caching, else None.

        Default: no caching. E1 overrides to return
        ``e1:{ticker}:{earnings_id}:{manual_flag_id}``.
        """
        return None


# ---------------------------------------------------------------------------
# Helpers shared by shim implementations
# ---------------------------------------------------------------------------


def parse_json_object(raw_text: str) -> tuple[dict[str, Any], str | None]:
    """Best-effort JSON parse: returns ``(payload, error_msg | None)``.

    Handles the common case where the LLM wraps JSON in code fences or
    adds prose before / after the object. Returns the *first* parseable
    JSON object found.
    """
    text = raw_text.strip()
    # Strip a leading ```json / ``` fence if present.
    if text.startswith("```"):
        # Find the first newline + the closing fence
        first_nl = text.find("\n")
        last_fence = text.rfind("```")
        if first_nl != -1 and last_fence > first_nl:
            text = text[first_nl + 1 : last_fence].strip()

    # Locate the first '{' and try to balance braces from there.
    start = text.find("{")
    if start == -1:
        return {}, "no_json_object_found"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate), None
                    except json.JSONDecodeError as exc:
                        return {}, f"json_decode_error: {exc}"
    return {}, "unbalanced_braces"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchPolicy:
    """Retry + timeout policy applied uniformly to real-agent dispatches.

    Defaults match chunk 7.1 §9.4: 3 retries with backoff (1s, 4s, 16s)
    on timeout / 5xx / schema / semantic failure.
    """

    max_retries: int = 3
    retry_delay_seconds: tuple[float, ...] = (1.0, 4.0, 16.0)


class AgentDispatchError(RuntimeError):
    """Raised when retries are exhausted (case_arch08_b pattern)."""

    def __init__(self, agent_id: str, last_error: str, retry_count: int):
        super().__init__(
            f"agent_unavailability_persistent: {agent_id} failed across "
            f"{retry_count} retries; last error: {last_error}",
        )
        self.agent_id = agent_id
        self.last_error = last_error
        self.retry_count = retry_count


class AgentDispatcher:
    """Generic dispatcher orchestrating any :class:`AgentShim`.

    The dispatcher does not know agent-specific validation; it delegates
    everything beyond LLM-call orchestration to the shim. Tests inject a
    mock :class:`LLMClient` so the dispatcher path can be exercised
    without burning API tokens.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        policy: DispatchPolicy | None = None,
    ) -> None:
        self._llm = llm_client
        self._policy = policy or DispatchPolicy()

    def run(
        self,
        *,
        shim: AgentShim,
        skill_md_template: PromptTemplate,
        agent_inputs: AgentInputs,
    ) -> DispatchResult:
        """Run one shim end-to-end with retry policy.

        Returns :class:`DispatchResult` on success; raises
        :class:`AgentDispatchError` when retries are exhausted.
        """
        # Step 1: validate input.
        input_check = shim.validate_input(agent_inputs)
        if not input_check.success:
            raise AgentDispatchError(
                agent_id=shim.agent_id,
                last_error=(
                    f"input_validation_failed: {input_check.error_message}"
                ),
                retry_count=0,
            )

        # Step 2: format prompt (deterministic; no retry needed).
        prompt = shim.format_prompt(skill_md_template, agent_inputs)

        # Step 3: LLM call with retry policy.
        last_error: str = ""
        retries = 0
        for attempt in range(self._policy.max_retries):
            retries = attempt
            try:
                response = self._llm.complete(prompt)
            except LLMCallError as exc:
                last_error = f"llm_call_failed: {exc}"
                continue

            # Step 4: parse output.
            try:
                verdict = shim.parse_output(response, agent_inputs)
            except ValueError as exc:
                last_error = f"parse_failed: {exc}"
                continue

            # Step 5: semantic validation.
            sem_check = shim.validate_output(verdict, agent_inputs)
            if not sem_check.success:
                last_error = (
                    f"semantic_violation: {sem_check.error_message}"
                )
                continue

            return DispatchResult(
                verdict=verdict,
                llm_response=response,
                retry_count=retries,
                cache_hit=False,
            )

        raise AgentDispatchError(
            agent_id=shim.agent_id,
            last_error=last_error or "all_retries_exhausted",
            retry_count=self._policy.max_retries,
        )


__all__ = [
    "AgentDispatchError",
    "AgentDispatcher",
    "AgentInputs",
    "AgentShim",
    "DispatchPolicy",
    "DispatchResult",
    "ParsedVerdict",
    "ValidationResult",
    "parse_json_object",
]
