"""Pydantic read shapes for IndustryReport browse endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

OutlookLiteral = Literal["positive", "neutral", "negative"]


class IndustryReportRead(BaseModel):
    industry_report_id: str

    industry_code: str
    industry_name: str
    report_period: str
    report_date: date

    outlook: OutlookLiteral
    summary: str
    key_themes: list[str]
    drivers: list[str]
    risks: list[str]

    source_identifier: str
    source_subkey: str | None
    staging_record_id: str | None
    adapter_run_id: str | None

    created_at: datetime
    last_modified_at: datetime
    schema_version: int


class IndustryReportListResponse(BaseModel):
    reports: list[IndustryReportRead]
    total: int
    limit: int
    offset: int
