"""Cluster 7 chunk 7.2 — E1 verdict cache + manual-flag service tests.

Pins:

- :func:`repository.get_cached_verdict` returns a hit on round-trip and
  None on miss; lazy-TTL eviction drops rows older than ``ttl_days``.
- :func:`repository.write_cached_verdict` upserts on the same key.
- :func:`repository.invalidate_for_ticker_earnings` drops only the
  stale rows for that ticker.
- :func:`repository.invalidate_for_manual_flag` drops only the rows
  carrying the superseded flag.
- :func:`repository.evict_expired` bulk-drops rows past TTL.
- :func:`repository.evict_for_prompt_change` drops rows from prior
  prompt versions for the agent.
- Manual-flag service enforces one-active-per-ticker, auto-clears
  superseded flag, and invalidates cache rows.
- :class:`DBCacheBackend` round-trips through the repository.
- :class:`NullCacheBackend` always misses.
- :func:`runtime.dispatch_real_agent` short-circuits the LLM call on
  a cache hit, and writes on miss.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Register every model the test fixtures pull through Base.metadata.
import artha.api_v2.agents.cache.models  # noqa: F401
import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.cases.models  # noqa: F401
import artha.api_v2.d0.industry.models  # noqa: F401
import artha.api_v2.d0.instruments.models  # noqa: F401
import artha.api_v2.d0.macro.models  # noqa: F401
import artha.api_v2.d0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.m2.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.agents import config as agents_config
from artha.api_v2.agents import runtime as agents_runtime
from artha.api_v2.agents.cache import manual_flag as manual_flag_service
from artha.api_v2.agents.cache import repository as cache_repo
from artha.api_v2.agents.cache.backend import (
    DBCacheBackend,
    NullCacheBackend,
)
from artha.api_v2.agents.llm_client import MockLLMClient
from artha.api_v2.agents.prompt_loader import PromptTemplate
from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _e1_valid_payload(*, ticker: str = "RELIANCE") -> dict[str, Any]:
    reasoning = (
        f"{ticker} fundamentals: stable cashflows, low leverage, "
        + "consistent ROCE in the high-teens, valuation slightly above "
        + "long-term mean but justified by quality and growth outlook. "
        + "Margins resilient through cycles. " * 6
    )
    return {
        "ticker": ticker,
        "verdict": "positive",
        "confidence": 0.7,
        "metric_evaluations": {
            "roce": {"reading": "in-range"},
            "leverage": {"reading": "low"},
            "earnings_quality": {"reading": "high"},
            "valuation": {"reading": "fair"},
            "growth": {"reading": "moderate"},
            "margins": {"reading": "stable"},
        },
        "per_stock_framework": {
            "framework_axis": "quality_maturity_best_in_class",
            "axis_value": "consumer/IT large-cap value-quality blend",
        },
        "risk_signals": [],
        "reasoning_summary": reasoning,
        "key_drivers": [
            {"driver": "cashflow_stability", "weight": "high"},
        ],
    }


def _stage_payload(ticker: str = "RELIANCE") -> dict[str, Any]:
    return {
        "agent_id": "e1_listed_fundamental_equity",
        "risk_level": "low",
        "confidence": 0.7,
        "drivers": {"key_drivers": []},
        "flags": {},
        "structured_output": {"ticker": ticker, "verdict": "positive"},
        "reasoning_summary": "stub reasoning summary",
    }


async def _seed_cache_row(
    db,
    *,
    cache_key: str = "e1:RELIANCE:E20260308:null",
    ticker: str = "RELIANCE",
    earnings_id: str = "E20260308",
    manual_flag_id: str | None = None,
    prompt_version: str = "e1_listed_fundamental_equity@1.1",
    created_at: datetime | None = None,
) -> None:
    await cache_repo.write_cached_verdict(
        db,
        cache_key=cache_key,
        ticker=ticker,
        earnings_id=earnings_id,
        manual_flag_id=manual_flag_id,
        prompt_version=prompt_version,
        verdict_payload=_e1_valid_payload(ticker=ticker),
        stage_payload=_stage_payload(ticker=ticker),
        raw_text="raw",
        llm_model="claude-sonnet-4-5",
        input_tokens=120,
        output_tokens=240,
        case_id="case_seed",
        now=created_at,
    )


# ---------------------------------------------------------------------------
# repository — read / write
# ---------------------------------------------------------------------------


class TestRepoReadWrite:
    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self, db) -> None:
        result = await cache_repo.get_cached_verdict(
            db, cache_key="e1:RELIANCE:E20260308:null",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_round_trip(self, db) -> None:
        await _seed_cache_row(db)
        result = await cache_repo.get_cached_verdict(
            db, cache_key="e1:RELIANCE:E20260308:null",
        )
        assert result is not None
        assert result.verdict_payload["ticker"] == "RELIANCE"
        assert result.input_tokens == 120
        assert result.output_tokens == 240

    @pytest.mark.asyncio
    async def test_write_is_idempotent_on_key(self, db) -> None:
        await _seed_cache_row(db)
        # Re-write with different telemetry; should overwrite, not insert.
        await cache_repo.write_cached_verdict(
            db,
            cache_key="e1:RELIANCE:E20260308:null",
            ticker="RELIANCE",
            earnings_id="E20260308",
            manual_flag_id=None,
            prompt_version="e1_listed_fundamental_equity@1.1",
            verdict_payload={"new": "payload"},
            stage_payload=_stage_payload(),
            raw_text="raw2",
            llm_model="claude-sonnet-4-5",
            input_tokens=999,
            output_tokens=1,
        )
        result = await cache_repo.get_cached_verdict(
            db, cache_key="e1:RELIANCE:E20260308:null",
        )
        assert result is not None
        assert result.verdict_payload == {"new": "payload"}
        assert result.input_tokens == 999

    @pytest.mark.asyncio
    async def test_lazy_ttl_eviction_on_read(self, db) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=120)
        await _seed_cache_row(db, created_at=old)
        # Default TTL is 90 days → row is over budget → miss + delete.
        result = await cache_repo.get_cached_verdict(
            db, cache_key="e1:RELIANCE:E20260308:null",
        )
        assert result is None
        # Re-issue — still a miss because the prior call deleted the row.
        result2 = await cache_repo.get_cached_verdict(
            db, cache_key="e1:RELIANCE:E20260308:null",
        )
        assert result2 is None

    @pytest.mark.asyncio
    async def test_ttl_window_respected(self, db) -> None:
        recent = datetime.now(timezone.utc) - timedelta(days=30)
        await _seed_cache_row(db, created_at=recent)
        # 30 days < 90 days → hit.
        result = await cache_repo.get_cached_verdict(
            db, cache_key="e1:RELIANCE:E20260308:null",
        )
        assert result is not None


# ---------------------------------------------------------------------------
# repository — invalidation
# ---------------------------------------------------------------------------


class TestRepoInvalidation:
    @pytest.mark.asyncio
    async def test_invalidate_for_ticker_earnings(self, db) -> None:
        await _seed_cache_row(
            db, cache_key="e1:RELIANCE:E20260308:null",
            earnings_id="E20260308",
        )
        await _seed_cache_row(
            db, cache_key="e1:RELIANCE:E20251208:null",
            earnings_id="E20251208",
        )
        await _seed_cache_row(
            db, cache_key="e1:HDFCBANK:E20260308:null",
            ticker="HDFCBANK", earnings_id="E20260308",
        )
        # New earnings event for RELIANCE → drop both old reliance rows
        # (E20260308 + E20251208 differ from new id E20260315).
        deleted = await cache_repo.invalidate_for_ticker_earnings(
            db, ticker="RELIANCE", new_earnings_id="E20260315",
        )
        assert deleted == 2
        # HDFCBANK row untouched.
        result = await cache_repo.get_cached_verdict(
            db, cache_key="e1:HDFCBANK:E20260308:null",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_invalidate_for_manual_flag(self, db) -> None:
        await _seed_cache_row(
            db, cache_key="e1:RELIANCE:E20260308:null",
            manual_flag_id=None,
        )
        await _seed_cache_row(
            db, cache_key="e1:RELIANCE:E20260308:01HQZFLAG01",
            manual_flag_id="01HQZFLAG01",
        )
        # An analyst clears flag 01HQZFLAG01 → invalidate rows tied to it.
        deleted = await cache_repo.invalidate_for_manual_flag(
            db, ticker="RELIANCE", superseded_flag_id="01HQZFLAG01",
        )
        assert deleted == 1
        # The "no flag" row is still cached.
        still = await cache_repo.get_cached_verdict(
            db, cache_key="e1:RELIANCE:E20260308:null",
        )
        assert still is not None

    @pytest.mark.asyncio
    async def test_invalidate_for_manual_flag_no_prior(self, db) -> None:
        await _seed_cache_row(
            db, cache_key="e1:RELIANCE:E20260308:null",
            manual_flag_id=None,
        )
        # First-time flag set: superseded_flag_id is None → drop the
        # "no flag" cached row.
        deleted = await cache_repo.invalidate_for_manual_flag(
            db, ticker="RELIANCE", superseded_flag_id=None,
        )
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_evict_expired(self, db) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=120)
        recent = datetime.now(timezone.utc) - timedelta(days=20)
        await _seed_cache_row(
            db, cache_key="e1:OLD:E1:null", ticker="OLD", created_at=old,
        )
        await _seed_cache_row(
            db, cache_key="e1:NEW:E1:null", ticker="NEW", created_at=recent,
        )
        deleted = await cache_repo.evict_expired(db, ttl_days=90)
        assert deleted == 1
        # New row still alive.
        result = await cache_repo.get_cached_verdict(
            db, cache_key="e1:NEW:E1:null",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_evict_for_prompt_change(self, db) -> None:
        await _seed_cache_row(
            db, cache_key="e1:OLDPROMPT:E1:null",
            ticker="OLDPROMPT",
            prompt_version="e1_listed_fundamental_equity@1.1",
        )
        await _seed_cache_row(
            db, cache_key="e1:NEWPROMPT:E1:null",
            ticker="NEWPROMPT",
            prompt_version="e1_listed_fundamental_equity@1.2",
        )
        # Skill.md rolls forward to 1.2.
        deleted = await cache_repo.evict_for_prompt_change(
            db,
            agent_id="e1_listed_fundamental_equity",
            new_prompt_version="e1_listed_fundamental_equity@1.2",
        )
        assert deleted == 1
        survivor = await cache_repo.get_cached_verdict(
            db, cache_key="e1:NEWPROMPT:E1:null",
        )
        assert survivor is not None


# ---------------------------------------------------------------------------
# manual_flag service
# ---------------------------------------------------------------------------


class TestManualFlagService:
    @pytest.mark.asyncio
    async def test_create_first_flag(self, db) -> None:
        out = await manual_flag_service.create_manual_flag(
            db,
            ticker="RELIANCE",
            flagged_by="alice@firm",
            reason="promoter pledge increased",
        )
        assert out.new_flag is not None
        assert out.new_flag.is_active is True
        assert out.superseded_flag_id is None
        # Lookup should now return this flag.
        snap = await manual_flag_service.get_active_manual_flag_for_ticker(
            db, ticker="RELIANCE",
        )
        assert snap is not None
        assert snap.manual_flag_id == out.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_create_replaces_active_flag(self, db) -> None:
        first = await manual_flag_service.create_manual_flag(
            db, ticker="RELIANCE", flagged_by="alice", reason="r1",
        )
        # Seed a cache row referencing that flag so we can verify the
        # invalidation pathway.
        await _seed_cache_row(
            db,
            cache_key=f"e1:RELIANCE:E1:{first.new_flag.manual_flag_id}",
            manual_flag_id=first.new_flag.manual_flag_id,
        )
        second = await manual_flag_service.create_manual_flag(
            db, ticker="RELIANCE", flagged_by="bob", reason="r2",
        )
        assert second.superseded_flag_id == first.new_flag.manual_flag_id
        assert second.cache_rows_invalidated == 1
        # Only one active flag remains.
        snap = await manual_flag_service.get_active_manual_flag_for_ticker(
            db, ticker="RELIANCE",
        )
        assert snap is not None
        assert snap.manual_flag_id == second.new_flag.manual_flag_id
        # Prior flag is retained for audit but inactive.
        prior = await manual_flag_service.get_manual_flag(
            db, manual_flag_id=first.new_flag.manual_flag_id,
        )
        assert prior is not None
        assert prior.is_active is False

    @pytest.mark.asyncio
    async def test_clear_flag_invalidates_cache(self, db) -> None:
        out = await manual_flag_service.create_manual_flag(
            db, ticker="RELIANCE", flagged_by="alice", reason="r",
        )
        flag_id = out.new_flag.manual_flag_id
        await _seed_cache_row(
            db,
            cache_key=f"e1:RELIANCE:E1:{flag_id}",
            manual_flag_id=flag_id,
        )
        cleared = await manual_flag_service.clear_manual_flag(
            db, ticker="RELIANCE", cleared_by="alice",
        )
        assert cleared.superseded_flag_id == flag_id
        assert cleared.cache_rows_invalidated == 1
        snap = await manual_flag_service.get_active_manual_flag_for_ticker(
            db, ticker="RELIANCE",
        )
        assert snap is None

    @pytest.mark.asyncio
    async def test_clear_when_no_flag(self, db) -> None:
        out = await manual_flag_service.clear_manual_flag(
            db, ticker="HDFCBANK", cleared_by="alice",
        )
        assert out.superseded_flag_id is None
        assert out.cache_rows_invalidated == 0


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class TestBackend:
    @pytest.mark.asyncio
    async def test_db_backend_round_trip(self, db) -> None:
        backend = DBCacheBackend(db)
        miss = await backend.get(cache_key="e1:T:E:null")
        assert miss.hit is False
        await backend.put(
            cache_key="e1:T:E:null",
            ticker="T",
            earnings_id="E",
            manual_flag_id=None,
            prompt_version="e1_listed_fundamental_equity@1.1",
            verdict_payload={"v": 1},
            stage_payload={"s": 2},
            raw_text="raw",
            llm_model="m",
            input_tokens=10,
            output_tokens=20,
            case_id=None,
        )
        hit = await backend.get(cache_key="e1:T:E:null")
        assert hit.hit is True
        assert hit.verdict_payload == {"v": 1}
        assert hit.stage_payload == {"s": 2}
        assert hit.input_tokens == 10

    @pytest.mark.asyncio
    async def test_null_backend_always_misses(self, db) -> None:
        backend = NullCacheBackend()
        await backend.put(
            cache_key="e1:T:E:null",
            ticker="T", earnings_id="E", manual_flag_id=None,
            prompt_version="x@1", verdict_payload={}, stage_payload={},
            raw_text=None, llm_model="m", input_tokens=0, output_tokens=0,
            case_id=None,
        )
        result = await backend.get(cache_key="e1:T:E:null")
        assert result.hit is False


# ---------------------------------------------------------------------------
# Runtime integration with cache
# ---------------------------------------------------------------------------


class _FakeCase:
    def __init__(self, *, ticker: str = "RELIANCE") -> None:
        self.case_id = "01HQZTEST00000000000000001"
        self.case_mode = "proposed_action"
        self.case_intent = "invest_top_up"
        self.proposed_action_products = [ticker]
        self.proposed_action = "top up"
        self.dominant_lens = "growth"
        self.investor_id = "01HQZINV0000000000000000001"
        self.is_seed_data = False
        self.seed_archetype_id = None
        self.applicable_evidence_agents = []


def _skill_template(
    agent_id: str = "e1_listed_fundamental_equity",
) -> PromptTemplate:
    return PromptTemplate(
        agent_id=agent_id,
        skill_md_version="1.1",
        system_body="agent body",
        llm_model="claude-sonnet-4-5",
        max_tokens=4096,
        temperature=0.2,
        output_schema_ref="../schemas/x.json",
    )


class TestRuntimeCacheIntegration:
    def teardown_method(self) -> None:
        agents_runtime.reset_runtime()
        agents_config.set_agent_impl_overrides(None)

    @pytest.mark.asyncio
    async def test_cache_hit_short_circuits_llm(self, db) -> None:
        # Pre-seed the cache row matching what the input builder will
        # produce for our fake case.
        await _seed_cache_row(
            db,
            cache_key="e1:RELIANCE:no_earnings_seeded:null",
            ticker="RELIANCE",
            earnings_id="no_earnings_seeded",
            manual_flag_id=None,
        )

        client = MockLLMClient(responses=[])  # would error on call
        agents_runtime.set_llm_client(client)
        backend = DBCacheBackend(db)
        out = await agents_runtime.dispatch_real_agent(
            case=_FakeCase(),
            agent_id="e1_listed_fundamental_equity",
            skill_template_override=_skill_template(),
            cache=backend,
            db=db,
        )
        assert out.cache_hit is True
        # No LLM call should have been issued.
        assert client.call_log == []

    @pytest.mark.asyncio
    async def test_cache_miss_runs_llm_and_writes(self, db) -> None:
        body = json.dumps(_e1_valid_payload(ticker="RELIANCE"))
        client = MockLLMClient(responses=[body])
        agents_runtime.set_llm_client(client)
        backend = DBCacheBackend(db)

        out = await agents_runtime.dispatch_real_agent(
            case=_FakeCase(),
            agent_id="e1_listed_fundamental_equity",
            skill_template_override=_skill_template(),
            cache=backend,
            db=db,
        )
        assert out.cache_hit is False
        assert len(client.call_log) == 1

        # Second call against the same case should hit the cache.
        agents_runtime.set_llm_client(MockLLMClient(responses=[]))
        out2 = await agents_runtime.dispatch_real_agent(
            case=_FakeCase(),
            agent_id="e1_listed_fundamental_equity",
            skill_template_override=_skill_template(),
            cache=backend,
            db=db,
        )
        assert out2.cache_hit is True

    @pytest.mark.asyncio
    async def test_manual_flag_rotation_misses_cache(self, db) -> None:
        # Warm cache with no-flag verdict.
        body1 = json.dumps(_e1_valid_payload(ticker="RELIANCE"))
        agents_runtime.set_llm_client(MockLLMClient(responses=[body1]))
        backend = DBCacheBackend(db)
        await agents_runtime.dispatch_real_agent(
            case=_FakeCase(),
            agent_id="e1_listed_fundamental_equity",
            skill_template_override=_skill_template(),
            cache=backend,
            db=db,
        )

        # Analyst flips a flag — input builder picks the new flag id;
        # cache key changes; lookup should miss.
        await manual_flag_service.create_manual_flag(
            db,
            ticker="RELIANCE",
            flagged_by="alice@firm",
            reason="audit qualification surfaced",
        )

        body2 = json.dumps(_e1_valid_payload(ticker="RELIANCE"))
        client2 = MockLLMClient(responses=[body2])
        agents_runtime.set_llm_client(client2)
        out = await agents_runtime.dispatch_real_agent(
            case=_FakeCase(),
            agent_id="e1_listed_fundamental_equity",
            skill_template_override=_skill_template(),
            cache=backend,
            db=db,
        )
        assert out.cache_hit is False
        assert len(client2.call_log) == 1
