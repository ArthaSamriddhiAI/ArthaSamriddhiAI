"""Pydantic read shapes for the MacroSnapshot browse surface."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class MacroSnapshotRead(BaseModel):
    macro_snapshot_id: str

    country_code: str
    snapshot_period: str
    snapshot_date: date

    gdp_growth_pct: float | None
    cpi_inflation_pct: float | None
    wpi_inflation_pct: float | None
    repo_rate_pct: float | None
    reverse_repo_rate_pct: float | None
    bond_yield_10y_pct: float | None
    fx_usd_inr: float | None
    unemployment_rate_pct: float | None

    notes: str | None
    themes: list[str]

    source_identifier: str
    source_subkey: str | None
    staging_record_id: str | None
    adapter_run_id: str | None

    created_at: datetime
    last_modified_at: datetime
    schema_version: int


class MacroSnapshotListResponse(BaseModel):
    snapshots: list[MacroSnapshotRead]
    total: int
    limit: int
    offset: int
