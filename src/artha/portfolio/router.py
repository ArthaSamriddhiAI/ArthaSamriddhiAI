"""FastAPI endpoints for client portfolio management — all features."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session
from artha.portfolio.schemas import (
    AddHoldingRequest,
    FreezeRequest,
    HoldingResponse,
    PortfolioStatusResponse,
    PortfolioSummary,
    UnfreezeRequest,
    UpdateHoldingRequest,
)
from artha.portfolio.service import PortfolioService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _svc(session: AsyncSession = Depends(get_session)) -> PortfolioService:
    return PortfolioService(session)


# ── Advisor Dashboard (must come before {investor_id} routes) ──

@router.get("/advisor/dashboard")
async def advisor_dashboard(session: AsyncSession = Depends(get_session)):
    from artha.portfolio.advisor import get_advisor_dashboard
    return await get_advisor_dashboard(session)


@router.get("/scenarios/list")
async def list_scenarios_endpoint():
    from artha.portfolio.scenarios import list_scenarios
    return list_scenarios()


# ── Portfolio Lifecycle ──

@router.get("/{investor_id}/status", response_model=PortfolioStatusResponse)
async def get_portfolio_status(investor_id: str, svc: PortfolioService = Depends(_svc)):
    return await svc.get_status(investor_id)


@router.post("/{investor_id}/freeze", response_model=PortfolioStatusResponse)
async def freeze_portfolio(investor_id: str, req: FreezeRequest = FreezeRequest(), svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    try:
        result = await svc.freeze_portfolio(investor_id, req)
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{investor_id}/unfreeze", response_model=PortfolioStatusResponse)
async def unfreeze_portfolio(investor_id: str, req: UnfreezeRequest = UnfreezeRequest(), svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    try:
        result = await svc.unfreeze_portfolio(investor_id, req)
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{investor_id}/onboarding-type")
async def set_onboarding_type(investor_id: str, data: dict, svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    ob_type = data.get("onboarding_type", "existing")
    if ob_type not in ("existing", "partial", "new_capital"):
        raise HTTPException(400, "onboarding_type must be: existing, partial, or new_capital")
    result = await svc.set_onboarding_type(investor_id, ob_type)
    await session.commit()
    return result


@router.get("/{investor_id}/edit-log")
async def get_edit_log(investor_id: str, limit: int = Query(50, le=200), svc: PortfolioService = Depends(_svc)):
    return await svc.get_edit_log(investor_id, limit)


# ── Core Portfolio ──

@router.get("/{investor_id}/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(investor_id: str, svc: PortfolioService = Depends(_svc)):
    return await svc.get_portfolio_summary(investor_id)


@router.get("/{investor_id}/holdings", response_model=list[HoldingResponse])
async def get_holdings(investor_id: str, svc: PortfolioService = Depends(_svc)):
    summary = await svc.get_portfolio_summary(investor_id)
    return summary.holdings


@router.post("/{investor_id}/holdings", response_model=HoldingResponse)
async def add_holding(investor_id: str, req: AddHoldingRequest, svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    try:
        result = await svc.add_holding(investor_id, req)
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/{investor_id}/holdings/{holding_id}", response_model=HoldingResponse)
async def update_holding(investor_id: str, holding_id: str, req: UpdateHoldingRequest, svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    try:
        result = await svc.update_holding(investor_id, holding_id, req)
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/holdings/{holding_id}")
async def delete_holding(holding_id: str, svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    try:
        ok = await svc.delete_holding(holding_id)
        if not ok:
            raise HTTPException(404, "Holding not found")
        await session.commit()
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{investor_id}/import-csv")
async def import_csv(investor_id: str, file: UploadFile = File(...), svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    try:
        content = await file.read()
        csv_text = content.decode("utf-8-sig")
        result = await svc.import_csv(investor_id, csv_text)
        await session.commit()
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Performance Analytics ──

@router.get("/{investor_id}/performance")
async def get_performance(investor_id: str, svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    summary = await svc.get_portfolio_summary(investor_id)
    holdings_dicts = [h.model_dump() for h in summary.holdings]
    from artha.portfolio.analytics import compute_performance
    return await compute_performance(session, holdings_dicts, summary.total_invested, summary.current_value)


# ── Rebalancing ──

@router.get("/{investor_id}/rebalance-check")
async def check_rebalance(investor_id: str, svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    summary = await svc.get_portfolio_summary(investor_id)
    from sqlalchemy import text
    r = await session.execute(text("SELECT risk_category FROM investor_risk_profiles WHERE investor_id = :id ORDER BY computed_at DESC LIMIT 1"), {"id": investor_id})
    row = r.one_or_none()
    risk_cat = row[0] if row else "moderate"
    from artha.portfolio.analytics import check_drift
    return await check_drift(session, [a.model_dump() for a in summary.allocation], risk_cat)


# ── Client Review Report (PDF) ──

@router.get("/{investor_id}/report")
async def generate_report(investor_id: str, svc: PortfolioService = Depends(_svc), session: AsyncSession = Depends(get_session)):
    summary = await svc.get_portfolio_summary(investor_id)
    holdings_dicts = [h.model_dump() for h in summary.holdings]

    from artha.portfolio.analytics import compute_performance, check_drift
    performance = await compute_performance(session, holdings_dicts, summary.total_invested, summary.current_value)

    from sqlalchemy import text
    r = await session.execute(text("SELECT risk_category FROM investor_risk_profiles WHERE investor_id = :id ORDER BY computed_at DESC LIMIT 1"), {"id": investor_id})
    row = r.one_or_none()
    risk_cat = row[0] if row else "moderate"
    drift = await check_drift(session, [a.model_dump() for a in summary.allocation], risk_cat)

    ai_commentary = ""
    try:
        from artha.llm.registry import get_provider
        from artha.llm.models import LLMMessage, LLMRequest
        llm = get_provider()
        req = LLMRequest(messages=[
            LLMMessage(role="system", content="You are a wealth management advisor. Write a 100-word portfolio review commentary. Professional, specific, actionable."),
            LLMMessage(role="user", content=f"Client: {summary.investor_name}. AUM: Rs {summary.current_value:,.0f}. Return: {summary.total_gain_loss_pct:+.1f}%. Risk: {risk_cat}. Max drift: {drift.get('max_drift_pct',0):.1f}%. Top asset: {summary.allocation[0].label if summary.allocation else 'N/A'} at {summary.allocation[0].percentage:.0f}%."),
        ], temperature=0.3, max_tokens=256)
        resp = await llm.complete(req)
        ai_commentary = resp.content
    except Exception:
        pass

    from artha.portfolio.report import generate_report_html
    html = generate_report_html(summary=summary.model_dump(), performance=performance, drift=drift, risk_profile={"risk_category": risk_cat}, ai_commentary=ai_commentary)

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            pdf_bytes = await page.pdf(format="A4", margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"}, print_background=True)
            await browser.close()
        return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=portfolio_report_{investor_id[:8]}.pdf"})
    except Exception:
        return Response(content=html, media_type="text/html")


# ── Scenarios ──

@router.get("/{investor_id}/scenario")
async def run_scenario_endpoint(investor_id: str, type: str = Query("nifty_crash_20"), svc: PortfolioService = Depends(_svc)):
    summary = await svc.get_portfolio_summary(investor_id)
    holdings_dicts = [h.model_dump() for h in summary.holdings]
    from artha.portfolio.scenarios import run_scenario
    return run_scenario(holdings_dicts, type, summary.current_value)


# ── Tax Harvesting ──

@router.get("/{investor_id}/tax-summary")
async def get_tax_summary(investor_id: str, svc: PortfolioService = Depends(_svc)):
    summary = await svc.get_portfolio_summary(investor_id)
    holdings_dicts = [h.model_dump() for h in summary.holdings]
    from artha.portfolio.tax import compute_tax_summary
    return compute_tax_summary(holdings_dicts)


# ── Goals ──

@router.get("/{investor_id}/goals")
async def get_goals(investor_id: str, session: AsyncSession = Depends(get_session)):
    from artha.portfolio.goals import GoalService
    return await GoalService(session).get_goals(investor_id)


@router.post("/{investor_id}/goals")
async def add_goal(investor_id: str, data: dict, session: AsyncSession = Depends(get_session)):
    from artha.portfolio.goals import GoalService
    data["target_date"] = data.get("target_date", "2030-01-01")
    result = await GoalService(session).add_goal(investor_id, data)
    await session.commit()
    return result


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: str, session: AsyncSession = Depends(get_session)):
    from artha.portfolio.goals import GoalService
    ok = await GoalService(session).delete_goal(goal_id)
    if not ok:
        raise HTTPException(404, "Goal not found")
    await session.commit()
    return {"status": "deleted"}
