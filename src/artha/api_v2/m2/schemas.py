"""Pydantic shapes for the M2 model portfolio surface."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

RiskProfileLiteral = Literal["aggressive", "moderate", "conservative"]
HorizonLiteral = Literal["long_term", "medium_term", "short_term"]
PositionRoleLiteral = Literal["core", "satellite", "optional"]


# ---------------------------------------------------------------------------
# Instrument-with-tags shape (chunk 4.1 read; chunk 4.2 write)
# ---------------------------------------------------------------------------


class InstrumentWithTagsRead(BaseModel):
    """Instrument-shaped read for the model portfolio surfaces.

    Subset of cluster 3's full Instrument with the model-portfolio fields
    that chunks 4.2 / 4.3 actually need rendered (TER + AUM + Sharpe + 1y/3y
    returns are read from the staged source JSON in cluster 5+).
    """

    instrument_id: str
    isin: str | None
    amfi_scheme_code: str | None
    exchange_ticker: str | None
    name: str
    asset_class: str
    vehicle_type: str
    sebi_category: str | None
    amc_name: str | None
    riskometer_label: str | None
    status: str
    inception_date: date | None

    # Tag fields (cluster 4 chunk 4.1 schema additions)
    model_portfolio_tags: list[str]
    model_portfolio_tags_modified_at: datetime | None
    model_portfolio_tags_modified_by: str | None

    last_modified_at: datetime
    schema_version: int


class InstrumentListResponse(BaseModel):
    instruments: list[InstrumentWithTagsRead]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Preferred portfolio entry shapes (chunk 4.1 read; chunk 4.3 write)
# ---------------------------------------------------------------------------


class PreferredPortfolioEntryRead(BaseModel):
    """One preferred portfolio entry as the API renders it."""

    entry_id: str
    risk_profile: RiskProfileLiteral
    horizon: HorizonLiteral
    instrument_id: str
    instrument_name: str
    instrument_asset_class: str
    instrument_vehicle_type: str
    instrument_amc_name: str | None
    instrument_sebi_category: str | None
    position_role: PositionRoleLiteral
    rank_within_role: int
    notes: str | None
    has_matching_tag: bool
    created_at: datetime
    created_by: str
    created_via: str
    last_modified_at: datetime
    last_modified_by: str


class CellRoleSummary(BaseModel):
    core: int
    satellite: int
    optional: int


class CellSummary(BaseModel):
    """One cell's high-level stats for the matrix overview."""

    risk_profile: RiskProfileLiteral
    horizon: HorizonLiteral
    cell_id: str
    counts: CellRoleSummary
    last_modified_at: datetime | None
    top_core_names: list[str] = Field(
        default_factory=list,
        description="Up to 3 names of the cell's top-rank core entries (for hover preview).",
    )


class MatrixOverviewResponse(BaseModel):
    cells: list[CellSummary]
    total_entries: int
    last_modified_at: datetime | None


class CellDetailResponse(BaseModel):
    risk_profile: RiskProfileLiteral
    horizon: HorizonLiteral
    cell_id: str
    core: list[PreferredPortfolioEntryRead]
    satellite: list[PreferredPortfolioEntryRead]
    optional: list[PreferredPortfolioEntryRead]
    last_modified_at: datetime | None


class InstrumentInPreferredEntry(BaseModel):
    """Where one instrument appears in the preferred portfolio."""

    entry_id: str
    risk_profile: RiskProfileLiteral
    horizon: HorizonLiteral
    cell_id: str
    position_role: PositionRoleLiteral
    rank_within_role: int


class InstrumentInPreferredResponse(BaseModel):
    instrument_id: str
    instrument_name: str
    appearances: list[InstrumentInPreferredEntry]


# ---------------------------------------------------------------------------
# Health summary (chunk 4.1)
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Health summary for debugging + demos (chunk 4.1 §implementation_notes).

    Returns counts + per-cell role breakdown + last-modified timestamps so
    the audit role can scan model-portfolio state at a glance.
    """

    tagged_instruments_count: int
    untagged_instruments_count: int
    total_instruments: int
    total_preferred_entries: int
    preferred_entries_by_cell: dict[str, CellRoleSummary]
    last_tag_modification_at: datetime | None
    last_preferred_modification_at: datetime | None


# ---------------------------------------------------------------------------
# Chunk 4.2 tag-write request shapes
# ---------------------------------------------------------------------------


class TagSetRequest(BaseModel):
    """PUT /instruments/{id}/tags payload — replace the instrument's tag set."""

    tags: list[str] = Field(default_factory=list, max_length=9)


class BulkTagAddRequest(BaseModel):
    """POST /instruments/tags/bulk-add — add one tag to multiple instruments."""

    tag: str
    instrument_ids: list[str] = Field(min_length=1, max_length=2000)


class BulkTagRemoveRequest(BaseModel):
    """POST /instruments/tags/bulk-remove — remove one tag from multiple instruments."""

    tag: str
    instrument_ids: list[str] = Field(min_length=1, max_length=2000)


class BulkTagReplaceRequest(BaseModel):
    """POST /instruments/tags/bulk-replace — overwrite tag set for many instruments."""

    tags: list[str] = Field(default_factory=list, max_length=9)
    instrument_ids: list[str] = Field(min_length=1, max_length=2000)


class TagResetRequest(BaseModel):
    """POST /instruments/tags/reset-to-default — reset to FR 13.3 defaults.

    When ``instrument_ids`` is empty the reset applies to every instrument
    matching the filter (or all instruments if no filter). Filtered reset
    by ``instrument_ids`` is the chunk-4.2 default UI flow; the whole-
    universe reset uses an empty list with no filter.
    """

    instrument_ids: list[str] = Field(default_factory=list, max_length=5000)


class BulkTagOperationResponse(BaseModel):
    """Summary of a bulk tag operation (returned by add/remove/replace/reset)."""

    affected_count: int
    skipped_count: int
    failed_count: int
    operation: str


# ---------------------------------------------------------------------------
# Chunk 4.3 preferred-portfolio write request shapes
# ---------------------------------------------------------------------------


class CreatePreferredEntryRequest(BaseModel):
    """POST /preferred — add a new preferred portfolio entry."""

    risk_profile: RiskProfileLiteral
    horizon: HorizonLiteral
    instrument_id: str
    position_role: PositionRoleLiteral = "satellite"
    rank_within_role: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=500)


class UpdatePreferredEntryRequest(BaseModel):
    """PUT /preferred/{entry_id} — update role / rank / notes (any subset)."""

    position_role: PositionRoleLiteral | None = None
    rank_within_role: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=500)


class CellReorderItem(BaseModel):
    entry_id: str
    position_role: PositionRoleLiteral
    rank_within_role: int = Field(ge=0)


class CellReorderRequest(BaseModel):
    """POST /preferred/{rp}/{horizon}/reorder — atomic role + rank update for
    every entry in a cell."""

    items: list[CellReorderItem] = Field(min_length=1, max_length=200)


class CellDuplicateRequest(BaseModel):
    """POST /preferred/{rp}/{horizon}/duplicate-from — copy entries from
    a source cell to the current cell."""

    source_risk_profile: RiskProfileLiteral
    source_horizon: HorizonLiteral
    skip_existing: bool = True
    only_matching_tags: bool = True


class CellOperationResponse(BaseModel):
    """Summary returned by per-cell mutations (reorder / duplicate / reset)."""

    risk_profile: RiskProfileLiteral
    horizon: HorizonLiteral
    affected_count: int
    skipped_count: int
    operation: str
