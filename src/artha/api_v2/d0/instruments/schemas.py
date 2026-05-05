"""Pydantic read shapes for the Instrument browse surface."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class InstrumentRead(BaseModel):
    """One Instrument row as it appears in the admin browser + API."""

    instrument_id: str

    # Identifiers
    isin: str | None
    amfi_scheme_code: str | None
    exchange_ticker: str | None
    name: str
    short_name: str | None

    # Classification
    asset_class: str
    vehicle_type: str
    sebi_category: str | None
    sebi_subcategory: str | None
    classification_confidence: str

    # Issuer / fund house
    issuer_name: str | None
    amc_name: str | None

    # Risk
    riskometer_label: str | None

    # Status + lifecycle
    status: str
    inception_date: date | None

    # Source lineage
    source_identifier: str
    source_subkey: str | None
    staging_record_id: str | None
    adapter_run_id: str | None

    # Provenance
    created_at: datetime
    last_modified_at: datetime
    schema_version: int


class InstrumentListResponse(BaseModel):
    """Paginated browse response."""

    instruments: list[InstrumentRead]
    total: int
    limit: int
    offset: int


class InstrumentFilters(BaseModel):
    """Query-string filter shape (purely documentary; FastAPI parses
    individual query params, but this gives the schema a single home)."""

    asset_class: str | None = Field(default=None)
    vehicle_type: str | None = Field(default=None)
    sebi_category: str | None = Field(default=None)
    status: str | None = Field(default=None)
    search: str | None = Field(
        default=None,
        description=(
            "Case-insensitive substring match on name, ISIN, AMFI code, "
            "or exchange ticker."
        ),
    )
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
