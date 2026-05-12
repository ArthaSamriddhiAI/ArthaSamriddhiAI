"""ORM models for cluster 8 infrastructure tables.

Cluster 8 chunks 8.1-8.4 add:

- Macro regime tracking: ``v2_macro_regimes`` + ``v2_rate_policy_events``
  + ``v2_e3mv_verdict_cache``
- Sector classification: ``v2_sector_classifications`` + ``v2_ticker_sector_map``
  + ``v2_sector_level_manual_flags`` + ``v2_e2sv_verdict_cache``
  + ``v2_e2sis_verdict_cache``
- Fund disclosures: ``v2_quarterly_disclosure_events``
  + ``v2_fund_level_manual_flags`` + ``v2_e7_verdict_cache``
- News events: ``v2_news_events``

Chunk 8.2 also replaces cluster 7's ``v2_e1_manual_flags`` with the
generalised ``v2_stock_level_manual_flags`` table (adds ``firm_id``,
``invalidates_e1``, ``invalidates_e2sis``; renames columns for
uniformity).  The Python ORM for the old table is kept as
:class:`StockLevelManualFlag`; cluster 7's ``E1ManualFlag`` is aliased
for backward compat.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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
# Chunk 8.2: stock_level_manual_flags (replaces v2_e1_manual_flags)
# ---------------------------------------------------------------------------


class StockLevelManualFlag(Base):
    """Generalised per-stock manual flag shared by E1 and E2.StockInSector.

    Supersedes :class:`artha.api_v2.agents.cache.models.E1ManualFlag`
    (cluster 7 chunk 7.2).  Migration creates this table, copies cluster-7
    data, and drops the old table.

    ``cleared_at IS NULL`` is the canonical active-flag predicate; the
    ``is_active`` boolean is retained at the Python layer for query
    convenience and backward compat with existing manual_flag service code.
    """

    __tablename__ = "v2_stock_level_manual_flags"

    manual_flag_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticker: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    advisor_id: Mapped[str] = mapped_column(String(64), nullable=False)

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Per-push scoping (chunk 8.2 §2.1).
    invalidates_e1: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    invalidates_e2sis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Python-layer convenience field (not in DB spec, mirrored via cleared_at).
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    __table_args__ = (
        Index("ix_v2_slmf_firm_ticker_active", "firm_id", "ticker", "is_active"),
    )


# ---------------------------------------------------------------------------
# Chunk 8.1: Macro regime tracking
# ---------------------------------------------------------------------------


class MacroRegime(Base):
    """Active + historical macro regime entries (chunk 8.1 §1.1)."""

    __tablename__ = "v2_macro_regimes"

    regime_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    regime_name: Mapped[str] = mapped_column(String(128), nullable=False)
    regime_category: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggering_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    triggering_event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_v2_macro_regime_active", "ended_at", "started_at"),
    )


class RatePolicyEvent(Base):
    """Rate policy + macro shock events ingested from D0 (chunk 8.1 §1.2)."""

    __tablename__ = "v2_rate_policy_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    materiality_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        Index("ix_v2_rpe_type_date", "event_type", "event_date"),
        Index("ix_v2_rpe_material_date", "is_material", "event_date"),
    )


class E3mvVerdictCache(Base):
    """E3.MacroView verdict cache (chunk 8.1 §4)."""

    __tablename__ = "v2_e3mv_verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    macro_regime_id: Mapped[str] = mapped_column(String(64), nullable=False)
    latest_material_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stage_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_v2_e3mv_firm_regime", "firm_id", "macro_regime_id"),
    )


# ---------------------------------------------------------------------------
# Chunk 8.2: Sector classification + E2 caches
# ---------------------------------------------------------------------------


class SectorClassification(Base):
    """NSE sector codes (chunk 8.2 §1.1)."""

    __tablename__ = "v2_sector_classifications"

    sector_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nse_index_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TickerSectorMap(Base):
    """Ticker → sector mapping (chunk 8.2 §1.2). Supports conglomerates."""

    __tablename__ = "v2_ticker_sector_map"

    ticker: Mapped[str] = mapped_column(String(64), primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    primary_sector: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_v2_tsm_ticker_active", "ticker", "effective_until"),
    )


class SectorLevelManualFlag(Base):
    """Per-sector manual flag for E2.SectorView cache invalidation (chunk 8.2 §2.3)."""

    __tablename__ = "v2_sector_level_manual_flags"

    manual_flag_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_code: Mapped[str] = mapped_column(String(64), nullable=False)
    advisor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_v2_slvmf_firm_sector_active", "firm_id", "sector_code", "is_active"),
    )


class E2svVerdictCache(Base):
    """E2.SectorView verdict cache (chunk 8.2 §3.2)."""

    __tablename__ = "v2_e2sv_verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_code: Mapped[str] = mapped_column(String(64), nullable=False)
    macro_regime_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_manual_flag_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stage_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_v2_e2sv_firm_sector", "firm_id", "sector_code"),
    )


class E2sisVerdictCache(Base):
    """E2.StockInSector verdict cache (chunk 8.2 §4.2)."""

    __tablename__ = "v2_e2sis_verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_code: Mapped[str] = mapped_column(String(64), nullable=False)
    latest_earnings_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stock_manual_flag_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stage_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_v2_e2sis_firm_ticker", "firm_id", "ticker"),
    )


# ---------------------------------------------------------------------------
# Chunk 8.3: Quarterly disclosures + E7 cache
# ---------------------------------------------------------------------------


class QuarterlyDisclosureEvent(Base):
    """Quarterly MF disclosure event (chunk 8.3 §3.1)."""

    __tablename__ = "v2_quarterly_disclosure_events"

    disclosure_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fund_name: Mapped[str] = mapped_column(String(256), nullable=False)
    fund_category: Mapped[str] = mapped_column(String(64), nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(16), nullable=False)
    disclosure_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    aum_inr_cr: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    manager_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manager_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    manager_changed_this_quarter: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    ter_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    exit_load_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    top_holdings_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    portfolio_stats_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    performance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_v2_qde_fund_date", "fund_id", "disclosure_date"),
    )


class FundLevelManualFlag(Base):
    """Per-fund manual flag for E7 cache invalidation (chunk 8.3 §6.1)."""

    __tablename__ = "v2_fund_level_manual_flags"

    manual_flag_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False)
    advisor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_v2_flmf_firm_fund_active", "firm_id", "fund_id", "is_active"),
    )


class E7VerdictCache(Base):
    """E7 mutual fund verdict cache (chunk 8.3 §5)."""

    __tablename__ = "v2_e7_verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fund_id: Mapped[str] = mapped_column(String(64), nullable=False)
    latest_quarterly_disclosure_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fund_manual_flag_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stage_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_v2_e7_firm_fund", "firm_id", "fund_id"),
    )


# ---------------------------------------------------------------------------
# Chunk 8.4: News events
# ---------------------------------------------------------------------------


class NewsEvent(Base):
    """Per-ticker news event (chunk 8.4 §3.1)."""

    __tablename__ = "v2_news_events"

    news_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    associated_tickers: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    news_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_material_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_v2_news_published", "published_at"),
        Index("ix_v2_news_tickers_published", "associated_tickers", "published_at"),
    )


__all__ = [
    "E2sisVerdictCache",
    "E2svVerdictCache",
    "E3mvVerdictCache",
    "E7VerdictCache",
    "FundLevelManualFlag",
    "MacroRegime",
    "NewsEvent",
    "QuarterlyDisclosureEvent",
    "RatePolicyEvent",
    "SectorClassification",
    "SectorLevelManualFlag",
    "StockLevelManualFlag",
    "TickerSectorMap",
]
