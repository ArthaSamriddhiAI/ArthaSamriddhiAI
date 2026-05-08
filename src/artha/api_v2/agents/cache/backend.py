"""Cache-backend abstraction (cluster 7 chunk 7.2 §2.4).

The runtime orchestrator (:mod:`agents.runtime`) sits between the
shim (which knows the cache key shape) and the dispatcher (which
runs the LLM call). The cache lookup + write hooks bracket the
dispatcher call so the cache concern stays out of the dispatcher
core.

Two implementations:

- :class:`DBCacheBackend` — production wrapper around
  :mod:`agents.cache.repository` async functions.
- :class:`NullCacheBackend` — no-op for tests / dev where caching is
  disabled or no DB session is available. ``get`` always reports a
  miss; ``put`` is a no-op.

The tests' default is :class:`NullCacheBackend`; production wires
:class:`DBCacheBackend` via :func:`agents.runtime.dispatch_real_agent`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.agents.cache import repository


@dataclass(frozen=True)
class CacheLookupResult:
    """Outcome of a :meth:`CacheBackend.get` call."""

    hit: bool
    verdict_payload: dict[str, Any] | None = None
    stage_payload: dict[str, Any] | None = None
    raw_text: str | None = None
    llm_model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_version: str = ""


class CacheBackend(Protocol):
    """Minimal hooks the runtime calls around an LLM dispatch."""

    async def get(self, *, cache_key: str) -> CacheLookupResult:
        """Look up ``cache_key``. Return a hit/miss view."""
        ...

    async def put(
        self,
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
        input_tokens: int,
        output_tokens: int,
        case_id: str | None,
    ) -> None:
        """Persist a successful verdict for ``cache_key``."""
        ...


# ---------------------------------------------------------------------------
# Null backend
# ---------------------------------------------------------------------------


class NullCacheBackend:
    """No-op backend. Used when caching is disabled or no DB is wired."""

    async def get(self, *, cache_key: str) -> CacheLookupResult:
        return CacheLookupResult(hit=False)

    async def put(
        self,
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
        input_tokens: int,
        output_tokens: int,
        case_id: str | None,
    ) -> None:
        return None


# ---------------------------------------------------------------------------
# DB-backed backend
# ---------------------------------------------------------------------------


class DBCacheBackend:
    """Production cache backend backed by :mod:`agents.cache.repository`.

    Constructor takes the async session in use for the current case
    transaction; lookups + writes ride that session so they participate
    in the same atomic boundary as the rest of the pipeline.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        ttl_days: int = repository.DEFAULT_TTL_DAYS,
    ) -> None:
        self._db = db
        self._ttl_days = ttl_days

    async def get(self, *, cache_key: str) -> CacheLookupResult:
        cached = await repository.get_cached_verdict(
            self._db, cache_key=cache_key, ttl_days=self._ttl_days,
        )
        if cached is None:
            return CacheLookupResult(hit=False)
        return CacheLookupResult(
            hit=True,
            verdict_payload=cached.verdict_payload,
            stage_payload=cached.stage_payload,
            raw_text=cached.raw_text,
            llm_model=cached.llm_model,
            input_tokens=cached.input_tokens,
            output_tokens=cached.output_tokens,
            prompt_version=cached.prompt_version,
        )

    async def put(
        self,
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
        input_tokens: int,
        output_tokens: int,
        case_id: str | None,
    ) -> None:
        await repository.write_cached_verdict(
            self._db,
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
        )


__all__ = [
    "CacheBackend",
    "CacheLookupResult",
    "DBCacheBackend",
    "NullCacheBackend",
]
