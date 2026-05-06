"""Cluster 4 chunk 4.2 — tag editing write endpoint tests.

Pins:

- ``PUT /instruments/{id}/tags`` — single-instrument tag replace
- ``POST /instruments/tags/bulk-add`` — add one tag to many instruments
- ``POST /instruments/tags/bulk-remove`` — remove one tag from many
- ``POST /instruments/tags/bulk-replace`` — overwrite tag sets
- ``POST /instruments/tags/reset-to-default`` — reset to FR 13.3 defaults
- Permission gates: CIO writes; advisor + compliance + audit blocked
- Validation: unknown tag values return 400
- T1 telemetry: emits the appropriate change events
"""

from __future__ import annotations

from datetime import datetime, timezone

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
    INSTRUMENT_TAGS_CHANGED,
    MODEL_PORTFOLIO_TAGS_BULK_RESET,
)
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


async def _seed_three_instruments(db) -> list[Instrument]:
    now = datetime.now(timezone.utc)
    rows = [
        Instrument(
            instrument_id=str(ULID()),
            amfi_scheme_code=f"FUND_{i}",
            name=f"Fund {i}",
            asset_class="equity",
            vehicle_type="mutual_fund",
            sebi_category="large_cap",
            classification_confidence="high",
            status="active",
            source_identifier="test",
            created_at=now,
            last_modified_at=now,
            model_portfolio_tags=[],
            schema_version=2,
        )
        for i in range(1, 4)
    ]
    db.add_all(rows)
    await db.commit()
    return rows


# ---------------------------------------------------------------------------
# PUT /instruments/{id}/tags
# ---------------------------------------------------------------------------


class TestSingleInstrumentTagReplace:
    @pytest.mark.asyncio
    async def test_cio_can_replace_tags(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "cio1")
        r = await http.put(
            f"/api/v2/model-portfolio/instruments/{rows[0].instrument_id}/tags",
            headers=_h(token),
            json={"tags": ["aggressive_long_term", "moderate_long_term"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Tags returned in matrix-row order regardless of input order.
        assert body["model_portfolio_tags"] == [
            "aggressive_long_term",
            "moderate_long_term",
        ]
        assert body["model_portfolio_tags_modified_by"] == "cio1"

    @pytest.mark.asyncio
    async def test_replace_with_empty_set_clears_tags(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "cio1")
        r = await http.put(
            f"/api/v2/model-portfolio/instruments/{rows[0].instrument_id}/tags",
            headers=_h(token),
            json={"tags": []},
        )
        assert r.status_code == 200
        assert r.json()["model_portfolio_tags"] == []

    @pytest.mark.asyncio
    async def test_invalid_tag_returns_400(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "cio1")
        r = await http.put(
            f"/api/v2/model-portfolio/instruments/{rows[0].instrument_id}/tags",
            headers=_h(token),
            json={"tags": ["very_aggressive_forever"]},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_instrument_returns_404(self, http, db):
        token = await _login(http, "cio1")
        r = await http.put(
            "/api/v2/model-portfolio/instruments/01NOPE000000000000000000/tags",
            headers=_h(token),
            json={"tags": ["aggressive_long_term"]},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_advisor_blocked(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "advisor1")
        r = await http.put(
            f"/api/v2/model-portfolio/instruments/{rows[0].instrument_id}/tags",
            headers=_h(token),
            json={"tags": ["aggressive_long_term"]},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_emits_t1_event(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "cio1")
        await http.put(
            f"/api/v2/model-portfolio/instruments/{rows[0].instrument_id}/tags",
            headers=_h(token),
            json={"tags": ["aggressive_long_term"]},
        )
        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == INSTRUMENT_TAGS_CHANGED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1
        assert events[0].payload["change_type"] == "single"


# ---------------------------------------------------------------------------
# Bulk add
# ---------------------------------------------------------------------------


class TestBulkAddTag:
    @pytest.mark.asyncio
    async def test_adds_to_all_selected(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/bulk-add",
            headers=_h(token),
            json={
                "tag": "aggressive_long_term",
                "instrument_ids": [r.instrument_id for r in rows],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["affected_count"] == 3
        assert body["operation"] == "bulk_add"

    @pytest.mark.asyncio
    async def test_skips_instruments_already_tagged(self, http, db):
        rows = await _seed_three_instruments(db)
        rows[0].model_portfolio_tags = ["aggressive_long_term"]
        await db.commit()

        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/bulk-add",
            headers=_h(token),
            json={
                "tag": "aggressive_long_term",
                "instrument_ids": [r.instrument_id for r in rows],
            },
        )
        body = r.json()
        assert body["affected_count"] == 2
        assert body["skipped_count"] == 1

    @pytest.mark.asyncio
    async def test_advisor_blocked(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "advisor1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/bulk-add",
            headers=_h(token),
            json={
                "tag": "aggressive_long_term",
                "instrument_ids": [rows[0].instrument_id],
            },
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_tag_400(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/bulk-add",
            headers=_h(token),
            json={
                "tag": "fake_cell",
                "instrument_ids": [rows[0].instrument_id],
            },
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Bulk remove
# ---------------------------------------------------------------------------


class TestBulkRemoveTag:
    @pytest.mark.asyncio
    async def test_removes_from_tagged_only(self, http, db):
        rows = await _seed_three_instruments(db)
        rows[0].model_portfolio_tags = ["aggressive_long_term", "moderate_long_term"]
        rows[1].model_portfolio_tags = ["aggressive_long_term"]
        # rows[2] has no tags.
        await db.commit()

        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/bulk-remove",
            headers=_h(token),
            json={
                "tag": "aggressive_long_term",
                "instrument_ids": [r.instrument_id for r in rows],
            },
        )
        body = r.json()
        assert body["affected_count"] == 2
        assert body["skipped_count"] == 1


# ---------------------------------------------------------------------------
# Bulk replace
# ---------------------------------------------------------------------------


class TestBulkReplaceTags:
    @pytest.mark.asyncio
    async def test_overwrites_tag_sets(self, http, db):
        rows = await _seed_three_instruments(db)
        rows[0].model_portfolio_tags = ["aggressive_long_term"]
        rows[1].model_portfolio_tags = ["moderate_short_term", "conservative_short_term"]
        await db.commit()

        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/bulk-replace",
            headers=_h(token),
            json={
                "tags": ["moderate_long_term"],
                "instrument_ids": [r.instrument_id for r in rows],
            },
        )
        body = r.json()
        # All 3 instruments get overwritten with the new set.
        assert body["affected_count"] == 3

        # Refresh cached identity-map rows so we see the endpoint's
        # committed state.
        for row in rows:
            await db.refresh(row)
        for row in rows:
            assert row.model_portfolio_tags == ["moderate_long_term"]

    @pytest.mark.asyncio
    async def test_skips_instruments_with_identical_set(self, http, db):
        rows = await _seed_three_instruments(db)
        rows[0].model_portfolio_tags = ["moderate_long_term"]
        await db.commit()

        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/bulk-replace",
            headers=_h(token),
            json={
                "tags": ["moderate_long_term"],
                "instrument_ids": [rows[0].instrument_id, rows[1].instrument_id],
            },
        )
        body = r.json()
        # rows[0] already has the same set → skipped; rows[1] gets it → affected.
        assert body["affected_count"] == 1
        assert body["skipped_count"] == 1


# ---------------------------------------------------------------------------
# Reset to default
# ---------------------------------------------------------------------------


class TestResetTagsToDefault:
    @pytest.mark.asyncio
    async def test_resets_filtered_subset(self, http, db):
        rows = await _seed_three_instruments(db)
        # Custom CIO tags that we'll wipe.
        rows[0].model_portfolio_tags = ["conservative_short_term"]
        await db.commit()

        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/reset-to-default",
            headers=_h(token),
            json={"instrument_ids": [rows[0].instrument_id]},
        )
        body = r.json()
        assert body["affected_count"] == 1

        # Refresh the cached object explicitly so we see the endpoint's
        # committed state (otherwise the identity map serves stale tags).
        await db.refresh(rows[0])
        # large_cap default → moderate_medium_term, moderate_long_term,
        # aggressive_medium_term, aggressive_long_term.
        assert "aggressive_long_term" in rows[0].model_portfolio_tags
        assert "moderate_long_term" in rows[0].model_portfolio_tags
        assert "conservative_short_term" not in rows[0].model_portfolio_tags

    @pytest.mark.asyncio
    async def test_resets_all_when_empty_list(self, http, db):
        rows = await _seed_three_instruments(db)
        for r in rows:
            r.model_portfolio_tags = ["conservative_short_term"]
        await db.commit()

        token = await _login(http, "cio1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/reset-to-default",
            headers=_h(token),
            json={"instrument_ids": []},
        )
        body = r.json()
        assert body["affected_count"] == 3

    @pytest.mark.asyncio
    async def test_emits_bulk_reset_event(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "cio1")
        await http.post(
            "/api/v2/model-portfolio/instruments/tags/reset-to-default",
            headers=_h(token),
            json={"instrument_ids": [rows[0].instrument_id]},
        )
        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == MODEL_PORTFOLIO_TAGS_BULK_RESET
                    )
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_advisor_blocked(self, http, db):
        rows = await _seed_three_instruments(db)
        token = await _login(http, "advisor1")
        r = await http.post(
            "/api/v2/model-portfolio/instruments/tags/reset-to-default",
            headers=_h(token),
            json={"instrument_ids": [rows[0].instrument_id]},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_compliance_and_audit_blocked(self, http, db):
        rows = await _seed_three_instruments(db)
        for role in ("compliance1", "audit1"):
            token = await _login(http, role)
            r = await http.post(
                "/api/v2/model-portfolio/instruments/tags/reset-to-default",
                headers=_h(token),
                json={"instrument_ids": [rows[0].instrument_id]},
            )
            assert r.status_code == 403, f"{role} should not have write permission"
