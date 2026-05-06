"""Cluster 4 chunk 4.3 — preferred portfolio write endpoint tests.

Pins:

- POST /preferred                           — create entry
- PUT /preferred/{entry_id}                 — modify role/rank/notes
- DELETE /preferred/{entry_id}              — delete
- POST /preferred/{rp}/{h}/reorder          — atomic cell reorder
- POST /preferred/{rp}/{h}/duplicate-from   — copy from source cell
- POST /preferred/{rp}/{h}/reset-to-default — reset cell from fixture
- POST /preferred/reset-to-default          — full reset

Plus permission gates: CIO writes; advisor + compliance + audit blocked.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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
from artha.api_v2.m2.event_names import (
    MODEL_PORTFOLIO_PREFERRED_BULK_RESET,
    PREFERRED_PORTFOLIO_CELL_DUPLICATED,
    PREFERRED_PORTFOLIO_CELL_REORDERED,
    PREFERRED_PORTFOLIO_ENTRY_CREATED,
    PREFERRED_PORTFOLIO_ENTRY_DELETED,
    PREFERRED_PORTFOLIO_ENTRY_MODIFIED,
    PREFERRED_PORTFOLIO_ENTRY_WITHOUT_MATCHING_TAG,
)
from artha.api_v2.m2.models import PreferredPortfolioEntry
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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_two_instruments(db) -> dict[str, Instrument]:
    now = datetime.now(timezone.utc)
    flexi = Instrument(
        instrument_id=str(ULID()),
        amfi_scheme_code="FLEXI",
        name="Flexi Cap Fund",
        asset_class="equity",
        vehicle_type="mutual_fund",
        sebi_category="flexi_cap",
        classification_confidence="high",
        status="active",
        source_identifier="test",
        created_at=now,
        last_modified_at=now,
        model_portfolio_tags=["aggressive_long_term", "moderate_long_term"],
        schema_version=2,
    )
    liquid = Instrument(
        instrument_id=str(ULID()),
        amfi_scheme_code="LIQUID",
        name="Liquid Fund",
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
    db.add_all([flexi, liquid])
    await db.commit()
    return {"flexi": flexi, "liquid": liquid}


# ---------------------------------------------------------------------------
# POST /preferred
# ---------------------------------------------------------------------------


class TestCreateEntry:
    @pytest.mark.asyncio
    async def test_cio_can_create(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "aggressive",
                "horizon": "long_term",
                "instrument_id": seeds["flexi"].instrument_id,
                "position_role": "core",
                "rank_within_role": 1,
                "notes": "Anchor flexi cap",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["instrument_name"] == "Flexi Cap Fund"
        assert body["position_role"] == "core"
        assert body["has_matching_tag"] is True

    @pytest.mark.asyncio
    async def test_duplicate_returns_409(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        payload = {
            "risk_profile": "aggressive",
            "horizon": "long_term",
            "instrument_id": seeds["flexi"].instrument_id,
            "position_role": "core",
            "rank_within_role": 1,
        }
        r1 = await http.post(
            "/api/v2/model-portfolio/preferred", headers=_h(token), json=payload
        )
        assert r1.status_code == 201
        r2 = await http.post(
            "/api/v2/model-portfolio/preferred", headers=_h(token), json=payload
        )
        assert r2.status_code == 409

    @pytest.mark.asyncio
    async def test_unknown_instrument_returns_404(self, http):
        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "aggressive",
                "horizon": "long_term",
                "instrument_id": "01NOPE000000000000000000",
                "position_role": "core",
                "rank_within_role": 1,
            },
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_advisor_blocked(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "advisor1")
        r = await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "aggressive",
                "horizon": "long_term",
                "instrument_id": seeds["flexi"].instrument_id,
                "position_role": "core",
                "rank_within_role": 1,
            },
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_emits_creation_event(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "aggressive",
                "horizon": "long_term",
                "instrument_id": seeds["flexi"].instrument_id,
                "position_role": "core",
                "rank_within_role": 1,
            },
        )
        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == PREFERRED_PORTFOLIO_ENTRY_CREATED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_tag_mismatch_emits_warning_event(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        # Liquid is tagged for conservative_short_term but we add it to
        # aggressive_long_term — should emit the soft-validation event.
        await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "aggressive",
                "horizon": "long_term",
                "instrument_id": seeds["liquid"].instrument_id,
                "position_role": "satellite",
                "rank_within_role": 1,
            },
        )
        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name
                        == PREFERRED_PORTFOLIO_ENTRY_WITHOUT_MATCHING_TAG
                    )
                )
            ).scalars()
        )
        assert len(events) == 1


# ---------------------------------------------------------------------------
# PUT + DELETE
# ---------------------------------------------------------------------------


class TestUpdateAndDelete:
    @pytest.mark.asyncio
    async def test_cio_can_update_role_rank_notes(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        created = (
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["flexi"].instrument_id,
                    "position_role": "core",
                    "rank_within_role": 1,
                },
            )
        ).json()

        r = await http.put(
            f"/api/v2/model-portfolio/preferred/{created['entry_id']}",
            headers=_h(token),
            json={
                "position_role": "satellite",
                "rank_within_role": 5,
                "notes": "Demoted to satellite after review",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["position_role"] == "satellite"
        assert body["rank_within_role"] == 5
        assert "Demoted" in body["notes"]

    @pytest.mark.asyncio
    async def test_emits_modified_event(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        created = (
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["flexi"].instrument_id,
                    "position_role": "core",
                    "rank_within_role": 1,
                },
            )
        ).json()

        await http.put(
            f"/api/v2/model-portfolio/preferred/{created['entry_id']}",
            headers=_h(token),
            json={"position_role": "satellite"},
        )
        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == PREFERRED_PORTFOLIO_ENTRY_MODIFIED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_delete_returns_204_and_emits_event(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        created = (
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["flexi"].instrument_id,
                    "position_role": "core",
                    "rank_within_role": 1,
                },
            )
        ).json()

        r = await http.delete(
            f"/api/v2/model-portfolio/preferred/{created['entry_id']}",
            headers=_h(token),
        )
        assert r.status_code == 204

        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == PREFERRED_PORTFOLIO_ENTRY_DELETED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_delete_unknown_returns_404(self, http):
        token = await _login(http, "cio1")
        r = await http.delete(
            "/api/v2/model-portfolio/preferred/01NOPE000000000000000000",
            headers=_h(token),
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_advisor_blocked_from_update(self, http, db):
        seeds = await _seed_two_instruments(db)
        cio_token = await _login(http, "cio1")
        created = (
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(cio_token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["flexi"].instrument_id,
                    "position_role": "core",
                    "rank_within_role": 1,
                },
            )
        ).json()

        adv_token = await _login(http, "advisor1")
        r = await http.put(
            f"/api/v2/model-portfolio/preferred/{created['entry_id']}",
            headers=_h(adv_token),
            json={"position_role": "satellite"},
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


class TestReorder:
    @pytest.mark.asyncio
    async def test_reorders_role_and_rank_atomically(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        e1 = (
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["flexi"].instrument_id,
                    "position_role": "core",
                    "rank_within_role": 1,
                },
            )
        ).json()
        e2 = (
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["liquid"].instrument_id,
                    "position_role": "satellite",
                    "rank_within_role": 1,
                },
            )
        ).json()

        # Promote e2 to core rank 1, demote e1 to satellite rank 1.
        r = await http.post(
            "/api/v2/model-portfolio/preferred/aggressive/long_term/reorder",
            headers=_h(token),
            json={
                "items": [
                    {
                        "entry_id": e2["entry_id"],
                        "position_role": "core",
                        "rank_within_role": 1,
                    },
                    {
                        "entry_id": e1["entry_id"],
                        "position_role": "satellite",
                        "rank_within_role": 1,
                    },
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["affected_count"] == 2

        # Verify state
        cell = (
            await http.get(
                "/api/v2/model-portfolio/preferred/aggressive/long_term",
                headers=_h(token),
            )
        ).json()
        assert len(cell["core"]) == 1
        assert cell["core"][0]["instrument_name"] == "Liquid Fund"
        assert len(cell["satellite"]) == 1
        assert cell["satellite"][0]["instrument_name"] == "Flexi Cap Fund"

    @pytest.mark.asyncio
    async def test_emits_reorder_event(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        e1 = (
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["flexi"].instrument_id,
                    "position_role": "core",
                    "rank_within_role": 1,
                },
            )
        ).json()

        await http.post(
            "/api/v2/model-portfolio/preferred/aggressive/long_term/reorder",
            headers=_h(token),
            json={
                "items": [
                    {
                        "entry_id": e1["entry_id"],
                        "position_role": "satellite",
                        "rank_within_role": 1,
                    }
                ],
            },
        )
        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == PREFERRED_PORTFOLIO_CELL_REORDERED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_advisor_blocked(self, http, db):
        token = await _login(http, "advisor1")
        r = await http.post(
            "/api/v2/model-portfolio/preferred/aggressive/long_term/reorder",
            headers=_h(token),
            json={
                "items": [
                    {
                        "entry_id": "01NOPE",
                        "position_role": "core",
                        "rank_within_role": 1,
                    }
                ],
            },
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Duplicate from
# ---------------------------------------------------------------------------


class TestDuplicateCell:
    @pytest.mark.asyncio
    async def test_duplicates_matching_tagged_entries(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        # Create a moderate_long_term entry for flexi (it's tagged for that cell).
        await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "moderate",
                "horizon": "long_term",
                "instrument_id": seeds["flexi"].instrument_id,
                "position_role": "core",
                "rank_within_role": 1,
            },
        )

        # Duplicate moderate_long_term → aggressive_long_term. Flexi is also
        # tagged for aggressive_long_term so the entry should copy.
        r = await http.post(
            "/api/v2/model-portfolio/preferred/aggressive/long_term/duplicate-from",
            headers=_h(token),
            json={
                "source_risk_profile": "moderate",
                "source_horizon": "long_term",
                "skip_existing": True,
                "only_matching_tags": True,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["affected_count"] == 1

        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == PREFERRED_PORTFOLIO_CELL_DUPLICATED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_skips_when_only_matching_tags_excludes_target(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "cio1")
        # Liquid is tagged for moderate_short_term + conservative_short_term
        # only. Add it to moderate_short_term, then try to duplicate to
        # aggressive_long_term — should skip because tag doesn't match.
        await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "moderate",
                "horizon": "short_term",
                "instrument_id": seeds["liquid"].instrument_id,
                "position_role": "core",
                "rank_within_role": 1,
            },
        )
        r = await http.post(
            "/api/v2/model-portfolio/preferred/aggressive/long_term/duplicate-from",
            headers=_h(token),
            json={
                "source_risk_profile": "moderate",
                "source_horizon": "short_term",
                "skip_existing": True,
                "only_matching_tags": True,
            },
        )
        body = r.json()
        assert body["affected_count"] == 0
        assert body["skipped_count"] == 1

    @pytest.mark.asyncio
    async def test_source_equals_target_returns_400(self, http):
        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/preferred/aggressive/long_term/duplicate-from",
            headers=_h(token),
            json={
                "source_risk_profile": "aggressive",
                "source_horizon": "long_term",
            },
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Cell reset / full reset
# ---------------------------------------------------------------------------


class TestCellResetAndBulkReset:
    @pytest.mark.asyncio
    async def test_reset_cell_loads_fixture(self, http, db, monkeypatch):
        # Point the loader at a tiny fixture in a tempfile so the test
        # doesn't depend on the repo's main fixture having matching
        # AMFI codes.
        seeds = await _seed_two_instruments(db)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            json.dump(
                {
                    "preferred_portfolio_entries": [
                        {
                            "risk_profile": "aggressive",
                            "horizon": "long_term",
                            "instrument_lookup": {
                                "external_identifier_type": "amfi_code",
                                "external_identifier_value": "FLEXI",
                            },
                            "position_role": "core",
                            "rank_within_role": 1,
                            "notes": "Default flexi cap",
                        }
                    ]
                },
                fh,
            )
            tmp_path = Path(fh.name)
        monkeypatch.setattr(
            settings,
            "samriddhi_default_model_portfolio_path",
            str(tmp_path),
        )

        try:
            token = await _login(http, "cio1")
            # Pre-populate the cell with a different entry to be wiped.
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["liquid"].instrument_id,
                    "position_role": "satellite",
                    "rank_within_role": 1,
                },
            )

            r = await http.post(
                "/api/v2/model-portfolio/preferred/aggressive/long_term/reset-to-default",
                headers=_h(token),
            )
            assert r.status_code == 200, r.text

            # Re-read the cell — only the fixture entry should remain.
            cell = (
                await http.get(
                    "/api/v2/model-portfolio/preferred/aggressive/long_term",
                    headers=_h(token),
                )
            ).json()
            assert len(cell["core"]) + len(cell["satellite"]) == 1
            assert cell["core"][0]["instrument_name"] == "Flexi Cap Fund"
        finally:
            tmp_path.unlink()

    @pytest.mark.asyncio
    async def test_reset_all_emits_bulk_event(self, http, db, monkeypatch):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            json.dump({"preferred_portfolio_entries": []}, fh)
            tmp_path = Path(fh.name)
        monkeypatch.setattr(
            settings,
            "samriddhi_default_model_portfolio_path",
            str(tmp_path),
        )

        try:
            seeds = await _seed_two_instruments(db)
            token = await _login(http, "cio1")
            # Seed a couple of entries.
            await http.post(
                "/api/v2/model-portfolio/preferred",
                headers=_h(token),
                json={
                    "risk_profile": "aggressive",
                    "horizon": "long_term",
                    "instrument_id": seeds["flexi"].instrument_id,
                    "position_role": "core",
                    "rank_within_role": 1,
                },
            )
            await http.post(
                "/api/v2/model-portfolio/preferred/reset-to-default",
                headers=_h(token),
            )

            events = list(
                (
                    await db.execute(
                        select(T1Event).where(
                            T1Event.event_name == MODEL_PORTFOLIO_PREFERRED_BULK_RESET
                        )
                    )
                ).scalars()
            )
            assert len(events) == 1

            # Verify all entries are gone (fixture is empty).
            remaining = list(
                (await db.execute(select(PreferredPortfolioEntry))).scalars()
            )
            assert remaining == []
        finally:
            tmp_path.unlink()


# ---------------------------------------------------------------------------
# Permission gates summary
# ---------------------------------------------------------------------------


class TestPermissionGatesSummary:
    @pytest.mark.asyncio
    async def test_compliance_blocked_from_writes(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "compliance1")
        r = await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "aggressive",
                "horizon": "long_term",
                "instrument_id": seeds["flexi"].instrument_id,
                "position_role": "core",
                "rank_within_role": 1,
            },
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_audit_blocked_from_writes(self, http, db):
        seeds = await _seed_two_instruments(db)
        token = await _login(http, "audit1")
        r = await http.post(
            "/api/v2/model-portfolio/preferred",
            headers=_h(token),
            json={
                "risk_profile": "aggressive",
                "horizon": "long_term",
                "instrument_id": seeds["flexi"].instrument_id,
                "position_role": "core",
                "rank_within_role": 1,
            },
        )
        assert r.status_code == 403
