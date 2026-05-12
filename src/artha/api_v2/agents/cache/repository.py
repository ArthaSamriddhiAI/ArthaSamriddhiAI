"""Async CRUD for the E1 verdict cache (cluster 7 chunk 7.2 §2 + §3).

Three invalidation pathways:

1. **earnings auto** (:func:`invalidate_for_ticker_earnings`) — when a
   new earnings event for ``ticker`` lands, every row whose
   ``earnings_id`` differs from the new id is dropped. The cluster-7.4
   data-layer hook calls this after persisting the new earnings row.
2. **manual flag** (:func:`invalidate_for_manual_flag`) — when an
   analyst flips a flag, every row referencing the now-superseded
   ``manual_flag_id`` is dropped.
3. **TTL** (:func:`evict_expired`) — rows older than ``ttl_days``
   (default 90 per cluster 7 ideation log) are dropped.

The :func:`get_cached_verdict` lookup honours TTL implicitly: if the
matched row is older than ``ttl_days`` it's deleted in-place and the
caller treats it as a miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.agents.cache.models import E1VerdictCache

#: Default cache TTL per cluster 7 ideation log §6.5.
DEFAULT_TTL_DAYS = 90


@dataclass(frozen=True)
class CachedVerdict:
    """Result of a successful :func:`get_cached_verdict` lookup."""

    cache_key: str
    verdict_payload: dict[str, Any]
    stage_payload: dict[str, Any]
    raw_text: str | None
    llm_model: str
    input_tokens: int
    output_tokens: int
    prompt_version: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_cached_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime | None = None,
) -> CachedVerdict | None:
    """Return the cached verdict for ``cache_key`` if any (and not expired).

    Lazy TTL: if the row is older than ``ttl_days`` we delete it in
    the same call and report a miss. Caller emits the
    ``cache_invalidated_ttl`` T1 event.
    """
    stmt = select(E1VerdictCache).where(E1VerdictCache.cache_key == cache_key)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None

    moment = now or datetime.now(timezone.utc)
    if _is_expired(row, ttl_days=ttl_days, now=moment):
        await db.delete(row)
        await db.flush()
        return None

    return CachedVerdict(
        cache_key=row.cache_key,
        verdict_payload=row.verdict_payload,
        stage_payload=row.stage_payload,
        raw_text=row.raw_text,
        llm_model=row.llm_model,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def write_cached_verdict(
    db: AsyncSession,
    *,
    cache_key: str,
    ticker: str,
    earnings_id: str,
    manual_flag_id: str | None,
    prompt_version: str,
    verdict_payload: dict[str, Any],
    stage_payload: dict[str, Any],
    raw_text: str | None,
    llm_model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    case_id: str | None = None,
    now: datetime | None = None,
) -> E1VerdictCache:
    """Insert (or replace) a cache row for ``cache_key``.

    Idempotent on ``cache_key``: if the same key is already present
    (e.g. retry after a transient cache write failure) we overwrite
    the prior row in-place. Cluster 7.2 ideation §6.7 — last-write-
    wins is acceptable since each call's ``verdict_payload`` carries
    the same prompt_version + earnings + manual_flag context.
    """
    moment = now or datetime.now(timezone.utc)

    existing = (
        await db.execute(
            select(E1VerdictCache).where(
                E1VerdictCache.cache_key == cache_key
            ),
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.verdict_payload = verdict_payload
        existing.stage_payload = stage_payload
        existing.raw_text = raw_text
        existing.llm_model = llm_model
        existing.input_tokens = input_tokens
        existing.output_tokens = output_tokens
        existing.prompt_version = prompt_version
        existing.case_id = case_id
        existing.created_at = moment
        await db.flush()
        return existing

    row = E1VerdictCache(
        cache_key=cache_key,
        ticker=ticker,
        earnings_id=earnings_id,
        manual_flag_id=manual_flag_id,
        prompt_version=prompt_version,
        verdict_payload=verdict_payload,
        stage_payload=stage_payload,
        raw_text=raw_text,
        llm_model=llm_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        case_id=case_id,
        created_at=moment,
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


async def invalidate_for_ticker_earnings(
    db: AsyncSession,
    *,
    ticker: str,
    new_earnings_id: str,
) -> int:
    """Drop cache rows whose ``earnings_id`` is now stale for ``ticker``.

    Returns the number of rows deleted. Cluster 7.4's earnings-loader
    hook calls this once per earnings event after persisting the new
    earnings row.
    """
    stmt = delete(E1VerdictCache).where(
        E1VerdictCache.ticker == ticker,
        E1VerdictCache.earnings_id != new_earnings_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def invalidate_for_manual_flag(
    db: AsyncSession,
    *,
    ticker: str,
    superseded_flag_id: str | None,
) -> int:
    """Drop cache rows whose ``manual_flag_id`` is now stale for ``ticker``.

    Called by :mod:`agents.cache.manual_flag` whenever a flag is
    created or cleared. ``superseded_flag_id`` is the *previous*
    flag id (or ``None`` if no flag was active). After the call,
    every cache row for ``ticker`` referencing that prior flag state
    is gone.
    """
    stmt = delete(E1VerdictCache).where(
        E1VerdictCache.ticker == ticker,
        E1VerdictCache.manual_flag_id == superseded_flag_id,
    )
    # SQLAlchemy maps ``IS DISTINCT FROM`` differently on SQLite vs PG;
    # we rely on the equality predicate, which already handles the
    # ``manual_flag_id IS NULL`` case in both backends.
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def invalidate_all_for_ticker(
    db: AsyncSession,
    *,
    ticker: str,
) -> int:
    """Drop ALL E1 cache rows for ``ticker`` regardless of flag state.

    Used by the E3.NewsScanner push mechanism when a material news event
    warrants full cache invalidation independent of the current flag.
    """
    stmt = delete(E1VerdictCache).where(E1VerdictCache.ticker == ticker)
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def evict_expired(
    db: AsyncSession,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime | None = None,
) -> int:
    """Bulk-evict cache rows older than ``ttl_days``.

    Returns the count. Background-task glue (cluster 12+) calls this
    on a daily cadence; the lazy-TTL path in :func:`get_cached_verdict`
    handles per-row eviction in the meantime.
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=ttl_days)
    stmt = delete(E1VerdictCache).where(E1VerdictCache.created_at < cutoff)
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


async def evict_for_prompt_change(
    db: AsyncSession,
    *,
    agent_id: str,
    new_prompt_version: str,
) -> int:
    """Drop cache rows whose ``prompt_version`` differs from the new one.

    Skill.md edits bump the prompt_version (e.g. ``e1_listed_fundamental_equity@1.2``).
    Cluster 7.4 wires this to the skill.md hot-reload event so the
    cache stays consistent with the live prompt.
    """
    if not agent_id:
        return 0
    prefix = f"{agent_id}@"
    stmt = delete(E1VerdictCache).where(
        E1VerdictCache.prompt_version.like(f"{prefix}%"),
        E1VerdictCache.prompt_version != new_prompt_version,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_expired(
    row: E1VerdictCache,
    *,
    ttl_days: int,
    now: datetime,
) -> bool:
    cutoff = now - timedelta(days=ttl_days)
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created < cutoff


__all__ = [
    "DEFAULT_TTL_DAYS",
    "CachedVerdict",
    "evict_expired",
    "evict_for_prompt_change",
    "get_cached_verdict",
    "invalidate_all_for_ticker",
    "invalidate_for_manual_flag",
    "invalidate_for_ticker_earnings",
    "write_cached_verdict",
]
