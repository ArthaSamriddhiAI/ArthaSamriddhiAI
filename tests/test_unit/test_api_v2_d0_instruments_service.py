"""Cluster 3 chunk 3.2 — Instrument service-layer test suite.

Covers :func:`upsert_instrument`, :func:`find_by_identifier`, and
:func:`list_instruments`. Endpoint behaviour is pinned in
``test_api_v2_d0_instruments_endpoints.py``; this file isolates the
service-layer logic from HTTP and auth concerns.
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
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
from artha.api_v2.d0.instruments import service
from artha.common.db.base import Base


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _payload(**overrides):
    base = {
        "isin": "INF200K01XX2",
        "amfi_scheme_code": "118989",
        "name": "SBI Bluechip",
        "asset_class": "equity",
        "vehicle_type": "mutual_fund",
        "sebi_category": "large_cap",
        "amc_name": "SBI MF",
        "inception_date": date(2013, 1, 1),
    }
    base.update(overrides)
    return base


class TestUpsertCreate:
    @pytest.mark.asyncio
    async def test_creates_new_instrument(self, db):
        row, created = await service.upsert_instrument(
            db,
            payload=_payload(),
            source_identifier="json_fixture:demo",
            adapter_run_id="run_1",
            staging_record_id="staging_1",
        )
        await db.commit()
        assert created is True
        assert row.name == "SBI Bluechip"
        assert row.classification_confidence == "high"


class TestUpsertUpdate:
    @pytest.mark.asyncio
    async def test_isin_match_updates_existing(self, db):
        await service.upsert_instrument(
            db,
            payload=_payload(name="SBI Bluechip — v1"),
            source_identifier="src",
            adapter_run_id="run_1",
            staging_record_id="s1",
        )
        await db.commit()

        row, created = await service.upsert_instrument(
            db,
            payload=_payload(name="SBI Bluechip — v2"),
            source_identifier="src",
            adapter_run_id="run_2",
            staging_record_id="s2",
        )
        await db.commit()
        assert created is False
        assert row.name == "SBI Bluechip — v2"
        assert row.adapter_run_id == "run_2"


class TestFindByIdentifier:
    @pytest.mark.asyncio
    async def test_isin_lookup_wins_over_amfi(self, db):
        # Two rows: same AMFI code, different ISINs (artificial but tests order).
        await service.upsert_instrument(
            db,
            payload=_payload(isin="INF111", amfi_scheme_code="555"),
            source_identifier="src",
            adapter_run_id="r",
            staging_record_id="s",
        )
        await service.upsert_instrument(
            db,
            payload=_payload(isin="INF222", amfi_scheme_code="999", name="Other"),
            source_identifier="src",
            adapter_run_id="r",
            staging_record_id="s",
        )
        await db.commit()

        # Searching by ISIN INF222 should return that row even when AMFI 555
        # is also present (which would match a different row).
        row = await service.find_by_identifier(
            db, isin="INF222", amfi_scheme_code="555"
        )
        assert row is not None
        assert row.isin == "INF222"


class TestListInstruments:
    @pytest.mark.asyncio
    async def test_filters_compose(self, db):
        await service.upsert_instrument(
            db,
            payload=_payload(
                isin="INF1",
                amfi_scheme_code="111",
                sebi_category="large_cap",
            ),
            source_identifier="s",
            adapter_run_id="r",
            staging_record_id=None,
        )
        await service.upsert_instrument(
            db,
            payload=_payload(
                isin="INF2",
                amfi_scheme_code="222",
                name="Liquid",
                asset_class="cash",
                vehicle_type="mutual_fund",
                sebi_category="liquid",
            ),
            source_identifier="s",
            adapter_run_id="r",
            staging_record_id=None,
        )
        await db.commit()

        rows, total = await service.list_instruments(db, asset_class="cash")
        assert total == 1
        assert rows[0].sebi_category == "liquid"

        rows, total = await service.list_instruments(db, search="liquid")
        assert total == 1

        rows, total = await service.list_instruments(db)
        assert total == 2
