"""IndustryReport canonical-entity ORM (FR Entry 10.7 §6 cluster-3 revision).

One row per ``(industry_code, report_period)`` pair. ``industry_code`` is
free-form (typically NIC, GICS-derived, or short labels like "BFSI" /
"IT" / "FMCG") because the Indian advisory ecosystem doesn't pin to one
taxonomy — adapter feeds vary in their classification scheme.

The ``outlook`` enum captures the analyst direction (positive / neutral /
negative); ``key_themes``, ``drivers``, and ``risks`` are JSON string
arrays carrying the structured commentary. ``summary`` is the free-form
prose paragraph rendered at the top of the report card in the admin UI.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class IndustryReport(Base):
    """One industry report for an industry sector in one period."""

    __tablename__ = "v2_industry_reports"

    industry_report_id: Mapped[str] = mapped_column(
        String(26), primary_key=True
    )

    # ----- Identity -----
    industry_code: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    industry_name: Mapped[str] = mapped_column(String(120), nullable=False)
    report_period: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # ----- Body -----
    outlook: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_themes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    drivers: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    risks: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )

    # ----- Source lineage -----
    source_identifier: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    source_subkey: Mapped[str | None] = mapped_column(String(255), nullable=True)
    staging_record_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    adapter_run_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )

    # ----- Provenance -----
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "industry_code",
            "report_period",
            name="uq_v2_industry_reports_code_period",
        ),
        Index(
            "ix_v2_industry_reports_code_date",
            "industry_code",
            "report_date",
        ),
    )
