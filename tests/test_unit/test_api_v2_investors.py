"""Cluster 1 chunk 1.1 backend test suite.

Covers:
- POST /api/v2/investors creates + enriches synchronously (FR 11.1 §6)
- POST /api/v2/investors duplicate-PAN warn-and-proceed (Ideation Log §2.2)
- POST /api/v2/investors validation rules (FR 10.7 §2.4)
- GET /api/v2/investors scoping per role (advisor own_book vs firm_scope)
- GET /api/v2/investors/{id} 404 when out-of-scope or unknown
- POST/GET /api/v2/households + inline household creation during onboarding
- T1 events fire correctly (FR 10.7 acceptance + chunk 1.1 §scope_in)
- Permission gates: write requires INVESTORS_WRITE_OWN_BOOK (advisor only);
  reads accept either own_book or firm_scope variant
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.investors.event_names import (
    HOUSEHOLD_CREATED,
    INVESTOR_CREATED,
    INVESTOR_ENRICHMENT_COMPLETED,
)
from artha.api_v2.investors.models import Investor
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
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def http(db):
    async def _override_get_session():
        yield db

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


async def _login(http, user_id: str) -> str:
    resp = await http.post("/api/v2/auth/dev-login", json={"user_id": user_id})
    return resp.json()["access_token"]


def _valid_investor_payload(**overrides) -> dict:
    """Standard valid payload that should hit the accumulation/essential
    happy-path enrichment (age 30, moderate, over_5_years)."""
    base = {
        "name": "Anjali Mehta",
        "email": "anjali@example.com",
        "phone": "9876543210",  # 10-digit Indian → +91 default
        "pan": "ABCDE1234F",
        "age": 30,
        "household_name": "Mehta Household",
        "risk_appetite": "moderate",
        "time_horizon": "over_5_years",
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. Happy-path investor creation
# ===========================================================================


class TestCreateInvestorHappyPath:
    @pytest.mark.asyncio
    async def test_create_returns_201_with_enriched_record(self, http):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # Identity round-trips
        assert body["name"] == "Anjali Mehta"
        assert body["pan"] == "ABCDE1234F"
        assert body["age"] == 30
        # Phone normalised to +91 prefix
        assert body["phone"] == "+919876543210"
        # I0 enrichment populated synchronously
        assert body["life_stage"] == "accumulation"
        assert body["life_stage_confidence"] == "high"
        assert body["liquidity_tier"] == "essential"
        assert body["liquidity_tier_range"] == "5-15%"
        assert body["enrichment_version"] == "i0_active_layer_v1.0"
        # Demo addendum §1.1: kyc_status always pending
        assert body["kyc_status"] == "pending"
        # Provenance
        assert body["created_by"] == "advisor1"
        assert body["created_via"] == "form"  # default for no header
        assert body["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_create_uppercases_pan(self, http):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(pan="abcde1234f"),  # lowercase
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["pan"] == "ABCDE1234F"

    @pytest.mark.asyncio
    async def test_create_via_api_source_header_marks_created_via_api(self, http):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(pan="XXXXX1234F"),
            headers={"Authorization": f"Bearer {token}", "X-API-Source": "api"},
        )
        assert resp.json()["created_via"] == "api"

    @pytest.mark.asyncio
    async def test_phone_with_country_code_passes_through(self, http):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(phone="+14155551234"),  # US number
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["phone"] == "+14155551234"


# ===========================================================================
# 2. Validation failures (FR 10.7 §2.4)
# ===========================================================================


class TestValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_pan", ["ABC", "ABCDE12345", "12345ABCDE", "abcde1234"])
    async def test_invalid_pan_rejected(self, http, bad_pan):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(pan=bad_pan),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_age", [17, 101, 0, -5])
    async def test_age_out_of_range_rejected(self, http, bad_age):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(age=bad_age),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_name_without_space_rejected(self, http):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(name="Singleword"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_email_rejected(self, http):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(email="not-an-email"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_household_returns_400(self, http):
        token = await _login(http, "advisor1")
        payload = _valid_investor_payload()
        payload.pop("household_name")
        resp = await http.post(
            "/api/v2/investors",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "household" in resp.json()["detail"].lower()


# ===========================================================================
# 3. Duplicate PAN warn-and-proceed (Ideation Log §2.2)
# ===========================================================================


class TestDuplicatePan:
    @pytest.mark.asyncio
    async def test_first_create_succeeds(self, http):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(pan="DUPED1234A"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_second_create_same_pan_returns_409_with_duplicate_payload(self, http):
        token = await _login(http, "advisor1")
        payload = _valid_investor_payload(pan="DUPED1234A")
        first = await http.post(
            "/api/v2/investors", json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 201

        # Same PAN, no acknowledgement → 409 with duplicate payload
        second = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(pan="DUPED1234A", name="Other Person"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 409
        body = second.json()
        assert body["title"] == "Duplicate PAN"
        assert "duplicate" in body
        assert body["duplicate"]["duplicate_of_name"] == "Anjali Mehta"
        assert body["duplicate"]["pan"] == "DUPED1234A"

    @pytest.mark.asyncio
    async def test_acknowledged_duplicate_creates_second_record(self, http):
        token = await _login(http, "advisor1")
        await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(pan="ACKED1234A"),
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(
                pan="ACKED1234A", name="Other Person", duplicate_pan_acknowledged=True
            ),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["duplicate_pan_acknowledged"] is True


# ===========================================================================
# 4. List + detail with role-based scoping
# ===========================================================================


class TestRoleScopedReads:
    @pytest.mark.asyncio
    async def test_advisor_lists_own_book_only(self, http, db):
        # advisor1 creates one investor; advisor2 creates another (we simulate
        # advisor2 by hand-inserting a row with a different advisor_id).
        token_a = await _login(http, "advisor1")
        await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(pan="OWNED1234A"),
            headers={"Authorization": f"Bearer {token_a}"},
        )
        # Insert a different-advisor row directly so we don't need a second login.
        from datetime import datetime, timezone

        from ulid import ULID
        async with db.begin():
            db.add(
                Investor(
                    investor_id=str(ULID()),
                    name="Other Advisor's Client",
                    email="other@example.com", phone="+919999999999",
                    pan="OTHER1234B", age=40,
                    household_id="01ABCDEFGHJKMNPQRSTVWXYZ56",
                    advisor_id="advisor2",  # different advisor
                    risk_appetite="moderate", time_horizon="over_5_years",
                    kyc_status="pending",
                    created_at=datetime.now(timezone.utc),
                    created_by="advisor2", created_via="form",
                    duplicate_pan_acknowledged=False,
                    last_modified_at=datetime.now(timezone.utc),
                    last_modified_by="advisor2", schema_version=1,
                )
            )
            # Need a household row for the FK.
            from artha.api_v2.investors.models import Household
            db.add(
                Household(
                    household_id="01ABCDEFGHJKMNPQRSTVWXYZ56",
                    name="Other HH", created_by="advisor2",
                    created_at=datetime.now(timezone.utc),
                )
            )

        # advisor1 lists → sees only their own investor
        resp = await http.get(
            "/api/v2/investors",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["investors"]) == 1
        assert body["investors"][0]["pan"] == "OWNED1234A"

    @pytest.mark.asyncio
    async def test_cio_lists_firm_wide(self, http, db):
        # Seed two investors under different advisors.
        from datetime import datetime, timezone

        from ulid import ULID

        from artha.api_v2.investors.models import Household
        async with db.begin():
            for advisor_id, pan in [("advisor1", "AAAAA1111A"), ("advisor2", "BBBBB2222B")]:
                hh_id = str(ULID())
                db.add(Household(
                    household_id=hh_id, name="HH",
                    created_by=advisor_id, created_at=datetime.now(timezone.utc),
                ))
                db.add(Investor(
                    investor_id=str(ULID()),
                    name="Test Investor", email="t@example.com", phone="+919999999999",
                    pan=pan, age=40, household_id=hh_id, advisor_id=advisor_id,
                    risk_appetite="moderate", time_horizon="over_5_years",
                    kyc_status="pending",
                    created_at=datetime.now(timezone.utc),
                    created_by=advisor_id, created_via="form",
                    duplicate_pan_acknowledged=False,
                    last_modified_at=datetime.now(timezone.utc),
                    last_modified_by=advisor_id, schema_version=1,
                ))

        # CIO sees both
        cio_token = await _login(http, "cio1")
        resp = await http.get(
            "/api/v2/investors",
            headers={"Authorization": f"Bearer {cio_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["investors"]) == 2

    @pytest.mark.asyncio
    async def test_advisor_cannot_get_other_advisors_investor(self, http, db):
        # Advisor1 creates an investor; advisor2 (we simulate via a second
        # login since cio1 is the only other YAML user) tries to read it.
        # Easier: use cio1 to set up a non-matching investor and verify
        # advisor1 doesn't see it on the detail endpoint.
        from datetime import datetime, timezone

        from ulid import ULID

        from artha.api_v2.investors.models import Household
        hh_id = str(ULID())
        inv_id = str(ULID())
        async with db.begin():
            db.add(Household(
                household_id=hh_id, name="X",
                created_by="cio1", created_at=datetime.now(timezone.utc),
            ))
            db.add(Investor(
                investor_id=inv_id,
                name="CIO Owned", email="x@y.z", phone="+919999999999",
                pan="CIOEX1234A", age=40, household_id=hh_id, advisor_id="cio1",
                risk_appetite="moderate", time_horizon="over_5_years",
                kyc_status="pending",
                created_at=datetime.now(timezone.utc),
                created_by="cio1", created_via="form",
                duplicate_pan_acknowledged=False,
                last_modified_at=datetime.now(timezone.utc),
                last_modified_by="cio1", schema_version=1,
            ))

        advisor_token = await _login(http, "advisor1")
        resp = await http.get(
            f"/api/v2/investors/{inv_id}",
            headers={"Authorization": f"Bearer {advisor_token}"},
        )
        assert resp.status_code == 404


# ===========================================================================
# 5. Households
# ===========================================================================


class TestHouseholds:
    @pytest.mark.asyncio
    async def test_create_household_returns_201(self, http):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/households",
            json={"name": "test family"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Test Family"  # title-cased
        assert body["created_by"] == "advisor1"

    @pytest.mark.asyncio
    async def test_list_households_advisor_sees_own_only(self, http):
        token = await _login(http, "advisor1")
        await http.post(
            "/api/v2/households", json={"name": "a"},
            headers={"Authorization": f"Bearer {token}"},
        )
        await http.post(
            "/api/v2/households", json={"name": "b"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await http.get(
            "/api/v2/households",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert len(resp.json()["households"]) == 2

    @pytest.mark.asyncio
    async def test_inline_household_creation_during_investor_onboarding(self, http, db):
        token = await _login(http, "advisor1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(household_name="Brand New Family"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        # Investor's household_id references a freshly-created household.
        list_resp = await http.get(
            "/api/v2/households",
            headers={"Authorization": f"Bearer {token}"},
        )
        names = [h["name"] for h in list_resp.json()["households"]]
        assert "Brand New Family" in names


# ===========================================================================
# 6. T1 telemetry — chunk 1.1 §scope_in
# ===========================================================================


class TestT1Events:
    @pytest.mark.asyncio
    async def test_create_emits_investor_created_and_enrichment_completed(self, http, db):
        token = await _login(http, "advisor1")
        await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        result = await db.execute(select(T1Event))
        names = [e.event_name for e in result.scalars()]
        assert INVESTOR_CREATED in names
        assert INVESTOR_ENRICHMENT_COMPLETED in names

    @pytest.mark.asyncio
    async def test_inline_household_creation_emits_household_created(self, http, db):
        token = await _login(http, "advisor1")
        await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(household_name="Inline HH"),
            headers={"Authorization": f"Bearer {token}"},
        )
        result = await db.execute(
            select(T1Event).where(T1Event.event_name == HOUSEHOLD_CREATED)
        )
        events = list(result.scalars())
        assert len(events) >= 1
        assert events[0].payload.get("created_inline_for_investor") is True

    @pytest.mark.asyncio
    async def test_enrichment_event_carries_life_stage_and_tier(self, http, db):
        token = await _login(http, "advisor1")
        await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(age=60, time_horizon="under_3_years"),
            headers={"Authorization": f"Bearer {token}"},
        )
        result = await db.execute(
            select(T1Event).where(T1Event.event_name == INVESTOR_ENRICHMENT_COMPLETED)
        )
        events = list(result.scalars())
        assert len(events) == 1
        assert events[0].payload["life_stage"] == "distribution"
        assert events[0].payload["liquidity_tier"] == "deep"


# ===========================================================================
# 7. Permission gates
# ===========================================================================


class TestPermissionGates:
    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, http):
        resp = await http.post("/api/v2/investors", json=_valid_investor_payload())
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cio_cannot_write_investor(self, http):
        """CIO has read:firm_scope but NOT write:own_book in cluster 1."""
        token = await _login(http, "cio1")
        resp = await http.post(
            "/api/v2/investors",
            json=_valid_investor_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["advisor1", "cio1", "compliance1", "audit1"])
    async def test_all_roles_can_list_investors(self, http, user_id):
        token = await _login(http, user_id)
        resp = await http.get(
            "/api/v2/investors",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 200 with 0 investors (empty book) is the expected baseline.
        assert resp.status_code == 200
