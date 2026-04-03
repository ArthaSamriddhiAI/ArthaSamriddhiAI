"""FastAPI endpoints for the Investor Risk Profile module."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session
from artha.investor.schemas import (
    CreateFamilyOfficeRequest,
    CreateInvestorRequest,
    FamilyOfficeResponse,
    InvestorResponse,
    QuestionnaireTemplate,
    RiskProfileResponse,
    SubmitQuestionnaireRequest,
    get_questionnaire_template,
)
from artha.investor.service import InvestorService

router = APIRouter(prefix="/investor", tags=["investor"])


def _get_service(session: AsyncSession = Depends(get_session)) -> InvestorService:
    return InvestorService(session)


@router.get("/questionnaire/template", response_model=QuestionnaireTemplate)
async def get_template():
    """Get the full questionnaire structure with all categories and questions."""
    return get_questionnaire_template()


@router.post("/investors", response_model=InvestorResponse)
async def create_investor(
    req: CreateInvestorRequest,
    service: InvestorService = Depends(_get_service),
    session: AsyncSession = Depends(get_session),
):
    result = await service.create_investor(req)
    await session.commit()
    return result


@router.get("/investors", response_model=list[InvestorResponse])
async def list_investors(
    limit: int = 50,
    service: InvestorService = Depends(_get_service),
):
    return await service.list_investors(limit)


@router.get("/investors/{investor_id}", response_model=InvestorResponse)
async def get_investor(
    investor_id: str,
    service: InvestorService = Depends(_get_service),
):
    result = await service.get_investor(investor_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Investor not found")
    return result


@router.post("/investors/{investor_id}/questionnaire", response_model=RiskProfileResponse)
async def submit_questionnaire(
    investor_id: str,
    req: SubmitQuestionnaireRequest,
    service: InvestorService = Depends(_get_service),
    session: AsyncSession = Depends(get_session),
):
    result = await service.submit_questionnaire(investor_id, req)
    await session.commit()
    return result


@router.get("/investors/{investor_id}/profile", response_model=RiskProfileResponse)
async def get_profile(
    investor_id: str,
    service: InvestorService = Depends(_get_service),
):
    result = await service.get_profile(investor_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No risk profile found for this investor")
    return result


@router.post("/family-offices", response_model=FamilyOfficeResponse)
async def create_family_office(
    req: CreateFamilyOfficeRequest,
    service: InvestorService = Depends(_get_service),
    session: AsyncSession = Depends(get_session),
):
    result = await service.create_family_office(req)
    await session.commit()
    return result


@router.get("/investors/{investor_id}/assessments")
async def get_assessment_history(
    investor_id: str,
    service: InvestorService = Depends(_get_service),
):
    """Get all historical assessments for an investor (view-only, immutable)."""
    return await service.get_assessment_history(investor_id)


@router.get("/assessments/{assessment_id}")
async def get_assessment_detail(
    assessment_id: str,
    service: InvestorService = Depends(_get_service),
):
    """Get a single historical assessment with full Q&A snapshot (view-only)."""
    result = await service.get_assessment_detail(assessment_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return result


# ── Mandates ──

@router.get("/mandate-types")
async def get_mandate_types():
    """Get all available mandate types with descriptions."""
    from artha.investor.mandates import MANDATE_TYPES
    return MANDATE_TYPES


@router.get("/investors/{investor_id}/mandates")
async def get_mandates(investor_id: str, session: AsyncSession = Depends(get_session)):
    from artha.investor.mandates import MandateService
    return await MandateService(session).get_mandates(investor_id)


@router.post("/investors/{investor_id}/mandates")
async def set_mandate(
    investor_id: str, data: dict,
    session: AsyncSession = Depends(get_session),
):
    from artha.investor.mandates import MandateService
    result = await MandateService(session).set_mandate(
        investor_id, data.get("mandate_type", ""), data.get("value"), data.get("created_by", "advisor")
    )
    await session.commit()
    return result


@router.delete("/mandates/{mandate_id}")
async def delete_mandate(mandate_id: str, session: AsyncSession = Depends(get_session)):
    from artha.investor.mandates import MandateService
    ok = await MandateService(session).delete_mandate(mandate_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Mandate not found")
    await session.commit()
    return {"status": "deleted"}
