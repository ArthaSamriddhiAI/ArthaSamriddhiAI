"""Async CRUD for cluster-9 verdict caches (chunks 9.2–9.3).

Three per-agent cache tables — each keyed by the deterministic string
the corresponding shim's :meth:`compute_cache_key` produces:

  e5_fund_view  → v2_e5fv_verdict_cache
  e5_deal_view  → v2_e5dv_verdict_cache
  e4_behavioural → v2_e4_verdict_cache

Column name note: cluster-9 tables use ``verdict_json`` only (no
``stage_json`` column like cluster 8).  The :class:`CachedVerdict`
returned by :func:`get_cached_verdict_c9` maps ``verdict_json`` to both
``verdict_payload`` and ``stage_payload`` for interface compatibility —
callers that need the stage dict should use ``verdict_payload`` directly.

TTL semantics: hard expiry via ``expires_at`` (set at write time).
Every cache hit bumps ``last_accessed_at`` and ``cache_hit_count``.

Invalidation helpers:

- :func:`invalidate_e5fv_for_fund_flag` — drop E5.FundView rows
  referencing a superseded ``fund_manual_flag_id``.
- :func:`invalidate_e5dv_for_deal_flag` — drop E5.DealView rows
  referencing a superseded ``deal_manual_flag_id``.
- :func:`invalidate_e4_for_investor_flag` — drop E4 rows referencing
  a superseded ``behavioural_manual_flag_id``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.agents.cache.models_cluster9 import (
    E4VerdictCache,
    E5dvVerdictCache,
    E5fvVerdictCache,
)
from artha.api_v2.agents.cache.repository import CachedVerdict

#: Default TTL for E5.FundView and E5.DealView (90 days per spec).
DEFAULT_TTL_DAYS_E5 = 90

#: Default TTL for E4 (30 days per chunk 9.3 Lock 6).
DEFAULT_TTL_DAYS_E4 = 30


# ---------------------------------------------------------------------------
# Generic read
# ---------------------------------------------------------------------------


async def get_cached_verdict_c9(
    db: AsyncSession,
    *,
    agent_id: str,
    cache_key: str,
    now: datetime | None = None,
) -> CachedVerdict | None:
    """Return the cached verdict for ``cache_key`` if any (and not expired).

    Expiry check uses ``expires_at`` (hard expiry, set at write time).
    A hit bumps ``last_accessed_at`` and ``cache_hit_count`` in-place.
    Returns ``None`` (miss) if the row is stale or absent.
    """
    moment = now or datetime.now(timezone.utc)

    if agent_id == "e5_fund_view":
        return await _get_e5fv(db, cache_key=cache_key, now=moment)
    if agent_id == "e5_deal_view":
        return await _get_e5dv(db, cache_key=cache_key, now=moment)
    if agent_id == "e4_behavioural":
        return await _get_e4(db, cache_key=cache_key, now=moment)
    return None


# ---------------------------------------------------------------------------
# Agent-specific writes
# ---------------------------------------------------------------------------


async def write_e5fv_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    firm_id: str,
    aif_id: str,
    latest_aif_disclosure_id: str | None,
    fund_manual_flag_id: str | None,
    verdict_json: dict[str, Any],
    llm_model: str,
    prompt_version: str,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    ttl_days: int = DEFAULT_TTL_DAYS_E5,
    now: datetime | None = None,
) -> E5fvVerdictCache:
    """Upsert an E5.FundView verdict row.  Last-write-wins on key collision."""
    moment = now or datetime.now(timezone.utc)
    expires = moment + timedelta(days=ttl_days)

    existing: E5fvVerdictCache | None = (
        await db.execute(
            select(E5fvVerdictCache).where(E5fvVerdictCache.cache_key == cache_key),
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.verdict_json = verdict_json
        existing.llm_model = llm_model
        existing.prompt_version = prompt_version
        existing.total_input_tokens = total_input_tokens
        existing.total_output_tokens = total_output_tokens
        existing.expires_at = expires
        existing.last_accessed_at = moment
        existing.cache_hit_count = 0
        await db.flush()
        return existing

    row = E5fvVerdictCache(
        cache_key=cache_key,
        firm_id=firm_id,
        aif_id=aif_id,
        latest_aif_disclosure_id=latest_aif_disclosure_id or None,
        fund_manual_flag_id=_norm_flag(fund_manual_flag_id),
        verdict_json=verdict_json,
        llm_model=llm_model,
        prompt_version=prompt_version,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        cache_hit_count=0,
        created_at=moment,
        expires_at=expires,
        last_accessed_at=moment,
    )
    db.add(row)
    await db.flush()
    return row


async def write_e5dv_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    firm_id: str,
    deal_id: str,
    fund_or_firm_id: str,
    cin_or_internal: str,
    latest_mca_filing_id: str | None,
    deal_manual_flag_id: str | None,
    verdict_json: dict[str, Any],
    llm_model: str,
    prompt_version: str,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    ttl_days: int = DEFAULT_TTL_DAYS_E5,
    now: datetime | None = None,
) -> E5dvVerdictCache:
    """Upsert an E5.DealView verdict row."""
    moment = now or datetime.now(timezone.utc)
    expires = moment + timedelta(days=ttl_days)

    existing: E5dvVerdictCache | None = (
        await db.execute(
            select(E5dvVerdictCache).where(E5dvVerdictCache.cache_key == cache_key),
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.verdict_json = verdict_json
        existing.llm_model = llm_model
        existing.prompt_version = prompt_version
        existing.total_input_tokens = total_input_tokens
        existing.total_output_tokens = total_output_tokens
        existing.expires_at = expires
        existing.last_accessed_at = moment
        existing.cache_hit_count = 0
        await db.flush()
        return existing

    row = E5dvVerdictCache(
        cache_key=cache_key,
        firm_id=firm_id,
        deal_id=deal_id,
        fund_or_firm_id=fund_or_firm_id,
        cin_or_internal=cin_or_internal,
        latest_mca_filing_id=latest_mca_filing_id or None,
        deal_manual_flag_id=_norm_flag(deal_manual_flag_id),
        verdict_json=verdict_json,
        llm_model=llm_model,
        prompt_version=prompt_version,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        cache_hit_count=0,
        created_at=moment,
        expires_at=expires,
        last_accessed_at=moment,
    )
    db.add(row)
    await db.flush()
    return row


async def write_e4_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    firm_id: str,
    investor_id: str,
    window_id: str,
    behavioural_manual_flag_id: str | None,
    verdict_json: dict[str, Any],
    llm_model: str,
    prompt_version: str,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    ttl_days: int = DEFAULT_TTL_DAYS_E4,
    now: datetime | None = None,
) -> E4VerdictCache:
    """Upsert an E4 Behavioural verdict row (30-day TTL)."""
    moment = now or datetime.now(timezone.utc)
    expires = moment + timedelta(days=ttl_days)

    existing: E4VerdictCache | None = (
        await db.execute(
            select(E4VerdictCache).where(E4VerdictCache.cache_key == cache_key),
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.verdict_json = verdict_json
        existing.llm_model = llm_model
        existing.prompt_version = prompt_version
        existing.total_input_tokens = total_input_tokens
        existing.total_output_tokens = total_output_tokens
        existing.expires_at = expires
        existing.last_accessed_at = moment
        existing.cache_hit_count = 0
        await db.flush()
        return existing

    row = E4VerdictCache(
        cache_key=cache_key,
        firm_id=firm_id,
        investor_id=investor_id,
        window_id=window_id,
        behavioural_manual_flag_id=_norm_flag(behavioural_manual_flag_id),
        verdict_json=verdict_json,
        llm_model=llm_model,
        prompt_version=prompt_version,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        cache_hit_count=0,
        created_at=moment,
        expires_at=expires,
        last_accessed_at=moment,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


async def invalidate_e5fv_for_fund_flag(
    db: AsyncSession,
    *,
    aif_id: str,
    superseded_flag_id: str | None,
) -> int:
    """Drop E5.FundView rows whose ``fund_manual_flag_id`` is now stale."""
    stmt = delete(E5fvVerdictCache).where(
        E5fvVerdictCache.aif_id == aif_id,
        E5fvVerdictCache.fund_manual_flag_id == superseded_flag_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def invalidate_e5dv_for_deal_flag(
    db: AsyncSession,
    *,
    deal_id: str,
    superseded_flag_id: str | None,
) -> int:
    """Drop E5.DealView rows whose ``deal_manual_flag_id`` is now stale."""
    stmt = delete(E5dvVerdictCache).where(
        E5dvVerdictCache.deal_id == deal_id,
        E5dvVerdictCache.deal_manual_flag_id == superseded_flag_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def invalidate_e4_for_investor_flag(
    db: AsyncSession,
    *,
    investor_id: str,
    superseded_flag_id: str | None,
) -> int:
    """Drop E4 rows whose ``behavioural_manual_flag_id`` is now stale."""
    stmt = delete(E4VerdictCache).where(
        E4VerdictCache.investor_id == investor_id,
        E4VerdictCache.behavioural_manual_flag_id == superseded_flag_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm_flag(flag_id: str | None) -> str | None:
    """Normalise the sentinel string ``"null"`` to ``None`` for storage."""
    return None if flag_id in (None, "null", "") else flag_id


async def _get_e5fv(
    db: AsyncSession,
    *,
    cache_key: str,
    now: datetime,
) -> CachedVerdict | None:
    row: E5fvVerdictCache | None = (
        await db.execute(
            select(E5fvVerdictCache).where(E5fvVerdictCache.cache_key == cache_key),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if _is_expired(row.expires_at, now=now):
        await db.delete(row)
        await db.flush()
        return None
    row.last_accessed_at = now
    row.cache_hit_count = (row.cache_hit_count or 0) + 1
    await db.flush()
    return _to_cached_verdict(row)


async def _get_e5dv(
    db: AsyncSession,
    *,
    cache_key: str,
    now: datetime,
) -> CachedVerdict | None:
    row: E5dvVerdictCache | None = (
        await db.execute(
            select(E5dvVerdictCache).where(E5dvVerdictCache.cache_key == cache_key),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if _is_expired(row.expires_at, now=now):
        await db.delete(row)
        await db.flush()
        return None
    row.last_accessed_at = now
    row.cache_hit_count = (row.cache_hit_count or 0) + 1
    await db.flush()
    return _to_cached_verdict(row)


async def _get_e4(
    db: AsyncSession,
    *,
    cache_key: str,
    now: datetime,
) -> CachedVerdict | None:
    row: E4VerdictCache | None = (
        await db.execute(
            select(E4VerdictCache).where(E4VerdictCache.cache_key == cache_key),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if _is_expired(row.expires_at, now=now):
        await db.delete(row)
        await db.flush()
        return None
    row.last_accessed_at = now
    row.cache_hit_count = (row.cache_hit_count or 0) + 1
    await db.flush()
    return _to_cached_verdict(row)


def _is_expired(
    expires_at: datetime,
    *,
    now: datetime,
) -> bool:
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return now > exp


def _to_cached_verdict(
    row: E5fvVerdictCache | E5dvVerdictCache | E4VerdictCache,
) -> CachedVerdict:
    """Convert any cluster-9 cache row to the shared CachedVerdict DTO."""
    return CachedVerdict(
        cache_key=row.cache_key,
        verdict_payload=row.verdict_json,
        stage_payload=row.verdict_json,  # cluster-9 has no separate stage_json
        raw_text=None,
        llm_model=row.llm_model,
        input_tokens=row.total_input_tokens,
        output_tokens=row.total_output_tokens,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
    )


__all__ = [
    "DEFAULT_TTL_DAYS_E4",
    "DEFAULT_TTL_DAYS_E5",
    "get_cached_verdict_c9",
    "invalidate_e4_for_investor_flag",
    "invalidate_e5dv_for_deal_flag",
    "invalidate_e5fv_for_fund_flag",
    "write_e4_verdict",
    "write_e5dv_verdict",
    "write_e5fv_verdict",
]
