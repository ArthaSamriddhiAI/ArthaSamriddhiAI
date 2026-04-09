"""PAM API endpoints — Portfolio Analysis Module."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session
from artha.llm.registry import get_provider

router = APIRouter(prefix="/portfolio-analysis", tags=["portfolio-analysis"])


# ── Upload & Parse ──

@router.post("/{investor_id}/upload-xlsx")
async def upload_xlsx(
    investor_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upload an XLSX spreadsheet and parse into canonical portfolio JSON."""
    from artha.portfolio_analysis.ingestion.spreadsheet_parser import parse_spreadsheet

    content = await file.read()
    try:
        portfolio = parse_spreadsheet(content, investor_id)
        # Store in session for preview
        return {"status": "parsed", "portfolio": portfolio}
    except Exception as e:
        raise HTTPException(400, f"Failed to parse spreadsheet: {str(e)[:200]}")


@router.post("/{investor_id}/upload-ecas")
async def upload_ecas(
    investor_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upload a CAMS/KFintech ECAS file and parse into canonical portfolio JSON."""
    from artha.portfolio_analysis.ingestion.ecas_parser import parse_ecas

    content = await file.read()
    file_ext = (file.filename or "").split(".")[-1].lower()
    try:
        portfolio = parse_ecas(content, file_type=file_ext or "xml")
        portfolio["client_id"] = investor_id
        return {"status": "parsed", "portfolio": portfolio}
    except Exception as e:
        raise HTTPException(400, f"Failed to parse ECAS: {str(e)[:200]}")


@router.post("/{investor_id}/preview")
async def preview_holdings(
    investor_id: str,
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Return parsed holdings preview for advisor review before triggering analysis."""
    from artha.portfolio_analysis.ingestion.schema_validator import validate_portfolio
    from artha.portfolio_analysis.ingestion.holdings_preview import build_preview

    try:
        portfolio = validate_portfolio(data.get("portfolio", data))
        preview = build_preview(portfolio)
        return preview
    except Exception as e:
        raise HTTPException(400, f"Validation failed: {str(e)[:200]}")


# ── Phase 1: Comprehensive Portfolio Review ──

@router.post("/{investor_id}/review")
async def run_portfolio_review(
    investor_id: str,
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Trigger Phase 1 — Comprehensive Portfolio Review (CPR).

    Expects: {"portfolio": <canonical JSON>, "client_profile": {...}}
    Returns: CPR with all 10 sections + review_id for later PDF generation.
    """
    from artha.portfolio_analysis.ingestion.schema_validator import validate_portfolio, check_preconditions
    from artha.portfolio_analysis.orchestrator.pa_o import PortfolioAnalysisOrchestrator
    from artha.investor.mandates import MandateService

    llm = get_provider()

    # Validate portfolio
    portfolio_data = data.get("portfolio", {})
    portfolio_data["client_id"] = investor_id
    try:
        portfolio = validate_portfolio(portfolio_data)
    except Exception as e:
        raise HTTPException(400, f"Invalid portfolio: {str(e)[:200]}")

    # Check mandate exists (non-blocking — review can proceed without mandate)
    mandate_svc = MandateService(session)
    mandates = await mandate_svc.get_mandates(investor_id)
    has_mandate = len(mandates) > 0

    # Check preconditions (only block on critical failures)
    issues = check_preconditions(portfolio, has_mandate)
    critical_issues = [i for i in issues if "no holdings" in i.lower() or "only cash" in i.lower()]
    if critical_issues:
        raise HTTPException(400, f"Cannot review: {'; '.join(critical_issues)}")

    # Build client profile
    client_profile = data.get("client_profile", {})
    if not client_profile.get("mandates"):
        client_profile["mandates"] = await mandate_svc.get_mandates_for_governance(investor_id)

    # Fetch risk profile
    try:
        from artha.investor.service import InvestorService
        inv_svc = InvestorService(session)
        profile = await inv_svc.get_profile(investor_id)
        if profile:
            client_profile["risk_score"] = profile.overall_score
            client_profile["risk_category"] = profile.risk_category.value
    except Exception:
        pass

    # Run Phase 1
    orchestrator = PortfolioAnalysisOrchestrator(session, llm)
    cpr = await orchestrator.run_phase1_cpr(portfolio, client_profile)
    await session.commit()

    return cpr


# ── Phase 2: Investment Suggestion Engine ──

@router.post("/{investor_id}/suggestions")
async def generate_suggestions(
    investor_id: str,
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Trigger Phase 2 — Investment Suggestion Engine (ISE).

    Expects: {"portfolio": <canonical JSON>, "cpr": <CPR from Phase 1>, "review_id": "..."}
    Returns: Filtered suggestion_set (BLOCKED removed, only APPROVED/ESCALATION_REQUIRED).
    """
    from artha.portfolio_analysis.ingestion.schema_validator import validate_portfolio
    from artha.portfolio_analysis.orchestrator.pa_o import PortfolioAnalysisOrchestrator

    llm = get_provider()

    portfolio_data = data.get("portfolio", {})
    portfolio_data["client_id"] = investor_id
    try:
        portfolio = validate_portfolio(portfolio_data)
    except Exception as e:
        raise HTTPException(400, f"Invalid portfolio: {str(e)[:200]}")

    cpr = data.get("cpr", {})
    review_id = data.get("review_id", f"pr-{investor_id}-{int(datetime.now(UTC).timestamp())}")

    orchestrator = PortfolioAnalysisOrchestrator(session, llm)
    result = await orchestrator.run_phase2_ise(portfolio, cpr, review_id)
    await session.commit()

    return result


# ── Human Decision on Suggestion ──

@router.post("/{investor_id}/suggestion/{suggestion_id}/decide")
async def decide_suggestion(
    investor_id: str,
    suggestion_id: str,
    data: dict,
    session: AsyncSession = Depends(get_session),
):
    """Record human decision on a suggestion (accept/reject/modify)."""
    from artha.accountability.trace.graph import DecisionTraceBuilder
    from artha.accountability.trace.models import TraceNodeType

    decision = data.get("decision", "rejected")  # accept, reject, modify
    rationale = data.get("rationale", "")
    modification_note = data.get("modification_note", "")
    review_id = data.get("review_id", "")
    linked_suggestion_id = data.get("linked_suggestion_id")

    # Record as trace node
    decision_id = data.get("decision_id", str(uuid.uuid4()))
    trace = DecisionTraceBuilder(session, decision_id)
    await trace.add_node(
        TraceNodeType.HUMAN_APPROVAL,
        {
            "suggestion_id": suggestion_id,
            "decision": decision,
            "rationale": rationale,
            "modification_note": modification_note,
            "portfolio_review_id": review_id,
            "linked_suggestion_id": linked_suggestion_id,
            "actor": data.get("actor", "advisor"),
            "timestamp": datetime.now(UTC).isoformat(),
        },
        parent_ids=[],
    )
    await session.commit()

    return {
        "status": "recorded",
        "suggestion_id": suggestion_id,
        "decision": decision,
    }


# ── PDF Export ──

@router.get("/{investor_id}/review/{review_id}/pdf")
async def export_cpr_pdf(
    investor_id: str,
    review_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Generate PDF of a CPR from the telemetry record."""
    from artha.portfolio_analysis.report.cpr_pdf import generate_cpr_pdf

    try:
        pdf_bytes = await generate_cpr_pdf(review_id, session)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=cpr_{review_id[:12]}.pdf"
            },
        )
    except Exception as e:
        # Fallback: return error
        raise HTTPException(500, f"PDF generation failed: {str(e)[:200]}")
