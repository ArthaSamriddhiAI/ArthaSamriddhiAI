"""FastAPI endpoints for client portfolio management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session
from artha.portfolio.schemas import AddHoldingRequest, HoldingResponse, PortfolioSummary
from artha.portfolio.service import PortfolioService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _svc(session: AsyncSession = Depends(get_session)) -> PortfolioService:
    return PortfolioService(session)


@router.get("/{investor_id}/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(
    investor_id: str,
    svc: PortfolioService = Depends(_svc),
):
    """Full portfolio with live valuations, allocation, and gain/loss."""
    return await svc.get_portfolio_summary(investor_id)


@router.get("/{investor_id}/holdings", response_model=list[HoldingResponse])
async def get_holdings(
    investor_id: str,
    svc: PortfolioService = Depends(_svc),
):
    summary = await svc.get_portfolio_summary(investor_id)
    return summary.holdings


@router.post("/{investor_id}/holdings", response_model=HoldingResponse)
async def add_holding(
    investor_id: str,
    req: AddHoldingRequest,
    svc: PortfolioService = Depends(_svc),
    session: AsyncSession = Depends(get_session),
):
    result = await svc.add_holding(investor_id, req)
    await session.commit()
    return result


@router.delete("/holdings/{holding_id}")
async def delete_holding(
    holding_id: str,
    svc: PortfolioService = Depends(_svc),
    session: AsyncSession = Depends(get_session),
):
    ok = await svc.delete_holding(holding_id)
    if not ok:
        raise HTTPException(404, "Holding not found")
    await session.commit()
    return {"status": "deleted"}


@router.post("/{investor_id}/import-csv")
async def import_csv(
    investor_id: str,
    file: UploadFile = File(...),
    svc: PortfolioService = Depends(_svc),
    session: AsyncSession = Depends(get_session),
):
    """Import portfolio holdings from CSV file."""
    content = await file.read()
    csv_text = content.decode("utf-8-sig")
    result = await svc.import_csv(investor_id, csv_text)
    await session.commit()
    return result
