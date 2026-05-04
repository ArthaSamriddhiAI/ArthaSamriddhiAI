"""Cluster 2 chunks 2.1 + 2.4 — REST endpoint test suite.

Covers the full surface from the chunk plans:

- ``GET    /api/v2/investors/{id}/mandate/defaults``  — I0 defaults + sources
- ``POST   /api/v2/investors/{id}/mandate``           — create initial mandate
- ``GET    /api/v2/investors/{id}/mandate``           — fetch active mandate
- ``GET    /api/v2/investors/{id}/mandate/versions``  — list all versions
- ``GET    /api/v2/mandates/{mandate_id}``            — fetch by mandate_id
- ``POST   /api/v2/mandates/from-pdf``                — chunk 2.4 stub (501)

End-to-end happy path creates an investor → fetches I0 defaults → creates
mandate (auto-active version=1) → reads back. Other tests verify
duplicate-mandate 409, validation-failure 400 with structured failures,
soft warnings, the PDF stub returns 501, and permission gates.
"""

from __future__ import annotations

import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.m1.event_names import (
    MANDATE_CREATED,
    MANDATE_CREATION_BLOCKED_EXISTING,
    MANDATE_VERSION_ACTIVATED,
    MANDATE_VERSION_CREATED,
    PDF_ENDPOINT_CALLED,
)
from artha.api_v2.m1.models import Mandate, MandateVersion
from artha.api_v2.observability.models import T1Event
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


def _valid_investor_payload(**overrides) -> dict:
    base = {
        "name": "Anjali Mehta",
        "email": "anjali@example.com",
        "phone": "9876543210",
        "pan": "ABCDE1234F",
        "age": 30,
        "household_name": "Mehta Household",
        "risk_appetite": "moderate",
        "time_horizon": "over_5_years",
    }
    base.update(overrides)
    return base


def _valid_mandate_payload(**overrides) -> dict:
    base = {
        "equity_min_pct": 50,
        "equity_max_pct": 70,
        "debt_min_pct": 20,
        "debt_max_pct": 40,
        "alternatives_min_pct": 5,
        "alternatives_max_pct": 15,
        "single_position_max_pct": 5,
        "liquidity_floor_pct": 20,
        "sector_max_pct": 25,
        "prohibited_instruments": [],
    }
    base.update(overrides)
    return base


async def _create_investor(http, token: str, **overrides) -> str:
    """Helper: create a fresh investor and return investor_id."""
    resp = await http.post(
        "/api/v2/investors",
        json=_valid_investor_payload(**overrides),
        headers=_h(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["investor_id"]


# ===========================================================================
# 1. Defaults endpoint
# ===========================================================================


class TestDefaultsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_i0_suggested_values_for_moderate_over_5_years(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        resp = await http.get(
            f"/api/v2/investors/{investor_id}/mandate/defaults",
            headers=_h(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Moderate / over_5_years → essential liquidity tier; equity 50-70.
        assert body["equity_min_pct"] == 50
        assert body["equity_max_pct"] == 70
        assert body["liquidity_floor_pct"] == 10
        assert body["risk_appetite"] == "moderate"
        assert body["liquidity_tier"] == "essential"
        # Source labels populated for every constraint field.
        assert body["sources"]["liquidity_floor_pct"] == "i0_liquidity_tier"
        assert body["sources"]["equity_min_pct"] == "i0_risk_appetite"
        assert body["sources"]["sector_max_pct"] == "industry_standard"

    @pytest.mark.asyncio
    async def test_unknown_investor_returns_404(self, http):
        token = await _login(http, "advisor1")
        resp = await http.get(
            "/api/v2/investors/01ABCNONEXIST5678/mandate/defaults",
            headers=_h(token),
        )
        assert resp.status_code == 404


# ===========================================================================
# 2. Create mandate happy path
# ===========================================================================


class TestCreateMandateHappyPath:
    @pytest.mark.asyncio
    async def test_create_returns_201_with_active_version(self, http, db):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)

        resp = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(token),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["mandate"]["investor_id"] == investor_id
        assert body["mandate"]["active_version_id"] is not None
        active = body["mandate"]["active_version"]
        assert active is not None
        assert active["status"] == "active"
        assert active["version_number"] == 1
        assert active["created_via"] == "form"
        assert active["activated_at"] is not None
        assert body["warnings"] == []

        # DB rows exist + mandate.active_version_id matches version.version_id.
        mandate = (await db.execute(select(Mandate))).scalar_one()
        version = (await db.execute(select(MandateVersion))).scalar_one()
        assert mandate.active_version_id == version.version_id
        assert version.status == "active"

    @pytest.mark.asyncio
    async def test_create_via_api_source_header_marks_via(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        resp = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers={**_h(token), "X-API-Source": "api"},
        )
        assert resp.status_code == 201
        assert resp.json()["mandate"]["active_version"]["created_via"] == "api"

    @pytest.mark.asyncio
    async def test_create_via_c0_source_header_marks_conversational(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        resp = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers={**_h(token), "X-API-Source": "c0"},
        )
        assert resp.status_code == 201
        assert (
            resp.json()["mandate"]["active_version"]["created_via"]
            == "conversational"
        )

    @pytest.mark.asyncio
    async def test_create_emits_three_t1_events(self, http, db):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(token),
        )
        for name in (
            MANDATE_CREATED,
            MANDATE_VERSION_CREATED,
            MANDATE_VERSION_ACTIVATED,
        ):
            ev = (
                await db.execute(
                    select(T1Event).where(T1Event.event_name == name)
                )
            ).scalars().all()
            assert len(ev) == 1, f"missing T1 event {name!r}"


# ===========================================================================
# 3. Validation failures
# ===========================================================================


class TestValidationFailures:
    @pytest.mark.asyncio
    async def test_max_below_min_returns_400_with_failure_list(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        resp = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(equity_min_pct=70, equity_max_pct=50),
            headers=_h(token),
        )
        assert resp.status_code == 400, resp.text
        body = resp.json()
        codes = [f["code"] for f in body["failures"]]
        assert "max_less_than_min" in codes

    @pytest.mark.asyncio
    async def test_sum_min_over_100_returns_400(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        resp = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(
                equity_min_pct=60, equity_max_pct=70,
                debt_min_pct=30, debt_max_pct=40,
                alternatives_min_pct=20, alternatives_max_pct=30,
            ),
            headers=_h(token),
        )
        assert resp.status_code == 400
        codes = [f["code"] for f in resp.json()["failures"]]
        assert "sum_min_exceeds_100" in codes

    @pytest.mark.asyncio
    async def test_out_of_range_pct_returns_422(self, http):
        # Pydantic catches this before service-layer validation runs.
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        resp = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(equity_max_pct=200),
            headers=_h(token),
        )
        assert resp.status_code == 422


# ===========================================================================
# 4. Soft warnings
# ===========================================================================


class TestSoftWarnings:
    @pytest.mark.asyncio
    async def test_atypical_single_position_returns_warning_but_creates(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        resp = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(single_position_max_pct=15),
            headers=_h(token),
        )
        assert resp.status_code == 201
        body = resp.json()
        codes = [w["code"] for w in body["warnings"]]
        assert "single_position_outside_typical" in codes


# ===========================================================================
# 5. Duplicate mandate (409)
# ===========================================================================


class TestDuplicateMandate:
    @pytest.mark.asyncio
    async def test_second_create_returns_409_with_existing_id(self, http, db):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        first = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(token),
        )
        existing_id = first.json()["mandate"]["mandate_id"]

        second = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(token),
        )
        assert second.status_code == 409, second.text
        body = second.json()
        assert body["mandate_id"] == existing_id
        assert "amendment" in body["detail"].lower()

        # T1 records the blocked attempt.
        ev = (
            await db.execute(
                select(T1Event).where(
                    T1Event.event_name == MANDATE_CREATION_BLOCKED_EXISTING
                )
            )
        ).scalars().all()
        assert len(ev) == 1


# ===========================================================================
# 6. Read paths
# ===========================================================================


class TestReadPaths:
    @pytest.mark.asyncio
    async def test_get_active_mandate_after_create(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(token),
        )
        r = await http.get(
            f"/api/v2/investors/{investor_id}/mandate", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["active_version"]["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_active_mandate_404_when_no_mandate(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        r = await http.get(
            f"/api/v2/investors/{investor_id}/mandate", headers=_h(token)
        )
        assert r.status_code == 404
        assert "does not have a mandate" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_versions_returns_only_active_after_create(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(token),
        )
        r = await http.get(
            f"/api/v2/investors/{investor_id}/mandate/versions",
            headers=_h(token),
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["versions"]) == 1
        assert body["versions"][0]["version_number"] == 1
        assert body["versions"][0]["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_mandate_by_id(self, http):
        token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, token)
        create = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(token),
        )
        mandate_id = create.json()["mandate"]["mandate_id"]
        r = await http.get(
            f"/api/v2/mandates/{mandate_id}", headers=_h(token)
        )
        assert r.status_code == 200
        assert r.json()["mandate_id"] == mandate_id

    @pytest.mark.asyncio
    async def test_get_mandate_by_id_404_when_unknown(self, http):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/mandates/01ABCNONEXIST5678", headers=_h(token)
        )
        assert r.status_code == 404


# ===========================================================================
# 7. Permission gates
# ===========================================================================


class TestPermissionGates:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["cio1", "compliance1", "audit1"])
    async def test_non_advisor_cannot_create_mandate(self, http, user_id):
        # Set up an investor as advisor1 first.
        advisor_token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, advisor_token)
        # Then try to create a mandate as a non-advisor.
        token = await _login(http, user_id)
        resp = await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["cio1", "compliance1", "audit1"])
    async def test_non_advisor_can_read_mandate_firm_wide(self, http, user_id):
        advisor_token = await _login(http, "advisor1")
        investor_id = await _create_investor(http, advisor_token)
        await http.post(
            f"/api/v2/investors/{investor_id}/mandate",
            json=_valid_mandate_payload(),
            headers=_h(advisor_token),
        )
        # CIO/compliance/audit can read firm-wide.
        token = await _login(http, user_id)
        r = await http.get(
            f"/api/v2/investors/{investor_id}/mandate", headers=_h(token)
        )
        assert r.status_code == 200, f"{user_id} got {r.status_code}: {r.text}"

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, http):
        resp = await http.get(
            "/api/v2/investors/x/mandate"
        )
        assert resp.status_code == 401


# ===========================================================================
# 8. PDF stub (chunk 2.4)
# ===========================================================================


class TestPdfStub:
    @pytest.mark.asyncio
    async def test_pdf_endpoint_returns_501_with_problem_detail(self, http, db):
        token = await _login(http, "advisor1")
        files = {"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
        resp = await http.post(
            "/api/v2/mandates/from-pdf",
            files=files,
            headers=_h(token),
        )
        assert resp.status_code == 501, resp.text
        body = resp.json()
        assert body["title"] == "PDF parsing not yet implemented"
        assert "structured JSON" in body["detail"]
        assert (
            body["alternative_endpoint"]
            == "/api/v2/investors/{investor_id}/mandate"
        )

        # T1 records the call for usage analytics.
        ev = (
            await db.execute(
                select(T1Event).where(T1Event.event_name == PDF_ENDPOINT_CALLED)
            )
        ).scalars().all()
        assert len(ev) == 1
        assert ev[0].payload["filename"] == "test.pdf"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["cio1", "compliance1", "audit1"])
    async def test_non_advisor_pdf_endpoint_returns_403(self, http, user_id):
        token = await _login(http, user_id)
        files = {"file": ("x.pdf", io.BytesIO(b"x"), "application/pdf")}
        resp = await http.post(
            "/api/v2/mandates/from-pdf",
            files=files,
            headers=_h(token),
        )
        assert resp.status_code == 403
