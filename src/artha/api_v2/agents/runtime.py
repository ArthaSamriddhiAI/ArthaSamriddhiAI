"""Real-agent runtime — cluster 7 chunks 7.1 §3 + 7.2 §2.4.

Glue that orchestrates the per-agent shim framework when the case
pipeline calls :func:`artha.api_v2.cases.dispatch.dispatch_agent` for
an agent flagged as ``real`` via the per-agent config (chunk 7.1
§12.3).

The runtime owns three pieces of state:

- The configured :class:`LLMClient` (production:
  :class:`AnthropicLLMClient`; tests: :class:`MockLLMClient` injected
  via :func:`set_llm_client`).
- The :class:`DispatchPolicy` (defaults to 3 retries with 1/4/16s
  back-off per chunk 7.1 §9.4) — overridable via
  :func:`set_dispatch_policy`.
- The shim registry (:mod:`.registry`) — discovered at import.

Cluster 7.2 adds the cache hooks. The runtime brackets the dispatcher
call with :meth:`CacheBackend.get` / :meth:`CacheBackend.put` calls so
the dispatcher core stays cache-agnostic. When ``cache`` is ``None``
or :class:`NullCacheBackend`, behaviour matches Stage 1.

Cluster 7.4 will wire the M0 portfolio_state / pre-action /
post-action / mandate inputs from the real PortfolioAnalytics outputs;
for now tests inject ``agent_inputs_override`` to exercise the full
path with synthetic data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from artha.api_v2.agents.cache import manual_flag as manual_flag_service
from artha.api_v2.agents.cache.backend import CacheBackend, NullCacheBackend
from artha.api_v2.agents.llm_client import LLMClient, LLMResponse
from artha.api_v2.agents.prompt_loader import (
    PromptTemplate,
    load_prompt_template,
)
from artha.api_v2.agents.registry import get_shim
from artha.api_v2.agents.shim import (
    AgentDispatcher,
    AgentInputs,
    DispatchPolicy,
    DispatchResult,
    ParsedVerdict,
)

if TYPE_CHECKING:  # avoid runtime import; we only access duck-typed attrs
    from sqlalchemy.ext.asyncio import AsyncSession

    from artha.api_v2.cases.models import Case


# ---------------------------------------------------------------------------
# Module-level config (test-overridable)
# ---------------------------------------------------------------------------


_LLM_CLIENT: LLMClient | None = None
_DISPATCH_POLICY: DispatchPolicy = DispatchPolicy()


def set_llm_client(client: LLMClient | None) -> None:
    """Test helper: pin the LLM client used by the real-agent runtime.

    Pass ``None`` to unset; the next dispatch call will then raise
    :class:`RealAgentRuntimeError` until a client is configured.
    """
    global _LLM_CLIENT
    _LLM_CLIENT = client


def get_llm_client() -> LLMClient | None:
    """Return the currently configured LLM client (or ``None`` if not set)."""
    return _LLM_CLIENT


def set_dispatch_policy(policy: DispatchPolicy) -> None:
    """Test helper: override the dispatch policy (e.g. zero retries)."""
    global _DISPATCH_POLICY
    _DISPATCH_POLICY = policy


def get_dispatch_policy() -> DispatchPolicy:
    """Return the current dispatch policy."""
    return _DISPATCH_POLICY


def reset_runtime() -> None:
    """Test helper: clear LLM client + policy back to defaults."""
    global _LLM_CLIENT, _DISPATCH_POLICY
    _LLM_CLIENT = None
    _DISPATCH_POLICY = DispatchPolicy()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RealAgentRuntimeError(RuntimeError):
    """Raised when the real-agent runtime can't service a dispatch call.

    Distinct from :class:`AgentDispatchError` (the domain-level "agent
    failed after retries"); this signals infrastructural problems —
    missing shim, no LLM client configured, etc.
    """


# ---------------------------------------------------------------------------
# Input building
# ---------------------------------------------------------------------------


async def _build_agent_inputs(
    *,
    case: Case,
    agent_id: str,
    upstream: dict[str, Any],
    seed_payload: dict[str, Any],
    inputs_override: AgentInputs | None,
    db: AsyncSession | None = None,
) -> AgentInputs:
    """Assemble :class:`AgentInputs` from case + upstream + seed payload.

    When ``inputs_override`` is supplied (typically from tests) it
    short-circuits the extraction. Otherwise the runtime extracts what
    it can from the case row + upstream pipeline state. Cluster 7.4
    will wire the M0 portfolio_state outputs as additional sources.

    Cluster 7.2 wires the manual-flag lookup: when ``db`` is provided
    and the agent is E1, the active manual flag for the ticker
    populates the cache-key component so manual-flag rotation
    auto-invalidates.
    """
    if inputs_override is not None:
        return inputs_override

    payload: dict[str, Any] = {}

    if agent_id == "e1_listed_fundamental_equity":
        # First product becomes the ticker. Cluster 7.4's per-ticker
        # fan-out runs E1 once per holding; for Stage 1/2 we keep the
        # single-call shape to prove the wiring.
        products = list(case.proposed_action_products or [])
        ticker = products[0] if products else None
        if ticker:
            payload["ticker"] = ticker
        seed_e1 = seed_payload.get("evidence.e1_listed_fundamental_equity") or {}
        if isinstance(seed_e1, dict) and seed_e1:
            structured = seed_e1.get("structured_output") or {}
            payload["snapshot_excerpt"] = str(
                structured.get("verdict_summary", "")
                or "No snapshot excerpt available.",
            )
        payload["mandate_excerpt"] = (
            f"investor_id={case.investor_id}; "
            f"case_intent={case.case_intent or 'review'}"
        )
        # Cluster 7.4 will substitute the real earnings_id from the
        # earnings data layer; the sentinel keeps the cache-key format
        # stable in the meantime.
        payload["latest_earnings_id"] = "no_earnings_seeded"

        # Cluster 7.2: look up the active manual flag for the ticker
        # so the cache key reflects the current flag state.
        active_flag_id: str | None = None
        if db is not None and ticker:
            snap = await manual_flag_service.get_active_manual_flag_for_ticker(
                db, ticker=ticker,
            )
            if snap is not None:
                active_flag_id = snap.manual_flag_id
        payload["manual_flag_id"] = active_flag_id or "null"

    elif agent_id == "m0_portfolio_risk_analytics":
        # Cluster 7.4 will populate these from PortfolioAnalytics outputs
        # in the upstream dict. For Stage 2 we surface what's already
        # there so tests can inject overrides.
        payload["mandate"] = upstream.get("mandate", {}) or {}
        payload["portfolio_analytics_pre_action"] = (
            upstream.get("portfolio_analytics_pre_action", {}) or {}
        )
        if case.case_mode in {"proposed_action", "scenario"}:
            payload["portfolio_analytics_post_action"] = (
                upstream.get("portfolio_analytics_post_action", {}) or {}
            )
        payload["proposed_action_summary"] = case.proposed_action or ""
        payload["dominant_lens"] = case.dominant_lens
        payload["evidence_summaries"] = upstream.get("evidence_verdicts", []) or []

    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=case.case_intent,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Public entry: dispatch_real_agent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealDispatchOutput:
    """Output of :func:`dispatch_real_agent` — verdict + telemetry."""

    agent_id: str
    parsed: ParsedVerdict
    retry_count: int
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    model: str
    prompt_version: str


async def dispatch_real_agent(
    *,
    case: Case,
    agent_id: str,
    upstream: dict[str, Any] | None = None,
    seed_payload: dict[str, Any] | None = None,
    agent_inputs_override: AgentInputs | None = None,
    skill_template_override: PromptTemplate | None = None,
    cache: CacheBackend | None = None,
    db: AsyncSession | None = None,
) -> RealDispatchOutput:
    """Run the real shim for ``agent_id`` end-to-end.

    Cluster 7.2: when ``cache`` is supplied, the runtime first
    consults it via :meth:`CacheBackend.get`. On a hit, it
    short-circuits the LLM call and returns a :class:`RealDispatchOutput`
    with ``cache_hit=True``. On a miss, the LLM call runs as in
    Stage 1; on success the verdict is persisted via
    :meth:`CacheBackend.put`.

    Tests inject ``agent_inputs_override`` + ``skill_template_override``
    plus :func:`set_llm_client(MockLLMClient(...))` to exercise this
    path without on-disk skill.md files / live API calls.

    Raises :class:`RealAgentRuntimeError` for missing shim or unset LLM
    client; :class:`AgentDispatchError` when retries are exhausted.
    """
    shim = get_shim(agent_id)
    if shim is None:
        raise RealAgentRuntimeError(
            f"No real shim registered for agent_id={agent_id!r}; expected "
            f"one of e1_listed_fundamental_equity, "
            f"m0_portfolio_risk_analytics.",
        )

    llm = _LLM_CLIENT
    if llm is None:
        raise RealAgentRuntimeError(
            "No LLM client configured — call "
            "agents.runtime.set_llm_client() before dispatching real "
            "agents.",
        )

    template = (
        skill_template_override
        if skill_template_override is not None
        else load_prompt_template(agent_id)
    )

    inputs = await _build_agent_inputs(
        case=case,
        agent_id=agent_id,
        upstream=upstream or {},
        seed_payload=seed_payload or {},
        inputs_override=agent_inputs_override,
        db=db,
    )

    backend: CacheBackend = cache if cache is not None else NullCacheBackend()
    cache_key = shim.compute_cache_key(inputs)

    # ---- Cache lookup -------------------------------------------------
    if cache_key:
        lookup = await backend.get(cache_key=cache_key)
        if lookup.hit:
            cached_verdict = ParsedVerdict(
                agent_id=agent_id,
                structured=lookup.verdict_payload or {},
                stage_payload=lookup.stage_payload or {},
                raw_text=lookup.raw_text or "",
            )
            return RealDispatchOutput(
                agent_id=agent_id,
                parsed=cached_verdict,
                retry_count=0,
                cache_hit=True,
                input_tokens=lookup.input_tokens,
                output_tokens=lookup.output_tokens,
                model=lookup.llm_model,
                prompt_version=lookup.prompt_version or template.prompt_version,
            )

    # ---- Live LLM call ------------------------------------------------
    dispatcher = AgentDispatcher(
        llm_client=llm,
        policy=_DISPATCH_POLICY,
    )
    result: DispatchResult = dispatcher.run(
        shim=shim,
        skill_md_template=template,
        agent_inputs=inputs,
    )

    # ---- Cache write --------------------------------------------------
    if cache_key:
        ticker = inputs.payload.get("ticker") or ""
        earnings_id = (
            inputs.payload.get("latest_earnings_id") or "no_earnings_seeded"
        )
        raw_flag = inputs.payload.get("manual_flag_id")
        manual_flag_id = (
            None if raw_flag in (None, "null", "") else str(raw_flag)
        )
        await backend.put(
            cache_key=cache_key,
            ticker=ticker,
            earnings_id=earnings_id,
            manual_flag_id=manual_flag_id,
            prompt_version=template.prompt_version,
            verdict_payload=result.verdict.structured,
            stage_payload=result.verdict.stage_payload,
            raw_text=result.verdict.raw_text,
            llm_model=result.llm_response.model or template.llm_model,
            input_tokens=result.llm_response.input_tokens,
            output_tokens=result.llm_response.output_tokens,
            case_id=case.case_id,
        )

    return RealDispatchOutput(
        agent_id=agent_id,
        parsed=result.verdict,
        retry_count=result.retry_count,
        cache_hit=False,
        input_tokens=result.llm_response.input_tokens,
        output_tokens=result.llm_response.output_tokens,
        model=result.llm_response.model,
        prompt_version=template.prompt_version,
    )


# Hint to type checkers that LLMResponse is referenced indirectly via
# DispatchResult; keep the import alive without ``noqa``.
_LLMResponse = LLMResponse


__all__ = [
    "RealAgentRuntimeError",
    "RealDispatchOutput",
    "dispatch_real_agent",
    "get_dispatch_policy",
    "get_llm_client",
    "reset_runtime",
    "set_dispatch_policy",
    "set_llm_client",
]
