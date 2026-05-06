"""Cluster 5 chunk 5.6 — seed loader / reset tests.

Pins:

- Load creates households + investors + mandates + cases all tagged
  ``is_seed_data=True``; case stages tagged
  ``produced_via='lookup_stub_seed'``.
- Re-load is rejected (idempotency).
- Reset wipes every seed row + cascades through stage tables.
- Permission gate: non-CIO actor → SeedNotAuthorisedError.
- Seed status counts reflect post-load and post-reset state.
- Repo's on-disk demo_seed.json + case_seed_data.json fixtures both
  parse + load end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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
from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.cases import dispatch, seed_loader
from artha.api_v2.cases.models import Case, EvidenceVerdict
from artha.api_v2.cases.seed_loader import (
    SeedAlreadyLoadedError,
    SeedFixtureMissingError,
    SeedNotAuthorisedError,
)
from artha.api_v2.investors.models import Household, Investor
from artha.api_v2.m1.models import Mandate
from artha.common.db.base import Base


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


def _cio() -> UserContext:
    return UserContext(
        user_id="cio1",
        firm_id="firm-1",
        role=Role.CIO,
        email="c@example.com",
        name="CIO",
        session_id="s",
    )


def _advisor() -> UserContext:
    return UserContext(
        user_id="advisor1",
        firm_id="firm-1",
        role=Role.ADVISOR,
        email="a@example.com",
        name="A",
        session_id="s",
    )


# Minimal fixture used by most tests (3 investors, 1 case per mode).
_TINY_FIXTURE = {
    "version": "test-tiny",
    "households": [
        {
            "household_id": "01HHTESTHH00000000000000A",
            "name": "Test Household A",
            "created_by": "advisor1",
            "created_at": "2026-04-01T10:00:00+00:00",
        },
    ],
    "investors": [
        {
            "investor_id": "01INVTESTAARAV0000000001",
            "household_id": "01HHTESTHH00000000000000A",
            "name": "Test Aarav",
            "email": "ta@demo.test",
            "phone": "+919999900001",
            "pan": "TESTA1234A",
            "age": 35,
            "advisor_id": "advisor1",
            "risk_appetite": "aggressive",
            "time_horizon": "over_5_years",
            "created_at": "2026-04-01T10:05:00+00:00",
            "archetype_id": "test_aggressive",
        },
        {
            "investor_id": "01INVTESTDIYA00000000002",
            "household_id": "01HHTESTHH00000000000000A",
            "name": "Test Diya",
            "email": "td@demo.test",
            "phone": "+919999900002",
            "pan": "TESTD1234B",
            "age": 33,
            "advisor_id": "advisor1",
            "risk_appetite": "moderate",
            "time_horizon": "over_5_years",
            "created_at": "2026-04-01T10:10:00+00:00",
            "archetype_id": "test_moderate",
        },
    ],
    "mandates": [
        {
            "mandate_id": "01MNDTESTAARAV00000000001",
            "investor_id": "01INVTESTAARAV0000000001",
            "version_id": "01MVTESTAARAV0000000001",
            "equity_min_pct": 60,
            "equity_max_pct": 80,
            "debt_min_pct": 10,
            "debt_max_pct": 25,
            "cash_min_pct": 0,
            "cash_max_pct": 10,
            "alternatives_min_pct": 5,
            "alternatives_max_pct": 20,
            "single_position_max_pct": 8,
            "liquidity_floor_pct": 5,
            "sector_max_pct": 30,
            "prohibited_instruments": [],
            "created_at": "2026-04-01T10:30:00+00:00",
            "created_by": "advisor1",
        },
        {
            "mandate_id": "01MNDTESTDIYA00000000002",
            "investor_id": "01INVTESTDIYA00000000002",
            "version_id": "01MVTESTDIYA00000000002",
            "equity_min_pct": 40,
            "equity_max_pct": 60,
            "debt_min_pct": 30,
            "debt_max_pct": 50,
            "cash_min_pct": 0,
            "cash_max_pct": 10,
            "alternatives_min_pct": 5,
            "alternatives_max_pct": 15,
            "single_position_max_pct": 5,
            "liquidity_floor_pct": 5,
            "sector_max_pct": 25,
            "prohibited_instruments": [],
            "created_at": "2026-04-01T10:35:00+00:00",
            "created_by": "advisor1",
        },
    ],
    "cases": [
        {
            "investor_id": "01INVTESTAARAV0000000001",
            "case_mode": "diagnostic",
            "case_intent": "portfolio_health",
            "opened_by": "advisor1",
            "seed_archetype_id": "test_aggressive",
        },
        {
            "investor_id": "01INVTESTDIYA00000000002",
            "case_mode": "briefing",
            "case_intent": "meeting_prep",
            "opened_by": "advisor1",
            "seed_archetype_id": "test_moderate",
        },
    ],
}


@pytest.fixture
def tiny_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "demo_seed.json"
    path.write_text(json.dumps(_TINY_FIXTURE), encoding="utf-8")
    seed_loader.set_demo_fixture_path(path)
    yield path
    seed_loader.set_demo_fixture_path(None)


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------


class TestPermission:
    @pytest.mark.asyncio
    async def test_advisor_blocked_from_load(self, db, tiny_fixture):
        with pytest.raises(SeedNotAuthorisedError):
            await seed_loader.load_demo_seed(db, actor=_advisor())

    @pytest.mark.asyncio
    async def test_advisor_blocked_from_reset(self, db):
        with pytest.raises(SeedNotAuthorisedError):
            await seed_loader.reset_demo_seed(db, actor=_advisor())


# ---------------------------------------------------------------------------
# Load + reset round-trip
# ---------------------------------------------------------------------------


class TestLoadResetRoundTrip:
    @pytest.mark.asyncio
    async def test_load_inserts_all_seed_tagged(self, db, tiny_fixture):
        result = await seed_loader.load_demo_seed(db, actor=_cio())
        await db.commit()

        assert result.households == 1
        assert result.investors == 2
        assert result.mandates == 2
        assert result.cases == 2

        # Every row tagged seed.
        hh_count = (
            await db.execute(
                select(func.count())
                .select_from(Household)
                .where(Household.is_seed_data.is_(True)),
            )
        ).scalar_one()
        assert hh_count == 1

        inv_count = (
            await db.execute(
                select(func.count())
                .select_from(Investor)
                .where(Investor.is_seed_data.is_(True)),
            )
        ).scalar_one()
        assert inv_count == 2

        mnd_count = (
            await db.execute(
                select(func.count())
                .select_from(Mandate)
                .where(Mandate.is_seed_data.is_(True)),
            )
        ).scalar_one()
        assert mnd_count == 2

        case_count = (
            await db.execute(
                select(func.count())
                .select_from(Case)
                .where(Case.is_seed_data.is_(True)),
            )
        ).scalar_one()
        assert case_count == 2

        # Stage rows tagged with the seed produced_via marker.
        evidence = list(
            (
                await db.execute(
                    select(EvidenceVerdict).where(
                        EvidenceVerdict.is_seed_data.is_(True),
                    ),
                )
            ).scalars()
        )
        assert len(evidence) > 0
        assert all(e.produced_via == "lookup_stub_seed" for e in evidence)

    @pytest.mark.asyncio
    async def test_status_reflects_load(self, db, tiny_fixture):
        before = await seed_loader.get_status(db)
        assert before.is_loaded is False

        await seed_loader.load_demo_seed(db, actor=_cio())
        await db.commit()

        after = await seed_loader.get_status(db)
        assert after.is_loaded is True
        assert after.counts["investors"] == 2
        assert after.counts["cases"] == 2

    @pytest.mark.asyncio
    async def test_double_load_rejected(self, db, tiny_fixture):
        await seed_loader.load_demo_seed(db, actor=_cio())
        await db.commit()
        with pytest.raises(SeedAlreadyLoadedError):
            await seed_loader.load_demo_seed(db, actor=_cio())

    @pytest.mark.asyncio
    async def test_reset_wipes_every_seed_row(self, db, tiny_fixture):
        await seed_loader.load_demo_seed(db, actor=_cio())
        await db.commit()

        result = await seed_loader.reset_demo_seed(db, actor=_cio())
        await db.commit()

        assert result.households_deleted == 1
        assert result.investors_deleted == 2
        assert result.mandates_deleted == 2
        assert result.cases_deleted == 2
        assert result.stage_rows_deleted > 0

        # Verify nothing is left.
        status = await seed_loader.get_status(db)
        assert status.is_loaded is False
        assert all(v == 0 for v in status.counts.values())

        # Stage rows scrubbed too.
        ev_count = (
            await db.execute(
                select(func.count())
                .select_from(EvidenceVerdict)
                .where(EvidenceVerdict.is_seed_data.is_(True)),
            )
        ).scalar_one()
        assert ev_count == 0

    @pytest.mark.asyncio
    async def test_load_after_reset_works(self, db, tiny_fixture):
        await seed_loader.load_demo_seed(db, actor=_cio())
        await db.commit()
        await seed_loader.reset_demo_seed(db, actor=_cio())
        await db.commit()
        # Second load now succeeds.
        result = await seed_loader.load_demo_seed(db, actor=_cio())
        assert result.investors == 2


# ---------------------------------------------------------------------------
# Fixture errors
# ---------------------------------------------------------------------------


class TestFixtureErrors:
    @pytest.mark.asyncio
    async def test_missing_fixture_raises(self, db, tmp_path):
        seed_loader.set_demo_fixture_path(tmp_path / "absent.json")
        try:
            with pytest.raises(SeedFixtureMissingError):
                await seed_loader.load_demo_seed(db, actor=_cio())
        finally:
            seed_loader.set_demo_fixture_path(None)


# ---------------------------------------------------------------------------
# On-disk demo_seed.json end-to-end
# ---------------------------------------------------------------------------


class TestRepoFixture:
    @pytest.mark.asyncio
    async def test_repo_demo_seed_loads_clean(self, db):
        """The repo-shipped demo_seed.json must load against a fresh DB."""
        seed_loader.set_demo_fixture_path(None)
        dispatch.set_seed_fixture_path(None)
        dispatch.reset_seed_cache()

        try:
            result = await seed_loader.load_demo_seed(db, actor=_cio())
            await db.commit()
            assert result.households == 7
            assert result.investors == 15
            assert result.mandates == 15
            assert result.cases >= 8

            # Spot-check: archetype-specific synthesis output makes it
            # into the persisted synthesis row when a seed payload is
            # available.
            from artha.api_v2.cases import repository

            cases = list(
                (
                    await db.execute(
                        select(Case).where(Case.is_seed_data.is_(True)),
                    )
                ).scalars()
            )
            for case in cases:
                if case.seed_archetype_id == "young_aggressive_techie":
                    synth = await repository.get_synthesis(
                        db, case_id=case.case_id,
                    )
                    if synth is not None:
                        assert synth.produced_via == "lookup_stub_seed"
                        # Seeded narrative must reference the archetype
                        # voice ("Aarav" appears in the seed payload).
                        assert (
                            "Aarav" in (synth.synthesis_narrative or "")
                        )
                    break
        finally:
            dispatch.reset_seed_cache()


# ---------------------------------------------------------------------------
# REST surface
# ---------------------------------------------------------------------------


class TestRestSurface:
    """Live integration via the FastAPI app + httpx ASGI client."""

    @pytest_asyncio.fixture
    async def http(self, monkeypatch, tmp_path):
        from httpx import ASGITransport, AsyncClient

        from artha.api_v2.auth.dev_users import reload as reload_catalogue
        from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
        from artha.app import app
        from artha.common.db.session import get_session
        from artha.config import settings

        monkeypatch.setattr(
            settings,
            "jwt_secret",
            "test-secret-must-be-at-least-32-bytes-long-for-hs256",
        )
        reset_dev_secret_cache()
        reload_catalogue()

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def _override_get_session():
            async with factory() as session:
                yield session

        # Tiny fixture override so the e2e test runs quickly.
        path = tmp_path / "demo_seed.json"
        path.write_text(json.dumps(_TINY_FIXTURE), encoding="utf-8")
        seed_loader.set_demo_fixture_path(path)

        app.dependency_overrides[get_session] = _override_get_session
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver",
        ) as client:
            yield client
        app.dependency_overrides.pop(get_session, None)
        seed_loader.set_demo_fixture_path(None)
        reset_dev_secret_cache()
        await engine.dispose()

    async def _login(self, http, user_id: str) -> str:
        resp = await http.post(
            "/api/v2/auth/dev-login", json={"user_id": user_id},
        )
        return resp.json()["access_token"]

    @pytest.mark.asyncio
    async def test_advisor_blocked_from_load(self, http):
        token = await self._login(http, "advisor1")
        resp = await http.post(
            "/api/v2/admin/seed/load",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cio_full_lifecycle(self, http):
        token = await self._login(http, "cio1")
        h = {"Authorization": f"Bearer {token}"}

        # Status pre-load.
        resp = await http.get("/api/v2/admin/seed/status", headers=h)
        assert resp.status_code == 200
        assert resp.json()["is_loaded"] is False

        # Load.
        resp = await http.post("/api/v2/admin/seed/load", headers=h)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["investors"] == 2
        assert body["cases"] == 2

        # Status post-load.
        resp = await http.get("/api/v2/admin/seed/status", headers=h)
        body = resp.json()
        assert body["is_loaded"] is True
        assert body["counts"]["cases"] == 2

        # Re-load rejected.
        resp = await http.post("/api/v2/admin/seed/load", headers=h)
        assert resp.status_code == 409

        # Reset.
        resp = await http.post("/api/v2/admin/seed/reset", headers=h)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cases_deleted"] == 2
        assert body["investors_deleted"] == 2

        # Status post-reset.
        resp = await http.get("/api/v2/admin/seed/status", headers=h)
        assert resp.json()["is_loaded"] is False
