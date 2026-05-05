"""Cluster 3 chunk 3.4 — Snapshot machinery tests.

Pins:

- create_snapshot captures every canonical-entity table.
- content_hash is deterministic across re-serialisation.
- verify_snapshot flips verified_status to ``verified`` on hash match,
  ``verification_failed`` on drift.
- list/get filter by trigger_type + verified_status.
- diff_snapshots produces a per-table added/removed/changed structure.
- Endpoint permission gates (audit can write, CIO + compliance read only).
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
from artha.api_v2.d0.event_names import (
    SNAPSHOT_CREATED,
    SNAPSHOT_VERIFICATION_FAILED,
)
from artha.api_v2.d0.models import Snapshot
from artha.api_v2.d0.snapshot import service as snapshot_service
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


async def _seed_a_few_instruments(db) -> None:
    adapter = JSONFixtureAdapter(
        fixture_name="snap-test",
        fixture={
            "instruments": [
                {
                    "isin": "INF1",
                    "name": "Test Equity Fund",
                    "sebi_category": "large_cap",
                    "amfi_scheme_code": "AAA1",
                },
                {
                    "isin": "INF2",
                    "name": "Test Liquid Fund",
                    "sebi_category": "liquid",
                    "amfi_scheme_code": "AAA2",
                },
            ]
        },
    )
    await adapter.run(db)
    await db.commit()


# ---------------------------------------------------------------------------
# Service: create + capture
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_creates_snapshot_with_every_entity_table(self, db):
        await _seed_a_few_instruments(db)
        snap = await snapshot_service.create_snapshot(
            db, created_by="audit1", trigger_type="manual"
        )
        await db.commit()

        # entity_counts must include every freshness-tracked table.
        from artha.api_v2.d0 import freshness_service  # local to keep import cheap

        for table in freshness_service._TABLE_TO_MODEL:  # noqa: SLF001
            assert table in snap.entity_counts

        # Two instruments seeded, others empty.
        assert snap.entity_counts["instruments"] == 2
        assert snap.entity_counts["investors"] == 0
        assert snap.serialised_payload_size_bytes > 0
        assert len(snap.content_hash) == 64  # sha256 hex

    @pytest.mark.asyncio
    async def test_emits_snapshot_created_t1_event(self, db):
        await snapshot_service.create_snapshot(
            db, created_by="audit1"
        )
        await db.commit()

        events = list(
            (
                await db.execute(
                    select(T1Event).where(T1Event.event_name == SNAPSHOT_CREATED)
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_captured_payload_is_deterministic(self, db):
        await _seed_a_few_instruments(db)
        s1 = await snapshot_service.create_snapshot(db, created_by="audit1")
        s2 = await snapshot_service.create_snapshot(db, created_by="audit1")
        await db.commit()
        # Bit-identical payload → identical hash.
        assert s1.content_hash == s2.content_hash

    @pytest.mark.asyncio
    async def test_associated_adapter_run_ids_collected(self, db):
        await _seed_a_few_instruments(db)
        snap = await snapshot_service.create_snapshot(db, created_by="audit1")
        await db.commit()
        assert len(snap.associated_adapter_run_ids) == 1


# ---------------------------------------------------------------------------
# Service: verify
# ---------------------------------------------------------------------------


class TestVerify:
    @pytest.mark.asyncio
    async def test_verifies_clean_snapshot_to_verified(self, db):
        snap = await snapshot_service.create_snapshot(
            db, created_by="audit1"
        )
        await db.commit()

        result = await snapshot_service.verify_snapshot(
            db, snapshot_id=snap.snapshot_id
        )
        await db.commit()
        assert result.verified_status == "verified"
        assert result.verified_at is not None

    @pytest.mark.asyncio
    async def test_drifted_payload_flips_to_verification_failed(self, db):
        snap = await snapshot_service.create_snapshot(
            db, created_by="audit1"
        )
        # Tamper: mutate the stored content_hash.
        snap.content_hash = "0" * 64
        await db.commit()

        result = await snapshot_service.verify_snapshot(
            db, snapshot_id=snap.snapshot_id
        )
        await db.commit()
        assert result.verified_status == "verification_failed"

        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == SNAPSHOT_VERIFICATION_FAILED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_unknown_snapshot_id_raises(self, db):
        with pytest.raises(KeyError):
            await snapshot_service.verify_snapshot(
                db, snapshot_id="01NOTHING00000000000000000"
            )


# ---------------------------------------------------------------------------
# Service: list filtering
# ---------------------------------------------------------------------------


class TestListFilters:
    @pytest.mark.asyncio
    async def test_filter_by_trigger_type(self, db):
        await snapshot_service.create_snapshot(
            db, created_by="audit1", trigger_type="manual"
        )
        await snapshot_service.create_snapshot(
            db, created_by="audit1", trigger_type="scheduled"
        )
        await db.commit()

        rows, total = await snapshot_service.list_snapshots(
            db, trigger_type="manual"
        )
        assert total == 1


# ---------------------------------------------------------------------------
# Service: diff
# ---------------------------------------------------------------------------


class TestDiff:
    @pytest.mark.asyncio
    async def test_diff_detects_added_removed_changed(self, db):
        # Snapshot A: 2 instruments
        await _seed_a_few_instruments(db)
        snap_a = await snapshot_service.create_snapshot(
            db, created_by="audit1", description="A"
        )
        await db.commit()

        # Mutate state: rename one, drop one (simulated by deleting).
        from artha.api_v2.d0.instruments.models import Instrument

        rows = list((await db.execute(select(Instrument))).scalars())
        rows[0].name = "Test Equity Fund — RENAMED"
        # Delete the second instrument.
        await db.delete(rows[1])
        await db.commit()

        # Add a brand-new instrument.
        adapter = JSONFixtureAdapter(
            fixture_name="snap-test",
            fixture={
                "instruments": [
                    {
                        "isin": "INF3",
                        "name": "New Mid Cap Fund",
                        "sebi_category": "mid_cap",
                        "amfi_scheme_code": "AAA3",
                    }
                ]
            },
        )
        await adapter.run(db)
        await db.commit()

        snap_b = await snapshot_service.create_snapshot(
            db, created_by="audit1", description="B"
        )
        await db.commit()

        diff = await snapshot_service.diff_snapshots(
            db,
            snapshot_a_id=snap_a.snapshot_id,
            snapshot_b_id=snap_b.snapshot_id,
        )
        await db.commit()

        instruments_diff = diff["per_table"]["instruments"]
        assert len(instruments_diff["added"]) == 1
        assert instruments_diff["added"][0]["name"] == "New Mid Cap Fund"
        assert len(instruments_diff["removed"]) == 1
        assert len(instruments_diff["changed"]) == 1
        assert (
            "RENAMED" in instruments_diff["changed"][0]["after"]["name"]
        )

        # Summary mirrors the per-table counts.
        assert diff["summary"]["instruments"] == {
            "added": 1,
            "removed": 1,
            "changed": 1,
        }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class TestSnapshotEndpoints:
    @pytest.mark.asyncio
    async def test_audit_can_create_snapshot(self, http):
        token = await _login(http, "audit1")
        r = await http.post(
            "/api/v2/admin/snapshots",
            headers=_h(token),
            json={"description": "first manual snap"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["trigger_type"] == "manual"
        assert body["verified_status"] == "never_verified"

    @pytest.mark.asyncio
    async def test_audit_can_list_snapshots(self, http):
        token = await _login(http, "audit1")
        await http.post(
            "/api/v2/admin/snapshots",
            headers=_h(token),
            json={"description": "snap"},
        )
        r = await http.get(
            "/api/v2/admin/snapshots", headers=_h(token)
        )
        body = r.json()
        assert body["total"] == 1

    @pytest.mark.asyncio
    async def test_audit_can_verify_snapshot(self, http):
        token = await _login(http, "audit1")
        created = await http.post(
            "/api/v2/admin/snapshots",
            headers=_h(token),
            json={"description": "to verify"},
        )
        snap_id = created.json()["snapshot_id"]

        r = await http.post(
            f"/api/v2/admin/snapshots/{snap_id}/verify", headers=_h(token)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verified_status"] == "verified"
        assert body["stored_hash"] == body["recomputed_hash"]

    @pytest.mark.asyncio
    async def test_diff_endpoint(self, http):
        token = await _login(http, "audit1")
        a = (
            await http.post(
                "/api/v2/admin/snapshots",
                headers=_h(token),
                json={"description": "A"},
            )
        ).json()
        b = (
            await http.post(
                "/api/v2/admin/snapshots",
                headers=_h(token),
                json={"description": "B"},
            )
        ).json()
        r = await http.get(
            f"/api/v2/admin/snapshots-diff?a={a['snapshot_id']}&b={b['snapshot_id']}",
            headers=_h(token),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["snapshot_a_id"] == a["snapshot_id"]
        # Empty DB → empty diffs across the board.
        for table, counts in body["summary"].items():
            assert counts == {"added": 0, "removed": 0, "changed": 0}

    @pytest.mark.asyncio
    async def test_404_on_unknown_snapshot(self, http):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/snapshots/01NOTHING00000000000000000",
            headers=_h(token),
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_cio_can_read_but_not_create(self, http):
        token = await _login(http, "cio1")
        r_list = await http.get(
            "/api/v2/admin/snapshots", headers=_h(token)
        )
        assert r_list.status_code == 200

        r_create = await http.post(
            "/api/v2/admin/snapshots",
            headers=_h(token),
            json={"description": "cio attempt"},
        )
        assert r_create.status_code == 403

    @pytest.mark.asyncio
    async def test_compliance_can_read_but_not_verify(self, http):
        token = await _login(http, "compliance1")
        # Compliance can list (D0_ADMIN_READ).
        r_list = await http.get(
            "/api/v2/admin/snapshots", headers=_h(token)
        )
        assert r_list.status_code == 200

        # Verify requires D0_ADMIN_WRITE.
        r_verify = await http.post(
            "/api/v2/admin/snapshots/01ANYTHING000000000000000/verify",
            headers=_h(token),
        )
        assert r_verify.status_code == 403

    @pytest.mark.asyncio
    async def test_advisor_blocked(self, http):
        token = await _login(http, "advisor1")
        r = await http.get(
            "/api/v2/admin/snapshots", headers=_h(token)
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Snapshot row write integrity
# ---------------------------------------------------------------------------


class TestSnapshotRowIntegrity:
    @pytest.mark.asyncio
    async def test_serialised_payload_carries_all_tables(self, db):
        snap = await snapshot_service.create_snapshot(
            db, created_by="audit1"
        )
        await db.commit()

        from artha.api_v2.d0 import freshness_service

        payload_keys = set(snap.serialised_payload.keys())
        for table in freshness_service._TABLE_TO_MODEL:  # noqa: SLF001
            assert table in payload_keys

    @pytest.mark.asyncio
    async def test_verify_after_no_changes_succeeds(self, db):
        snap = await snapshot_service.create_snapshot(
            db, created_by="audit1"
        )
        await db.commit()
        result = await snapshot_service.verify_snapshot(
            db, snapshot_id=snap.snapshot_id
        )
        await db.commit()
        # The row exists in the snapshot table.
        rows = list((await db.execute(select(Snapshot))).scalars())
        assert len(rows) == 1
        assert result.verified_status == "verified"
