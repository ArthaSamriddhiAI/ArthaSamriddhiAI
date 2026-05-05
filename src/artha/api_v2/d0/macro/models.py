"""MacroSnapshot canonical-entity ORM (FR Entry 10.7 §5 cluster-3 revision).

One row per ``(country_code, snapshot_period)`` pair. The natural-key
uniqueness is enforced via a composite unique index; `snapshot_period`
is a string ("2026-Q1", "2026-04", "2026-04-15", etc.) so different
cadences (quarterly / monthly / point-in-time) can coexist without
schema branches.

Indicator coverage targets the Indian macro context for cluster 3 — the
RBI's repo / reverse-repo / bond-yield set plus CPI / WPI inflation,
GDP growth, FX (USD/INR), and unemployment. Each indicator is nullable
because not every snapshot from every source covers the whole set; the
JSONFixtureAdapter writes whatever the fixture provides and leaves the
rest null.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class MacroSnapshot(Base):
    """One macro-indicator snapshot for a country in one period."""

    __tablename__ = "v2_macro_snapshots"

    macro_snapshot_id: Mapped[str] = mapped_column(
        String(26), primary_key=True
    )

    # ----- Identity -----
    country_code: Mapped[str] = mapped_column(
        String(2), nullable=False, index=True
    )
    snapshot_period: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )

    # ----- Indicators (all nullable; sources differ in coverage) -----
    gdp_growth_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpi_inflation_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    wpi_inflation_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    repo_rate_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reverse_repo_rate_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    bond_yield_10y_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    fx_usd_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    unemployment_rate_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    # ----- Free-form -----
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    themes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

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
            "country_code",
            "snapshot_period",
            name="uq_v2_macro_snapshots_country_period",
        ),
        Index(
            "ix_v2_macro_snapshots_country_date",
            "country_code",
            "snapshot_date",
        ),
    )
