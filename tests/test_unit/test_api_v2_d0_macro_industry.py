"""Cluster 3 chunk 3.3 — MacroSnapshot + IndustryReport tests.

Pins:

- The JSONFixtureAdapter loads ``macro_snapshots`` + ``industry_reports``
  sections in addition to instruments.
- Natural-key uniqueness: re-running with same (country_code, period)
  updates instead of inserts; same for (industry_code, period).
- Schema-mismatch errors land in result.errors without failing other rows.
- Invalid outlook values are rejected.
- Service helpers list / get / find by natural key.
- Admin endpoints return seeded data with permission gates.
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.d0.adapters.json_fixture import JSONFixtureAdapter
from artha.api_v2.d0.industry import service as industry_service
from artha.api_v2.d0.industry.models import IndustryReport
from artha.api_v2.d0.macro import service as macro_service
from artha.api_v2.d0.macro.models import MacroSnapshot
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import settings

_TEST_JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def jwt_secret_for_tests(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", _TEST_JWT_SECRET)
    reset_dev_secret_cache()
    yield
    reset_dev_secret_cache()


@pytest.fixture(autouse=True)
def reset_users_cache():
    reload_catalogue()
    yield


@pytest_asyncio.fixture
async def engine_and_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine_and_factory):
    _, factory = engine_and_factory
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def http(engine_and_factory):
    _, factory = engine_and_factory

    async def _override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


async def _login(http, user_id: str) -> str:
    resp = await http.post("/api/v2/auth/dev-login", json={"user_id": user_id})
    return resp.json()["access_token"]


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Sample fixture
# ---------------------------------------------------------------------------


def _macro_industry_fixture() -> dict:
    return {
        "macro_snapshots": [
            {
                "country_code": "IN",
                "snapshot_period": "2026-Q1",
                "snapshot_date": "2026-03-31",
                "gdp_growth_pct": 7.2,
                "cpi_inflation_pct": 4.5,
                "repo_rate_pct": 6.5,
                "bond_yield_10y_pct": 7.1,
                "fx_usd_inr": 83.5,
                "themes": ["disinflation_underway", "growth_resilient"],
            },
            {
                "country_code": "IN",
                "snapshot_period": "2025-Q4",
                "snapshot_date": "2025-12-31",
                "gdp_growth_pct": 7.0,
                "cpi_inflation_pct": 5.0,
                "repo_rate_pct": 6.5,
            },
        ],
        "industry_reports": [
            {
                "industry_code": "BFSI",
                "industry_name": "Banking, Financial Services, Insurance",
                "report_period": "2026-Q1",
                "report_date": "2026-03-31",
                "outlook": "positive",
                "summary": "Credit growth normalising; NIMs stable.",
                "key_themes": ["credit_growth_normalising"],
                "drivers": ["loan_book_expansion", "digital_adoption"],
                "risks": ["unsecured_lending_stress"],
            },
            {
                "industry_code": "IT",
                "industry_name": "Information Technology Services",
                "report_period": "2026-Q1",
                "report_date": "2026-03-31",
                "outlook": "neutral",
                "summary": "Discretionary spend remains soft.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Adapter loading
# ---------------------------------------------------------------------------


class TestAdapterLoadsMacroAndIndustry:
    @pytest.mark.asyncio
    async def test_loads_both_sections(self, db):
        adapter = JSONFixtureAdapter(
            fixture_name="t", fixture=_macro_industry_fixture()
        )
        result = await adapter.run(db)
        await db.commit()

        assert result.status == "success"
        assert result.canonical_entities_created == {
            "MacroSnapshot": 2,
            "IndustryReport": 2,
        }
        assert result.metadata["macro_snapshots_seen"] == 2
        assert result.metadata["industry_reports_seen"] == 2

        macro_rows = list((await db.execute(select(MacroSnapshot))).scalars())
        assert len(macro_rows) == 2
        industry_rows = list(
            (await db.execute(select(IndustryReport))).scalars()
        )
        assert len(industry_rows) == 2

    @pytest.mark.asyncio
    async def test_macro_snapshot_missing_country_code_records_error(self, db):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "macro_snapshots": [
                    {
                        "snapshot_period": "2026-Q1",
                        "snapshot_date": "2026-03-31",
                        "gdp_growth_pct": 7.2,
                    }
                ]
            },
        )
        result = await adapter.run(db)
        await db.commit()

        assert any(
            "country_code" in e.message
            for e in result.errors
            if e.error_type == "schema_mismatch"
        )
        rows = list((await db.execute(select(MacroSnapshot))).scalars())
        assert rows == []

    @pytest.mark.asyncio
    async def test_industry_invalid_outlook_records_error(self, db):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "industry_reports": [
                    {
                        "industry_code": "BFSI",
                        "industry_name": "BFSI",
                        "report_period": "2026-Q1",
                        "report_date": "2026-03-31",
                        "outlook": "amazing",  # invalid
                        "summary": "...",
                    }
                ]
            },
        )
        result = await adapter.run(db)
        await db.commit()

        assert any(
            "Unknown outlook" in e.message for e in result.errors
        )
        rows = list((await db.execute(select(IndustryReport))).scalars())
        assert rows == []

    @pytest.mark.asyncio
    async def test_macro_idempotent_on_natural_key(self, db):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "macro_snapshots": [
                    {
                        "country_code": "IN",
                        "snapshot_period": "2026-Q1",
                        "snapshot_date": "2026-03-31",
                        "gdp_growth_pct": 7.0,
                    }
                ]
            },
        )
        r1 = await adapter.run(db)
        await db.commit()
        assert r1.canonical_entities_created == {"MacroSnapshot": 1}

        adapter2 = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "macro_snapshots": [
                    {
                        "country_code": "IN",
                        "snapshot_period": "2026-Q1",
                        "snapshot_date": "2026-03-31",
                        "gdp_growth_pct": 7.5,  # updated
                    }
                ]
            },
        )
        r2 = await adapter2.run(db)
        await db.commit()
        assert r2.canonical_entities_updated == {"MacroSnapshot": 1}
        rows = list((await db.execute(select(MacroSnapshot))).scalars())
        assert len(rows) == 1
        assert rows[0].gdp_growth_pct == 7.5


# ---------------------------------------------------------------------------
# Service helpers (macro)
# ---------------------------------------------------------------------------


class TestMacroServiceLayer:
    @pytest.mark.asyncio
    async def test_find_by_natural_key(self, db):
        await macro_service.upsert_macro_snapshot(
            db,
            payload={
                "country_code": "IN",
                "snapshot_period": "2026-Q1",
                "snapshot_date": date(2026, 3, 31),
                "repo_rate_pct": 6.5,
            },
            source_identifier="test",
            adapter_run_id="r",
            staging_record_id=None,
        )
        await db.commit()

        row = await macro_service.find_by_natural_key(
            db, country_code="IN", snapshot_period="2026-Q1"
        )
        assert row is not None
        assert row.repo_rate_pct == 6.5

        none_row = await macro_service.find_by_natural_key(
            db, country_code="US", snapshot_period="2026-Q1"
        )
        assert none_row is None

    @pytest.mark.asyncio
    async def test_list_filters(self, db):
        for period in ("2026-Q1", "2025-Q4", "2025-Q3"):
            await macro_service.upsert_macro_snapshot(
                db,
                payload={
                    "country_code": "IN",
                    "snapshot_period": period,
                    "snapshot_date": date(2026, 3, 31),
                },
                source_identifier="t",
                adapter_run_id="r",
                staging_record_id=None,
            )
        await db.commit()

        rows, total = await macro_service.list_macro_snapshots(
            db, country_code="IN"
        )
        assert total == 3

        rows, total = await macro_service.list_macro_snapshots(
            db, snapshot_period="2026-Q1"
        )
        assert total == 1


# ---------------------------------------------------------------------------
# Service helpers (industry)
# ---------------------------------------------------------------------------


class TestIndustryServiceLayer:
    @pytest.mark.asyncio
    async def test_outlook_validation(self, db):
        with pytest.raises(ValueError, match="Unknown outlook"):
            await industry_service.upsert_industry_report(
                db,
                payload={
                    "industry_code": "X",
                    "industry_name": "X",
                    "report_period": "P1",
                    "report_date": date(2026, 1, 1),
                    "outlook": "best",
                    "summary": "...",
                },
                source_identifier="t",
                adapter_run_id="r",
                staging_record_id=None,
            )

    @pytest.mark.asyncio
    async def test_list_by_outlook(self, db):
        for code, outlook in (
            ("BFSI", "positive"),
            ("IT", "neutral"),
            ("FMCG", "positive"),
        ):
            await industry_service.upsert_industry_report(
                db,
                payload={
                    "industry_code": code,
                    "industry_name": code,
                    "report_period": "2026-Q1",
                    "report_date": date(2026, 3, 31),
                    "outlook": outlook,
                    "summary": "x",
                },
                source_identifier="t",
                adapter_run_id="r",
                staging_record_id=None,
            )
        await db.commit()

        rows, total = await industry_service.list_industry_reports(
            db, outlook="positive"
        )
        assert total == 2
        assert {r.industry_code for r in rows} == {"BFSI", "FMCG"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def _seed_via_adapter(db) -> None:
    adapter = JSONFixtureAdapter(
        fixture_name="seed", fixture=_macro_industry_fixture()
    )
    await adapter.run(db)
    await db.commit()


class TestMacroEndpoints:
    @pytest.mark.asyncio
    async def test_list_endpoint_for_audit(self, http, db):
        await _seed_via_adapter(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/macro-snapshots", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        # newest-first
        assert body["snapshots"][0]["snapshot_period"] == "2026-Q1"

    @pytest.mark.asyncio
    async def test_filter_by_country_code(self, http, db):
        await _seed_via_adapter(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/macro-snapshots?country_code=US", headers=_h(token)
        )
        body = r.json()
        assert body["total"] == 0

        r = await http.get(
            "/api/v2/admin/macro-snapshots?country_code=IN", headers=_h(token)
        )
        body = r.json()
        assert body["total"] == 2

    @pytest.mark.asyncio
    async def test_advisor_blocked(self, http):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/admin/macro-snapshots", headers=_h(token)
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_id_returns_404(self, http):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/macro-snapshots/01NOPE", headers=_h(token)
        )
        assert r.status_code == 404


class TestIndustryEndpoints:
    @pytest.mark.asyncio
    async def test_list_endpoint_for_audit(self, http, db):
        await _seed_via_adapter(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/industry-reports", headers=_h(token)
        )
        body = r.json()
        assert body["total"] == 2
        codes = {x["industry_code"] for x in body["reports"]}
        assert codes == {"BFSI", "IT"}

    @pytest.mark.asyncio
    async def test_filter_by_outlook(self, http, db):
        await _seed_via_adapter(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/industry-reports?outlook=positive",
            headers=_h(token),
        )
        body = r.json()
        assert body["total"] == 1
        assert body["reports"][0]["industry_code"] == "BFSI"

    @pytest.mark.asyncio
    async def test_compliance_can_read(self, http, db):
        await _seed_via_adapter(db)
        token = await _login(http, "compliance1")
        r = await http.get(
            "/api/v2/admin/industry-reports", headers=_h(token)
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_advisor_blocked(self, http):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/admin/industry-reports", headers=_h(token)
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Freshness service (regression: chunks 3.2/3.3 entities now in the table)
# ---------------------------------------------------------------------------


class TestFreshnessIncludesNewEntities:
    @pytest.mark.asyncio
    async def test_freshness_endpoint_lists_macro_and_industry(self, http, db):
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/data-freshness", headers=_h(token)
        )
        body = r.json()
        tables = {row["entity_table"] for row in body["rows"]}
        assert "instruments" in tables
        assert "macro_snapshots" in tables
        assert "industry_reports" in tables
