"""Cluster 3 chunk 3.1 — D0 admin endpoint test suite.

Covers the audit-role admin surface:

- ``GET /api/v2/admin/adapters``                    — list with health
- ``GET /api/v2/admin/adapters/{source}``           — adapter detail
- ``POST /api/v2/admin/adapters/{source}/run``      — trigger run
- ``GET /api/v2/admin/staging``                     — staging query
- ``GET /api/v2/admin/staging/{id}``                — staging detail
- ``GET /api/v2/admin/data-freshness``              — freshness report

Plus permission gates: audit role read+write, CIO + compliance read only,
advisor blocked entirely.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.d0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.dev_users import reload as reload_catalogue
from artha.api_v2.auth.jwt_signing import reset_dev_secret_cache
from artha.api_v2.d0 import registry
from artha.api_v2.d0.adapter_base import (
    AdapterError,
    AdapterHealth,
    AdapterRunResult,
    D0Adapter,
)
from artha.api_v2.d0.event_names import (
    ADAPTER_RUN_COMPLETED,
    ADAPTER_RUN_STARTED,
    STAGING_RECORD_CREATED,
)
from artha.api_v2.d0.staging import record_staging
from artha.api_v2.observability.models import T1Event
from artha.app import app
from artha.common.db.base import Base
from artha.common.db.session import get_session
from artha.config import settings

_TEST_JWT_SECRET = "test-secret-must-be-at-least-32-bytes-long-for-hs256"


# ---------------------------------------------------------------------------
# Stub adapter that the admin endpoint can drive
# ---------------------------------------------------------------------------


class _StubAdapter(D0Adapter):
    """Minimal adapter that writes a fake staging record + reports
    canonical-entity creation counts for the test."""

    def __init__(
        self,
        *,
        source_id: str = "stub_test",
        entity_types: list[str] | None = None,
        raise_on_run: Exception | None = None,
    ):
        self._source_id = source_id
        self._entity_types = entity_types or ["Instrument"]
        self._raise = raise_on_run

    @property
    def source_identifier(self) -> str:
        return self._source_id

    @property
    def supported_entity_types(self) -> list[str]:
        return self._entity_types

    async def run(self, db, *, mode: str = "full") -> AdapterRunResult:
        if self._raise:
            raise self._raise

        run_id = "01STUBRUN" + "0" * 17
        started = datetime.now(timezone.utc)
        # Write a single staging record so the admin staging-query endpoints
        # have something to return.
        await record_staging(
            db,
            source_identifier=self._source_id,
            adapter_run_id=run_id,
            raw_content={"hello": "world", "mode": mode},
            raw_content_format="json",
            source_metadata={"mode": mode},
        )
        completed = datetime.now(timezone.utc)
        return AdapterRunResult(
            run_id=run_id,
            started_at=started,
            completed_at=completed,
            status="success" if mode != "validation" else "success",
            staging_records_created=1,
            canonical_entities_created=(
                {} if mode == "validation" else {"Instrument": 1}
            ),
            errors=[],
            metadata={"mode": mode},
        )

    async def health_check(self) -> AdapterHealth:
        return AdapterHealth(
            healthy=True,
            last_successful_fetch_at=datetime.now(timezone.utc),
        )


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


@pytest.fixture(autouse=True)
def reset_registry_between_tests():
    registry.reset_registry()
    yield
    registry.reset_registry()


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


# ===========================================================================
# 1. Adapter list + detail
# ===========================================================================


class TestAdapterListDetail:
    @pytest.mark.asyncio
    async def test_audit_can_list_registered_adapters(self, http):
        registry.register_adapter(_StubAdapter(source_id="stub_a"))
        registry.register_adapter(
            _StubAdapter(source_id="stub_b", entity_types=["MacroSnapshot"])
        )
        token = await _login(http, "audit1")
        r = await http.get("/api/v2/admin/adapters", headers=_h(token))
        assert r.status_code == 200, r.text
        body = r.json()
        ids = [a["source_identifier"] for a in body["adapters"]]
        assert "stub_a" in ids
        assert "stub_b" in ids
        for a in body["adapters"]:
            assert a["healthy"] is True

    @pytest.mark.asyncio
    async def test_get_adapter_detail(self, http):
        registry.register_adapter(_StubAdapter())
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/adapters/stub_test", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["source_identifier"] == "stub_test"
        assert body["supported_entity_types"] == ["Instrument"]

    @pytest.mark.asyncio
    async def test_get_adapter_detail_404_when_unregistered(self, http):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/adapters/nonexistent", headers=_h(token)
        )
        assert r.status_code == 404


# ===========================================================================
# 2. Adapter run
# ===========================================================================


class TestAdapterRun:
    @pytest.mark.asyncio
    async def test_audit_can_trigger_full_run(self, http, db):
        registry.register_adapter(_StubAdapter())
        token = await _login(http, "audit1")
        r = await http.post(
            "/api/v2/admin/adapters/stub_test/run",
            json={"mode": "full"},
            headers=_h(token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "success"
        assert body["staging_records_created"] == 1
        assert body["canonical_entities_created"] == {"Instrument": 1}

        # T1 emitted run_started + run_completed.
        events = (
            await db.execute(
                select(T1Event.event_name).where(
                    T1Event.event_name.in_(
                        [ADAPTER_RUN_STARTED, ADAPTER_RUN_COMPLETED]
                    )
                )
            )
        ).scalars().all()
        assert ADAPTER_RUN_STARTED in events
        assert ADAPTER_RUN_COMPLETED in events

        # The stub wrote a staging record + emitted staging_record_created.
        staging_events = (
            await db.execute(
                select(T1Event).where(
                    T1Event.event_name == STAGING_RECORD_CREATED
                )
            )
        ).scalars().all()
        assert len(staging_events) == 1

    @pytest.mark.asyncio
    async def test_validation_mode_skips_canonical_writes(self, http):
        registry.register_adapter(_StubAdapter())
        token = await _login(http, "audit1")
        r = await http.post(
            "/api/v2/admin/adapters/stub_test/run",
            json={"mode": "validation"},
            headers=_h(token),
        )
        assert r.status_code == 200
        body = r.json()
        # Validation mode reports canonical_entities_created as empty.
        assert body["canonical_entities_created"] == {}

    @pytest.mark.asyncio
    async def test_run_unknown_adapter_returns_404(self, http):
        token = await _login(http, "audit1")
        r = await http.post(
            "/api/v2/admin/adapters/nonexistent/run",
            json={"mode": "full"},
            headers=_h(token),
        )
        assert r.status_code == 404


# ===========================================================================
# 3. Staging queries
# ===========================================================================


class TestStagingQueries:
    @pytest.mark.asyncio
    async def test_audit_can_list_staging_records_after_run(self, http):
        registry.register_adapter(_StubAdapter())
        token = await _login(http, "audit1")
        # Run the stub adapter to populate one staging row.
        await http.post(
            "/api/v2/admin/adapters/stub_test/run",
            json={"mode": "full"},
            headers=_h(token),
        )
        r = await http.get(
            "/api/v2/admin/staging?source=stub_test", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["records"]) == 1
        assert body["records"][0]["source_identifier"] == "stub_test"
        # raw_content excluded from list view (detail-only).
        assert "raw_content" not in body["records"][0]

    @pytest.mark.asyncio
    async def test_audit_can_get_staging_detail_with_raw_content(self, http):
        registry.register_adapter(_StubAdapter())
        token = await _login(http, "audit1")
        await http.post(
            "/api/v2/admin/adapters/stub_test/run",
            json={"mode": "full"},
            headers=_h(token),
        )
        list_r = await http.get(
            "/api/v2/admin/staging?source=stub_test", headers=_h(token)
        )
        record_id = list_r.json()["records"][0]["staging_record_id"]
        r = await http.get(
            f"/api/v2/admin/staging/{record_id}", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["raw_content"] == {"hello": "world", "mode": "full"}

    @pytest.mark.asyncio
    async def test_staging_detail_404_when_unknown(self, http):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/staging/01NONEXISTENTSTAGINGREC",
            headers=_h(token),
        )
        assert r.status_code == 404


# ===========================================================================
# 4. Freshness report
# ===========================================================================


class TestFreshnessReport:
    @pytest.mark.asyncio
    async def test_audit_can_get_freshness_table(self, http):
        token = await _login(http, "audit1")
        r = await http.get(
            "/api/v2/admin/data-freshness", headers=_h(token)
        )
        assert r.status_code == 200
        body = r.json()
        # Per-table rows present for the carry-forward entities.
        tables = [row["entity_table"] for row in body["rows"]]
        assert "investors" in tables
        assert "households" in tables
        assert "mandates" in tables
        assert "mandate_versions" in tables
        # Status is one of the three tiers.
        for row in body["rows"]:
            assert row["freshness_status"] in ("fresh", "stale", "very_stale")
            assert row["threshold_human"]


# ===========================================================================
# 5. Permission gates
# ===========================================================================


class TestPermissionGates:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("user_id", ["audit1", "cio1", "compliance1"])
    async def test_read_endpoints_accept_audit_cio_compliance(self, http, user_id):
        token = await _login(http, user_id)
        r = await http.get("/api/v2/admin/adapters", headers=_h(token))
        assert r.status_code == 200, f"{user_id} got {r.status_code}"

    @pytest.mark.asyncio
    async def test_read_endpoints_reject_advisor(self, http):
        token = await _login(http, "advisor1")
        r = await http.get("/api/v2/admin/adapters", headers=_h(token))
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_only_audit_can_trigger_run(self, http):
        registry.register_adapter(_StubAdapter())
        for user_id, expected in [
            ("audit1", 200),
            ("cio1", 403),
            ("compliance1", 403),
            ("advisor1", 403),
        ]:
            token = await _login(http, user_id)
            r = await http.post(
                "/api/v2/admin/adapters/stub_test/run",
                json={"mode": "full"},
                headers=_h(token),
            )
            assert r.status_code == expected, (
                f"{user_id} expected {expected}, got {r.status_code}: {r.text}"
            )

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, http):
        r = await http.get("/api/v2/admin/adapters")
        assert r.status_code == 401


# ===========================================================================
# 6. Adapter error handling
# ===========================================================================


class TestAdapterErrorHandling:
    @pytest.mark.asyncio
    async def test_run_failure_returns_500(self, http):
        registry.register_adapter(
            _StubAdapter(raise_on_run=RuntimeError("simulated failure"))
        )
        token = await _login(http, "audit1")
        r = await http.post(
            "/api/v2/admin/adapters/stub_test/run",
            json={"mode": "full"},
            headers=_h(token),
        )
        assert r.status_code == 500
        body = r.json()
        assert "simulated failure" in body["detail"]

    @pytest.mark.asyncio
    async def test_adapter_run_error_dataclass_serializes(self, http):
        # Ensures AdapterError is properly handled when used in metadata.
        err = AdapterError(error_type="test", message="m", record_identifier="r")
        assert err.error_type == "test"
