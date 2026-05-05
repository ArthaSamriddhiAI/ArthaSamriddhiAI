"""Cluster 3 chunk 3.2 — instrument browse-endpoint test suite.

Pins the chunk-3.2 admin endpoints:

- ``GET /api/v2/admin/instruments``           — paginated list with filters
- ``GET /api/v2/admin/instruments/{id}``      — one row's detail
- ``GET /api/v2/admin/sebi-categories``       — full SEBI map dump

Plus permission gates: audit + CIO + compliance can read; advisor blocked.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.d0.instruments.models  # noqa: F401
import artha.api_v2.d0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.d0.adapters.json_fixture import JSONFixtureAdapter
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import settings

_TEST_JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"


# ---------------------------------------------------------------------------
# Setup fixtures (mirroring chunk 3.1 admin tests)
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
# Seed helper
# ---------------------------------------------------------------------------


async def _seed_instruments(db) -> None:
    fixture = {
        "instruments": [
            {
                "isin": "INF200K01XX2",
                "amfi_scheme_code": "118989",
                "name": "SBI Bluechip Fund Direct Plan Growth",
                "sebi_category": "large_cap",
                "amc_name": "SBI Mutual Fund",
            },
            {
                "isin": "INF879O01027",
                "amfi_scheme_code": "120505",
                "name": "Mirae Asset Liquid Fund Direct Plan Growth",
                "sebi_category": "liquid",
                "amc_name": "Mirae Asset Mutual Fund",
            },
            {
                "isin": "INE002A01018",
                "name": "Reliance Industries Stock",
                "asset_class": "equity",
                "vehicle_type": "stock",
            },
        ]
    }
    adapter = JSONFixtureAdapter(fixture_name="test", fixture=fixture)
    await adapter.run(db)
    await db.commit()


# ---------------------------------------------------------------------------
# GET /api/v2/admin/instruments
# ---------------------------------------------------------------------------


class TestListEndpoint:
    @pytest.mark.asyncio
    async def test_list_returns_seeded_instruments_for_audit(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "audit1")

        r = await http.get("/api/v2/admin/instruments", headers=_h(token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert len(body["instruments"]) == 3
        names = {i["name"] for i in body["instruments"]}
        assert "SBI Bluechip Fund Direct Plan Growth" in names

    @pytest.mark.asyncio
    async def test_filter_by_asset_class(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/instruments?asset_class=cash", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["instruments"][0]["sebi_category"] == "liquid"

    @pytest.mark.asyncio
    async def test_filter_by_sebi_category(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/instruments?sebi_category=large_cap",
            headers=_h(token),
        )
        body = r.json()
        assert body["total"] == 1
        assert "Bluechip" in body["instruments"][0]["name"]

    @pytest.mark.asyncio
    async def test_search_matches_name(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/instruments?search=Mirae", headers=_h(token)
        )
        body = r.json()
        assert body["total"] == 1
        assert "Mirae" in body["instruments"][0]["name"]

    @pytest.mark.asyncio
    async def test_search_matches_isin(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/instruments?search=INE002A01018",
            headers=_h(token),
        )
        body = r.json()
        assert body["total"] == 1
        assert body["instruments"][0]["vehicle_type"] == "stock"

    @pytest.mark.asyncio
    async def test_pagination_offset_and_limit(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "audit1")

        r = await http.get(
            "/api/v2/admin/instruments?limit=2&offset=0", headers=_h(token)
        )
        body = r.json()
        assert len(body["instruments"]) == 2
        assert body["total"] == 3
        assert body["limit"] == 2
        assert body["offset"] == 0

        r = await http.get(
            "/api/v2/admin/instruments?limit=2&offset=2", headers=_h(token)
        )
        body = r.json()
        assert len(body["instruments"]) == 1
        assert body["offset"] == 2


# ---------------------------------------------------------------------------
# GET /api/v2/admin/instruments/{id}
# ---------------------------------------------------------------------------


class TestDetailEndpoint:
    @pytest.mark.asyncio
    async def test_detail_returns_full_row(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "audit1")

        listing = (
            await http.get("/api/v2/admin/instruments", headers=_h(token))
        ).json()
        ident = listing["instruments"][0]["instrument_id"]

        r = await http.get(
            f"/api/v2/admin/instruments/{ident}", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["instrument_id"] == ident
        assert body["asset_class"] in {"equity", "debt", "cash", "alternatives"}
        assert "source_identifier" in body

    @pytest.mark.asyncio
    async def test_detail_unknown_id_returns_404(self, http):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/instruments/01NOPENOPE000000000000000",
            headers=_h(token),
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v2/admin/sebi-categories
# ---------------------------------------------------------------------------


class TestSebiCategoriesEndpoint:
    @pytest.mark.asyncio
    async def test_lists_all_50_categories(self, http):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/sebi-categories", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["categories"]) == 50

    @pytest.mark.asyncio
    async def test_each_category_carries_asset_class_and_vehicle(self, http):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/sebi-categories", headers=_h(token)
        )
        body = r.json()
        for entry in body["categories"]:
            assert "category" in entry
            assert "asset_class" in entry
            assert "vehicle_type" in entry
            assert entry["asset_class"] in {
                "equity",
                "debt",
                "cash",
                "alternatives",
            }


# ---------------------------------------------------------------------------
# Permission gates
# ---------------------------------------------------------------------------


class TestPermissionGates:
    @pytest.mark.asyncio
    async def test_advisor_blocked_from_instruments_list(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/admin/instruments", headers=_h(token)
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_cio_can_read_instruments(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "cio1")
        r = await http.get(
            "/api/v2/admin/instruments", headers=_h(token)
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_compliance_can_read_instruments(self, http, db):
        await _seed_instruments(db)
        token = await _login(http, "compliance1")
        r = await http.get(
            "/api/v2/admin/instruments", headers=_h(token)
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_advisor_blocked_from_sebi_categories(self, http):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/admin/sebi-categories", headers=_h(token)
        )
        assert r.status_code == 403
