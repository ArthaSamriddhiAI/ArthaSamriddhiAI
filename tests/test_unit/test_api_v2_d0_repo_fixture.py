"""Cluster 3 addendum — repo-hosted fixture integration test.

Validates the addendum's acceptance criteria against the actual file at
``data/fixtures/SamriddhiAI_data_merged.json``:

- 1300+ Instruments (the addendum's stated floor; current count ~3000)
- 1 MacroSnapshot
- 14 IndustryReports
- Adapter completes successfully (status="success")
- Per-vehicle distribution covers stock + mutual_fund + etf + pms + aif +
  unlisted_equity

The test is skipped when the fixture file is absent (e.g. on a CI
checkout that excludes the fixture). The bulk-load takes ~2 seconds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.d0.industry.models  # noqa: F401
import artha.api_v2.d0.instruments.models  # noqa: F401
import artha.api_v2.d0.macro.models  # noqa: F401
import artha.api_v2.d0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.d0.adapters.json_fixture import JSONFixtureAdapter
from artha.api_v2.d0.industry.models import IndustryReport
from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.d0.macro.models import MacroSnapshot
from artha.common.db.base import Base

_FIXTURE_PATH = Path("data/fixtures/SamriddhiAI_data_merged.json")


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


@pytest.mark.skipif(
    not _FIXTURE_PATH.exists(),
    reason=(
        "Repo fixture file not present at data/fixtures/SamriddhiAI_data_merged.json"
    ),
)
class TestRepoFixtureIntegration:
    @pytest.mark.asyncio
    async def test_acceptance_criteria_counts(self, db):
        """Addendum §1.3 + §5: adapter run from the repo path produces the
        expected canonical entity counts."""
        adapter = JSONFixtureAdapter(
            fixture_name="repo", fixture_path=_FIXTURE_PATH
        )
        result = await adapter.run(db)
        await db.commit()

        # Adapter completes without errors
        assert result.status == "success", (
            f"errors: {[e.error_type for e in result.errors[:5]]}"
        )

        i_count = (
            await db.execute(select(func.count()).select_from(Instrument))
        ).scalar()
        m_count = (
            await db.execute(select(func.count()).select_from(MacroSnapshot))
        ).scalar()
        r_count = (
            await db.execute(select(func.count()).select_from(IndustryReport))
        ).scalar()

        # Addendum stated minimums
        assert i_count >= 1300, (
            f"expected 1300+ instruments per addendum acceptance, got {i_count}"
        )
        assert m_count == 1
        assert r_count == 14

    @pytest.mark.asyncio
    async def test_vehicle_type_coverage(self, db):
        """All 6 cluster-3 vehicle types end up in the catalogue."""
        adapter = JSONFixtureAdapter(
            fixture_name="repo", fixture_path=_FIXTURE_PATH
        )
        await adapter.run(db)
        await db.commit()

        for vt in (
            "stock",
            "mutual_fund",
            "etf",
            "pms",
            "aif",
            "unlisted_equity",
        ):
            n = (
                await db.execute(
                    select(func.count())
                    .select_from(Instrument)
                    .where(Instrument.vehicle_type == vt)
                )
            ).scalar()
            assert n > 0, f"expected at least one {vt} instrument from the fixture"

    @pytest.mark.asyncio
    async def test_idempotent_re_run(self, db):
        """Running twice produces no new instruments — re-runs update in place."""
        adapter = JSONFixtureAdapter(
            fixture_name="repo", fixture_path=_FIXTURE_PATH
        )
        r1 = await adapter.run(db)
        await db.commit()
        first_count = (
            await db.execute(select(func.count()).select_from(Instrument))
        ).scalar()

        r2 = await adapter.run(db)
        await db.commit()
        second_count = (
            await db.execute(select(func.count()).select_from(Instrument))
        ).scalar()

        assert second_count == first_count
        # All Instrument writes in the second run are updates.
        assert r2.canonical_entities_created.get("Instrument", 0) == 0
        assert r2.canonical_entities_updated.get("Instrument", 0) > 0
        # Sanity check on first run
        assert r1.canonical_entities_created.get("Instrument", 0) > 0
