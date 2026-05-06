"""Cluster 5 chunk 5.3 — cases REST router integration tests.

Pins the chunk 5.3 surface:

- ``POST /api/v2/cases``                 — opens a case end-to-end
- ``GET  /api/v2/cases``                 — list filtered by actor scope
- ``GET  /api/v2/cases/{id}``            — single case (own_book / firm_scope)
- ``GET  /api/v2/cases/{id}/detail``     — case + all stage rows (chunk 5.5
  shape, ships now in chunk 5.3 as a stable contract)

Permission expectations:

- Advisor opens cases on their own_book; blocked by 403 outside scope.
- CIO opens cases firm-wide.
- Compliance + audit can read but not create.
- Manual evidence-agent override is CIO-only (advisor 403).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from ulid import ULID

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
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.investors.models import Household, Investor
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


@pytest_asyncio.fixture
async def seeded_book(db) -> dict[str, str]:
    """Seed two investors: one for advisor1, one for advisor2 (not in catalogue
    but assigned via raw user_id) — so we can exercise the own_book gate.
    """
    now = datetime.now(timezone.utc)

    household = Household(
        household_id=str(ULID()),
        name="Sharma Family",
        created_by="advisor1",
        created_at=now,
    )
    db.add(household)

    investor_advisor1 = Investor(
        investor_id=str(ULID()),
        household_id=household.household_id,
        name="Aarav Sharma",
        email="aarav@example.com",
        phone="+919999999991",
        pan="AAAAA1234F",
        age=35,
        advisor_id="advisor1",
        risk_appetite="moderate",
        time_horizon="3_to_5_years",
        kyc_status="pending",
        created_at=now,
        created_by="advisor1",
        created_via="form",
        last_modified_at=now,
        last_modified_by="advisor1",
    )
    db.add(investor_advisor1)

    investor_other = Investor(
        investor_id=str(ULID()),
        household_id=household.household_id,
        name="Priya Other",
        email="priya@example.com",
        phone="+919999999992",
        pan="BBBBB1234F",
        age=42,
        advisor_id="advisor_other",  # NOT advisor1
        risk_appetite="aggressive",
        time_horizon="over_5_years",
        kyc_status="pending",
        created_at=now,
        created_by="advisor_other",
        created_via="form",
        last_modified_at=now,
        last_modified_by="advisor_other",
    )
    db.add(investor_other)
    await db.commit()
    return {
        "advisor1_investor": investor_advisor1.investor_id,
        "other_investor": investor_other.investor_id,
    }


# ---------------------------------------------------------------------------
# POST /api/v2/cases
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_advisor_opens_case_in_own_book(self, http, seeded_book):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "diagnostic",
                "case_intent": "portfolio_health",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # Chunk 5.4 pipeline runs the case to its mode-specific end-state.
        # Diagnostic auto-decides without a CIO decision form.
        assert body["status"] == "decided"
        assert body["closed_reason"] == "decided"
        assert body["snapshot_bundle_id"] is not None
        assert body["case_mode"] == "diagnostic"
        assert body["created_via"] == "api"
        assert body["assigned_to"] == "advisor1"
        # M0 router decision persisted on the row.
        assert "e1_equity_evidence" in body["applicable_evidence_agents"]

    @pytest.mark.asyncio
    async def test_advisor_blocked_outside_book(self, http, seeded_book):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["other_investor"],
                "case_mode": "diagnostic",
            },
        )
        assert resp.status_code == 403
        assert "outside" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_cio_opens_case_firm_wide(self, http, seeded_book):
        token = await _login(http, "cio1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["other_investor"],
                "case_mode": "diagnostic",
                "case_intent": "portfolio_health",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["opened_by"] == "cio1"
        # Assigned-to follows the investor's advisor, not the opener.
        assert body["assigned_to"] == "advisor_other"
        assert body["status"] == "decided"

    @pytest.mark.asyncio
    async def test_compliance_blocked_from_create(self, http, seeded_book):
        token = await _login(http, "compliance1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "diagnostic",
            },
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_manual_override_advisor_blocked(self, http, seeded_book):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "proposed_action",
                "case_intent": "rebalance_proposal",
                "manual_override_evidence_agents": ["e1_equity_evidence"],
            },
        )
        assert resp.status_code == 403
        assert "manual" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_manual_override_cio_allowed(self, http, seeded_book):
        token = await _login(http, "cio1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "proposed_action",
                "case_intent": "rebalance_proposal",
                "manual_override_evidence_agents": [
                    "e1_equity_evidence",
                    "e1_tax_evidence",
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["applicable_evidence_agents"] == [
            "e1_equity_evidence",
            "e1_tax_evidence",
        ]
        # proposed_action stops at awaiting_decision (CIO records decision in 5.5).
        assert body["status"] == "awaiting_decision"

    @pytest.mark.asyncio
    async def test_invalid_mode_intent_returns_422(self, http, seeded_book):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "proposed_action",
                "case_intent": "portfolio_health",  # diagnostic-only
            },
        )
        assert resp.status_code == 422
        assert "diagnostic" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_unknown_investor_returns_404(self, http):
        token = await _login(http, "cio1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": "01ABCDEFGHIJKLMNOPQRSTUVWX",
                "case_mode": "diagnostic",
            },
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_proposed_action_with_amount(self, http, seeded_book):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "proposed_action",
                "case_intent": "new_investment",
                "proposed_action": "Buy 5L of HDFC PMS",
                "proposed_action_amount_inr": "500000",
                "proposed_action_products": ["pms"],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["proposed_action"] == "Buy 5L of HDFC PMS"
        assert Decimal(body["proposed_action_amount_inr"]) == Decimal("500000")
        assert body["proposed_action_products"] == ["pms"]
        # Materiality gate fires for PMS product → IC1 → governance →
        # challenge → awaiting_decision.
        assert body["status"] == "awaiting_decision"
        assert body["is_material"] is True
        assert "MAT_PRODUCT_PMS_AIF_SIF" in body["materiality_reason"]


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------


class TestRead:
    @pytest.mark.asyncio
    async def test_advisor_lists_only_own_book(self, http, seeded_book):
        # Open one case as advisor1, one as cio1 for a different advisor.
        advisor_token = await _login(http, "advisor1")
        cio_token = await _login(http, "cio1")
        await http.post(
            "/api/v2/cases",
            headers=_h(advisor_token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "diagnostic",
            },
        )
        await http.post(
            "/api/v2/cases",
            headers=_h(cio_token),
            json={
                "investor_id": seeded_book["other_investor"],
                "case_mode": "diagnostic",
            },
        )

        resp = await http.get("/api/v2/cases", headers=_h(advisor_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["cases"][0]["assigned_to"] == "advisor1"

    @pytest.mark.asyncio
    async def test_cio_sees_firm_wide(self, http, seeded_book):
        cio_token = await _login(http, "cio1")
        # Open two cases.
        await http.post(
            "/api/v2/cases",
            headers=_h(cio_token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "diagnostic",
            },
        )
        await http.post(
            "/api/v2/cases",
            headers=_h(cio_token),
            json={
                "investor_id": seeded_book["other_investor"],
                "case_mode": "diagnostic",
            },
        )
        resp = await http.get("/api/v2/cases", headers=_h(cio_token))
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_get_case_returns_404_for_unknown(self, http):
        token = await _login(http, "cio1")
        resp = await http.get(
            "/api/v2/cases/01NOTAREALCASEIDENTIFIERZZ",
            headers=_h(token),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_advisor_403_on_other_book_case(self, http, seeded_book):
        cio_token = await _login(http, "cio1")
        advisor_token = await _login(http, "advisor1")

        resp = await http.post(
            "/api/v2/cases",
            headers=_h(cio_token),
            json={
                "investor_id": seeded_book["other_investor"],
                "case_mode": "diagnostic",
            },
        )
        case_id = resp.json()["case_id"]
        resp = await http.get(
            f"/api/v2/cases/{case_id}", headers=_h(advisor_token),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_case_detail_includes_pipeline_stage_rows(
        self, http, seeded_book,
    ):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/cases",
            headers=_h(token),
            json={
                "investor_id": seeded_book["advisor1_investor"],
                "case_mode": "diagnostic",
                "case_intent": "portfolio_health",
            },
        )
        assert resp.status_code == 201, resp.text
        case_id = resp.json()["case_id"]

        resp = await http.get(
            f"/api/v2/cases/{case_id}/detail",
            headers=_h(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Diagnostic pipeline writes evidence + portfolio_risk + synthesis +
        # G1 governance + health report.
        assert len(body["evidence_verdicts"]) > 0
        assert body["portfolio_risk_analytics"] is not None
        assert body["synthesis"] is not None
        assert body["synthesis"]["output_mode"] == "diagnostic"
        assert len(body["governance_results"]) == 1
        assert body["governance_results"][0]["gate"] == "g1_mandate"
        assert body["health_report"] is not None
        # Diagnostic skips IC1 + A1 + decision artifact.
        assert body["ic1_deliberation"] is None
        assert body["a1_challenge"] is None
        assert body["decision_artifact"] is None
        assert body["case"]["case_id"] == case_id
