"""ORM models for the E1 verdict cache + manual-flag service.

Two tables (cluster 7 chunk 7.2 §2):

- ``v2_e1_verdict_cache`` — keyed by the cache string the E1 shim
  produces. Stores the full structured verdict + the EvidenceVerdict-
  shaped stage payload + LLM-call telemetry for cost rollups.
- ``v2_e1_manual_flags`` — analyst-set flags that rotate the cache key
  for a ticker (e.g. "promoter pledge changed", "audit qualification
  surfaced"). At most one active flag per ticker at a time.

Both tables carry ``schema_version=1`` to forward-compat the
cluster-7+ shim outputs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# v2_e1_verdict_cache
# ---------------------------------------------------------------------------


class E1VerdictCache(Base):
    """One cached E1 verdict (chunk 7.2 §2.1).

    Primary key is the deterministic cache key the E1 shim produces:

        e1:{ticker}:{latest_earnings_id}:{manual_flag_id}

    Earnings or manual-flag rotation naturally produces a new key, so
    a cache hit only fires when both the ticker's earnings cohort and
    the manual-flag state still match.
    """

    __tablename__ = "v2_e1_verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(200), primary_key=True)

    # Decomposed components for invalidation queries (so we can find
    # all rows for a ticker, or all rows referencing a manual_flag_id).
    ticker: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    earnings_id: Mapped[str] = mapped_column(String(64), nullable=False)
    manual_flag_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True,
    )

    # Cluster 7.1 enriched skill.md version — invalidates implicitly
    # through :func:`repository.evict_on_prompt_change` when prompts
    # are rolled forward.
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)

    # Verdict + LLM telemetry.
    verdict_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stage_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str] = mapped_column(String(80), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Lineage.
    case_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_v2_e1_cache_ticker_earnings", "ticker", "earnings_id"),
    )


# ---------------------------------------------------------------------------
# v2_e1_manual_flags
# ---------------------------------------------------------------------------


class E1ManualFlag(Base):
    """Analyst-set flag that rotates the E1 cache key for a ticker.

    Use cases (chunk 7.2 §3.2):

    - Promoter pledge increases / decreases materially.
    - Audit qualification surfaces between earnings.
    - Regulatory action pending against the issuer.
    - Material litigation update.

    At most one *active* flag per ticker at a time (enforced at the
    application layer in :mod:`.manual_flag`). When an analyst clears
    the flag, ``cleared_at`` is set and ``is_active`` flips to
    ``False``; the row is retained for audit lineage.
    """

    __tablename__ = "v2_e1_manual_flags"

    manual_flag_id: Mapped[str] = mapped_column(String(26), primary_key=True)

    ticker: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    flagged_by: Mapped[str] = mapped_column(String(64), nullable=False)
    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cleared_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_v2_e1_manual_flags_ticker_active", "ticker", "is_active"),
    )


__all__ = ["E1ManualFlag", "E1VerdictCache"]
