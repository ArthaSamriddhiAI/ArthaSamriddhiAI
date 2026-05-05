"""IndustryReport service helpers used by the JSONFixtureAdapter and router."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.d0.event_names import (
    CANONICAL_ENTITY_CREATED,
    CANONICAL_ENTITY_UPDATED,
)
from artha.api_v2.d0.industry.models import IndustryReport
from artha.api_v2.observability.t1 import emit_event

VALID_OUTLOOKS: tuple[str, ...] = ("positive", "neutral", "negative")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def list_industry_reports(
    db: AsyncSession,
    *,
    industry_code: str | None = None,
    outlook: str | None = None,
    report_period: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[IndustryReport], int]:
    base = select(IndustryReport)
    count_base = select(func.count()).select_from(IndustryReport)

    filters = []
    if industry_code is not None:
        filters.append(IndustryReport.industry_code == industry_code)
    if outlook is not None:
        filters.append(IndustryReport.outlook == outlook)
    if report_period is not None:
        filters.append(IndustryReport.report_period == report_period)

    if filters:
        base = base.where(*filters)
        count_base = count_base.where(*filters)

    base = (
        base.order_by(IndustryReport.report_date.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = list((await db.execute(base)).scalars())
    total = (await db.execute(count_base)).scalar_one() or 0
    return rows, int(total)


async def get_industry_report(
    db: AsyncSession, *, industry_report_id: str
) -> IndustryReport | None:
    return (
        await db.execute(
            select(IndustryReport).where(
                IndustryReport.industry_report_id == industry_report_id
            )
        )
    ).scalar_one_or_none()


async def find_by_natural_key(
    db: AsyncSession, *, industry_code: str, report_period: str
) -> IndustryReport | None:
    return (
        await db.execute(
            select(IndustryReport).where(
                IndustryReport.industry_code == industry_code,
                IndustryReport.report_period == report_period,
            )
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def upsert_industry_report(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    source_identifier: str,
    adapter_run_id: str,
    staging_record_id: str | None,
    source_subkey: str | None = None,
    firm_id: str | None = None,
) -> tuple[IndustryReport, bool]:
    """Insert or update one IndustryReport.

    Identity = (industry_code, report_period). Returns ``(row, created)``.
    """
    industry_code = payload["industry_code"]
    report_period = payload["report_period"]
    outlook = payload["outlook"]
    if outlook not in VALID_OUTLOOKS:
        raise ValueError(
            f"Unknown outlook {outlook!r}; expected one of {VALID_OUTLOOKS}"
        )

    existing = await find_by_natural_key(
        db,
        industry_code=industry_code,
        report_period=report_period,
    )
    now = datetime.now(timezone.utc)

    report_date = payload["report_date"]
    if isinstance(report_date, str):
        report_date = date.fromisoformat(report_date)

    if existing is None:
        row = IndustryReport(
            industry_report_id=str(ULID()),
            industry_code=industry_code,
            industry_name=payload["industry_name"],
            report_period=report_period,
            report_date=report_date,
            outlook=outlook,
            summary=payload["summary"],
            key_themes=payload.get("key_themes", []) or [],
            drivers=payload.get("drivers", []) or [],
            risks=payload.get("risks", []) or [],
            source_identifier=source_identifier,
            source_subkey=source_subkey,
            staging_record_id=staging_record_id,
            adapter_run_id=adapter_run_id,
            created_at=now,
            last_modified_at=now,
            schema_version=1,
        )
        db.add(row)
        await db.flush()
        await emit_event(
            db,
            event_name=CANONICAL_ENTITY_CREATED,
            payload={
                "entity_type": "IndustryReport",
                "entity_id": row.industry_report_id,
                "industry_code": industry_code,
                "report_period": report_period,
                "source_identifier": source_identifier,
                "adapter_run_id": adapter_run_id,
            },
            firm_id=firm_id,
        )
        return row, True

    existing.industry_name = payload["industry_name"]
    existing.report_date = report_date
    existing.outlook = outlook
    existing.summary = payload["summary"]
    existing.key_themes = payload.get("key_themes", []) or []
    existing.drivers = payload.get("drivers", []) or []
    existing.risks = payload.get("risks", []) or []
    existing.source_identifier = source_identifier
    existing.source_subkey = source_subkey
    existing.staging_record_id = staging_record_id
    existing.adapter_run_id = adapter_run_id
    existing.last_modified_at = now
    await db.flush()
    await emit_event(
        db,
        event_name=CANONICAL_ENTITY_UPDATED,
        payload={
            "entity_type": "IndustryReport",
            "entity_id": existing.industry_report_id,
            "industry_code": industry_code,
            "report_period": report_period,
            "source_identifier": source_identifier,
            "adapter_run_id": adapter_run_id,
        },
        firm_id=firm_id,
    )
    return existing, False
