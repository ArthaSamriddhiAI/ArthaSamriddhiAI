"""Decision recording service (FR Entry 20.4 + FR 20.1 §1.5 terminal).

Single entry point :func:`record_decision` that the ``POST /api/v2/
cases/{id}/decision`` endpoint calls. CIO-only — the router enforces
the permission gate; the service double-checks ``actor.role`` is CIO
to defend against future direct call sites.

Flow (FR 20.4 §3):

1. Load case + verify ``status=awaiting_decision`` (proposed_action /
   scenario only — diagnostic + briefing auto-decide in chunk 5.4).
2. Hydrate every stage row associated with the case.
3. Compute the six-hash bundle via :mod:`.hashing`.
4. Insert :class:`DecisionArtifact` (UNIQUE on case_id; second attempt
   surfaces as :class:`DecisionAlreadyRecordedError`).
5. Transition the case to ``decided`` with
   ``closed_reason='decided'`` (emits ``case_decided`` T1).

Re-recording protection: the UNIQUE constraint on ``case_id`` prevents
double-decisions at the DB layer; this service catches the
``IntegrityError`` and surfaces a friendly error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.cases import event_names, hashing, repository
from artha.api_v2.cases.hashing import DecisionHashBundle
from artha.api_v2.cases.models import (
    A1Challenge,
    DecisionArtifact,
    EvidenceVerdict,
    GovernanceResult,
    IC1Deliberation,
    PortfolioRiskAnalyticsOutput,
    SynthesisOutput,
)
from artha.api_v2.cases.repository import (
    CaseNotFoundError,
    DecisionAlreadyRecordedError,
)
from artha.api_v2.cases.state_machine import (
    CaseClosedReason,
    CaseStatus,
    DecisionVerdict,
)
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DecisionRecordingError(RuntimeError):
    """Base error for decision-recording failures."""


class CaseNotInAwaitingDecisionError(DecisionRecordingError):
    """Case isn't ready for decision (status != awaiting_decision)."""


class NotAuthorisedToDecideError(DecisionRecordingError):
    """Actor isn't a CIO; cluster 5 ships CIO-only decision authority
    per FR 20.4 §7.1."""


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordDecisionRequest:
    """Normalised input to :func:`record_decision`.

    Built by the REST router from ``DecisionRecordRequest``.
    """

    decision: DecisionVerdict | str
    rationale: str
    modifications: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None


@dataclass(frozen=True)
class RecordDecisionResult:
    """Outcome of :func:`record_decision`."""

    artifact: DecisionArtifact
    hashes: DecisionHashBundle


# ---------------------------------------------------------------------------
# ORM → dict helpers (canonical for hashing)
# ---------------------------------------------------------------------------


def _evidence_row_to_dict(row: EvidenceVerdict) -> dict[str, Any]:
    """Stable dict representation used for hashing.

    The hash input must be deterministic across re-reads — we project
    only the schema-required fields and exclude row-internal ids /
    timestamps that can vary per fetch (none today, but keeping the
    projection explicit guards against accidents).
    """
    return {
        "verdict_id": row.verdict_id,
        "case_id": row.case_id,
        "agent_id": row.agent_id,
        "produced_at": row.produced_at,
        "produced_via": row.produced_via,
        "risk_level": row.risk_level,
        "confidence": row.confidence,
        "drivers": row.drivers,
        "flags": row.flags,
        "structured_output": row.structured_output,
        "reasoning_summary": row.reasoning_summary,
        "schema_version": row.schema_version,
    }


def _synthesis_row_to_dict(row: SynthesisOutput) -> dict[str, Any]:
    return {
        "synthesis_id": row.synthesis_id,
        "case_id": row.case_id,
        "produced_at": row.produced_at,
        "produced_via": row.produced_via,
        "output_mode": row.output_mode,
        "consensus": row.consensus,
        "agreement_areas": row.agreement_areas,
        "conflict_areas": row.conflict_areas,
        "uncertainty_flag": row.uncertainty_flag,
        "uncertainty_reasons": row.uncertainty_reasons,
        "amplification": row.amplification,
        "mode_dominance": row.mode_dominance,
        "escalation_recommended": row.escalation_recommended,
        "escalation_reason": row.escalation_reason,
        "counterfactual_framing": row.counterfactual_framing,
        "synthesis_narrative": row.synthesis_narrative,
        "recommendation": row.recommendation,
        "flags": row.flags,
        "reasoning_summary": row.reasoning_summary,
        "schema_version": row.schema_version,
    }


def _governance_row_to_dict(row: GovernanceResult) -> dict[str, Any]:
    return {
        "result_id": row.result_id,
        "case_id": row.case_id,
        "gate": row.gate,
        "produced_at": row.produced_at,
        "produced_via": row.produced_via,
        "outcome": row.outcome,
        "blocking_rule_id": row.blocking_rule_id,
        "blocking_rule_text": row.blocking_rule_text,
        "reasoning": row.reasoning,
        "override_requirements": row.override_requirements,
        "conditions_to_attach": row.conditions_to_attach,
        "rule_corpus_version": row.rule_corpus_version,
        "schema_version": row.schema_version,
    }


def _portfolio_risk_row_to_dict(
    row: PortfolioRiskAnalyticsOutput | None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "output_id": row.output_id,
        "case_id": row.case_id,
        "produced_at": row.produced_at,
        "produced_via": row.produced_via,
        "concentration_assessment": row.concentration_assessment,
        "leverage_assessment": row.leverage_assessment,
        "liquidity_assessment": row.liquidity_assessment,
        "return_quality_assessment": row.return_quality_assessment,
        "deployment_assessment": row.deployment_assessment,
        "cascade_assessment": row.cascade_assessment,
        "overall_risk_level": row.overall_risk_level,
        "overall_confidence": row.overall_confidence,
        "drivers": row.drivers,
        "flags": row.flags,
        "reasoning_summary": row.reasoning_summary,
        "portfolio_analytics_input_hash": row.portfolio_analytics_input_hash,
        "schema_version": row.schema_version,
    }


def _ic1_row_to_dict(row: IC1Deliberation | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "deliberation_id": row.deliberation_id,
        "case_id": row.case_id,
        "produced_at": row.produced_at,
        "produced_via": row.produced_via,
        "chair_summary": row.chair_summary,
        "devils_advocate_position": row.devils_advocate_position,
        "risk_assessment": row.risk_assessment,
        "counterfactual_engine_output": row.counterfactual_engine_output,
        "minutes": row.minutes,
        "dissent": row.dissent,
        "recommendation": row.recommendation,
        "conditions": row.conditions,
        "escalation_to_human": row.escalation_to_human,
        "reasoning_summary": row.reasoning_summary,
        "schema_version": row.schema_version,
    }


def _a1_row_to_dict(row: A1Challenge | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "challenge_id": row.challenge_id,
        "case_id": row.case_id,
        "produced_at": row.produced_at,
        "produced_via": row.produced_via,
        "counter_arguments": row.counter_arguments,
        "alternative_proposals": row.alternative_proposals,
        "stress_test_scenarios": row.stress_test_scenarios,
        "edge_cases": row.edge_cases,
        "accountability_flags": row.accountability_flags,
        "reasoning_summary": row.reasoning_summary,
        "schema_version": row.schema_version,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compute_hashes_for_case(
    db: AsyncSession,
    *,
    case_id: str,
) -> DecisionHashBundle:
    """Hydrate stage rows and compute the six-hash bundle for ``case_id``.

    Surfaced as a public helper so audit-replay code (cluster 17) can
    re-compute hashes from the persisted rows and compare against the
    decision_artifact to detect tampering.
    """
    evidence = await repository.list_evidence_verdicts(db, case_id=case_id)
    synthesis = await repository.get_synthesis(db, case_id=case_id)
    governance = await repository.list_governance_results(db, case_id=case_id)
    portfolio_risk = await repository.get_portfolio_risk_analytics(
        db, case_id=case_id,
    )
    ic1 = await repository.get_ic1_deliberation(db, case_id=case_id)
    a1 = await repository.get_a1_challenge(db, case_id=case_id)

    if synthesis is None:
        raise DecisionRecordingError(
            f"Case {case_id!r} has no synthesis row; cannot record decision.",
        )

    return hashing.compute_decision_hashes(
        evidence_rows=[_evidence_row_to_dict(e) for e in evidence],
        synthesis_row=_synthesis_row_to_dict(synthesis),
        governance_rows=[_governance_row_to_dict(g) for g in governance],
        portfolio_risk_row=_portfolio_risk_row_to_dict(portfolio_risk),
        ic1_row=_ic1_row_to_dict(ic1),
        a1_row=_a1_row_to_dict(a1),
    )


async def record_decision(
    db: AsyncSession,
    *,
    case_id: str,
    request: RecordDecisionRequest,
    actor: UserContext,
) -> RecordDecisionResult:
    """Record the CIO's decision on a case (FR 20.4 §3).

    Caller wraps in ``async with db.begin():``. On success, returns a
    :class:`RecordDecisionResult` containing the persisted artifact +
    the freshly computed hashes.
    """
    if actor.role is not Role.CIO:
        raise NotAuthorisedToDecideError(
            "Decision recording is CIO-only (FR 20.4 §7.1).",
        )

    case = await repository.get_case(db, case_id=case_id)
    if case is None:
        raise CaseNotFoundError(f"Case {case_id!r} not found.")
    if case.status != CaseStatus.AWAITING_DECISION.value:
        raise CaseNotInAwaitingDecisionError(
            f"Case {case_id!r} is in {case.status!r}; decisions can only be "
            f"recorded from {CaseStatus.AWAITING_DECISION.value!r}.",
        )

    decision_value = (
        DecisionVerdict(request.decision).value
        if isinstance(request.decision, str)
        else request.decision.value
    )

    bundle = await compute_hashes_for_case(db, case_id=case_id)

    try:
        artifact = await repository.insert_decision_artifact(
            db,
            case_id=case_id,
            decided_by=actor.user_id,
            decision=decision_value,
            rationale=request.rationale,
            evidence_packet_hash=bundle.evidence_packet_hash,
            synthesis_hash=bundle.synthesis_hash,
            governance_packet_hash=bundle.governance_packet_hash,
            portfolio_risk_hash=bundle.portfolio_risk_hash,
            ic1_hash=bundle.ic1_hash,
            a1_hash=bundle.a1_hash,
            modifications=request.modifications,
            conditions=request.conditions,
            is_seed_data=case.is_seed_data,
        )
    except DecisionAlreadyRecordedError:
        # Re-raise so the router maps to 409.
        raise

    # Transition case to decided. Failures here are unusual but possible
    # (e.g. case got archived in flight); surface as DecisionRecordingError
    # so the wrapping transaction rolls back the artifact insert.
    try:
        await repository.transition_status(
            db,
            case=case,
            to_status=CaseStatus.DECIDED,
            closed_reason=CaseClosedReason.DECIDED,
            firm_id=actor.firm_id,
        )
    except Exception as exc:  # noqa: BLE001
        await emit_event(
            db,
            event_name=event_names.CASE_DECISION_RECORDING_FAILED,
            payload={
                "case_id": case_id,
                "error": str(exc),
                "stage": "post_artifact_transition",
            },
            firm_id=actor.firm_id,
        )
        raise DecisionRecordingError(
            f"Decision artifact written but transition to decided failed: {exc}",
        ) from exc

    return RecordDecisionResult(artifact=artifact, hashes=bundle)


__all__ = [
    "CaseNotInAwaitingDecisionError",
    "DecisionRecordingError",
    "NotAuthorisedToDecideError",
    "RecordDecisionRequest",
    "RecordDecisionResult",
    "compute_hashes_for_case",
    "record_decision",
]
