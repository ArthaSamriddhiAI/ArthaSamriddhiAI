"""ORM models for cluster 9 infrastructure tables.

Cluster 9 chunks 9.1–9.4 add:

- **Unlisted entity masters** (chunk 9.1):
  ``v2_aif_master`` + ``v2_unlisted_company_master``
  + ``v2_firm_internal_entity_master``
- **Event / disclosure tables** (chunk 9.1):
  ``v2_aif_disclosure_events`` + ``v2_mca_filing_events`` + ``v2_deals``
- **E5.FundView + E5.DealView** (chunk 9.2):
  ``v2_deal_level_manual_flags`` + ``v2_e5fv_verdict_cache``
  + ``v2_e5dv_verdict_cache``
- **E4 Behavioural** (chunk 9.3):
  ``v2_investor_level_manual_flags`` + ``v2_e4_verdict_cache``
- **E3.NewsScanner push audit trail** (chunk 9.4):
  ``v2_e3_push_log``

Existing cluster-8 tables that receive new columns (added directly to
:mod:`models_cluster8`):

- ``v2_fund_level_manual_flags`` — new ``invalidates_e7`` +
  ``invalidates_e5fv`` columns (chunk 9.2 §1.1).
- ``v2_news_events`` — new ``entity_type`` + ``entity_id``
  + ``source_path`` columns (chunk 9.4 §1.3).
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# Chunk 9.1: Unlisted entity masters
# ---------------------------------------------------------------------------


class AifMaster(Base):
    """SEBI-registered Alternative Investment Fund master record (chunk 9.1 §1).

    Keyed on SEBI AIF Registration ID (e.g. ``IN/AIF2/24-25/00123``).
    """

    __tablename__ = "v2_aif_master"

    aif_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fund_name: Mapped[str] = mapped_column(String(256), nullable=False)
    fund_house: Mapped[str] = mapped_column(String(256), nullable=False)
    aif_category: Mapped[str] = mapped_column(String(32), nullable=False)
    aif_sub_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vintage_year: Mapped[int] = mapped_column(Integer, nullable=False)
    target_corpus_inr_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    committed_corpus_inr_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    drawn_corpus_inr_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    fund_manager_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fund_manager_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    focus_area: Mapped[str | None] = mapped_column(String(256), nullable=True)
    lockup_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_exit_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sebi_registered_at: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    sebi_registration_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_v2_aif_category_active", "aif_category", "sebi_registration_active"),
        Index("ix_v2_aif_manager", "fund_manager_id"),
        Index("ix_v2_aif_active_until", "sebi_registration_active", "effective_until"),
    )


class UnlistedCompanyMaster(Base):
    """MCA-registered unlisted company master record (chunk 9.1 §2).

    Keyed on Corporate Identification Number (CIN).
    """

    __tablename__ = "v2_unlisted_company_master"

    cin: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    incorporation_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    registered_office_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registered_office_city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_paid_up_capital: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    authorized_capital: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    sector_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sub_sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_funding_round_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_known_valuation_inr_cr: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    mca_status_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_v2_ucm_sector", "sector_code"),
        Index("ix_v2_ucm_stage_status", "stage", "status"),
        Index("ix_v2_ucm_active_until", "mca_status_active", "effective_until"),
    )


class FirmInternalEntityMaster(Base):
    """Firm-issued master record for edge-case entities (chunk 9.1 §3).

    Covers foreign entities, pre-incorporation stakes, private deals not
    yet CIN-registered, and similar out-of-scope identifiers.
    """

    __tablename__ = "v2_firm_internal_entity_master"

    internal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(256), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    related_cin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_aif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index("ix_v2_fiem_firm_active", "firm_id", "effective_until"),
        Index("ix_v2_fiem_entity_type", "entity_type"),
    )


# ---------------------------------------------------------------------------
# Chunk 9.1: Event / disclosure tables
# ---------------------------------------------------------------------------


class AifDisclosureEvent(Base):
    """AIF quarterly LP disclosure event (chunk 9.1 §4).

    Analogous to :class:`~models_cluster8.QuarterlyDisclosureEvent` for
    E7 mutual funds; cluster-9 parallel for AIFs.
    """

    __tablename__ = "v2_aif_disclosure_events"

    disclosure_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    aif_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(16), nullable=False)
    disclosure_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    ingested_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    ingestion_source: Mapped[str] = mapped_column(String(32), nullable=False)
    nav_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(15, 4), nullable=True)
    total_aum_inr_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    irr_since_inception_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    dpi_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tvpi_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    manager_continuity_signal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manager_changed_this_quarter: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    capital_call_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    distributions_inr_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    portfolio_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_deals_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    governance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_v2_ade_aif_date", "aif_id", "disclosure_date"),
        Index("ix_v2_ade_manager_change", "manager_changed_this_quarter", "disclosure_date"),
    )


class McaFilingEvent(Base):
    """MCA filing event for unlisted companies (chunk 9.1 §5)."""

    __tablename__ = "v2_mca_filing_events"

    filing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cin: Mapped[str] = mapped_column(String(64), nullable=False)
    filing_type: Mapped[str] = mapped_column(String(64), nullable=False)
    filing_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    ingested_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fiscal_year: Mapped[str | None] = mapped_column(String(16), nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_material_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    materiality_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        Index("ix_v2_mca_cin_date", "cin", "filing_date"),
        Index("ix_v2_mca_type_date", "filing_type", "filing_date"),
        Index("ix_v2_mca_material_date", "is_material_seed", "filing_date"),
    )


class Deal(Base):
    """Firm-supplied deal metadata (chunk 9.1 §8.2).

    Stores per-deal information for direct investments, AIF look-through
    deals, and firm co-investment data supplied via the D0 metadata API.
    """

    __tablename__ = "v2_deals"

    deal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fund_or_firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    company_cin_or_internal: Mapped[str] = mapped_column(String(64), nullable=False)
    deal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    deal_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    round_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_inr_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    valuation_pre_money_inr_cr: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True,
    )
    valuation_post_money_inr_cr: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True,
    )
    lead_investor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    board_seat_taken: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exit_horizon_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingested_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    source_document_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_v2_deals_company", "company_cin_or_internal", "deal_date"),
        Index("ix_v2_deals_fund", "fund_or_firm_id", "deal_date"),
    )


# ---------------------------------------------------------------------------
# Chunk 9.2: E5.FundView + E5.DealView — flag + cache tables
# ---------------------------------------------------------------------------


class DealLevelManualFlag(Base):
    """Per-deal manual flag for E5.DealView cache invalidation (chunk 9.2 §1.4).

    Python-layer ``is_active`` mirrors ``cleared_at IS NULL`` for query
    convenience (same pattern as cluster-8 flag tables).
    """

    __tablename__ = "v2_deal_level_manual_flags"

    manual_flag_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    deal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    advisor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidates_e5dv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_v2_dlmf_firm_deal_active", "firm_id", "deal_id", "cleared_at"),
        Index("ix_v2_dlmf_firm_deal_is_active", "firm_id", "deal_id", "is_active"),
    )


class E5fvVerdictCache(Base):
    """E5.FundView verdict cache (chunk 9.2 §2.2).

    Cache key: ``e5fv:{aif_id}:{latest_aif_disclosure_id}:{fund_manual_flag_id}``.
    Sentinel ``null`` when no active flag.  90-day soft TTL via ``expires_at``.
    """

    __tablename__ = "v2_e5fv_verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    aif_id: Mapped[str] = mapped_column(String(64), nullable=False)
    latest_aif_disclosure_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fund_manual_flag_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_v2_e5fv_firm_aif_expires", "firm_id", "aif_id", "expires_at"),
    )


class E5dvVerdictCache(Base):
    """E5.DealView verdict cache (chunk 9.2 §3.2).

    Cache key:
    ``e5dv:{deal_id}:{fund_or_firm_id}:{latest_mca_filing_id}:{deal_manual_flag_id}``.
    90-day soft TTL via ``expires_at``.
    """

    __tablename__ = "v2_e5dv_verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    deal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fund_or_firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cin_or_internal: Mapped[str] = mapped_column(String(64), nullable=False)
    latest_mca_filing_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deal_manual_flag_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_v2_e5dv_firm_deal_expires", "firm_id", "deal_id", "expires_at"),
        Index("ix_v2_e5dv_cin", "cin_or_internal", "expires_at"),
    )


# ---------------------------------------------------------------------------
# Chunk 9.3: E4 Behavioural — flag + cache tables
# ---------------------------------------------------------------------------


class InvestorLevelManualFlag(Base):
    """Per-investor behavioural manual flag for E4 cache invalidation (chunk 9.3 §5).

    Set by advisors when they observe a behavioural shift not yet captured
    in trading patterns (e.g. panic during a market correction).  Changing
    the flag changes the E4 cache key, forcing a fresh verdict.

    Python-layer ``is_active`` mirrors ``cleared_at IS NULL`` for query
    convenience.
    """

    __tablename__ = "v2_investor_level_manual_flags"

    manual_flag_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    investor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    advisor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidates_e4: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_v2_ilmf_firm_investor_active", "firm_id", "investor_id", "cleared_at"),
        Index("ix_v2_ilmf_is_active", "firm_id", "investor_id", "is_active"),
    )


class E4VerdictCache(Base):
    """E4 Behavioural verdict cache (chunk 9.3 §4).

    Cache key:
    ``e4:{investor_id}:{window_id}:{behavioural_manual_flag_id}``.
    30-day TTL backstop via ``expires_at`` (shorter than 90-day standard
    per Lock 6 — behavioural patterns shift on monthly cadence).
    """

    __tablename__ = "v2_e4_verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    investor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    window_id: Mapped[str] = mapped_column(String(32), nullable=False)
    behavioural_manual_flag_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_v2_e4_firm_investor_expires", "firm_id", "investor_id", "expires_at"),
    )


# ---------------------------------------------------------------------------
# Chunk 9.4: E3.NewsScanner push audit trail
# ---------------------------------------------------------------------------


class E3PushLog(Base):
    """E3.NewsScanner push-insertion audit trail (chunk 9.4 §6.3).

    Each cache-invalidation push attempt emitted by E3.NewsScanner is
    logged here (success or failure) for retrospective audit and
    operational alerting.
    """

    __tablename__ = "v2_e3_push_log"

    push_log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    e3_scanner_call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pushed_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resulting_flag_table: Mapped[str] = mapped_column(String(64), nullable=False)
    resulting_flag_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resulting_flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    push_status: Mapped[str] = mapped_column(String(32), nullable=False)
    push_failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_v2_e3pl_call", "e3_scanner_call_id"),
        Index("ix_v2_e3pl_entity", "entity_type", "entity_id"),
    )


__all__ = [
    # Chunk 9.1: entity masters
    "AifMaster",
    "AifDisclosureEvent",
    "Deal",
    "FirmInternalEntityMaster",
    "McaFilingEvent",
    "UnlistedCompanyMaster",
    # Chunk 9.2: E5.FundView + E5.DealView
    "DealLevelManualFlag",
    "E5dvVerdictCache",
    "E5fvVerdictCache",
    # Chunk 9.3: E4 Behavioural
    "E4VerdictCache",
    "InvestorLevelManualFlag",
    # Chunk 9.4: E3.NewsScanner push log
    "E3PushLog",
]
