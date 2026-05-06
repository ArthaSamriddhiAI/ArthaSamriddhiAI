"""Cluster 4 chunk 4.1 — default tag + preferred portfolio loader tests."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
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
from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.m2 import default_loader
from artha.api_v2.m2.event_names import (
    DEFAULT_PREFERRED_ENTRY_SKIPPED_MISSING_INSTRUMENT,
    INSTRUMENT_DEFAULT_TAGGING_FAILED,
)
from artha.api_v2.m2.models import PreferredPortfolioEntry
from artha.api_v2.observability.models import T1Event
from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    async with factory() as session:
        yield session
    await engine.dispose()


def _seed_instrument(
    *,
    name: str,
    asset_class: str = "equity",
    vehicle_type: str = "mutual_fund",
    sebi_category: str | None = "large_cap",
    isin: str | None = None,
    amfi_scheme_code: str | None = None,
    exchange_ticker: str | None = None,
    tags: list[str] | None = None,
) -> Instrument:
    now = datetime.now(timezone.utc)
    return Instrument(
        instrument_id=str(ULID()),
        isin=isin,
        amfi_scheme_code=amfi_scheme_code,
        exchange_ticker=exchange_ticker,
        name=name,
        asset_class=asset_class,
        vehicle_type=vehicle_type,
        sebi_category=sebi_category,
        classification_confidence="high",
        status="active",
        source_identifier="test",
        created_at=now,
        last_modified_at=now,
        model_portfolio_tags=tags or [],
        schema_version=2,
    )


# ---------------------------------------------------------------------------
# Default tagging
# ---------------------------------------------------------------------------


class TestApplyDefaultTags:
    @pytest.mark.asyncio
    async def test_tags_empty_instruments(self, db):
        db.add(_seed_instrument(name="Liquid Fund", sebi_category="liquid"))
        db.add(_seed_instrument(name="Small Cap Fund", sebi_category="small_cap"))
        await db.commit()

        summary = await default_loader.apply_default_tags(db)
        await db.commit()

        assert summary["tagged"] == 2
        assert summary["skipped_already_tagged"] == 0

        rows = list((await db.execute(select(Instrument))).scalars())
        liquid = next(r for r in rows if "Liquid" in r.name)
        small = next(r for r in rows if "Small" in r.name)
        assert len(liquid.model_portfolio_tags) == 9
        assert small.model_portfolio_tags == ["aggressive_long_term"]

    @pytest.mark.asyncio
    async def test_skips_already_tagged(self, db):
        # Pre-existing tag set should NOT be overwritten.
        db.add(_seed_instrument(
            name="Already Tagged",
            sebi_category="liquid",
            tags=["moderate_long_term"],
        ))
        await db.commit()

        summary = await default_loader.apply_default_tags(db)
        await db.commit()

        assert summary["tagged"] == 0
        assert summary["skipped_already_tagged"] == 1

        row = (await db.execute(select(Instrument))).scalar_one()
        assert row.model_portfolio_tags == ["moderate_long_term"]

    @pytest.mark.asyncio
    async def test_failed_classification_emits_t1_event(self, db):
        # MF with no SEBI category → unclassifiable.
        db.add(_seed_instrument(
            name="Mystery Fund",
            sebi_category=None,
            vehicle_type="mutual_fund",
        ))
        await db.commit()

        summary = await default_loader.apply_default_tags(db)
        await db.commit()

        assert summary["failed_classification"] == 1

        events = list(
            (
                await db.execute(
                    select(T1Event).where(
                        T1Event.event_name == INSTRUMENT_DEFAULT_TAGGING_FAILED
                    )
                )
            ).scalars()
        )
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_idempotent_on_repeated_runs(self, db):
        db.add(_seed_instrument(name="Liquid Fund", sebi_category="liquid"))
        await db.commit()

        s1 = await default_loader.apply_default_tags(db)
        await db.commit()
        assert s1["tagged"] == 1

        s2 = await default_loader.apply_default_tags(db)
        await db.commit()
        assert s2["tagged"] == 0
        assert s2["skipped_already_tagged"] == 1

    @pytest.mark.asyncio
    async def test_modified_at_left_null_for_defaults(self, db):
        # Defaults are NOT human edits — modified_at must stay NULL so the
        # admin UI can render "default" vs "edited" appropriately.
        db.add(_seed_instrument(name="Liquid Fund", sebi_category="liquid"))
        await db.commit()

        await default_loader.apply_default_tags(db)
        await db.commit()

        row = (await db.execute(select(Instrument))).scalar_one()
        assert row.model_portfolio_tags_modified_at is None
        assert row.model_portfolio_tags_modified_by is None

    @pytest.mark.asyncio
    async def test_tags_emitted_in_matrix_row_order(self, db):
        # Tags should be ordered ``aggressive_long_term, aggressive_medium_term,
        # aggressive_short_term, ...`` rather than insertion-order so the
        # JSON encoding is deterministic.
        db.add(_seed_instrument(name="Large Cap Fund", sebi_category="large_cap"))
        await db.commit()
        await default_loader.apply_default_tags(db)
        await db.commit()

        row = (await db.execute(select(Instrument))).scalar_one()
        # Expected matrix-row order: aggressive_medium_term then
        # aggressive_long_term then moderate_medium_term then
        # moderate_long_term.
        from artha.api_v2.m2 import cells

        assert row.model_portfolio_tags == [
            t for t in cells.ALL_CELLS if t in row.model_portfolio_tags
        ]


# ---------------------------------------------------------------------------
# Default preferred portfolio loader
# ---------------------------------------------------------------------------


class TestLoadDefaultPreferredPortfolio:
    @pytest.mark.asyncio
    async def test_loads_entries_resolving_amfi_codes(self, db):
        inst = _seed_instrument(
            name="SBI Liquid",
            amfi_scheme_code="105280",
            sebi_category="liquid",
        )
        db.add(inst)
        await db.commit()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            json.dump(
                {
                    "_metadata": {"version": "1.0"},
                    "preferred_portfolio_entries": [
                        {
                            "risk_profile": "conservative",
                            "horizon": "short_term",
                            "instrument_lookup": {
                                "external_identifier_type": "amfi_code",
                                "external_identifier_value": "105280",
                            },
                            "position_role": "core",
                            "rank_within_role": 1,
                            "notes": "Primary cash core",
                        }
                    ],
                },
                fh,
            )
            tmp_path = Path(fh.name)

        try:
            summary = await default_loader.load_default_preferred_portfolio(
                db, fixture_path=tmp_path
            )
            await db.commit()
            assert summary["loaded"] == 1
            assert summary["already_present"] == 0

            entries = list(
                (await db.execute(select(PreferredPortfolioEntry))).scalars()
            )
            assert len(entries) == 1
            entry = entries[0]
            assert entry.instrument_id == inst.instrument_id
            assert entry.risk_profile == "conservative"
            assert entry.horizon == "short_term"
            assert entry.position_role == "core"
            assert entry.notes == "Primary cash core"
            assert entry.created_via == "default_loader"
        finally:
            tmp_path.unlink()

    @pytest.mark.asyncio
    async def test_idempotent_on_repeated_loads(self, db):
        inst = _seed_instrument(
            name="SBI Liquid",
            amfi_scheme_code="105280",
            sebi_category="liquid",
        )
        db.add(inst)
        await db.commit()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            json.dump(
                {
                    "preferred_portfolio_entries": [
                        {
                            "risk_profile": "conservative",
                            "horizon": "short_term",
                            "instrument_lookup": {
                                "external_identifier_type": "amfi_code",
                                "external_identifier_value": "105280",
                            },
                            "position_role": "core",
                            "rank_within_role": 1,
                        }
                    ],
                },
                fh,
            )
            tmp_path = Path(fh.name)

        try:
            await default_loader.load_default_preferred_portfolio(
                db, fixture_path=tmp_path
            )
            await db.commit()
            s2 = await default_loader.load_default_preferred_portfolio(
                db, fixture_path=tmp_path
            )
            await db.commit()
            assert s2["loaded"] == 0
            assert s2["already_present"] == 1
            count = (
                await db.execute(select(func.count()).select_from(PreferredPortfolioEntry))
            ).scalar_one()
            assert count == 1
        finally:
            tmp_path.unlink()

    @pytest.mark.asyncio
    async def test_skips_missing_instrument(self, db):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            json.dump(
                {
                    "preferred_portfolio_entries": [
                        {
                            "risk_profile": "moderate",
                            "horizon": "long_term",
                            "instrument_lookup": {
                                "external_identifier_type": "amfi_code",
                                "external_identifier_value": "999999",
                            },
                            "position_role": "core",
                            "rank_within_role": 1,
                        }
                    ],
                },
                fh,
            )
            tmp_path = Path(fh.name)

        try:
            summary = await default_loader.load_default_preferred_portfolio(
                db, fixture_path=tmp_path
            )
            await db.commit()
            assert summary["loaded"] == 0
            assert summary["skipped_missing_instrument"] == 1

            events = list(
                (
                    await db.execute(
                        select(T1Event).where(
                            T1Event.event_name
                            == DEFAULT_PREFERRED_ENTRY_SKIPPED_MISSING_INSTRUMENT
                        )
                    )
                ).scalars()
            )
            assert len(events) == 1
        finally:
            tmp_path.unlink()

    @pytest.mark.asyncio
    async def test_skips_invalid_records(self, db):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as fh:
            json.dump(
                {
                    "preferred_portfolio_entries": [
                        # Missing required fields.
                        {"risk_profile": "moderate"},
                        # Invalid risk_profile.
                        {
                            "risk_profile": "speculative",
                            "horizon": "long_term",
                            "instrument_lookup": {
                                "external_identifier_type": "amfi_code",
                                "external_identifier_value": "111",
                            },
                            "position_role": "core",
                        },
                        # Invalid lookup_type.
                        {
                            "risk_profile": "moderate",
                            "horizon": "long_term",
                            "instrument_lookup": {
                                "external_identifier_type": "psychic_match",
                                "external_identifier_value": "111",
                            },
                            "position_role": "core",
                        },
                    ],
                },
                fh,
            )
            tmp_path = Path(fh.name)

        try:
            summary = await default_loader.load_default_preferred_portfolio(
                db, fixture_path=tmp_path
            )
            await db.commit()
            assert summary["skipped_invalid"] == 3
            assert summary["loaded"] == 0
        finally:
            tmp_path.unlink()

    @pytest.mark.asyncio
    async def test_isin_lookup_path(self, db):
        inst = _seed_instrument(
            name="Parag Parikh Flexi Cap",
            amfi_scheme_code="122640",
            isin="INF879O01019",
            sebi_category="flexi_cap",
        )
        db.add(inst)
        await db.commit()

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
                                "external_identifier_type": "isin",
                                "external_identifier_value": "INF879O01019",
                            },
                            "position_role": "core",
                            "rank_within_role": 1,
                        }
                    ],
                },
                fh,
            )
            tmp_path = Path(fh.name)

        try:
            summary = await default_loader.load_default_preferred_portfolio(
                db, fixture_path=tmp_path
            )
            await db.commit()
            assert summary["loaded"] == 1
        finally:
            tmp_path.unlink()

    @pytest.mark.asyncio
    async def test_missing_fixture_returns_zero_summary(self, db):
        summary = await default_loader.load_default_preferred_portfolio(
            db, fixture_path=Path("/tmp/definitely-not-there-12345.json")
        )
        # Loader logs warning + returns zeros; must not crash.
        assert summary["loaded"] == 0
