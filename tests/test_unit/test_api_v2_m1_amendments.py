"""Cluster 2 chunk 2.3 — amendment-workflow REST endpoint test suite.

Covers the full lifecycle:

- ``POST /api/v2/investors/{id}/mandate/amend``           — propose draft
- ``PUT  /api/v2/mandate-versions/{id}``                  — edit draft
- ``POST /api/v2/mandate-versions/{id}/submit``           — draft → pending
- ``GET  /api/v2/cio/pending-amendments``                 — CIO queue
- ``GET  /api/v2/mandate-versions/{id}/diff``             — diff + impact
- ``POST /api/v2/mandate-versions/{id}/approve``          — pending → active
- ``POST /api/v2/mandate-versions/{id}/reject``           — pending → rejected
- ``POST /api/v2/mandate-versions/{id}/request-changes``  — pending → draft

Plus pre-validation (no active mandate, pending already exists), atomic
approval (active version updated + previously-active archived in one
transaction), permission gates (advisor write, CIO approve), and T1
event emission for every state transition.
"""

from __future__ import annotations

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
    MANDATE_AMENDMENT_APPROVED,
    MANDATE_AMENDMENT_CHANGES_REQUESTED,
    MANDATE_AMENDMENT_PROPOSED,
    MANDATE_AMENDMENT_REJECTED,
    MANDATE_VERSION_ACTIVATED,
    MANDATE_VERSION_ARCHIVED,
    MANDATE_VERSION_CREATED,
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


def _investor_payload(**overrides) -> dict:
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


def _mandate_payload(**overrides) -> dict:
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


async def _setup_investor_with_mandate(http) -> tuple[str, str, str]:
    """Onboard investor + create mandate. Returns (advisor_token, investor_id, mandate_id)."""
    advisor = await _login(http, "advisor1")
    investor = await http.post(
        "/api/v2/investors", json=_investor_payload(), headers=_h(advisor)
    )
    investor_id = investor.json()["investor_id"]
    create = await http.post(
        f"/api/v2/investors/{investor_id}/mandate",
        json=_mandate_payload(),
        headers=_h(advisor),
    )
    mandate_id = create.json()["mandate"]["mandate_id"]
    return advisor, investor_id, mandate_id


# ===========================================================================
# 1. Propose amendment
# ===========================================================================


class TestProposeAmendment:
    @pytest.mark.asyncio
    async def test_advisor_can_propose_draft_with_active_values_copied(self, http, db):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)

        r = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # Draft has version=2 with active's values copied verbatim.
        assert body["version_number"] == 2
        assert body["status"] == "draft"
        assert body["equity_min_pct"] == 50
        assert body["equity_max_pct"] == 70
        assert body["parent_version_id"] is not None

        # T1 event fired.
        ev = (
            await db.execute(
                select(T1Event).where(T1Event.event_name == MANDATE_VERSION_CREATED)
            )
        ).scalars().all()
        # 2 created events: version=1 from create + version=2 draft.
        assert len(ev) == 2

    @pytest.mark.asyncio
    async def test_no_active_mandate_returns_404(self, http):
        advisor = await _login(http, "advisor1")
        investor = await http.post(
            "/api/v2/investors", json=_investor_payload(), headers=_h(advisor)
        )
        investor_id = investor.json()["investor_id"]
        # No mandate created — amend should 404.
        r = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        assert r.status_code == 404
        assert "no active mandate" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_pending_amendment_blocks_new_proposal(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        first = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        first_id = first.json()["version_id"]
        # Second attempt should hit the strict-one-at-a-time guard.
        second = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        assert second.status_code == 409
        assert second.json()["version_id"] == first_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["cio1", "compliance1", "audit1"])
    async def test_non_advisor_cannot_propose(self, http, user_id):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        token = await _login(http, user_id)
        r = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(token),
        )
        assert r.status_code == 403


# ===========================================================================
# 2. Update draft
# ===========================================================================


class TestUpdateDraft:
    @pytest.mark.asyncio
    async def test_advisor_can_edit_draft(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        r = await http.put(
            f"/api/v2/mandate-versions/{version_id}",
            json=_mandate_payload(equity_max_pct=75),
            headers=_h(advisor),
        )
        assert r.status_code == 200, r.text
        assert r.json()["equity_max_pct"] == 75

    @pytest.mark.asyncio
    async def test_validation_failure_returns_400(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        r = await http.put(
            f"/api/v2/mandate-versions/{version_id}",
            json=_mandate_payload(equity_min_pct=80, equity_max_pct=70),
            headers=_h(advisor),
        )
        assert r.status_code == 400
        codes = [f["code"] for f in r.json()["failures"]]
        assert "max_less_than_min" in codes

    @pytest.mark.asyncio
    async def test_cannot_edit_active_version(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        active = await http.get(
            f"/api/v2/investors/{investor_id}/mandate", headers=_h(advisor)
        )
        active_id = active.json()["active_version_id"]
        r = await http.put(
            f"/api/v2/mandate-versions/{active_id}",
            json=_mandate_payload(),
            headers=_h(advisor),
        )
        assert r.status_code == 409
        assert "draft required" in r.json()["detail"]


# ===========================================================================
# 3. Submit for approval
# ===========================================================================


class TestSubmitForApproval:
    @pytest.mark.asyncio
    async def test_submit_transitions_to_pending_approval(self, http, db):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        r = await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "pending_approval"
        assert body["proposed_at"] is not None
        assert body["proposed_by"] == "advisor1"

        # T1 event.
        ev = (
            await db.execute(
                select(T1Event).where(T1Event.event_name == MANDATE_AMENDMENT_PROPOSED)
            )
        ).scalars().all()
        assert len(ev) == 1


# ===========================================================================
# 4. CIO pending queue
# ===========================================================================


class TestPendingQueue:
    @pytest.mark.asyncio
    async def test_cio_sees_pending_amendment_in_queue(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.put(
            f"/api/v2/mandate-versions/{version_id}",
            json=_mandate_payload(equity_max_pct=75),
            headers=_h(advisor),
        )
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )

        cio = await _login(http, "cio1")
        r = await http.get(
            "/api/v2/cio/pending-amendments", headers=_h(cio)
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["pending"]) == 1
        item = body["pending"][0]
        assert item["version_id"] == version_id
        assert item["investor_name"] == "Anjali Mehta"
        assert item["investor_pan"] == "ABCDE1234F"
        assert item["version_number"] == 2
        assert any("70" in line and "75" in line for line in item["change_summary"])

    @pytest.mark.asyncio
    async def test_pending_queue_excludes_approved_amendments(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )

        cio = await _login(http, "cio1")
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/approve",
            json={},
            headers=_h(cio),
        )
        r = await http.get(
            "/api/v2/cio/pending-amendments", headers=_h(cio)
        )
        assert r.status_code == 200
        assert r.json()["pending"] == []

    @pytest.mark.asyncio
    async def test_advisor_pending_queue_only_their_own_book(self, http, db):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )
        # Advisor reads their own queue — should see exactly one pending.
        r = await http.get(
            "/api/v2/cio/pending-amendments", headers=_h(advisor)
        )
        assert r.status_code == 200
        assert len(r.json()["pending"]) == 1


# ===========================================================================
# 5. Diff endpoint
# ===========================================================================


class TestDiffEndpoint:
    @pytest.mark.asyncio
    async def test_diff_shows_active_proposed_summary_and_impact(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.put(
            f"/api/v2/mandate-versions/{version_id}",
            json=_mandate_payload(
                equity_max_pct=75, prohibited_instruments=["tobacco stocks"]
            ),
            headers=_h(advisor),
        )
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )

        cio = await _login(http, "cio1")
        r = await http.get(
            f"/api/v2/mandate-versions/{version_id}/diff", headers=_h(cio)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["active"]["version_number"] == 1
        assert body["proposed"]["version_number"] == 2
        # Numeric change captured.
        fields = [c["field"] for c in body["numeric_changes"]]
        assert "equity_max_pct" in fields
        # Prohibited added.
        assert "tobacco stocks" in body["prohibited_change"]["added"]
        # Summary contains plain-language change.
        assert any("70" in s and "75" in s for s in body["summary"])
        # Impact analysis structure.
        assert body["impact"]["portfolio_implications"]["status"] == "cluster_4_placeholder"
        assert "version 2" in body["impact"]["activation_summary"]


# ===========================================================================
# 6. Approve
# ===========================================================================


class TestApprove:
    @pytest.mark.asyncio
    async def test_approve_atomically_activates_proposed_and_archives_active(
        self, http, db
    ):
        advisor, investor_id, mandate_id = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        proposed_id = proposal.json()["version_id"]
        await http.put(
            f"/api/v2/mandate-versions/{proposed_id}",
            json=_mandate_payload(equity_max_pct=75),
            headers=_h(advisor),
        )
        await http.post(
            f"/api/v2/mandate-versions/{proposed_id}/submit",
            json={},
            headers=_h(advisor),
        )

        cio = await _login(http, "cio1")
        r = await http.post(
            f"/api/v2/mandate-versions/{proposed_id}/approve",
            json={"comments": "looks good"},
            headers=_h(cio),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "active"
        assert body["approved_by"] == "cio1"
        assert body["approval_comments"] == "looks good"
        assert body["activated_at"] is not None

        # Mandate.active_version_id updated.
        mandate = (
            await db.execute(select(Mandate).where(Mandate.mandate_id == mandate_id))
        ).scalar_one()
        assert mandate.active_version_id == proposed_id

        # Previously-active version archived.
        versions = (await db.execute(select(MandateVersion))).scalars().all()
        v1 = next(v for v in versions if v.version_number == 1)
        v2 = next(v for v in versions if v.version_number == 2)
        assert v1.status == "archived"
        assert v1.archived_at is not None
        assert v2.status == "active"

        # T1 — three events from the approve action.
        for name in (
            MANDATE_AMENDMENT_APPROVED,
            MANDATE_VERSION_ACTIVATED,
            MANDATE_VERSION_ARCHIVED,
        ):
            ev = (
                await db.execute(
                    select(T1Event).where(T1Event.event_name == name)
                )
            ).scalars().all()
            assert len(ev) >= 1, f"missing T1 event {name!r}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["advisor1", "compliance1", "audit1"])
    async def test_non_cio_cannot_approve(self, http, user_id):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )

        token = await _login(http, user_id)
        r = await http.post(
            f"/api/v2/mandate-versions/{version_id}/approve",
            json={},
            headers=_h(token),
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_approve_already_approved_returns_409(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )
        cio = await _login(http, "cio1")
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/approve",
            json={},
            headers=_h(cio),
        )
        # Second approval attempt — version is now active.
        r = await http.post(
            f"/api/v2/mandate-versions/{version_id}/approve",
            json={},
            headers=_h(cio),
        )
        assert r.status_code == 409


# ===========================================================================
# 7. Reject
# ===========================================================================


class TestReject:
    @pytest.mark.asyncio
    async def test_reject_transitions_to_rejected_keeps_previously_active(
        self, http, db
    ):
        advisor, investor_id, mandate_id = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        proposed_id = proposal.json()["version_id"]
        await http.post(
            f"/api/v2/mandate-versions/{proposed_id}/submit",
            json={},
            headers=_h(advisor),
        )

        cio = await _login(http, "cio1")
        r = await http.post(
            f"/api/v2/mandate-versions/{proposed_id}/reject",
            json={"rejection_reason": "Equity max too aggressive"},
            headers=_h(cio),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "rejected"
        assert body["rejection_reason"] == "Equity max too aggressive"

        # Previously-active version remains active.
        mandate = (
            await db.execute(select(Mandate).where(Mandate.mandate_id == mandate_id))
        ).scalar_one()
        versions = (await db.execute(select(MandateVersion))).scalars().all()
        v1 = next(v for v in versions if v.version_number == 1)
        assert v1.status == "active"
        assert mandate.active_version_id == v1.version_id

        # T1.
        ev = (
            await db.execute(
                select(T1Event).where(T1Event.event_name == MANDATE_AMENDMENT_REJECTED)
            )
        ).scalars().all()
        assert len(ev) == 1

    @pytest.mark.asyncio
    async def test_reject_requires_reason(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )
        cio = await _login(http, "cio1")
        r = await http.post(
            f"/api/v2/mandate-versions/{version_id}/reject",
            json={},  # no rejection_reason
            headers=_h(cio),
        )
        assert r.status_code == 422  # Pydantic missing-field


# ===========================================================================
# 8. Request changes
# ===========================================================================


class TestRequestChanges:
    @pytest.mark.asyncio
    async def test_request_changes_returns_to_draft_with_comments(self, http, db):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )

        cio = await _login(http, "cio1")
        r = await http.post(
            f"/api/v2/mandate-versions/{version_id}/request-changes",
            json={"comments": "Reduce equity max to 72"},
            headers=_h(cio),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "draft"
        assert body["changes_requested_comments"] == "Reduce equity max to 72"
        # version_number unchanged (per FR 12.2 §5.3).
        assert body["version_number"] == 2
        # proposed_at reset so a fresh submit re-stamps.
        assert body["proposed_at"] is None

        ev = (
            await db.execute(
                select(T1Event).where(
                    T1Event.event_name == MANDATE_AMENDMENT_CHANGES_REQUESTED
                )
            )
        ).scalars().all()
        assert len(ev) == 1

    @pytest.mark.asyncio
    async def test_propose_after_reject_uses_next_version_number(self, http):
        """Regression: rejecting v=2 leaves the slot taken; the next
        amendment must use v=3 (MAX + 1), not v=2 again — otherwise the
        unique (mandate_id, version_number) constraint trips."""
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        first = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        v2_id = first.json()["version_id"]
        assert first.json()["version_number"] == 2
        await http.post(
            f"/api/v2/mandate-versions/{v2_id}/submit",
            json={},
            headers=_h(advisor),
        )
        cio = await _login(http, "cio1")
        await http.post(
            f"/api/v2/mandate-versions/{v2_id}/reject",
            json={"rejection_reason": "no"},
            headers=_h(cio),
        )

        second = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        assert second.status_code == 201, second.text
        assert second.json()["version_number"] == 3

    @pytest.mark.asyncio
    async def test_advisor_can_resubmit_after_changes_requested(self, http):
        advisor, investor_id, _ = await _setup_investor_with_mandate(http)
        proposal = await http.post(
            f"/api/v2/investors/{investor_id}/mandate/amend",
            headers=_h(advisor),
        )
        version_id = proposal.json()["version_id"]
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )
        cio = await _login(http, "cio1")
        await http.post(
            f"/api/v2/mandate-versions/{version_id}/request-changes",
            json={"comments": "lower the equity max"},
            headers=_h(cio),
        )
        # Advisor edits + resubmits.
        await http.put(
            f"/api/v2/mandate-versions/{version_id}",
            json=_mandate_payload(equity_max_pct=72),
            headers=_h(advisor),
        )
        r = await http.post(
            f"/api/v2/mandate-versions/{version_id}/submit",
            json={},
            headers=_h(advisor),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "pending_approval"
