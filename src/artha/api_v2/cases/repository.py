"""Case repository — CRUD + transition + snapshot helpers.

Thin SQLAlchemy layer the chunk 5.3 case-creator + chunk 5.5 decision
recorder consume. Pure DB access; orchestration logic lives in
``case_creator.py`` (chunk 5.3).

Key invariants enforced here:

- Status transitions go through :func:`transition_status`, which calls
  the FR 20.1 §1.5 validator first and emits the
  ``case_status_transition`` T1 event after the row update.
- ``snapshot_bundle_id`` immutability: once non-null, subsequent
  attempts to update it raise :class:`SnapshotAlreadyPinnedError`. The
  spec recommends a DB trigger; we enforce in code instead so the
  schema stays portable across SQLite + Postgres.
- Decision artifact creation is single-shot (UNIQUE on ``case_id``
  enforces at the DB layer; the repository raises
  :class:`DecisionAlreadyRecordedError` for the friendly message path).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.cases import event_names
from artha.api_v2.cases.models import (
    A1Challenge,
    BriefingNote,
    Case,
    DecisionArtifact,
    EvidenceVerdict,
    GovernanceResult,
    HealthReport,
    IC1Deliberation,
    PortfolioRiskAnalyticsOutput,
    SynthesisOutput,
)
from artha.api_v2.cases.state_machine import (
    CaseClosedReason,
    CaseStatus,
    InvalidStateTransitionError,
    is_terminal,
    validate_transition,
)
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CaseNotFoundError(KeyError):
    """No case with the given id."""


class SnapshotAlreadyPinnedError(RuntimeError):
    """Attempt to overwrite a non-null snapshot_bundle_id (FR 20.1 §4.1)."""


class TerminalStateMutationError(RuntimeError):
    """Attempt to modify a case in a terminal state (decided / archived /
    failed)."""


class DecisionAlreadyRecordedError(RuntimeError):
    """A decision_artifact already exists for this case (UNIQUE on case_id)."""


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


async def get_case(db: AsyncSession, *, case_id: str) -> Case | None:
    return (
        await db.execute(select(Case).where(Case.case_id == case_id))
    ).scalar_one_or_none()


async def list_cases(
    db: AsyncSession,
    *,
    investor_id: str | None = None,
    assigned_to: str | None = None,
    status: str | None = None,
    case_mode: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Case], int]:
    """Filter + paginate cases. Returns ``(rows, total)``."""
    base = select(Case)
    count_base = select(func.count()).select_from(Case)
    filters = []
    if investor_id is not None:
        filters.append(Case.investor_id == investor_id)
    if assigned_to is not None:
        filters.append(Case.assigned_to == assigned_to)
    if status is not None:
        filters.append(Case.status == status)
    if case_mode is not None:
        filters.append(Case.case_mode == case_mode)
    if filters:
        base = base.where(*filters)
        count_base = count_base.where(*filters)
    base = (
        base.order_by(Case.created_at.desc())
        .limit(min(max(1, limit), 500))
        .offset(max(0, offset))
    )
    rows = list((await db.execute(base)).scalars())
    total = int((await db.execute(count_base)).scalar_one() or 0)
    return rows, total


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


async def create_case(
    db: AsyncSession,
    *,
    investor_id: str,
    household_id: str | None,
    opened_by: str,
    assigned_to: str,
    case_mode: str,
    case_intent: str | None,
    dominant_lens: str | None,
    proposed_action: str | None,
    proposed_action_amount_inr: Any | None,
    proposed_action_products: list[str],
    materiality_manual_flag: bool,
    created_via: str,
    applicable_evidence_agents: list[str],
    is_seed_data: bool = False,
    seed_archetype_id: str | None = None,
    supersedes_case_id: str | None = None,
    firm_id: str | None = None,
    case_id: str | None = None,
) -> Case:
    """Insert a new Case row in ``opening`` status.

    Snapshot pinning happens via :func:`update_snapshot_bundle` after
    the SnapshotAssembler returns. T1 emits ``case_created``.

    ``case_id`` defaults to a fresh ULID. Cluster 6 stage 3 passes a
    stable string (e.g. ``case_arch01_a``) for seeded cases so the
    dispatcher's case_id-keyed seed-payload lookup matches.
    """
    now = datetime.now(timezone.utc)
    row = Case(
        case_id=case_id or str(ULID()),
        investor_id=investor_id,
        household_id=household_id,
        opened_by=opened_by,
        assigned_to=assigned_to,
        case_mode=case_mode,
        case_intent=case_intent,
        dominant_lens=dominant_lens,
        proposed_action=proposed_action,
        proposed_action_amount_inr=proposed_action_amount_inr,
        proposed_action_products=list(proposed_action_products),
        materiality_manual_flag=materiality_manual_flag,
        status=CaseStatus.OPENING.value,
        status_changed_at=now,
        created_at=now,
        created_via=created_via,
        applicable_evidence_agents=list(applicable_evidence_agents),
        supersedes_case_id=supersedes_case_id,
        is_seed_data=is_seed_data,
        seed_archetype_id=seed_archetype_id,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    await emit_event(
        db,
        event_name=event_names.CASE_CREATED,
        payload={
            "case_id": row.case_id,
            "investor_id": investor_id,
            "case_mode": case_mode,
            "case_intent": case_intent,
            "created_via": created_via,
            "is_seed_data": is_seed_data,
        },
        firm_id=firm_id,
    )
    return row


async def update_snapshot_bundle(
    db: AsyncSession,
    *,
    case: Case,
    snapshot_bundle_id: str,
    firm_id: str | None = None,
) -> Case:
    """Pin a snapshot bundle to a case (FR 20.1 §5.2 step 5).

    Once set, attempts to set a different value raise
    :class:`SnapshotAlreadyPinnedError`. Re-setting the same value is
    idempotent (no-op + no event).
    """
    if case.snapshot_bundle_id is not None:
        if case.snapshot_bundle_id == snapshot_bundle_id:
            return case
        raise SnapshotAlreadyPinnedError(
            f"Case {case.case_id!r} already has snapshot_bundle_id="
            f"{case.snapshot_bundle_id!r}; cannot overwrite with "
            f"{snapshot_bundle_id!r} (FR 20.1 §4.1 immutability)."
        )
    case.snapshot_bundle_id = snapshot_bundle_id
    await db.flush()
    await emit_event(
        db,
        event_name=event_names.CASE_CREATION_SNAPSHOT_PINNED,
        payload={
            "case_id": case.case_id,
            "snapshot_bundle_id": snapshot_bundle_id,
        },
        firm_id=firm_id,
    )
    return case


async def transition_status(
    db: AsyncSession,
    *,
    case: Case,
    to_status: CaseStatus | str,
    closed_reason: CaseClosedReason | str | None = None,
    firm_id: str | None = None,
) -> Case:
    """Transition a case's status with FR 20.1 §1.5 validation.

    Emits ``case_status_transition`` (and ``case_decided`` /
    ``case_failed`` / ``case_archived`` for terminal states). Validates
    via the pure state-machine helper; raises
    :class:`InvalidStateTransitionError` on failure.

    ``closed_reason`` is required for terminal transitions
    (decided / archived / failed) and ignored otherwise.
    """
    src = case.status
    target = (
        CaseStatus(to_status) if isinstance(to_status, str) else to_status
    )
    # Raises InvalidStateTransitionError on bad transition; pass through.
    validate_transition(
        from_state=src,
        to_state=target,
        case_mode=case.case_mode,
    )

    if is_terminal(target):
        if closed_reason is None:
            raise InvalidStateTransitionError(
                from_state=src,
                to_state=target.value,
                case_mode=case.case_mode,
                reason=(
                    f"Terminal transition to {target.value!r} requires a "
                    "closed_reason (decided / withdrawn / superseded / "
                    "archived / failed)."
                ),
            )

    now = datetime.now(timezone.utc)
    case.status = target.value
    case.status_changed_at = now
    if is_terminal(target):
        case.closed_at = now
        case.closed_reason = (
            closed_reason.value
            if isinstance(closed_reason, CaseClosedReason)
            else closed_reason
        )
    await db.flush()

    payload = {
        "case_id": case.case_id,
        "from": src,
        "to": target.value,
        "case_mode": case.case_mode,
    }
    await emit_event(
        db,
        event_name=event_names.CASE_STATUS_TRANSITION,
        payload=payload,
        firm_id=firm_id,
    )

    if target == CaseStatus.DECIDED:
        await emit_event(
            db,
            event_name=event_names.CASE_DECIDED,
            payload=payload,
            firm_id=firm_id,
        )
    elif target == CaseStatus.FAILED:
        await emit_event(
            db,
            event_name=event_names.CASE_FAILED,
            payload=payload,
            firm_id=firm_id,
        )
    elif target == CaseStatus.ARCHIVED:
        await emit_event(
            db,
            event_name=event_names.CASE_ARCHIVED,
            payload=payload,
            firm_id=firm_id,
        )

    return case


async def record_materiality(
    db: AsyncSession,
    *,
    case: Case,
    is_material: bool,
    reason: str,
    firm_id: str | None = None,
) -> Case:
    """Persist the materiality gate's verdict on the case row + emit T1."""
    now = datetime.now(timezone.utc)
    case.is_material = is_material
    case.materiality_reason = reason
    case.materiality_assessed_at = now
    await db.flush()
    await emit_event(
        db,
        event_name=event_names.CASE_MATERIALITY_ASSESSED,
        payload={
            "case_id": case.case_id,
            "is_material": is_material,
            "reason": reason,
            "case_mode": case.case_mode,
        },
        firm_id=firm_id,
    )
    return case


# ---------------------------------------------------------------------------
# Stage table inserts (chunk 5.4 / 5.5 use these via the dispatch layer)
# ---------------------------------------------------------------------------


async def insert_evidence_verdict(
    db: AsyncSession,
    *,
    case_id: str,
    agent_id: str,
    produced_via: str,
    risk_level: str | None = None,
    confidence: Any | None = None,
    drivers: dict[str, Any] | None = None,
    flags: dict[str, Any] | None = None,
    structured_output: dict[str, Any] | None = None,
    reasoning_summary: str | None = None,
    is_seed_data: bool = False,
) -> EvidenceVerdict:
    row = EvidenceVerdict(
        verdict_id=str(ULID()),
        case_id=case_id,
        agent_id=agent_id,
        produced_at=datetime.now(timezone.utc),
        produced_via=produced_via,
        risk_level=risk_level,
        confidence=confidence,
        drivers=drivers,
        flags=flags,
        structured_output=structured_output,
        reasoning_summary=reasoning_summary,
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def insert_synthesis_output(
    db: AsyncSession,
    *,
    case_id: str,
    output_mode: str,
    produced_via: str,
    payload: dict[str, Any] | None = None,
    is_seed_data: bool = False,
) -> SynthesisOutput:
    payload = payload or {}
    row = SynthesisOutput(
        synthesis_id=str(ULID()),
        case_id=case_id,
        produced_at=datetime.now(timezone.utc),
        produced_via=produced_via,
        output_mode=output_mode,
        consensus=payload.get("consensus"),
        agreement_areas=payload.get("agreement_areas"),
        conflict_areas=payload.get("conflict_areas"),
        uncertainty_flag=payload.get("uncertainty_flag"),
        uncertainty_reasons=payload.get("uncertainty_reasons"),
        amplification=payload.get("amplification"),
        mode_dominance=payload.get("mode_dominance"),
        escalation_recommended=payload.get("escalation_recommended"),
        escalation_reason=payload.get("escalation_reason"),
        counterfactual_framing=payload.get("counterfactual_framing"),
        synthesis_narrative=payload.get("synthesis_narrative"),
        recommendation=payload.get("recommendation"),
        flags=payload.get("flags"),
        reasoning_summary=payload.get("reasoning_summary"),
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def insert_portfolio_risk_analytics(
    db: AsyncSession,
    *,
    case_id: str,
    produced_via: str,
    payload: dict[str, Any] | None = None,
    is_seed_data: bool = False,
) -> PortfolioRiskAnalyticsOutput:
    payload = payload or {}
    row = PortfolioRiskAnalyticsOutput(
        output_id=str(ULID()),
        case_id=case_id,
        produced_at=datetime.now(timezone.utc),
        produced_via=produced_via,
        concentration_assessment=payload.get("concentration_assessment"),
        leverage_assessment=payload.get("leverage_assessment"),
        liquidity_assessment=payload.get("liquidity_assessment"),
        return_quality_assessment=payload.get("return_quality_assessment"),
        deployment_assessment=payload.get("deployment_assessment"),
        cascade_assessment=payload.get("cascade_assessment"),
        overall_risk_level=payload.get("overall_risk_level"),
        overall_confidence=payload.get("overall_confidence"),
        drivers=payload.get("drivers"),
        flags=payload.get("flags"),
        reasoning_summary=payload.get("reasoning_summary"),
        portfolio_analytics_input_hash=payload.get("portfolio_analytics_input_hash"),
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def insert_ic1_deliberation(
    db: AsyncSession,
    *,
    case_id: str,
    produced_via: str,
    minutes: dict[str, Any],
    recommendation: str,
    payload: dict[str, Any] | None = None,
    is_seed_data: bool = False,
) -> IC1Deliberation:
    payload = payload or {}
    row = IC1Deliberation(
        deliberation_id=str(ULID()),
        case_id=case_id,
        produced_at=datetime.now(timezone.utc),
        produced_via=produced_via,
        chair_summary=payload.get("chair_summary"),
        devils_advocate_position=payload.get("devils_advocate_position"),
        risk_assessment=payload.get("risk_assessment"),
        counterfactual_engine_output=payload.get("counterfactual_engine_output"),
        minutes=minutes,
        dissent=payload.get("dissent"),
        recommendation=recommendation,
        conditions=payload.get("conditions"),
        escalation_to_human=True,
        reasoning_summary=payload.get("reasoning_summary"),
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def insert_governance_result(
    db: AsyncSession,
    *,
    case_id: str,
    gate: str,
    produced_via: str,
    outcome: str,
    payload: dict[str, Any] | None = None,
    is_seed_data: bool = False,
) -> GovernanceResult:
    payload = payload or {}
    row = GovernanceResult(
        result_id=str(ULID()),
        case_id=case_id,
        gate=gate,
        produced_at=datetime.now(timezone.utc),
        produced_via=produced_via,
        outcome=outcome,
        blocking_rule_id=payload.get("blocking_rule_id"),
        blocking_rule_text=payload.get("blocking_rule_text"),
        reasoning=payload.get("reasoning"),
        override_requirements=payload.get("override_requirements"),
        conditions_to_attach=payload.get("conditions_to_attach"),
        rule_corpus_version=payload.get("rule_corpus_version"),
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def insert_a1_challenge(
    db: AsyncSession,
    *,
    case_id: str,
    produced_via: str,
    payload: dict[str, Any] | None = None,
    is_seed_data: bool = False,
) -> A1Challenge:
    payload = payload or {}
    row = A1Challenge(
        challenge_id=str(ULID()),
        case_id=case_id,
        produced_at=datetime.now(timezone.utc),
        produced_via=produced_via,
        counter_arguments=payload.get("counter_arguments"),
        alternative_proposals=payload.get("alternative_proposals"),
        stress_test_scenarios=payload.get("stress_test_scenarios"),
        edge_cases=payload.get("edge_cases"),
        accountability_flags=payload.get("accountability_flags"),
        reasoning_summary=payload.get("reasoning_summary"),
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def insert_briefing_note(
    db: AsyncSession,
    *,
    case_id: str,
    produced_via: str,
    payload: dict[str, Any] | None = None,
    is_seed_data: bool = False,
) -> BriefingNote:
    payload = payload or {}
    row = BriefingNote(
        briefing_id=str(ULID()),
        case_id=case_id,
        produced_at=datetime.now(timezone.utc),
        produced_via=produced_via,
        meeting_context=payload.get("meeting_context"),
        recent_activity_summary=payload.get("recent_activity_summary"),
        current_state_summary=payload.get("current_state_summary"),
        market_context=payload.get("market_context"),
        prep_questions=payload.get("prep_questions"),
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


async def insert_health_report(
    db: AsyncSession,
    *,
    case_id: str,
    produced_via: str,
    overall_health: str,
    payload: dict[str, Any] | None = None,
    is_seed_data: bool = False,
) -> HealthReport:
    payload = payload or {}
    row = HealthReport(
        report_id=str(ULID()),
        case_id=case_id,
        produced_at=datetime.now(timezone.utc),
        produced_via=produced_via,
        overall_health=overall_health,
        asset_allocation_status=payload.get("asset_allocation_status"),
        performance_summary=payload.get("performance_summary"),
        drift_indicators=payload.get("drift_indicators"),
        recommendations=payload.get("recommendations"),
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Decision artifact insert (chunk 5.5)
# ---------------------------------------------------------------------------


async def insert_decision_artifact(
    db: AsyncSession,
    *,
    case_id: str,
    decided_by: str,
    decision: str,
    rationale: str,
    evidence_packet_hash: str,
    synthesis_hash: str,
    governance_packet_hash: str,
    portfolio_risk_hash: str | None = None,
    ic1_hash: str | None = None,
    a1_hash: str | None = None,
    modifications: dict[str, Any] | None = None,
    conditions: dict[str, Any] | None = None,
    is_seed_data: bool = False,
) -> DecisionArtifact:
    """Insert the immutable decision artifact for a case.

    Caller is responsible for transitioning case status to ``decided``
    via :func:`transition_status` (which emits ``case_decided``). The
    UNIQUE constraint on case_id raises :class:`IntegrityError` if a
    second artifact is attempted; we re-raise as
    :class:`DecisionAlreadyRecordedError` for the friendly path.
    """
    row = DecisionArtifact(
        artifact_id=str(ULID()),
        case_id=case_id,
        decided_at=datetime.now(timezone.utc),
        decided_by=decided_by,
        decision=decision,
        modifications=modifications,
        rationale=rationale,
        conditions=conditions,
        evidence_packet_hash=evidence_packet_hash,
        synthesis_hash=synthesis_hash,
        governance_packet_hash=governance_packet_hash,
        portfolio_risk_hash=portfolio_risk_hash,
        ic1_hash=ic1_hash,
        a1_hash=a1_hash,
        is_seed_data=is_seed_data,
        schema_version=1,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise DecisionAlreadyRecordedError(
            f"Case {case_id!r} already has a decision artifact."
        ) from exc
    return row


async def get_decision_artifact(
    db: AsyncSession, *, case_id: str
) -> DecisionArtifact | None:
    return (
        await db.execute(
            select(DecisionArtifact).where(DecisionArtifact.case_id == case_id)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Stage table reads
# ---------------------------------------------------------------------------


async def list_evidence_verdicts(
    db: AsyncSession, *, case_id: str
) -> list[EvidenceVerdict]:
    """Ordered by ``(agent_id, produced_at)`` per FR 20.1 §4.3 hash spec."""
    return list(
        (
            await db.execute(
                select(EvidenceVerdict)
                .where(EvidenceVerdict.case_id == case_id)
                .order_by(EvidenceVerdict.agent_id, EvidenceVerdict.produced_at)
            )
        ).scalars()
    )


async def get_synthesis(
    db: AsyncSession, *, case_id: str
) -> SynthesisOutput | None:
    return (
        await db.execute(
            select(SynthesisOutput).where(SynthesisOutput.case_id == case_id)
        )
    ).scalar_one_or_none()


async def list_governance_results(
    db: AsyncSession, *, case_id: str
) -> list[GovernanceResult]:
    """Ordered by ``gate`` per FR 20.1 §4.3 hash spec."""
    return list(
        (
            await db.execute(
                select(GovernanceResult)
                .where(GovernanceResult.case_id == case_id)
                .order_by(GovernanceResult.gate)
            )
        ).scalars()
    )


async def get_portfolio_risk_analytics(
    db: AsyncSession, *, case_id: str
) -> PortfolioRiskAnalyticsOutput | None:
    return (
        await db.execute(
            select(PortfolioRiskAnalyticsOutput).where(
                PortfolioRiskAnalyticsOutput.case_id == case_id
            )
        )
    ).scalar_one_or_none()


async def get_ic1_deliberation(
    db: AsyncSession, *, case_id: str
) -> IC1Deliberation | None:
    return (
        await db.execute(
            select(IC1Deliberation).where(IC1Deliberation.case_id == case_id)
        )
    ).scalar_one_or_none()


async def get_a1_challenge(db: AsyncSession, *, case_id: str) -> A1Challenge | None:
    return (
        await db.execute(
            select(A1Challenge).where(A1Challenge.case_id == case_id)
        )
    ).scalar_one_or_none()


async def get_briefing_note(db: AsyncSession, *, case_id: str) -> BriefingNote | None:
    return (
        await db.execute(
            select(BriefingNote).where(BriefingNote.case_id == case_id)
        )
    ).scalar_one_or_none()


async def get_health_report(db: AsyncSession, *, case_id: str) -> HealthReport | None:
    return (
        await db.execute(
            select(HealthReport).where(HealthReport.case_id == case_id)
        )
    ).scalar_one_or_none()
