"""FastAPI endpoints for the Governance layer."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session
from artha.governance.intent.models import GovernanceIntent
from artha.governance.schemas import GovernanceResult, SubmitIntentRequest
from artha.governance.service import GovernanceService

router = APIRouter(prefix="/governance", tags=["governance"])


def _get_service(session: AsyncSession = Depends(get_session)) -> GovernanceService:
    return GovernanceService(session)


@router.post("/intents", response_model=GovernanceResult)
async def submit_intent(
    request: SubmitIntentRequest,
    service: GovernanceService = Depends(_get_service),
    session: AsyncSession = Depends(get_session),
):
    intent = GovernanceIntent(
        intent_type=request.intent_type,
        source=request.source,
        initiator=request.initiator,
        symbols=request.symbols,
        holdings=request.holdings,
        parameters=request.parameters,
    )
    result = await service.process_intent(intent)
    await session.commit()
    return result
