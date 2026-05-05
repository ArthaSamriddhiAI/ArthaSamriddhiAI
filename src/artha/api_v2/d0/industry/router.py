"""Admin industry-report browse router (cluster 3 chunk 3.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.d0.industry import service
from artha.api_v2.d0.industry.schemas import (
    IndustryReportListResponse,
    IndustryReportRead,
)
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/admin", tags=["d0_admin_industry"])


def _to_read(row) -> IndustryReportRead:
    return IndustryReportRead(
        industry_report_id=row.industry_report_id,
        industry_code=row.industry_code,
        industry_name=row.industry_name,
        report_period=row.report_period,
        report_date=row.report_date,
        outlook=row.outlook,
        summary=row.summary,
        key_themes=row.key_themes or [],
        drivers=row.drivers or [],
        risks=row.risks or [],
        source_identifier=row.source_identifier,
        source_subkey=row.source_subkey,
        staging_record_id=row.staging_record_id,
        adapter_run_id=row.adapter_run_id,
        created_at=row.created_at,
        last_modified_at=row.last_modified_at,
        schema_version=row.schema_version,
    )


@router.get(
    "/industry-reports", response_model=IndustryReportListResponse
)
async def list_industry_reports_endpoint(
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    industry_code: str | None = None,
    outlook: str | None = None,
    report_period: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    rows, total = await service.list_industry_reports(
        db,
        industry_code=industry_code,
        outlook=outlook,
        report_period=report_period,
        limit=min(max(1, limit), 500),
        offset=max(0, offset),
    )
    return IndustryReportListResponse(
        reports=[_to_read(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/industry-reports/{industry_report_id}",
    response_model=IndustryReportRead,
)
async def get_industry_report_endpoint(
    industry_report_id: str,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.D0_ADMIN_READ))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    row = await service.get_industry_report(
        db, industry_report_id=industry_report_id
    )
    if row is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="IndustryReport not found",
            detail=f"No industry report with id={industry_report_id!r}",
        )
    return _to_read(row)
