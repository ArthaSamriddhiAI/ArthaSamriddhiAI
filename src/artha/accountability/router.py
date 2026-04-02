"""FastAPI endpoints for the Accountability layer."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session
from artha.accountability.approval.models import ApprovalRecord
from artha.accountability.audit.reconstructor import AuditReconstruction
from artha.accountability.schemas import SubmitApprovalRequest
from artha.accountability.service import AccountabilityService
from artha.accountability.trace.models import DecisionTrace

router = APIRouter(prefix="/accountability", tags=["accountability"])


def _get_service(session: AsyncSession = Depends(get_session)) -> AccountabilityService:
    return AccountabilityService(session)


@router.get("/decisions", response_model=list[str])
async def list_decisions(
    limit: int = 50,
    service: AccountabilityService = Depends(_get_service),
):
    return await service.list_decisions(limit)


@router.get("/decisions/summary")
async def list_decisions_summary(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Return rich decision summaries with status, type, timestamps, and client info."""
    import json
    from sqlalchemy import select
    from artha.governance.models import GovernanceDecisionRow

    stmt = (
        select(GovernanceDecisionRow)
        .order_by(GovernanceDecisionRow.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    summaries = []
    for row in rows:
        result_data = json.loads(row.result_json) if row.result_json else {}
        params = result_data.get("parameters", {})
        summaries.append({
            "decision_id": row.id,
            "intent_type": row.intent_type,
            "status": row.status,
            "initiator": result_data.get("initiator", ""),
            "client_name": params.get("client_name", ""),
            "portfolio_value": params.get("portfolio_value_inr", ""),
            "agent_count": result_data.get("agent_count", 0),
            "rule_count": result_data.get("rule_count", 0),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        })
    return summaries


@router.get("/decisions/{decision_id}/detail")
async def get_decision_detail(
    decision_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Return full decision detail including agent outputs, rules, permissions."""
    import json as json_mod
    from sqlalchemy import select
    from artha.governance.models import GovernanceDecisionRow

    stmt = select(GovernanceDecisionRow).where(GovernanceDecisionRow.id == decision_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Decision not found")

    result_data = json_mod.loads(row.result_json) if row.result_json else {}
    return {
        "decision_id": row.id,
        "intent_id": row.intent_id,
        "intent_type": row.intent_type,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "evidence_snapshot_id": row.evidence_snapshot_id,
        "initiator": result_data.get("initiator", ""),
        "client_name": result_data.get("parameters", {}).get("client_name", ""),
        "portfolio_value": result_data.get("parameters", {}).get("portfolio_value_inr", ""),
        "parameters": result_data.get("parameters", {}),
        "symbols": result_data.get("symbols", []),
        "agent_outputs": result_data.get("agent_outputs", []),
        "rule_evaluations": result_data.get("rule_evaluations", []),
        "permission_outcome": result_data.get("permission_outcome"),
    }


@router.get("/decisions/{decision_id}/trace", response_model=DecisionTrace)
async def get_trace(
    decision_id: str,
    service: AccountabilityService = Depends(_get_service),
):
    return await service.get_trace(decision_id)


@router.get("/decisions/{decision_id}/audit", response_model=AuditReconstruction)
async def reconstruct_decision(
    decision_id: str,
    service: AccountabilityService = Depends(_get_service),
):
    return await service.reconstruct(decision_id)


@router.post("/approvals", response_model=ApprovalRecord)
async def submit_approval(
    request: SubmitApprovalRequest,
    service: AccountabilityService = Depends(_get_service),
    session: AsyncSession = Depends(get_session),
):
    result = await service.submit_approval(
        decision_id=request.decision_id,
        approver=request.approver,
        action=request.action,
        rationale=request.rationale,
        conditions=request.conditions,
    )
    await session.commit()
    return result


@router.get("/decisions/{decision_id}/approvals", response_model=list[ApprovalRecord])
async def get_approvals(
    decision_id: str,
    service: AccountabilityService = Depends(_get_service),
):
    return await service.get_approvals(decision_id)


@router.get("/telemetry")
async def get_telemetry(session: AsyncSession = Depends(get_session)):
    """Decision telemetry analytics — aggregate patterns, disagreements, quality metrics."""
    from artha.accountability.telemetry import get_telemetry_analytics
    return await get_telemetry_analytics(session)
