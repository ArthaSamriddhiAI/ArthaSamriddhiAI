"""Cases REST router — chunk 5.3 surface.

Endpoints:

- ``POST /api/v2/cases``                 — create + open a case
- ``GET  /api/v2/cases``                 — list cases visible to actor
- ``GET  /api/v2/cases/{case_id}``       — fetch one case (CaseRead)
- ``GET  /api/v2/cases/{case_id}/detail`` — fetch case + every stage row
  (chunk 5.5 case detail UI; surfaced now in shell form so the contract
  is stable)

Permission gates:

- Read: ``cases:read:own_book`` OR ``cases:read:firm_scope`` (mode=any).
  The service applies advisor-scope filter by ``assigned_to``.
- Create: ``cases:create:own_book`` (advisor) OR
  ``cases:create:firm_scope`` (CIO).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.cases import case_opener, repository
from artha.api_v2.cases.case_opener import (
    CaseOpeningError,
    InvalidCaseModeError,
    InvestorNotFoundError,
    InvestorScopeError,
    OpenCaseDeps,
    OpenCaseRequest,
)
from artha.api_v2.cases.schemas import (
    A1ChallengeRead,
    BriefingNoteRead,
    CaseCreateRequest,
    CaseDetailResponse,
    CaseListResponse,
    CaseRead,
    DecisionArtifactRead,
    EvidenceVerdictRead,
    GovernanceResultRead,
    HealthReportRead,
    IC1DeliberationRead,
    PortfolioRiskAnalyticsRead,
    SynthesisOutputRead,
)
from artha.api_v2.m0.boss import boss as m0_boss
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/cases", tags=["cases"])


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


def _read_perms_any():
    return Depends(
        require_permission(
            Permission.CASES_READ_OWN_BOOK,
            Permission.CASES_READ_FIRM_SCOPE,
            mode="any",
        ),
    )


def _create_perms_any():
    return Depends(
        require_permission(
            Permission.CASES_CREATE_OWN_BOOK,
            Permission.CASES_CREATE_FIRM_SCOPE,
            mode="any",
        ),
    )


# ---------------------------------------------------------------------------
# Read shape adapter
# ---------------------------------------------------------------------------


def _to_case_read(row) -> CaseRead:  # noqa: ANN001
    return CaseRead(
        case_id=row.case_id,
        investor_id=row.investor_id,
        household_id=row.household_id,
        opened_by=row.opened_by,
        assigned_to=row.assigned_to,
        case_mode=row.case_mode,
        case_intent=row.case_intent,
        dominant_lens=row.dominant_lens,
        proposed_action=row.proposed_action,
        proposed_action_amount_inr=(
            Decimal(str(row.proposed_action_amount_inr))
            if row.proposed_action_amount_inr is not None
            else None
        ),
        proposed_action_products=list(row.proposed_action_products or []),
        materiality_manual_flag=bool(row.materiality_manual_flag),
        status=row.status,
        status_changed_at=row.status_changed_at,
        snapshot_bundle_id=row.snapshot_bundle_id,
        materiality_assessed_at=row.materiality_assessed_at,
        is_material=row.is_material,
        materiality_reason=row.materiality_reason,
        total_llm_cost_inr=Decimal(str(row.total_llm_cost_inr or 0)),
        total_llm_input_tokens=int(row.total_llm_input_tokens or 0),
        total_llm_output_tokens=int(row.total_llm_output_tokens or 0),
        created_at=row.created_at,
        created_via=row.created_via,
        closed_at=row.closed_at,
        closed_reason=row.closed_reason,
        applicable_evidence_agents=list(row.applicable_evidence_agents or []),
        supersedes_case_id=row.supersedes_case_id,
        is_seed_data=bool(row.is_seed_data),
        seed_archetype_id=row.seed_archetype_id,
        schema_version=int(row.schema_version),
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@router.get("", response_model=CaseListResponse)
async def list_cases(
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
    investor_id: Annotated[str | None, Query()] = None,
    assigned_to: Annotated[str | None, Query()] = None,
    case_status: Annotated[str | None, Query(alias="status")] = None,
    case_mode: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CaseListResponse:
    # Advisors only see their own book — force the assigned_to filter.
    effective_assigned_to = assigned_to
    if actor.role is Role.ADVISOR:
        effective_assigned_to = actor.user_id
    rows, total = await repository.list_cases(
        db,
        investor_id=investor_id,
        assigned_to=effective_assigned_to,
        status=case_status,
        case_mode=case_mode,
        limit=limit,
        offset=offset,
    )
    return CaseListResponse(
        cases=[_to_case_read(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{case_id}", response_model=CaseRead)
async def get_case(
    case_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    row = await repository.get_case(db, case_id=case_id)
    if row is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Case not found",
            detail=f"Case {case_id!r} does not exist.",
        )
    if actor.role is Role.ADVISOR and row.assigned_to != actor.user_id:
        return problem_response(
            status=status.HTTP_403_FORBIDDEN,
            title="Out of scope",
            detail=(
                f"Case {case_id!r} is outside your own book. Ask the "
                f"assigned advisor or your CIO."
            ),
        )
    return _to_case_read(row)


@router.get("/{case_id}/detail", response_model=CaseDetailResponse)
async def get_case_detail(
    case_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    row = await repository.get_case(db, case_id=case_id)
    if row is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Case not found",
            detail=f"Case {case_id!r} does not exist.",
        )
    if actor.role is Role.ADVISOR and row.assigned_to != actor.user_id:
        return problem_response(
            status=status.HTTP_403_FORBIDDEN,
            title="Out of scope",
            detail=(
                f"Case {case_id!r} is outside your own book. Ask the "
                f"assigned advisor or your CIO."
            ),
        )

    # Hydrate every stage row.
    evidence = await repository.list_evidence_verdicts(db, case_id=case_id)
    risk = await repository.get_portfolio_risk_analytics(db, case_id=case_id)
    synth = await repository.get_synthesis(db, case_id=case_id)
    ic1 = await repository.get_ic1_deliberation(db, case_id=case_id)
    governance = await repository.list_governance_results(db, case_id=case_id)
    a1 = await repository.get_a1_challenge(db, case_id=case_id)
    decision = await repository.get_decision_artifact(db, case_id=case_id)
    briefing = await repository.get_briefing_note(db, case_id=case_id)
    health = await repository.get_health_report(db, case_id=case_id)

    return CaseDetailResponse(
        case=_to_case_read(row),
        evidence_verdicts=[
            EvidenceVerdictRead.model_validate(v, from_attributes=True)
            for v in evidence
        ],
        portfolio_risk_analytics=(
            PortfolioRiskAnalyticsRead.model_validate(risk, from_attributes=True)
            if risk
            else None
        ),
        synthesis=(
            SynthesisOutputRead.model_validate(synth, from_attributes=True)
            if synth
            else None
        ),
        ic1_deliberation=(
            IC1DeliberationRead.model_validate(ic1, from_attributes=True)
            if ic1
            else None
        ),
        governance_results=[
            GovernanceResultRead.model_validate(g, from_attributes=True)
            for g in governance
        ],
        a1_challenge=(
            A1ChallengeRead.model_validate(a1, from_attributes=True)
            if a1
            else None
        ),
        decision_artifact=(
            DecisionArtifactRead.model_validate(decision, from_attributes=True)
            if decision
            else None
        ),
        briefing_note=(
            BriefingNoteRead.model_validate(briefing, from_attributes=True)
            if briefing
            else None
        ),
        health_report=(
            HealthReportRead.model_validate(health, from_attributes=True)
            if health
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_case(
    body: CaseCreateRequest,
    actor: Annotated[UserContext, _create_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    # CIO-only check on the manual override field.
    if body.manual_override_evidence_agents is not None and actor.role is not Role.CIO:
        return problem_response(
            status=status.HTTP_403_FORBIDDEN,
            title="Manual evidence-agent override is CIO-only",
            detail=(
                "Only the CIO role can override the M0 router's evidence-agent "
                "selection."
            ),
        )

    request = OpenCaseRequest(
        investor_id=body.investor_id,
        case_mode=body.case_mode,
        case_intent=body.case_intent,
        dominant_lens=body.dominant_lens,
        proposed_action=body.proposed_action,
        proposed_action_amount_inr=body.proposed_action_amount_inr,
        proposed_action_products=tuple(body.proposed_action_products),
        materiality_manual_flag=body.materiality_manual_flag,
        supersedes_case_id=body.supersedes_case_id,
        manual_override_evidence_agents=(
            tuple(body.manual_override_evidence_agents)
            if body.manual_override_evidence_agents is not None
            else None
        ),
        created_via="api",
    )

    try:
        async with db.begin():
            result = await case_opener.open_case(
                db,
                request,
                actor=actor,
                deps=OpenCaseDeps(boss=m0_boss),
            )
    except InvestorNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Investor not found",
            detail=str(exc),
        )
    except InvestorScopeError as exc:
        return problem_response(
            status=status.HTTP_403_FORBIDDEN,
            title="Investor outside own book",
            detail=str(exc),
        )
    except InvalidCaseModeError as exc:
        return problem_response(
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid case mode / intent combination",
            detail=str(exc),
        )
    except CaseOpeningError as exc:
        return problem_response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Case opening failed",
            detail=str(exc),
        )

    # Re-fetch in a fresh read so the returned shape reflects the
    # gathering_evidence transition committed inside the begin block.
    row = await repository.get_case(db, case_id=result.case.case_id)
    return _to_case_read(row)
