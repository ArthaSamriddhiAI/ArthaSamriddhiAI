"""Cluster 9 cache layer — repository_cluster9 + deal/investor/fund flag tests.

Pins:
- Hard-expiry TTL: expires_at set at write time; stale rows deleted on read.
- All three C9 per-agent cache tables (E5fv, E5dv, E4) round-trip correctly.
- Cache hit bumps cache_hit_count and last_accessed_at.
- Upsert: writing the same cache_key again resets verdict_json / cache_hit_count.
- get_cached_verdict_c9 with an unknown agent_id returns None.
- Invalidation helpers drop only the matching rows and return the row count.
- _norm_flag converts None / "null" / "" sentinel strings to None.
- DealManualFlag service enforces one-active-per-deal (auto-clear on create).
- InvestorManualFlag service enforces one-active-per-investor.
- FundManualFlag cluster-9 extensions: create_aif_flag sets
  invalidates_e5fv=True, invalidates_e7=False; get_active_aif_flag_id
  excludes flags created by create_fund_flag (invalidates_e5fv=False).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Register every model the test fixtures pull through Base.metadata.
import artha.api_v2.agents.cache.models  # noqa: F401
import artha.api_v2.agents.cache.models_cluster8  # noqa: F401
import artha.api_v2.agents.cache.models_cluster9  # noqa: F401
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
from artha.api_v2.agents.cache import deal_manual_flag as deal_flag_svc
from artha.api_v2.agents.cache import fund_manual_flag as fund_flag_svc
from artha.api_v2.agents.cache import investor_manual_flag as investor_flag_svc
from artha.api_v2.agents.cache import repository_cluster9 as c9repo
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
# Shared helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)

_VERDICT: dict[str, Any] = {"verdict": "pass", "confidence": 0.9}
_VERDICT2: dict[str, Any] = {"verdict": "fail", "confidence": 0.3}


async def _write_e5fv(
    db: Any,
    cache_key: str = "e5fv:aif1:disc1:null",
    aif_id: str = "aif1",
    fund_manual_flag_id: str | None = None,
    now: datetime | None = None,
) -> Any:
    return await c9repo.write_e5fv_verdict(
        db,
        cache_key=cache_key,
        firm_id="firm1",
        aif_id=aif_id,
        latest_aif_disclosure_id="disc1",
        fund_manual_flag_id=fund_manual_flag_id,
        verdict_json=_VERDICT,
        llm_model="claude-sonnet",
        prompt_version="v1",
        now=now or _T0,
    )


async def _write_e5dv(
    db: Any,
    cache_key: str = "e5dv:deal1:fund1:mca1:null",
    deal_id: str = "deal1",
    deal_manual_flag_id: str | None = None,
    now: datetime | None = None,
) -> Any:
    return await c9repo.write_e5dv_verdict(
        db,
        cache_key=cache_key,
        firm_id="firm1",
        deal_id=deal_id,
        fund_or_firm_id="fund1",
        cin_or_internal="CIN123456",
        latest_mca_filing_id="mca1",
        deal_manual_flag_id=deal_manual_flag_id,
        verdict_json=_VERDICT,
        llm_model="claude-sonnet",
        prompt_version="v1",
        now=now or _T0,
    )


async def _write_e4(
    db: Any,
    cache_key: str = "e4:inv1:2024Q1:null",
    investor_id: str = "inv1",
    behavioural_manual_flag_id: str | None = None,
    now: datetime | None = None,
) -> Any:
    return await c9repo.write_e4_verdict(
        db,
        cache_key=cache_key,
        firm_id="firm1",
        investor_id=investor_id,
        window_id="2024Q1",
        behavioural_manual_flag_id=behavioural_manual_flag_id,
        verdict_json=_VERDICT,
        llm_model="claude-sonnet",
        prompt_version="v1",
        now=now or _T0,
    )


# ---------------------------------------------------------------------------
# TestRepositoryCluster9E5fv
# ---------------------------------------------------------------------------


class TestRepositoryCluster9E5fv:
    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self, db: Any) -> None:
        result = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:missing:key",
            now=_T0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_write_then_read_returns_verdict(self, db: Any) -> None:
        await _write_e5fv(db)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:null",
            now=_T0,
        )
        assert hit is not None
        assert hit.verdict_payload == _VERDICT

    @pytest.mark.asyncio
    async def test_expired_row_returns_none(self, db: Any) -> None:
        await _write_e5fv(db, now=_T0)
        expired = _T0 + timedelta(days=91)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:null",
            now=expired,
        )
        assert hit is None

    @pytest.mark.asyncio
    async def test_expired_row_physically_deleted(self, db: Any) -> None:
        await _write_e5fv(db, now=_T0)
        expired = _T0 + timedelta(days=91)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:null",
            now=expired,
        )
        # A subsequent read — even with a non-expired now — must miss
        miss = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:null",
            now=_T0 + timedelta(days=1),
        )
        assert miss is None

    @pytest.mark.asyncio
    async def test_cache_hit_bumps_hit_count(self, db: Any) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E5fvVerdictCache

        await _write_e5fv(db, now=_T0)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:null",
            now=_T0 + timedelta(hours=1),
        )
        row = (
            await db.execute(
                select(E5fvVerdictCache).where(
                    E5fvVerdictCache.cache_key == "e5fv:aif1:disc1:null"
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.cache_hit_count == 1

    @pytest.mark.asyncio
    async def test_cache_hit_bumps_last_accessed_at(self, db: Any) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E5fvVerdictCache

        await _write_e5fv(db, now=_T0)
        t1 = _T0 + timedelta(hours=6)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:null",
            now=t1,
        )
        row = (
            await db.execute(
                select(E5fvVerdictCache).where(
                    E5fvVerdictCache.cache_key == "e5fv:aif1:disc1:null"
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        accessed = row.last_accessed_at
        if accessed.tzinfo is None:
            accessed = accessed.replace(tzinfo=timezone.utc)
        assert accessed >= t1

    @pytest.mark.asyncio
    async def test_upsert_updates_verdict_and_resets_hit_count(
        self, db: Any
    ) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E5fvVerdictCache

        await _write_e5fv(db, now=_T0)
        # Trigger a hit so cache_hit_count > 0
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:null",
            now=_T0 + timedelta(hours=1),
        )
        # Overwrite with a new verdict
        await c9repo.write_e5fv_verdict(
            db,
            cache_key="e5fv:aif1:disc1:null",
            firm_id="firm1",
            aif_id="aif1",
            latest_aif_disclosure_id="disc1",
            fund_manual_flag_id=None,
            verdict_json=_VERDICT2,
            llm_model="claude-sonnet",
            prompt_version="v2",
            now=_T0 + timedelta(hours=2),
        )
        row = (
            await db.execute(
                select(E5fvVerdictCache).where(
                    E5fvVerdictCache.cache_key == "e5fv:aif1:disc1:null"
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.verdict_json == _VERDICT2
        assert row.cache_hit_count == 0

    @pytest.mark.asyncio
    async def test_unknown_agent_id_returns_none(self, db: Any) -> None:
        await _write_e5fv(db)
        result = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="unknown_agent",
            cache_key="e5fv:aif1:disc1:null",
            now=_T0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_not_yet_expired_row_still_live(self, db: Any) -> None:
        await _write_e5fv(db, now=_T0)
        # 89 days in — still within the 90-day TTL
        t89 = _T0 + timedelta(days=89)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:null",
            now=t89,
        )
        assert hit is not None


# ---------------------------------------------------------------------------
# TestRepositoryCluster9E5dv
# ---------------------------------------------------------------------------


class TestRepositoryCluster9E5dv:
    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self, db: Any) -> None:
        result = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:missing:key",
            now=_T0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_write_then_read_returns_verdict(self, db: Any) -> None:
        await _write_e5dv(db)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal1:fund1:mca1:null",
            now=_T0,
        )
        assert hit is not None
        assert hit.verdict_payload == _VERDICT

    @pytest.mark.asyncio
    async def test_expired_row_returns_none(self, db: Any) -> None:
        await _write_e5dv(db, now=_T0)
        expired = _T0 + timedelta(days=91)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal1:fund1:mca1:null",
            now=expired,
        )
        assert hit is None

    @pytest.mark.asyncio
    async def test_expired_row_physically_deleted(self, db: Any) -> None:
        await _write_e5dv(db, now=_T0)
        expired = _T0 + timedelta(days=91)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal1:fund1:mca1:null",
            now=expired,
        )
        miss = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal1:fund1:mca1:null",
            now=_T0 + timedelta(days=1),
        )
        assert miss is None

    @pytest.mark.asyncio
    async def test_cache_hit_bumps_hit_count(self, db: Any) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E5dvVerdictCache

        await _write_e5dv(db, now=_T0)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal1:fund1:mca1:null",
            now=_T0 + timedelta(hours=1),
        )
        row = (
            await db.execute(
                select(E5dvVerdictCache).where(
                    E5dvVerdictCache.cache_key == "e5dv:deal1:fund1:mca1:null"
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.cache_hit_count == 1

    @pytest.mark.asyncio
    async def test_upsert_updates_verdict_and_resets_hit_count(
        self, db: Any
    ) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E5dvVerdictCache

        await _write_e5dv(db, now=_T0)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal1:fund1:mca1:null",
            now=_T0 + timedelta(hours=1),
        )
        await c9repo.write_e5dv_verdict(
            db,
            cache_key="e5dv:deal1:fund1:mca1:null",
            firm_id="firm1",
            deal_id="deal1",
            fund_or_firm_id="fund1",
            cin_or_internal="CIN123456",
            latest_mca_filing_id="mca1",
            deal_manual_flag_id=None,
            verdict_json=_VERDICT2,
            llm_model="claude-sonnet",
            prompt_version="v2",
            now=_T0 + timedelta(hours=2),
        )
        row = (
            await db.execute(
                select(E5dvVerdictCache).where(
                    E5dvVerdictCache.cache_key == "e5dv:deal1:fund1:mca1:null"
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.verdict_json == _VERDICT2
        assert row.cache_hit_count == 0

    @pytest.mark.asyncio
    async def test_not_yet_expired_row_still_live(self, db: Any) -> None:
        await _write_e5dv(db, now=_T0)
        t89 = _T0 + timedelta(days=89)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal1:fund1:mca1:null",
            now=t89,
        )
        assert hit is not None


# ---------------------------------------------------------------------------
# TestRepositoryCluster9E4
# ---------------------------------------------------------------------------


class TestRepositoryCluster9E4:
    """E4 Behavioural cache — 30-day hard TTL (shorter than E5's 90-day)."""

    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self, db: Any) -> None:
        result = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:missing:key",
            now=_T0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_write_then_read_returns_verdict(self, db: Any) -> None:
        await _write_e4(db)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv1:2024Q1:null",
            now=_T0,
        )
        assert hit is not None
        assert hit.verdict_payload == _VERDICT

    @pytest.mark.asyncio
    async def test_expired_row_returns_none_after_30_days(
        self, db: Any
    ) -> None:
        await _write_e4(db, now=_T0)
        expired = _T0 + timedelta(days=31)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv1:2024Q1:null",
            now=expired,
        )
        assert hit is None

    @pytest.mark.asyncio
    async def test_expired_row_physically_deleted(self, db: Any) -> None:
        await _write_e4(db, now=_T0)
        expired = _T0 + timedelta(days=31)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv1:2024Q1:null",
            now=expired,
        )
        miss = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv1:2024Q1:null",
            now=_T0 + timedelta(days=1),
        )
        assert miss is None

    @pytest.mark.asyncio
    async def test_not_yet_expired_at_29_days(self, db: Any) -> None:
        await _write_e4(db, now=_T0)
        t29 = _T0 + timedelta(days=29)
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv1:2024Q1:null",
            now=t29,
        )
        assert hit is not None

    @pytest.mark.asyncio
    async def test_cache_hit_bumps_hit_count(self, db: Any) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E4VerdictCache

        await _write_e4(db, now=_T0)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv1:2024Q1:null",
            now=_T0 + timedelta(hours=1),
        )
        row = (
            await db.execute(
                select(E4VerdictCache).where(
                    E4VerdictCache.cache_key == "e4:inv1:2024Q1:null"
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.cache_hit_count == 1

    @pytest.mark.asyncio
    async def test_upsert_updates_verdict_and_resets_hit_count(
        self, db: Any
    ) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E4VerdictCache

        await _write_e4(db, now=_T0)
        await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv1:2024Q1:null",
            now=_T0 + timedelta(hours=1),
        )
        await c9repo.write_e4_verdict(
            db,
            cache_key="e4:inv1:2024Q1:null",
            firm_id="firm1",
            investor_id="inv1",
            window_id="2024Q1",
            behavioural_manual_flag_id=None,
            verdict_json=_VERDICT2,
            llm_model="claude-sonnet",
            prompt_version="v2",
            now=_T0 + timedelta(hours=2),
        )
        row = (
            await db.execute(
                select(E4VerdictCache).where(
                    E4VerdictCache.cache_key == "e4:inv1:2024Q1:null"
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.verdict_json == _VERDICT2
        assert row.cache_hit_count == 0

    @pytest.mark.asyncio
    async def test_unknown_agent_id_returns_none(self, db: Any) -> None:
        await _write_e4(db)
        result = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="unknown_agent",
            cache_key="e4:inv1:2024Q1:null",
            now=_T0,
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestC9Invalidation
# ---------------------------------------------------------------------------


class TestC9Invalidation:
    @pytest.mark.asyncio
    async def test_invalidate_e5fv_for_fund_flag_drops_matching_rows(
        self, db: Any
    ) -> None:
        await _write_e5fv(
            db,
            cache_key="e5fv:aif1:disc1:flag_old",
            aif_id="aif1",
            fund_manual_flag_id="flag_old",
        )
        await _write_e5fv(
            db,
            cache_key="e5fv:aif1:disc1:flag_new",
            aif_id="aif1",
            fund_manual_flag_id="flag_new",
        )
        n = await c9repo.invalidate_e5fv_for_fund_flag(
            db, aif_id="aif1", superseded_flag_id="flag_old"
        )
        assert n == 1
        # flag_new row must remain
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif1:disc1:flag_new",
            now=_T0,
        )
        assert hit is not None

    @pytest.mark.asyncio
    async def test_invalidate_e5fv_for_fund_flag_no_match_returns_zero(
        self, db: Any
    ) -> None:
        await _write_e5fv(db, aif_id="aif1", fund_manual_flag_id=None)
        n = await c9repo.invalidate_e5fv_for_fund_flag(
            db, aif_id="aif1", superseded_flag_id="nonexistent_flag"
        )
        assert n == 0

    @pytest.mark.asyncio
    async def test_invalidate_e5fv_leaves_other_aif_rows_intact(
        self, db: Any
    ) -> None:
        await _write_e5fv(
            db,
            cache_key="e5fv:aif1:disc1:flag_old",
            aif_id="aif1",
            fund_manual_flag_id="flag_old",
        )
        await _write_e5fv(
            db,
            cache_key="e5fv:aif2:disc1:flag_old",
            aif_id="aif2",
            fund_manual_flag_id="flag_old",
        )
        n = await c9repo.invalidate_e5fv_for_fund_flag(
            db, aif_id="aif1", superseded_flag_id="flag_old"
        )
        assert n == 1
        # aif2 row must survive
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_fund_view",
            cache_key="e5fv:aif2:disc1:flag_old",
            now=_T0,
        )
        assert hit is not None

    @pytest.mark.asyncio
    async def test_invalidate_e5dv_for_deal_flag_drops_matching_rows(
        self, db: Any
    ) -> None:
        await _write_e5dv(
            db,
            cache_key="e5dv:deal1:fund1:mca1:flag_old",
            deal_id="deal1",
            deal_manual_flag_id="flag_old",
        )
        await _write_e5dv(
            db,
            cache_key="e5dv:deal1:fund1:mca1:flag_new",
            deal_id="deal1",
            deal_manual_flag_id="flag_new",
        )
        n = await c9repo.invalidate_e5dv_for_deal_flag(
            db, deal_id="deal1", superseded_flag_id="flag_old"
        )
        assert n == 1
        # flag_new row must remain
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal1:fund1:mca1:flag_new",
            now=_T0,
        )
        assert hit is not None

    @pytest.mark.asyncio
    async def test_invalidate_e5dv_leaves_other_deal_rows_intact(
        self, db: Any
    ) -> None:
        await _write_e5dv(
            db,
            cache_key="e5dv:deal1:fund1:mca1:flag_old",
            deal_id="deal1",
            deal_manual_flag_id="flag_old",
        )
        await _write_e5dv(
            db,
            cache_key="e5dv:deal2:fund1:mca1:flag_old",
            deal_id="deal2",
            deal_manual_flag_id="flag_old",
        )
        n = await c9repo.invalidate_e5dv_for_deal_flag(
            db, deal_id="deal1", superseded_flag_id="flag_old"
        )
        assert n == 1
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e5_deal_view",
            cache_key="e5dv:deal2:fund1:mca1:flag_old",
            now=_T0,
        )
        assert hit is not None

    @pytest.mark.asyncio
    async def test_invalidate_e4_for_investor_flag_drops_matching_rows(
        self, db: Any
    ) -> None:
        await _write_e4(
            db,
            cache_key="e4:inv1:2024Q1:flag_old",
            investor_id="inv1",
            behavioural_manual_flag_id="flag_old",
        )
        await _write_e4(
            db,
            cache_key="e4:inv1:2024Q1:flag_new",
            investor_id="inv1",
            behavioural_manual_flag_id="flag_new",
        )
        n = await c9repo.invalidate_e4_for_investor_flag(
            db, investor_id="inv1", superseded_flag_id="flag_old"
        )
        assert n == 1
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv1:2024Q1:flag_new",
            now=_T0,
        )
        assert hit is not None

    @pytest.mark.asyncio
    async def test_invalidate_e4_leaves_other_investor_rows_intact(
        self, db: Any
    ) -> None:
        await _write_e4(
            db,
            cache_key="e4:inv1:2024Q1:flag_old",
            investor_id="inv1",
            behavioural_manual_flag_id="flag_old",
        )
        await _write_e4(
            db,
            cache_key="e4:inv2:2024Q1:flag_old",
            investor_id="inv2",
            behavioural_manual_flag_id="flag_old",
        )
        n = await c9repo.invalidate_e4_for_investor_flag(
            db, investor_id="inv1", superseded_flag_id="flag_old"
        )
        assert n == 1
        hit = await c9repo.get_cached_verdict_c9(
            db,
            agent_id="e4_behavioural",
            cache_key="e4:inv2:2024Q1:flag_old",
            now=_T0,
        )
        assert hit is not None

    @pytest.mark.asyncio
    async def test_norm_flag_none_stored_as_null(self, db: Any) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E5fvVerdictCache

        row = await _write_e5fv(db, fund_manual_flag_id=None)
        assert row.fund_manual_flag_id is None

        db_row = (
            await db.execute(
                select(E5fvVerdictCache).where(
                    E5fvVerdictCache.cache_key == row.cache_key
                )
            )
        ).scalar_one_or_none()
        assert db_row is not None
        assert db_row.fund_manual_flag_id is None

    @pytest.mark.asyncio
    async def test_norm_flag_string_null_stored_as_none(
        self, db: Any
    ) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E5fvVerdictCache

        row = await c9repo.write_e5fv_verdict(
            db,
            cache_key="e5fv:aif1:disc1:normtest",
            firm_id="firm1",
            aif_id="aif1",
            latest_aif_disclosure_id="disc1",
            fund_manual_flag_id="null",  # sentinel string
            verdict_json=_VERDICT,
            llm_model="claude-sonnet",
            prompt_version="v1",
            now=_T0,
        )
        db_row = (
            await db.execute(
                select(E5fvVerdictCache).where(
                    E5fvVerdictCache.cache_key == row.cache_key
                )
            )
        ).scalar_one_or_none()
        assert db_row is not None
        assert db_row.fund_manual_flag_id is None

    @pytest.mark.asyncio
    async def test_norm_flag_empty_string_stored_as_none(
        self, db: Any
    ) -> None:
        from sqlalchemy import select

        from artha.api_v2.agents.cache.models_cluster9 import E5dvVerdictCache

        row = await c9repo.write_e5dv_verdict(
            db,
            cache_key="e5dv:deal9:fund1:mca1:normtest",
            firm_id="firm1",
            deal_id="deal9",
            fund_or_firm_id="fund1",
            cin_or_internal="CIN999",
            latest_mca_filing_id="mca1",
            deal_manual_flag_id="",  # empty-string sentinel
            verdict_json=_VERDICT,
            llm_model="claude-sonnet",
            prompt_version="v1",
            now=_T0,
        )
        db_row = (
            await db.execute(
                select(E5dvVerdictCache).where(
                    E5dvVerdictCache.cache_key == row.cache_key
                )
            )
        ).scalar_one_or_none()
        assert db_row is not None
        assert db_row.deal_manual_flag_id is None


# ---------------------------------------------------------------------------
# TestDealManualFlag
# ---------------------------------------------------------------------------


class TestDealManualFlag:
    @pytest.mark.asyncio
    async def test_create_flag_creates_active_row(self, db: Any) -> None:
        mut = await deal_flag_svc.create_deal_flag(
            db,
            firm_id="firm1",
            deal_id="deal_alpha",
            advisor_id="analyst1",
            reason="Material MCA filing confirmed",
            now=_T0,
        )
        assert mut.new_flag is not None
        assert mut.new_flag.is_active is True
        assert mut.superseded_flag_id is None

    @pytest.mark.asyncio
    async def test_get_active_deal_flag_id_returns_created_flag(
        self, db: Any
    ) -> None:
        mut = await deal_flag_svc.create_deal_flag(
            db,
            firm_id="firm1",
            deal_id="deal_beta",
            advisor_id="analyst1",
            reason="Valuation event",
            now=_T0,
        )
        flag_id = await deal_flag_svc.get_active_deal_flag_id(
            db, firm_id="firm1", deal_id="deal_beta"
        )
        assert flag_id == mut.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_create_twice_auto_clears_first_flag(self, db: Any) -> None:
        mut1 = await deal_flag_svc.create_deal_flag(
            db,
            firm_id="firm1",
            deal_id="deal_gamma",
            advisor_id="analyst1",
            reason="First flag",
            now=_T0,
        )
        mut2 = await deal_flag_svc.create_deal_flag(
            db,
            firm_id="firm1",
            deal_id="deal_gamma",
            advisor_id="analyst2",
            reason="Second flag supersedes first",
            now=_T0 + timedelta(days=1),
        )
        assert mut2.superseded_flag_id == mut1.new_flag.manual_flag_id
        assert mut2.new_flag is not None
        assert mut2.new_flag.is_active is True
        # Only the new flag should be returned as active
        flag_id = await deal_flag_svc.get_active_deal_flag_id(
            db, firm_id="firm1", deal_id="deal_gamma"
        )
        assert flag_id == mut2.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_clear_flag_marks_inactive(self, db: Any) -> None:
        await deal_flag_svc.create_deal_flag(
            db,
            firm_id="firm1",
            deal_id="deal_delta",
            advisor_id="analyst1",
            reason="Co-investor exit",
            now=_T0,
        )
        mut = await deal_flag_svc.clear_deal_flag(
            db,
            firm_id="firm1",
            deal_id="deal_delta",
            cleared_by="analyst1",
            now=_T0 + timedelta(hours=1),
        )
        assert mut.new_flag is None
        assert mut.superseded_flag_id is not None
        # No active flag should remain
        flag_id = await deal_flag_svc.get_active_deal_flag_id(
            db, firm_id="firm1", deal_id="deal_delta"
        )
        assert flag_id is None

    @pytest.mark.asyncio
    async def test_clear_flag_with_no_active_flag_is_noop(
        self, db: Any
    ) -> None:
        mut = await deal_flag_svc.clear_deal_flag(
            db,
            firm_id="firm1",
            deal_id="deal_nonexistent",
            cleared_by="analyst1",
        )
        assert mut.new_flag is None
        assert mut.superseded_flag_id is None

    @pytest.mark.asyncio
    async def test_create_with_empty_deal_id_raises(self, db: Any) -> None:
        with pytest.raises(ValueError, match="deal_id"):
            await deal_flag_svc.create_deal_flag(
                db,
                firm_id="firm1",
                deal_id="",
                advisor_id="analyst1",
                reason="Some reason",
            )

    @pytest.mark.asyncio
    async def test_create_with_empty_reason_raises(self, db: Any) -> None:
        with pytest.raises(ValueError, match="reason"):
            await deal_flag_svc.create_deal_flag(
                db,
                firm_id="firm1",
                deal_id="deal_epsilon",
                advisor_id="analyst1",
                reason="",
            )

    @pytest.mark.asyncio
    async def test_snapshot_fields_populated(self, db: Any) -> None:
        mut = await deal_flag_svc.create_deal_flag(
            db,
            firm_id="firm1",
            deal_id="deal_zeta",
            advisor_id="advisor99",
            reason="Distress signal confirmed",
            now=_T0,
        )
        snap = mut.new_flag
        assert snap is not None
        assert snap.firm_id == "firm1"
        assert snap.deal_id == "deal_zeta"
        assert snap.advisor_id == "advisor99"
        assert snap.reason == "Distress signal confirmed"
        assert snap.invalidates_e5dv is True
        assert snap.cleared_at is None
        assert snap.cleared_by is None


# ---------------------------------------------------------------------------
# TestInvestorManualFlag
# ---------------------------------------------------------------------------


class TestInvestorManualFlag:
    @pytest.mark.asyncio
    async def test_create_flag_creates_active_row(self, db: Any) -> None:
        mut = await investor_flag_svc.create_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_alpha",
            advisor_id="analyst1",
            reason="Panic event confirmed",
            now=_T0,
        )
        assert mut.new_flag is not None
        assert mut.new_flag.is_active is True
        assert mut.superseded_flag_id is None

    @pytest.mark.asyncio
    async def test_get_active_investor_flag_id_returns_created_flag(
        self, db: Any
    ) -> None:
        mut = await investor_flag_svc.create_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_beta",
            advisor_id="analyst1",
            reason="Material behavioural shift",
            now=_T0,
        )
        flag_id = await investor_flag_svc.get_active_investor_flag_id(
            db, firm_id="firm1", investor_id="inv_beta"
        )
        assert flag_id == mut.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_create_twice_auto_clears_first_flag(self, db: Any) -> None:
        mut1 = await investor_flag_svc.create_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_gamma",
            advisor_id="analyst1",
            reason="First investor flag",
            now=_T0,
        )
        mut2 = await investor_flag_svc.create_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_gamma",
            advisor_id="analyst2",
            reason="Second investor flag supersedes first",
            now=_T0 + timedelta(days=1),
        )
        assert mut2.superseded_flag_id == mut1.new_flag.manual_flag_id
        assert mut2.new_flag is not None
        assert mut2.new_flag.is_active is True
        flag_id = await investor_flag_svc.get_active_investor_flag_id(
            db, firm_id="firm1", investor_id="inv_gamma"
        )
        assert flag_id == mut2.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_clear_flag_marks_inactive(self, db: Any) -> None:
        await investor_flag_svc.create_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_delta",
            advisor_id="analyst1",
            reason="AUM change warrants fresh read",
            now=_T0,
        )
        mut = await investor_flag_svc.clear_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_delta",
            cleared_by="analyst1",
            now=_T0 + timedelta(hours=2),
        )
        assert mut.new_flag is None
        assert mut.superseded_flag_id is not None
        flag_id = await investor_flag_svc.get_active_investor_flag_id(
            db, firm_id="firm1", investor_id="inv_delta"
        )
        assert flag_id is None

    @pytest.mark.asyncio
    async def test_clear_flag_with_no_active_flag_is_noop(
        self, db: Any
    ) -> None:
        mut = await investor_flag_svc.clear_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_nonexistent",
            cleared_by="analyst1",
        )
        assert mut.new_flag is None
        assert mut.superseded_flag_id is None

    @pytest.mark.asyncio
    async def test_create_with_empty_investor_id_raises(
        self, db: Any
    ) -> None:
        with pytest.raises(ValueError, match="investor_id"):
            await investor_flag_svc.create_investor_flag(
                db,
                firm_id="firm1",
                investor_id="",
                advisor_id="analyst1",
                reason="Some reason",
            )

    @pytest.mark.asyncio
    async def test_create_with_empty_reason_raises(self, db: Any) -> None:
        with pytest.raises(ValueError, match="reason"):
            await investor_flag_svc.create_investor_flag(
                db,
                firm_id="firm1",
                investor_id="inv_epsilon",
                advisor_id="analyst1",
                reason="",
            )

    @pytest.mark.asyncio
    async def test_snapshot_fields_populated(self, db: Any) -> None:
        mut = await investor_flag_svc.create_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_zeta",
            advisor_id="advisor77",
            reason="Advisor notes a material behavioural shift",
            now=_T0,
        )
        snap = mut.new_flag
        assert snap is not None
        assert snap.firm_id == "firm1"
        assert snap.investor_id == "inv_zeta"
        assert snap.advisor_id == "advisor77"
        assert snap.invalidates_e4 is True
        assert snap.cleared_at is None
        assert snap.cleared_by is None

    @pytest.mark.asyncio
    async def test_flags_for_different_investors_are_independent(
        self, db: Any
    ) -> None:
        mut_a = await investor_flag_svc.create_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_x",
            advisor_id="analyst1",
            reason="Flag for X",
            now=_T0,
        )
        mut_b = await investor_flag_svc.create_investor_flag(
            db,
            firm_id="firm1",
            investor_id="inv_y",
            advisor_id="analyst1",
            reason="Flag for Y",
            now=_T0,
        )
        id_x = await investor_flag_svc.get_active_investor_flag_id(
            db, firm_id="firm1", investor_id="inv_x"
        )
        id_y = await investor_flag_svc.get_active_investor_flag_id(
            db, firm_id="firm1", investor_id="inv_y"
        )
        assert id_x == mut_a.new_flag.manual_flag_id
        assert id_y == mut_b.new_flag.manual_flag_id
        assert id_x != id_y


# ---------------------------------------------------------------------------
# TestFundManualFlagCluster9Extensions
# ---------------------------------------------------------------------------


class TestFundManualFlagCluster9Extensions:
    @pytest.mark.asyncio
    async def test_create_aif_flag_has_correct_scope_bits(
        self, db: Any
    ) -> None:
        mut = await fund_flag_svc.create_aif_flag(
            db,
            firm_id="firm1",
            aif_id="IN/AIF2/24-25/00123",
            advisor_id="analyst1",
            reason="Manager departure at AIF confirmed",
            now=_T0,
        )
        assert mut.new_flag is not None
        assert mut.new_flag.invalidates_e5fv is True
        assert mut.new_flag.invalidates_e7 is False
        assert mut.new_flag.is_active is True
        assert mut.superseded_flag_id is None

    @pytest.mark.asyncio
    async def test_get_active_aif_flag_id_returns_aif_flag(
        self, db: Any
    ) -> None:
        mut = await fund_flag_svc.create_aif_flag(
            db,
            firm_id="firm1",
            aif_id="IN/AIF2/24-25/00456",
            advisor_id="analyst1",
            reason="Distress signal on AIF",
            now=_T0,
        )
        flag_id = await fund_flag_svc.get_active_aif_flag_id(
            db, firm_id="firm1", aif_id="IN/AIF2/24-25/00456"
        )
        assert flag_id == mut.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_get_active_aif_flag_id_excludes_e7_only_flags(
        self, db: Any
    ) -> None:
        """create_fund_flag produces invalidates_e5fv=False flags; these must
        not surface via get_active_aif_flag_id."""
        aif_id = "IN/AIF2/24-25/00789"
        await fund_flag_svc.create_fund_flag(
            db,
            firm_id="firm1",
            fund_id=aif_id,  # same key space, but E7 flag
            advisor_id="analyst1",
            reason="E7 mutual fund flag, not AIF",
            now=_T0,
        )
        flag_id = await fund_flag_svc.get_active_aif_flag_id(
            db, firm_id="firm1", aif_id=aif_id
        )
        assert flag_id is None

    @pytest.mark.asyncio
    async def test_get_active_fund_flag_id_still_returns_regular_flag(
        self, db: Any
    ) -> None:
        """Existing get_active_fund_flag_id must not be affected by the
        cluster-9 extension."""
        mut = await fund_flag_svc.create_fund_flag(
            db,
            firm_id="firm1",
            fund_id="mirae_large_cap",
            advisor_id="analyst1",
            reason="Manager change notification",
            now=_T0,
        )
        flag_id = await fund_flag_svc.get_active_fund_flag_id(
            db, firm_id="firm1", fund_id="mirae_large_cap"
        )
        assert flag_id == mut.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_fund_flag_snapshot_has_invalidates_fields(
        self, db: Any
    ) -> None:
        """FundFlagSnapshot must expose both invalidates_e7 and invalidates_e5fv."""
        mut = await fund_flag_svc.create_fund_flag(
            db,
            firm_id="firm1",
            fund_id="axis_bluechip",
            advisor_id="analyst1",
            reason="AUM cliff concern",
            now=_T0,
        )
        snap = mut.new_flag
        assert snap is not None
        assert hasattr(snap, "invalidates_e7")
        assert hasattr(snap, "invalidates_e5fv")
        assert snap.invalidates_e7 is True
        assert snap.invalidates_e5fv is False

    @pytest.mark.asyncio
    async def test_aif_flag_snapshot_has_correct_invalidates_fields(
        self, db: Any
    ) -> None:
        mut = await fund_flag_svc.create_aif_flag(
            db,
            firm_id="firm1",
            aif_id="IN/AIF2/24-25/99999",
            advisor_id="analyst2",
            reason="Regulatory notice on AIF",
            now=_T0,
        )
        snap = mut.new_flag
        assert snap is not None
        assert snap.invalidates_e7 is False
        assert snap.invalidates_e5fv is True

    @pytest.mark.asyncio
    async def test_create_aif_flag_twice_auto_clears_first(
        self, db: Any
    ) -> None:
        aif_id = "IN/AIF2/24-25/11111"
        mut1 = await fund_flag_svc.create_aif_flag(
            db,
            firm_id="firm1",
            aif_id=aif_id,
            advisor_id="analyst1",
            reason="First AIF flag",
            now=_T0,
        )
        mut2 = await fund_flag_svc.create_aif_flag(
            db,
            firm_id="firm1",
            aif_id=aif_id,
            advisor_id="analyst2",
            reason="Second AIF flag supersedes first",
            now=_T0 + timedelta(days=1),
        )
        assert mut2.superseded_flag_id == mut1.new_flag.manual_flag_id
        assert mut2.new_flag is not None
        flag_id = await fund_flag_svc.get_active_aif_flag_id(
            db, firm_id="firm1", aif_id=aif_id
        )
        assert flag_id == mut2.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_clear_aif_flag_via_clear_fund_flag(self, db: Any) -> None:
        aif_id = "IN/AIF2/24-25/22222"
        await fund_flag_svc.create_aif_flag(
            db,
            firm_id="firm1",
            aif_id=aif_id,
            advisor_id="analyst1",
            reason="AIF flag to be cleared",
            now=_T0,
        )
        mut = await fund_flag_svc.clear_fund_flag(
            db,
            firm_id="firm1",
            fund_id=aif_id,
            cleared_by="analyst1",
            now=_T0 + timedelta(hours=1),
        )
        assert mut.new_flag is None
        assert mut.superseded_flag_id is not None
        flag_id = await fund_flag_svc.get_active_aif_flag_id(
            db, firm_id="firm1", aif_id=aif_id
        )
        assert flag_id is None
