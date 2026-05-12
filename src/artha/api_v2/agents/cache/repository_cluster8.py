"""Async CRUD for cluster-8 verdict caches (chunks 8.1-8.3).

Four per-agent cache tables — each keyed by the deterministic string
the corresponding shim's :meth:`compute_cache_key` produces:

  e3_macro_view       → v2_e3mv_verdict_cache
  e2_sector_view      → v2_e2sv_verdict_cache
  e2_stock_in_sector  → v2_e2sis_verdict_cache
  e7_mutual_fund      → v2_e7_verdict_cache

Column name note: cluster-8 tables use ``verdict_json`` / ``stage_json``
(not ``verdict_payload`` / ``stage_payload`` like E1). The public API
surfaces these as :class:`CachedVerdict` (``verdict_payload`` /
``stage_payload``) to stay consistent with the cluster-7 interface.

TTL semantics: sliding window on ``last_accessed_at``.  Every cache
hit bumps ``last_accessed_at`` and increments ``cache_hit_count``.

Invalidation helpers:

- :func:`invalidate_e2sis_for_stock_flag` — drop E2SIS rows referencing
  a superseded ``stock_manual_flag_id``.
- :func:`invalidate_all_e2sis_for_ticker` — drop ALL E2SIS rows for a
  ticker (used by the E3.NewsScanner push mechanism).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Union

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.agents.cache.models_cluster8 import (
    E2sisVerdictCache,
    E2svVerdictCache,
    E3mvVerdictCache,
    E7VerdictCache,
)
from artha.api_v2.agents.cache.repository import CachedVerdict

#: Default TTL mirrors the cluster-7 ideation log §6.5 (90 days).
DEFAULT_TTL_DAYS = 90

# All four cluster-8 cache ORM models keyed by agent_id.
_C8Model = Union[
    E3mvVerdictCache, E2svVerdictCache, E2sisVerdictCache, E7VerdictCache,
]
_AGENT_TO_MODEL: dict[str, type[_C8Model]] = {  # type: ignore[type-arg]
    "e3_macro_view": E3mvVerdictCache,
    "e2_sector_view": E2svVerdictCache,
    "e2_stock_in_sector": E2sisVerdictCache,
    "e7_mutual_fund": E7VerdictCache,
}


# ---------------------------------------------------------------------------
# Generic read
# ---------------------------------------------------------------------------


async def get_cached_verdict_c8(
    db: AsyncSession,
    *,
    agent_id: str,
    cache_key: str,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime | None = None,
) -> CachedVerdict | None:
    """Return the cached verdict for ``cache_key`` if any (and not expired).

    Sliding-window TTL: expiry is measured from ``last_accessed_at``.
    A hit bumps ``last_accessed_at`` and ``cache_hit_count`` in-place.
    Returns ``None`` (miss) if the row is stale or absent.
    """
    model = _AGENT_TO_MODEL.get(agent_id)
    if model is None:
        return None

    row: _C8Model | None = (
        await db.execute(select(model).where(model.cache_key == cache_key))
    ).scalar_one_or_none()
    if row is None:
        return None

    moment = now or datetime.now(timezone.utc)
    if _is_expired_c8(row, ttl_days=ttl_days, now=moment):
        await db.delete(row)
        await db.flush()
        return None

    # Sliding-window refresh.
    row.last_accessed_at = moment
    row.cache_hit_count = (row.cache_hit_count or 0) + 1
    await db.flush()

    return CachedVerdict(
        cache_key=row.cache_key,
        verdict_payload=row.verdict_json,
        stage_payload=row.stage_json,
        raw_text=row.raw_text,
        llm_model=row.llm_model,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Agent-specific writes
# ---------------------------------------------------------------------------


async def write_e3mv_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    firm_id: str,
    macro_regime_id: str,
    latest_material_event_id: str | None,
    verdict_json: dict[str, Any],
    stage_json: dict[str, Any],
    raw_text: str | None,
    llm_model: str,
    prompt_version: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    now: datetime | None = None,
) -> E3mvVerdictCache:
    """Upsert an E3.MacroView verdict row.  Last-write-wins on key collision."""
    moment = now or datetime.now(timezone.utc)
    existing = await _get_row(db, E3mvVerdictCache, cache_key)
    if existing is not None:
        _update_common(
            existing, verdict_json, stage_json, raw_text, llm_model,
            prompt_version, input_tokens, output_tokens, moment,
        )
        await db.flush()
        return existing

    row = E3mvVerdictCache(
        cache_key=cache_key,
        firm_id=firm_id,
        macro_regime_id=macro_regime_id,
        latest_material_event_id=latest_material_event_id,
        verdict_json=verdict_json,
        stage_json=stage_json,
        raw_text=raw_text,
        llm_model=llm_model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_hit_count=0,
        created_at=moment,
        last_accessed_at=moment,
    )
    db.add(row)
    await db.flush()
    return row


async def write_e2sv_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    firm_id: str,
    sector_code: str,
    macro_regime_id: str,
    sector_manual_flag_id: str | None,
    verdict_json: dict[str, Any],
    stage_json: dict[str, Any],
    raw_text: str | None,
    llm_model: str,
    prompt_version: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    now: datetime | None = None,
) -> E2svVerdictCache:
    """Upsert an E2.SectorView verdict row."""
    moment = now or datetime.now(timezone.utc)
    existing = await _get_row(db, E2svVerdictCache, cache_key)
    if existing is not None:
        _update_common(
            existing, verdict_json, stage_json, raw_text, llm_model,
            prompt_version, input_tokens, output_tokens, moment,
        )
        await db.flush()
        return existing

    row = E2svVerdictCache(
        cache_key=cache_key,
        firm_id=firm_id,
        sector_code=sector_code,
        macro_regime_id=macro_regime_id,
        sector_manual_flag_id=_norm_flag(sector_manual_flag_id),
        verdict_json=verdict_json,
        stage_json=stage_json,
        raw_text=raw_text,
        llm_model=llm_model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_hit_count=0,
        created_at=moment,
        last_accessed_at=moment,
    )
    db.add(row)
    await db.flush()
    return row


async def write_e2sis_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    firm_id: str,
    ticker: str,
    sector_code: str,
    latest_earnings_id: str | None,
    stock_manual_flag_id: str | None,
    verdict_json: dict[str, Any],
    stage_json: dict[str, Any],
    raw_text: str | None,
    llm_model: str,
    prompt_version: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    now: datetime | None = None,
) -> E2sisVerdictCache:
    """Upsert an E2.StockInSector verdict row."""
    moment = now or datetime.now(timezone.utc)
    existing = await _get_row(db, E2sisVerdictCache, cache_key)
    if existing is not None:
        _update_common(
            existing, verdict_json, stage_json, raw_text, llm_model,
            prompt_version, input_tokens, output_tokens, moment,
        )
        await db.flush()
        return existing

    row = E2sisVerdictCache(
        cache_key=cache_key,
        firm_id=firm_id,
        ticker=ticker,
        sector_code=sector_code,
        latest_earnings_id=latest_earnings_id or None,
        stock_manual_flag_id=_norm_flag(stock_manual_flag_id),
        verdict_json=verdict_json,
        stage_json=stage_json,
        raw_text=raw_text,
        llm_model=llm_model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_hit_count=0,
        created_at=moment,
        last_accessed_at=moment,
    )
    db.add(row)
    await db.flush()
    return row


async def write_e7_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    firm_id: str,
    fund_id: str,
    latest_quarterly_disclosure_id: str | None,
    fund_manual_flag_id: str | None,
    verdict_json: dict[str, Any],
    stage_json: dict[str, Any],
    raw_text: str | None,
    llm_model: str,
    prompt_version: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    now: datetime | None = None,
) -> E7VerdictCache:
    """Upsert an E7 MutualFund verdict row."""
    moment = now or datetime.now(timezone.utc)
    existing = await _get_row(db, E7VerdictCache, cache_key)
    if existing is not None:
        _update_common(
            existing, verdict_json, stage_json, raw_text, llm_model,
            prompt_version, input_tokens, output_tokens, moment,
        )
        await db.flush()
        return existing

    row = E7VerdictCache(
        cache_key=cache_key,
        firm_id=firm_id,
        fund_id=fund_id,
        latest_quarterly_disclosure_id=latest_quarterly_disclosure_id or None,
        fund_manual_flag_id=_norm_flag(fund_manual_flag_id),
        verdict_json=verdict_json,
        stage_json=stage_json,
        raw_text=raw_text,
        llm_model=llm_model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_hit_count=0,
        created_at=moment,
        last_accessed_at=moment,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


async def invalidate_e2sis_for_stock_flag(
    db: AsyncSession,
    *,
    ticker: str,
    superseded_flag_id: str | None,
) -> int:
    """Drop E2SIS rows whose ``stock_manual_flag_id`` is now stale.

    Called from :mod:`agents.cache.manual_flag` alongside the E1
    invalidation when a stock-level flag is created or cleared.
    """
    stmt = delete(E2sisVerdictCache).where(
        E2sisVerdictCache.ticker == ticker,
        E2sisVerdictCache.stock_manual_flag_id == superseded_flag_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def invalidate_all_e2sis_for_ticker(
    db: AsyncSession,
    *,
    ticker: str,
) -> int:
    """Drop ALL E2SIS cache rows for ``ticker``.

    Used by the E3.NewsScanner push mechanism when a material news
    event warrants full cache invalidation for a ticker regardless of
    the current flag state.
    """
    stmt = delete(E2sisVerdictCache).where(
        E2sisVerdictCache.ticker == ticker,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_row(
    db: AsyncSession,
    model: type[_C8Model],
    cache_key: str,
) -> _C8Model | None:
    return (
        await db.execute(select(model).where(model.cache_key == cache_key))
    ).scalar_one_or_none()


def _update_common(
    row: _C8Model,
    verdict_json: dict[str, Any],
    stage_json: dict[str, Any],
    raw_text: str | None,
    llm_model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    moment: datetime,
) -> None:
    """In-place update the common fields on a cache row (upsert path)."""
    row.verdict_json = verdict_json
    row.stage_json = stage_json
    row.raw_text = raw_text
    row.llm_model = llm_model
    row.prompt_version = prompt_version
    row.input_tokens = input_tokens
    row.output_tokens = output_tokens
    row.last_accessed_at = moment
    row.cache_hit_count = 0


def _is_expired_c8(
    row: _C8Model,
    *,
    ttl_days: int,
    now: datetime,
) -> bool:
    cutoff = now - timedelta(days=ttl_days)
    accessed = row.last_accessed_at
    if accessed.tzinfo is None:
        accessed = accessed.replace(tzinfo=timezone.utc)
    return accessed < cutoff


def _norm_flag(flag_id: str | None) -> str | None:
    """Normalise the sentinel string ``"null"`` to ``None`` for storage."""
    return None if flag_id in (None, "null", "") else flag_id


__all__ = [
    "DEFAULT_TTL_DAYS",
    "get_cached_verdict_c8",
    "invalidate_all_e2sis_for_ticker",
    "invalidate_e2sis_for_stock_flag",
    "write_e2sis_verdict",
    "write_e2sv_verdict",
    "write_e3mv_verdict",
    "write_e7_verdict",
]
