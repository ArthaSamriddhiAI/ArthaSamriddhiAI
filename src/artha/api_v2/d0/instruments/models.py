"""Instrument canonical-entity ORM (FR Entry 10.7 §4 cluster-3 revision).

One row per investable instrument — Indian mutual funds (SEBI-categorised),
ETFs, listed equities, bonds, and a few alternatives buckets. The schema
is deliberately wide rather than normalised: D0 is a write-shaped surface
where consumers care about a single read-friendly catalogue, and the
trade-off favours read-side simplicity over write-side normalisation.

Key design notes:

- ``isin`` is the canonical business identifier when present, but a
  meaningful slice of Indian MFs lack ISINs in third-party feeds, so we
  also persist ``amfi_scheme_code`` + ``exchange_ticker`` as fallback
  identifiers. The unique-where-not-null index on each is enforced at the
  application layer (cluster 3 keeps the schema portable across SQLite +
  Postgres without partial-index dialect quirks).
- Classification is split into ``asset_class`` (the four-band cluster-3
  vocabulary), ``vehicle_type`` (the wrapper kind), and the SEBI category
  + subcategory pair (when applicable). A separate
  ``classification_confidence`` enum records whether classification is
  trustworthy, in which case the JSONFixtureAdapter writes ``high``, vs
  uncertain, in which case the adapter emits the
  :data:`INSTRUMENT_CLASSIFICATION_UNCERTAIN` T1 event and writes ``low``.
- ``source_identifier`` + ``source_subkey`` + ``adapter_run_id`` +
  ``staging_record_id`` give every row complete D0 lineage so audit
  replay (cluster 15) can reconstruct any row from staging.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class Instrument(Base):
    """One investable instrument."""

    __tablename__ = "v2_instruments"

    instrument_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # ----- Identifiers -----
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    amfi_scheme_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    exchange_ticker: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ----- Classification -----
    asset_class: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    vehicle_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sebi_category: Mapped[str | None] = mapped_column(
        String(60), nullable=True, index=True
    )
    sebi_subcategory: Mapped[str | None] = mapped_column(String(80), nullable=True)
    classification_confidence: Mapped[str] = mapped_column(
        String(10), nullable=False, default="high"
    )

    # ----- Issuer / fund house -----
    issuer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amc_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ----- Risk -----
    riskometer_label: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ----- Status + lifecycle -----
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )
    inception_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ----- Source lineage (FR 10.0 §5.2) -----
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
    # ----- Model portfolio tags (cluster 4 chunk 4.1) -----
    # Per FR Entry 13.1 §2.1: a JSON array of cell-identifier strings from
    # the 9-element enum (e.g. "moderate_long_term"). The default loader
    # populates this from SEBI category + vehicle type rules at startup;
    # the CIO refines via the chunk 4.2 admin UI. Modification metadata
    # is initially NULL (defaults applied at startup are not "edited"),
    # populated when a human edits via the admin UI.
    model_portfolio_tags: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    model_portfolio_tags_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    model_portfolio_tags_modified_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    __table_args__ = (
        Index("ix_v2_instruments_class_vehicle", "asset_class", "vehicle_type"),
        Index("ix_v2_instruments_sebi_category_status", "sebi_category", "status"),
    )
