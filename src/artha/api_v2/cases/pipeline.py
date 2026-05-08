"""Cluster 5 chunk 5.4 — case pipeline orchestrator.

Walks a case through its mode-specific stage sequence (FR 20.1 §1.4 +
§1.5), running each stub via :mod:`.dispatch` and writing the result
through :mod:`.repository`. Emits ``stub_dispatched`` +
``pipeline_stage_completed`` T1 events as each stage finishes, plus
the lifecycle transitions (``case_status_transition`` / ``case_decided``)
emitted by ``transition_status`` itself.

Synchronous execution today: stubs are deterministic + sub-millisecond,
so running the full pipeline inline inside the case-opener call
(chunk 5.3) is acceptable. Cluster 7 swaps in real LLM calls and the
pipeline moves to a background worker.

Modes (FR 20.1 §1.4):

- ``proposed_action`` / ``scenario`` — full pipeline. Materiality gate
  branches between the IC1-then-governance and skip-IC1-go-governance
  paths. Stops at ``awaiting_decision`` so the CIO records the final
  call (chunk 5.5).
- ``diagnostic`` — evidence + portfolio_risk + diagnostic synthesis +
  G1 mandate gate + auto-decided. HealthReport stage row written.
- ``briefing`` — evidence (subset) + briefing synthesis + auto-decided.
  BriefingNote stage row written. Skips governance entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.agents import event_names as agent_event_names
from artha.api_v2.agents.shim import AgentDispatchError
from artha.api_v2.cases import dispatch, event_names, repository
from artha.api_v2.cases.dispatch import StageKind, StubResult
from artha.api_v2.cases.materiality import (
    DEFAULT_MATERIALITY_CONFIG,
    MaterialityInput,
    MaterialityResult,
    evaluate_materiality,
)
from artha.api_v2.cases.models import Case
from artha.api_v2.cases.state_machine import (
    CaseClosedReason,
    CaseMode,
    CaseStatus,
    InvalidStateTransitionError,
)
from artha.api_v2.cases.stubs import stub_briefing_note, stub_health_report
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PipelineError(RuntimeError):
    """Wraps lower-level errors emitted while running the pipeline.

    Caller (case_opener.open_case) catches this and transitions the
    case to ``failed`` with ``closed_reason='failed'``.
    """


# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineRunResult:
    """Outcome of :func:`run_pipeline`.

    ``final_status`` is the case's status after the orchestrator stops.
    For proposed_action / scenario, this is normally
    ``awaiting_decision``; for diagnostic / briefing it's ``decided``.
    """

    case_id: str
    final_status: CaseStatus
    materiality: MaterialityResult | None
    stages_run: tuple[str, ...]


@dataclass
class _PipelineState:
    """Mutable working state during a single pipeline run."""

    case: Case
    firm_id: str | None
    upstream: dict[str, Any] = field(default_factory=dict)
    stages_run: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------


async def _run_stub_and_persist(
    db: AsyncSession,
    state: _PipelineState,
    *,
    agent_id: str,
) -> StubResult:
    """Run one agent + write its stage row + emit T1 events.

    Cluster 7 chunk 7.1 §3 routing: when the per-agent config flips an
    agent from ``stub`` to ``real``, the call drops into the real-shim
    runtime; otherwise the legacy lookup-stub path runs. Telemetry is
    emitted via either ``stub_dispatched`` (legacy) or
    ``real_agent_dispatched`` (cluster 7+) accordingly.
    """
    try:
        result, telemetry = await dispatch.dispatch_agent(
            case=state.case,
            agent_id=agent_id,
            upstream=state.upstream,
            db=db,
        )
    except AgentDispatchError as exc:
        await emit_event(
            db,
            event_name=agent_event_names.AGENT_UNAVAILABLE_PERSISTENT,
            payload={
                "case_id": state.case.case_id,
                "agent_id": agent_id,
                "retry_count": exc.retry_count,
                "last_error": exc.last_error,
            },
            firm_id=state.firm_id,
        )
        raise PipelineError(
            f"Agent {agent_id!r} unavailable for case "
            f"{state.case.case_id!r} after {exc.retry_count} retries: "
            f"{exc.last_error}",
        ) from exc

    if telemetry is None:
        await emit_event(
            db,
            event_name=event_names.STUB_DISPATCHED,
            payload={
                "case_id": state.case.case_id,
                "agent_id": agent_id,
                "stage_kind": result.stage_kind,
                "produced_via": result.produced_via.value,
            },
            firm_id=state.firm_id,
        )
    else:
        await emit_event(
            db,
            event_name=agent_event_names.REAL_AGENT_DISPATCHED,
            payload={
                "case_id": state.case.case_id,
                "agent_id": agent_id,
                "stage_kind": result.stage_kind,
                "produced_via": result.produced_via.value,
                "retry_count": telemetry.retry_count,
                "cache_hit": telemetry.cache_hit,
                "input_tokens": telemetry.input_tokens,
                "output_tokens": telemetry.output_tokens,
                "model": telemetry.model,
                "prompt_version": telemetry.prompt_version,
            },
            firm_id=state.firm_id,
        )

    if result.stage_kind == StageKind.PORTFOLIO_RISK:
        row = await repository.insert_portfolio_risk_analytics(
            db,
            case_id=state.case.case_id,
            produced_via=result.produced_via.value,
            payload=result.payload,
            is_seed_data=state.case.is_seed_data,
        )
        state.upstream["portfolio_risk_analytics"] = row
    elif result.stage_kind == StageKind.EVIDENCE:
        row = await repository.insert_evidence_verdict(
            db,
            case_id=state.case.case_id,
            agent_id=agent_id,
            produced_via=result.produced_via.value,
            risk_level=result.payload.get("risk_level"),
            confidence=Decimal(str(result.payload.get("confidence") or 0)),
            drivers=result.payload.get("drivers"),
            flags=result.payload.get("flags"),
            structured_output=result.payload.get("structured_output"),
            reasoning_summary=result.payload.get("reasoning_summary"),
            is_seed_data=state.case.is_seed_data,
        )
        state.upstream.setdefault("evidence_verdicts", []).append(row)
    elif result.stage_kind == StageKind.SYNTHESIS:
        row = await repository.insert_synthesis_output(
            db,
            case_id=state.case.case_id,
            output_mode=result.payload.get("output_mode") or result.stage_arg or "case_mode",
            produced_via=result.produced_via.value,
            payload=result.payload,
            is_seed_data=state.case.is_seed_data,
        )
        state.upstream["synthesis"] = row
    elif result.stage_kind == StageKind.IC1:
        row = await repository.insert_ic1_deliberation(
            db,
            case_id=state.case.case_id,
            produced_via=result.produced_via.value,
            minutes=result.payload.get("minutes") or {},
            recommendation=(
                result.payload.get("recommendation")
                or "support_with_conditions"
            ),
            payload=result.payload,
            is_seed_data=state.case.is_seed_data,
        )
        state.upstream["ic1_deliberation"] = row
    elif result.stage_kind == StageKind.GOVERNANCE:
        row = await repository.insert_governance_result(
            db,
            case_id=state.case.case_id,
            gate=result.stage_arg or result.payload.get("gate"),
            produced_via=result.produced_via.value,
            outcome=result.payload.get("outcome") or "approved",
            payload=result.payload,
            is_seed_data=state.case.is_seed_data,
        )
        state.upstream.setdefault("governance_results", []).append(row)
    elif result.stage_kind == StageKind.A1:
        row = await repository.insert_a1_challenge(
            db,
            case_id=state.case.case_id,
            produced_via=result.produced_via.value,
            payload=result.payload,
            is_seed_data=state.case.is_seed_data,
        )
        state.upstream["a1_challenge"] = row
    else:
        raise PipelineError(
            f"Unknown stage_kind {result.stage_kind!r} for agent {agent_id!r}.",
        )

    state.stages_run.append(agent_id)
    await emit_event(
        db,
        event_name=event_names.PIPELINE_STAGE_COMPLETED,
        payload={
            "case_id": state.case.case_id,
            "stage": result.stage_kind,
            "agent_id": agent_id,
        },
        firm_id=state.firm_id,
    )
    return result


async def _transition(
    db: AsyncSession,
    state: _PipelineState,
    *,
    to_status: CaseStatus,
    closed_reason: CaseClosedReason | None = None,
) -> None:
    try:
        await repository.transition_status(
            db,
            case=state.case,
            to_status=to_status,
            closed_reason=closed_reason,
            firm_id=state.firm_id,
        )
    except InvalidStateTransitionError as exc:
        raise PipelineError(
            f"Pipeline failed transitioning {state.case.case_id!r} to "
            f"{to_status.value!r}: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Materiality assembly
# ---------------------------------------------------------------------------


def _build_materiality_input(case: Case) -> MaterialityInput:
    """Assemble the deterministic materiality input from the case row.

    Cluster 5.4 stub layer doesn't compute concentration / proximity /
    amplification from real portfolio data — those upstream signals
    require cluster 7's real M0 portfolio_state + analytics agents.
    For now we use:

    - ``proposed_action_amount_inr`` / ``proposed_action_products`` /
      ``materiality_manual_flag`` from the case row.
    - The other booleans default to ``False`` so the stub layer can
      still demonstrate the rule wiring without real upstream data.
    """
    products = frozenset(
        (case.proposed_action_products or []) if case.proposed_action_products else (),
    )
    return MaterialityInput(
        case_mode=CaseMode(case.case_mode),
        manual_flag=bool(case.materiality_manual_flag),
        proposed_action_amount_inr=(
            Decimal(str(case.proposed_action_amount_inr))
            if case.proposed_action_amount_inr is not None
            else None
        ),
        proposed_action_products=products,
        pushes_concentration_above_threshold=False,
        s1_amplification_flag=False,
        pushes_within_mandate_band_proximity=False,
        largest_single_instrument_exit_inr=None,
    )


async def _record_materiality(
    db: AsyncSession,
    state: _PipelineState,
) -> MaterialityResult:
    """Compute + persist materiality on the case row."""
    inp = _build_materiality_input(state.case)
    result = evaluate_materiality(inp, DEFAULT_MATERIALITY_CONFIG)
    await repository.record_materiality(
        db,
        case=state.case,
        is_material=result.is_material,
        reason=result.reason,
        firm_id=state.firm_id,
    )
    return result


# ---------------------------------------------------------------------------
# Mode-specific runners
# ---------------------------------------------------------------------------


async def _run_evidence_layer(
    db: AsyncSession,
    state: _PipelineState,
) -> None:
    """Run portfolio_risk_analytics + every applicable evidence agent."""
    await _run_stub_and_persist(
        db, state, agent_id="m0_portfolio_risk_analytics",
    )
    for agent_id in state.case.applicable_evidence_agents or []:
        if agent_id not in dispatch.STUB_DISPATCH:
            # Skip unknown agents gracefully; cluster 5.2's registry is
            # the authoritative inventory but not every entry has a
            # stub yet (deferred agents).
            continue
        await _run_stub_and_persist(db, state, agent_id=agent_id)


async def _run_case_mode(
    db: AsyncSession,
    state: _PipelineState,
) -> CaseStatus:
    """Run the proposed_action / scenario pipeline. Stops at
    awaiting_decision."""
    # gathering_evidence → run evidence layer.
    await _run_evidence_layer(db, state)

    # Transition to synthesizing + run S1.
    await _transition(db, state, to_status=CaseStatus.SYNTHESIZING)
    await _run_stub_and_persist(db, state, agent_id="s1_case_mode")

    # Materiality gate.
    materiality_result = await _record_materiality(db, state)

    if materiality_result.is_material:
        await _transition(db, state, to_status=CaseStatus.AWAITING_COMMITTEE)
        await _run_stub_and_persist(db, state, agent_id="ic1_chair")
        await _transition(db, state, to_status=CaseStatus.AWAITING_GOVERNANCE)
    else:
        await _transition(db, state, to_status=CaseStatus.AWAITING_GOVERNANCE)

    # Governance gates (G1, G2, G3 in order).
    for gate_agent in (
        "g1_mandate_gate",
        "g2_sebi_regulatory_gate",
        "g3_action_filter_gate",
    ):
        await _run_stub_and_persist(db, state, agent_id=gate_agent)

    # Challenge.
    await _transition(db, state, to_status=CaseStatus.AWAITING_CHALLENGE)
    await _run_stub_and_persist(db, state, agent_id="a1_challenge")

    # Wait for CIO decision (chunk 5.5).
    await _transition(db, state, to_status=CaseStatus.AWAITING_DECISION)
    return CaseStatus.AWAITING_DECISION


async def _run_diagnostic_mode(
    db: AsyncSession,
    state: _PipelineState,
) -> CaseStatus:
    """diagnostic flow: gathering_evidence → synthesizing →
    awaiting_governance (G1 only) → decided. HealthReport written."""
    await _run_evidence_layer(db, state)

    await _transition(db, state, to_status=CaseStatus.SYNTHESIZING)
    await _run_stub_and_persist(db, state, agent_id="s1_diagnostic_mode")

    # Materiality gate is mode-excluded but record for telemetry parity.
    mat = await _record_materiality(db, state)

    # HealthReport stage row.
    via = dispatch.produced_via_for(state.case)
    seed = dispatch.get_seed_payload_for(state.case)
    from artha.api_v2.cases.stubs import StubContext  # local import to avoid cycle

    health_payload = stub_health_report(
        StubContext(
            case=state.case,
            produced_via=via,
            seed_payload=seed,
            upstream=state.upstream,
        ),
        materiality=mat,
    )
    await repository.insert_health_report(
        db,
        case_id=state.case.case_id,
        produced_via=via.value,
        overall_health=health_payload.get("overall_health") or "healthy",
        payload=health_payload,
        is_seed_data=state.case.is_seed_data,
    )
    state.stages_run.append("health_report")

    # G1 mandate compliance check.
    await _transition(db, state, to_status=CaseStatus.AWAITING_GOVERNANCE)
    await _run_stub_and_persist(db, state, agent_id="g1_mandate_gate")

    # Auto-decided (diagnostic skips committee + challenge + decision form).
    await _transition(
        db,
        state,
        to_status=CaseStatus.DECIDED,
        closed_reason=CaseClosedReason.DECIDED,
    )
    return CaseStatus.DECIDED


async def _run_briefing_mode(
    db: AsyncSession,
    state: _PipelineState,
) -> CaseStatus:
    """briefing flow: gathering_evidence → synthesizing → decided.
    BriefingNote stage row written. Skips governance entirely."""
    await _run_evidence_layer(db, state)

    await _transition(db, state, to_status=CaseStatus.SYNTHESIZING)
    await _run_stub_and_persist(db, state, agent_id="s1_briefing_mode")

    # BriefingNote stage row.
    via = dispatch.produced_via_for(state.case)
    seed = dispatch.get_seed_payload_for(state.case)
    from artha.api_v2.cases.stubs import StubContext

    briefing_payload = stub_briefing_note(
        StubContext(
            case=state.case,
            produced_via=via,
            seed_payload=seed,
            upstream=state.upstream,
        ),
    )
    await repository.insert_briefing_note(
        db,
        case_id=state.case.case_id,
        produced_via=via.value,
        payload=briefing_payload,
        is_seed_data=state.case.is_seed_data,
    )
    state.stages_run.append("briefing_note")

    await _transition(
        db,
        state,
        to_status=CaseStatus.DECIDED,
        closed_reason=CaseClosedReason.DECIDED,
    )
    return CaseStatus.DECIDED


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_pipeline(
    db: AsyncSession,
    *,
    case: Case,
    firm_id: str | None = None,
) -> PipelineRunResult:
    """Run the case through its mode-specific pipeline (synchronous).

    Caller is responsible for:

    - Transaction boundary (case_opener wraps in ``async with db.begin()``).
    - Catching :class:`PipelineError` and transitioning the case to
      ``failed`` for graceful audit trail.

    The pipeline assumes the case is already in
    :attr:`CaseStatus.GATHERING_EVIDENCE` (case_opener moves it there
    after snapshot pinning). It transitions through the remaining
    states per FR 20.1 §1.5 and stops at the mode's natural end-state:

    - case modes → ``awaiting_decision`` (CIO decides in chunk 5.5)
    - diagnostic → ``decided``
    - briefing → ``decided``
    """
    if case.status != CaseStatus.GATHERING_EVIDENCE.value:
        raise PipelineError(
            f"Pipeline expected case status=gathering_evidence; got "
            f"{case.status!r} for case {case.case_id!r}.",
        )

    state = _PipelineState(case=case, firm_id=firm_id)
    mode = CaseMode(case.case_mode)
    materiality_result: MaterialityResult | None = None

    try:
        if mode in {CaseMode.PROPOSED_ACTION, CaseMode.SCENARIO}:
            final = await _run_case_mode(db, state)
            # Re-read materiality from the case row (already persisted).
            materiality_result = MaterialityResult(
                is_material=bool(case.is_material),
                reason=case.materiality_reason or "",
                rules_triggered=(),
            )
        elif mode is CaseMode.DIAGNOSTIC:
            final = await _run_diagnostic_mode(db, state)
        elif mode is CaseMode.BRIEFING:
            final = await _run_briefing_mode(db, state)
        else:  # pragma: no cover — exhaustive
            raise PipelineError(f"Unknown case_mode {mode!r}.")
    except PipelineError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PipelineError(
            f"Pipeline failed for case {case.case_id!r}: {exc}",
        ) from exc

    return PipelineRunResult(
        case_id=case.case_id,
        final_status=final,
        materiality=materiality_result,
        stages_run=tuple(state.stages_run),
    )


__all__ = [
    "PipelineError",
    "PipelineRunResult",
    "run_pipeline",
]
