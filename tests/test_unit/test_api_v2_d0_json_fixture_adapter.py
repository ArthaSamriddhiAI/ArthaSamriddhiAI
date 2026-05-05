"""Cluster 3 chunk 3.2 — JSONFixtureAdapter behaviour test suite.

Pins:

- The adapter loads instruments from an in-memory dict.
- ``run`` writes one staging record carrying the full fixture.
- SEBI category resolves asset_class + vehicle_type from the map.
- Explicit asset_class + vehicle_type without a SEBI category produces
  ``classification_confidence="medium"``.
- Missing classification triggers ``instrument_classification_uncertain``.
- ``mode="validation"`` does not write canonical entities.
- Idempotency: re-running on the same fixture updates instead of inserts.
- ISIN identity wins over AMFI code for upsert resolution.
- Health check reports ``healthy=True`` when fixture is loadable.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
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
from artha.api_v2.d0.adapters.json_fixture import JSONFixtureAdapter
from artha.api_v2.d0.event_names import (
    INSTRUMENT_CLASSIFICATION_UNCERTAIN,
    STAGING_RECORD_CREATED,
)
from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.d0.models import StagingRecord
from artha.api_v2.observability.models import T1Event
from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# In-memory engine fixture (per test)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------


def _two_instrument_fixture() -> dict:
    return {
        "instruments": [
            {
                "isin": "INF200K01XX2",
                "amfi_scheme_code": "118989",
                "name": "SBI Bluechip Fund Direct Plan Growth",
                "short_name": "SBI Bluechip Direct G",
                "sebi_category": "large_cap",
                "issuer_name": "SBI Funds Management",
                "amc_name": "SBI Mutual Fund",
                "riskometer_label": "very_high",
                "inception_date": "2013-01-01",
            },
            {
                "isin": "INF879O01027",
                "amfi_scheme_code": "120505",
                "name": "Mirae Asset Liquid Fund Direct Plan Growth",
                "sebi_category": "liquid",
                "amc_name": "Mirae Asset Mutual Fund",
                "riskometer_label": "low_to_moderate",
                "inception_date": "2008-01-01",
            },
        ]
    }


# ---------------------------------------------------------------------------
# Constructor + health
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_requires_fixture_or_path(self):
        with pytest.raises(ValueError, match="fixture"):
            JSONFixtureAdapter(fixture_name="empty")

    def test_source_identifier_includes_fixture_name(self):
        a = JSONFixtureAdapter(fixture_name="demo", fixture={"instruments": []})
        assert a.source_identifier == "json_fixture:demo"

    def test_supported_entity_types_includes_three_canonical_entities(self):
        # Chunk 3.2 shipped Instrument; chunk 3.3 added MacroSnapshot and
        # IndustryReport to the same adapter.
        a = JSONFixtureAdapter(fixture_name="demo", fixture={"instruments": []})
        assert a.supported_entity_types == [
            "Instrument",
            "MacroSnapshot",
            "IndustryReport",
        ]


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_in_memory_fixture_is_healthy(self):
        a = JSONFixtureAdapter(fixture_name="demo", fixture={"instruments": []})
        h = await a.health_check()
        assert h.healthy is True

    @pytest.mark.asyncio
    async def test_missing_path_is_unhealthy(self):
        a = JSONFixtureAdapter(
            fixture_name="missing",
            fixture_path=Path("/tmp/definitely-not-real-fixture-12345.json"),
        )
        h = await a.health_check()
        assert h.healthy is False
        assert h.error_message


# ---------------------------------------------------------------------------
# Run() basic flow
# ---------------------------------------------------------------------------


class TestRunFromInMemoryFixture:
    @pytest.mark.asyncio
    async def test_loads_two_instruments(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="demo", fixture=_two_instrument_fixture()
        )
        result = await adapter.run(session)
        await session.commit()

        assert result.status == "success"
        assert result.canonical_entities_created == {"Instrument": 2}
        assert result.staging_records_created == 1
        assert result.metadata["instruments_seen"] == 2

        rows = list((await session.execute(select(Instrument))).scalars())
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_writes_one_staging_record(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="demo", fixture=_two_instrument_fixture()
        )
        await adapter.run(session)
        await session.commit()

        staging = list(
            (await session.execute(select(StagingRecord))).scalars()
        )
        assert len(staging) == 1
        assert staging[0].source_identifier == "json_fixture:demo"
        assert staging[0].raw_content == _two_instrument_fixture()

    @pytest.mark.asyncio
    async def test_emits_staging_record_created_event(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="demo", fixture=_two_instrument_fixture()
        )
        await adapter.run(session)
        await session.commit()

        events = list(
            (
                await session.execute(
                    select(T1Event).where(
                        T1Event.event_name == STAGING_RECORD_CREATED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Classification path
# ---------------------------------------------------------------------------


class TestClassificationFromSebiCategory:
    @pytest.mark.asyncio
    async def test_large_cap_classifies_as_equity_mutual_fund(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "instruments": [
                    {
                        "isin": "INF111",
                        "name": "Test Large Cap",
                        "sebi_category": "large_cap",
                    }
                ]
            },
        )
        await adapter.run(session)
        await session.commit()

        row = (await session.execute(select(Instrument))).scalar_one()
        assert row.asset_class == "equity"
        assert row.vehicle_type == "mutual_fund"
        assert row.classification_confidence == "high"
        assert row.sebi_category == "large_cap"

    @pytest.mark.asyncio
    async def test_liquid_classifies_as_cash_not_debt(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "instruments": [
                    {
                        "isin": "INF222",
                        "name": "Test Liquid",
                        "sebi_category": "liquid",
                    }
                ]
            },
        )
        await adapter.run(session)
        await session.commit()

        row = (await session.execute(select(Instrument))).scalar_one()
        assert row.asset_class == "cash"

    @pytest.mark.asyncio
    async def test_etf_gold_classifies_as_alternatives_etf(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "instruments": [
                    {
                        "isin": "INF333",
                        "name": "Gold ETF",
                        "sebi_category": "etf_gold",
                    }
                ]
            },
        )
        await adapter.run(session)
        await session.commit()

        row = (await session.execute(select(Instrument))).scalar_one()
        assert row.asset_class == "alternatives"
        assert row.vehicle_type == "etf"


class TestExplicitClassification:
    @pytest.mark.asyncio
    async def test_explicit_asset_class_writes_medium_confidence(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "instruments": [
                    {
                        "isin": "INE999",
                        "name": "Some Equity Stock",
                        "asset_class": "equity",
                        "vehicle_type": "stock",
                    }
                ]
            },
        )
        result = await adapter.run(session)
        await session.commit()

        assert result.status == "success"
        row = (await session.execute(select(Instrument))).scalar_one()
        assert row.asset_class == "equity"
        assert row.vehicle_type == "stock"
        assert row.classification_confidence == "medium"
        assert row.sebi_category is None

    @pytest.mark.asyncio
    async def test_explicit_invalid_asset_class_records_error(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "instruments": [
                    {
                        "isin": "INE000",
                        "name": "Bad Class",
                        "asset_class": "made_up_class",
                        "vehicle_type": "stock",
                    }
                ]
            },
        )
        result = await adapter.run(session)
        await session.commit()

        assert result.status == "failure"
        assert any(e.error_type == "schema_mismatch" for e in result.errors)


class TestClassificationUncertain:
    @pytest.mark.asyncio
    async def test_no_category_no_explicit_class_records_uncertain(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="t",
            fixture={
                "instruments": [
                    {"isin": "INE111", "name": "Mystery Instrument"}
                ]
            },
        )
        result = await adapter.run(session)
        await session.commit()

        assert result.status == "failure"
        assert any(
            e.error_type == "classification_uncertain" for e in result.errors
        )

        # Row not written.
        rows = list((await session.execute(select(Instrument))).scalars())
        assert rows == []

        # T1 event emitted.
        events = list(
            (
                await session.execute(
                    select(T1Event).where(
                        T1Event.event_name == INSTRUMENT_CLASSIFICATION_UNCERTAIN
                    )
                )
            ).scalars()
        )
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Validation mode
# ---------------------------------------------------------------------------


class TestValidationMode:
    @pytest.mark.asyncio
    async def test_validation_mode_does_not_write_instruments(self, session):
        adapter = JSONFixtureAdapter(
            fixture_name="demo", fixture=_two_instrument_fixture()
        )
        result = await adapter.run(session, mode="validation")
        await session.commit()

        rows = list((await session.execute(select(Instrument))).scalars())
        assert rows == []
        assert result.status == "success"
        # canonical_entities_created counts what would-have-been-written.
        assert result.metadata["mode"] == "validation"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_second_run_updates_existing_isin(self, session):
        f1 = {
            "instruments": [
                {
                    "isin": "INF200K01XX2",
                    "amfi_scheme_code": "118989",
                    "name": "SBI Bluechip — v1",
                    "sebi_category": "large_cap",
                }
            ]
        }
        adapter = JSONFixtureAdapter(fixture_name="demo", fixture=f1)
        r1 = await adapter.run(session)
        await session.commit()
        assert r1.canonical_entities_created == {"Instrument": 1}

        # Second run with the same ISIN but different name
        f2 = {
            "instruments": [
                {
                    "isin": "INF200K01XX2",
                    "amfi_scheme_code": "118989",
                    "name": "SBI Bluechip — v2",
                    "sebi_category": "large_cap",
                }
            ]
        }
        adapter2 = JSONFixtureAdapter(fixture_name="demo", fixture=f2)
        r2 = await adapter2.run(session)
        await session.commit()

        assert r2.canonical_entities_updated == {"Instrument": 1}
        assert r2.canonical_entities_created == {}

        rows = list((await session.execute(select(Instrument))).scalars())
        assert len(rows) == 1
        assert rows[0].name == "SBI Bluechip — v2"


# ---------------------------------------------------------------------------
# File-loading path
# ---------------------------------------------------------------------------


class TestFileLoading:
    @pytest.mark.asyncio
    async def test_loads_from_disk(self, session):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            json.dump(_two_instrument_fixture(), fh)
            tmp_path = Path(fh.name)

        try:
            adapter = JSONFixtureAdapter(
                fixture_name="from_disk", fixture_path=tmp_path
            )
            result = await adapter.run(session)
            await session.commit()
            assert result.canonical_entities_created == {"Instrument": 2}
        finally:
            tmp_path.unlink()
