"""Cluster 4 chunk 4.1 — model portfolio read-only endpoint tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from ulid import ULID

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.d0.industry.models  # noqa: F401
import artha.api_v2.d0.instruments.models  # noqa: F401
import artha.api_v2.d0.macro.models  # noqa: F401
import artha.api_v2.d0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.m2.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.m2.models import PreferredPortfolioEntry
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
# Seed helper
# ---------------------------------------------------------------------------


async def _seed_demo(db) -> dict[str, Instrument]:
    """Seed three instruments + a small set of preferred entries."""
    now = datetime.now(timezone.utc)
    liquid = Instrument(
        instrument_id=str(ULID()),
        amfi_scheme_code="105280",
        name="SBI Liquid Fund",
        asset_class="cash",
        vehicle_type="mutual_fund",
        sebi_category="liquid",
        classification_confidence="high",
        status="active",
        source_identifier="test",
        created_at=now,
        last_modified_at=now,
        model_portfolio_tags=["conservative_short_term", "moderate_short_term"],
        schema_version=2,
    )
    flexi = Instrument(
        instrument_id=str(ULID()),
        amfi_scheme_code="122640",
        isin="INF879O01019",
        name="Parag Parikh Flexi Cap",
        asset_class="equity",
        vehicle_type="mutual_fund",
        sebi_category="flexi_cap",
        classification_confidence="high",
        status="active",
        source_identifier="test",
        created_at=now,
        last_modified_at=now,
        model_portfolio_tags=[
            "moderate_long_term",
            "aggressive_long_term",
            "aggressive_medium_term",
        ],
        schema_version=2,
    )
    untagged = Instrument(
        instrument_id=str(ULID()),
        amfi_scheme_code="999999",
        name="Mystery Instrument",
        asset_class="equity",
        vehicle_type="stock",
        classification_confidence="medium",
        status="active",
        source_identifier="test",
        created_at=now,
        last_modified_at=now,
        model_portfolio_tags=[],
        schema_version=2,
    )
    db.add_all([liquid, flexi, untagged])
    await db.commit()

    db.add(
        PreferredPortfolioEntry(
            entry_id=str(ULID()),
            risk_profile="conservative",
            horizon="short_term",
            instrument_id=liquid.instrument_id,
            position_role="core",
            rank_within_role=1,
            notes="Primary cash core",
            created_at=now,
            created_by="cio1",
            created_via="default_loader",
            last_modified_at=now,
            last_modified_by="cio1",
        )
    )
    db.add(
        PreferredPortfolioEntry(
            entry_id=str(ULID()),
            risk_profile="moderate",
            horizon="long_term",
            instrument_id=flexi.instrument_id,
            position_role="core",
            rank_within_role=1,
            created_at=now,
            created_by="cio1",
            created_via="default_loader",
            last_modified_at=now,
            last_modified_by="cio1",
        )
    )
    db.add(
        PreferredPortfolioEntry(
            entry_id=str(ULID()),
            risk_profile="aggressive",
            horizon="long_term",
            instrument_id=flexi.instrument_id,
            position_role="core",
            rank_within_role=1,
            created_at=now,
            created_by="cio1",
            created_via="default_loader",
            last_modified_at=now,
            last_modified_by="cio1",
        )
    )
    await db.commit()
    return {"liquid": liquid, "flexi": flexi, "untagged": untagged}


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestInstrumentList:
    @pytest.mark.asyncio
    async def test_advisor_can_read_instruments(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/instruments", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3

    @pytest.mark.asyncio
    async def test_filter_by_asset_class(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/instruments?asset_class=equity",
            headers=_h(token),
        )
        body = r.json()
        assert body["total"] == 2

    @pytest.mark.asyncio
    async def test_filter_untagged_only(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/model-portfolio/instruments?untagged_only=true",
            headers=_h(token),
        )
        body = r.json()
        assert body["total"] == 1
        assert body["instruments"][0]["name"] == "Mystery Instrument"

    @pytest.mark.asyncio
    async def test_filter_by_tag_include(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "cio1")
        r = await http.get(
            "/api/v2/model-portfolio/instruments?tag_include=aggressive_long_term",
            headers=_h(token),
        )
        body = r.json()
        assert body["total"] == 1
        assert body["instruments"][0]["name"] == "Parag Parikh Flexi Cap"

    @pytest.mark.asyncio
    async def test_search_by_name(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/instruments?search=Liquid", headers=_h(token)
        )
        body = r.json()
        assert body["total"] == 1


class TestInstrumentDetail:
    @pytest.mark.asyncio
    async def test_known_instrument_returns_tags(self, http, db):
        seeds = await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            f"/api/v2/model-portfolio/instruments/{seeds['flexi'].instrument_id}",
            headers=_h(token),
        )
        body = r.json()
        assert "aggressive_long_term" in body["model_portfolio_tags"]
        assert body["sebi_category"] == "flexi_cap"

    @pytest.mark.asyncio
    async def test_unknown_returns_404(self, http, db):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/instruments/01NOPE000000000000000000",
            headers=_h(token),
        )
        assert r.status_code == 404


class TestMatrixOverview:
    @pytest.mark.asyncio
    async def test_overview_returns_nine_cells(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/preferred", headers=_h(token)
        )
        body = r.json()
        assert len(body["cells"]) == 9
        assert body["total_entries"] == 3

    @pytest.mark.asyncio
    async def test_top_core_names_populated(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/preferred", headers=_h(token)
        )
        body = r.json()
        agg_lt = next(c for c in body["cells"] if c["cell_id"] == "aggressive_long_term")
        assert "Parag Parikh Flexi Cap" in agg_lt["top_core_names"]


class TestCellDetail:
    @pytest.mark.asyncio
    async def test_cell_with_entries(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/preferred/moderate/long_term",
            headers=_h(token),
        )
        body = r.json()
        assert len(body["core"]) == 1
        assert body["core"][0]["instrument_name"] == "Parag Parikh Flexi Cap"
        assert body["core"][0]["has_matching_tag"] is True

    @pytest.mark.asyncio
    async def test_empty_cell(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/preferred/conservative/long_term",
            headers=_h(token),
        )
        body = r.json()
        assert body["core"] == []
        assert body["satellite"] == []

    @pytest.mark.asyncio
    async def test_invalid_cell_returns_404(self, http, db):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/preferred/speculative/long_term",
            headers=_h(token),
        )
        assert r.status_code == 404


class TestByInstrument:
    @pytest.mark.asyncio
    async def test_returns_appearances(self, http, db):
        seeds = await _seed_demo(db)
        token = await _login(http, "advisor1")
        r = await http.get(
            f"/api/v2/model-portfolio/preferred/by-instrument/{seeds['flexi'].instrument_id}",
            headers=_h(token),
        )
        body = r.json()
        assert len(body["appearances"]) == 2
        cell_ids = {a["cell_id"] for a in body["appearances"]}
        assert cell_ids == {"moderate_long_term", "aggressive_long_term"}


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_summary(self, http, db):
        await _seed_demo(db)
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/model-portfolio/health", headers=_h(token)
        )
        body = r.json()
        assert body["total_instruments"] == 3
        assert body["tagged_instruments_count"] == 2
        assert body["untagged_instruments_count"] == 1
        assert body["total_preferred_entries"] == 3
        assert "moderate_long_term" in body["preferred_entries_by_cell"]


class TestPermissionGates:
    @pytest.mark.asyncio
    async def test_advisor_can_read(self, http, db):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/model-portfolio/instruments", headers=_h(token)
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_cio_can_read(self, http, db):
        token = await _login(http, "cio1")
        r = await http.get(
            "/api/v2/model-portfolio/preferred", headers=_h(token)
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_compliance_can_read(self, http, db):
        token = await _login(http, "compliance1")
        r = await http.get(
            "/api/v2/model-portfolio/health", headers=_h(token)
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_audit_can_read(self, http, db):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/model-portfolio/preferred/moderate/long_term",
            headers=_h(token),
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_unauthenticated_blocked(self, http, db):
        r = await http.get("/api/v2/model-portfolio/instruments")
        assert r.status_code == 401
