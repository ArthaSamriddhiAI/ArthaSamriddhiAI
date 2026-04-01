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
