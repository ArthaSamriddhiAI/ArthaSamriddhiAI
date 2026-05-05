"""Cluster 3 addendum — multi-source loader tests.

Pins:

- :func:`is_multi_source_fixture` detects the merged JSON shape from any
  of the well-known sentinel keys.
- Each per-source loader (Nifty500, MF Database, PMS, AIF, Unlisted,
  Macro, Industry) maps source records to canonical instrument /
  macro_snapshot / industry_report shapes.
- ``flatten_multi_source`` orchestrates all loaders + returns a sectioned
  shape the existing JSONFixtureAdapter run() can consume unchanged.
- Display-form SEBI categories from the MF database resolve through the
  alias system added by the addendum.
- Synthetic exchange_ticker generation is deterministic + collision-free
  via the hash-tail strategy.
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select
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
from artha.api_v2.d0.adapters import multi_source
from artha.api_v2.d0.adapters.json_fixture import JSONFixtureAdapter
from artha.api_v2.d0.industry.models import IndustryReport
from artha.api_v2.d0.instruments import sebi_mapping
from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.d0.macro.models import MacroSnapshot
from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestDetection:
    def test_sectioned_shape_is_not_multi_source(self):
        assert not multi_source.is_multi_source_fixture(
            {"instruments": [], "macro_snapshots": []}
        )

    def test_nifty500_key_triggers_multi_source(self):
        assert multi_source.is_multi_source_fixture(
            {"nifty500_fundamentals.json": {"companies": []}}
        )

    def test_mf_database_key_triggers_multi_source(self):
        assert multi_source.is_multi_source_fixture(
            {"SAMRIDDHI_MF_Database.json": {}}
        )

    def test_industry_data_prefix_triggers_multi_source(self):
        assert multi_source.is_multi_source_fixture(
            {"Industry data (JSON)/some_report.json": {}}
        )

    def test_unlisted_equity_prefix_triggers_multi_source(self):
        assert multi_source.is_multi_source_fixture(
            {"Unlisted Equity/some-company.json": {}}
        )

    def test_empty_fixture_is_not_multi_source(self):
        assert not multi_source.is_multi_source_fixture({})


# ---------------------------------------------------------------------------
# Per-source loaders
# ---------------------------------------------------------------------------


class TestNifty500Loader:
    def test_maps_companies_to_equity_stocks(self):
        rows = multi_source.load_nifty500(
            {
                "companies": [
                    {"name": "Reliance Industries", "cmp_rs": 1315.1},
                    {"name": "TCS", "cmp_rs": 3000.0},
                ]
            }
        )
        assert len(rows) == 2
        for r in rows:
            assert r["asset_class"] == "equity"
            assert r["vehicle_type"] == "stock"
            assert r["classification_confidence"] == "medium"
            assert r["status"] == "active"
            assert r["exchange_ticker"]

    def test_skips_companies_with_no_name(self):
        rows = multi_source.load_nifty500(
            {"companies": [{"name": ""}, {"name": "  "}, {}]}
        )
        assert rows == []

    def test_synthetic_ticker_is_deterministic(self):
        rows1 = multi_source.load_nifty500(
            {"companies": [{"name": "Reliance Industries"}]}
        )
        rows2 = multi_source.load_nifty500(
            {"companies": [{"name": "Reliance Industries"}]}
        )
        assert rows1[0]["exchange_ticker"] == rows2[0]["exchange_ticker"]


class TestMfDatabaseLoader:
    def test_maps_through_sebi_classification(self):
        rows = multi_source.load_mf_database(
            {
                "Large Cap Fund": [
                    {
                        "Fund Name": "Test Large Cap Fund",
                        "ISIN": "INF111",
                        "AMFI Code": 12345,
                        "SEBI Category": "Large Cap Fund",
                    }
                ],
                "Liquid Fund": [
                    {
                        "Fund Name": "Test Liquid Fund",
                        "ISIN": "INF222",
                        "AMFI Code": 67890,
                        "SEBI Category": "Liquid Fund",
                    }
                ],
            }
        )
        assert len(rows) == 2
        large = next(r for r in rows if "Large" in r["name"])
        liquid = next(r for r in rows if "Liquid" in r["name"])

        assert large["asset_class"] == "equity"
        assert large["sebi_category"] == "large_cap"
        assert liquid["asset_class"] == "cash"
        assert liquid["sebi_category"] == "liquid"

    def test_resolves_display_form_aliases(self):
        # "Passive ELSS" → elss; "Sectoral- Banking" → sectoral_thematic;
        # "Dynamic Asset Allocation or Bal" → dynamic_asset_allocation.
        rows = multi_source.load_mf_database(
            {
                "Passive ELSS": [
                    {"Fund Name": "X", "SEBI Category": "Passive ELSS"}
                ],
                "Sectoral- Banking": [
                    {"Fund Name": "Y", "SEBI Category": "Sectoral- Banking"}
                ],
                "Dynamic Asset Allocation or Bal": [
                    {
                        "Fund Name": "Z",
                        "SEBI Category": "Dynamic Asset Allocation or Bal",
                    }
                ],
            }
        )
        cat_by_name = {r["name"]: r["sebi_category"] for r in rows}
        assert cat_by_name["X"] == "elss"
        assert cat_by_name["Y"] == "sectoral_thematic"
        assert cat_by_name["Z"] == "dynamic_asset_allocation"

    def test_resolves_new_addendum_categories(self):
        # ETFs- Commodity / ETFs- Global / Debt Index Funds — added
        # canonical entries in the addendum.
        rows = multi_source.load_mf_database(
            {
                "ETFs- Commodity": [
                    {"Fund Name": "G", "SEBI Category": "ETFs- Commodity"}
                ],
                "ETFs- Global": [
                    {"Fund Name": "H", "SEBI Category": "ETFs- Global"}
                ],
                "Debt Index Funds": [
                    {"Fund Name": "I", "SEBI Category": "Debt Index Funds"}
                ],
            }
        )
        cat_by_name = {r["name"]: (r["asset_class"], r["vehicle_type"]) for r in rows}
        assert cat_by_name["G"] == ("alternatives", "etf")
        assert cat_by_name["H"] == ("equity", "etf")
        assert cat_by_name["I"] == ("debt", "mutual_fund")

    def test_skips_schemes_with_no_name(self):
        rows = multi_source.load_mf_database(
            {"Large Cap Fund": [{"ISIN": "INF1"}, {"Fund Name": ""}]}
        )
        assert rows == []


class TestPmsLoader:
    def test_maps_pms_funds_to_pms_vehicle(self):
        rows = multi_source.load_pms(
            {
                "funds": [
                    {
                        "identity": {
                            "fund_name": "Marcellus Consistent Compounders",
                            "fund_manager": "Saurabh Mukherjea",
                            "strategy_type": "equity",
                            "inception_date": "Jul 20, 2016",
                        }
                    }
                ]
            }
        )
        assert len(rows) == 1
        assert rows[0]["vehicle_type"] == "pms"
        assert rows[0]["asset_class"] == "equity"
        assert rows[0]["amc_name"] == "Saurabh Mukherjea"
        assert rows[0]["inception_date"] == date(2016, 7, 20)

    def test_unknown_strategy_falls_back_to_equity(self):
        rows = multi_source.load_pms(
            {
                "funds": [
                    {
                        "identity": {
                            "fund_name": "Mystery Fund",
                            "strategy_type": "alpha_overlay",  # not in vocab
                        }
                    }
                ]
            }
        )
        assert rows[0]["asset_class"] == "equity"


class TestAifLoader:
    def test_maps_aif_profiles(self):
        rows = multi_source.load_aif(
            {
                "Fund Profiles": [
                    {
                        "Fund Name": "INDIA DISCOVERY FUND II",
                        "AMC / Investment Manager": "35North Ventures Pvt Ltd",
                        "SEBI Category": "CAT I",
                    }
                ]
            }
        )
        assert len(rows) == 1
        assert rows[0]["vehicle_type"] == "aif"
        assert rows[0]["asset_class"] == "alternatives"
        assert rows[0]["sebi_subcategory"] == "CAT I"


class TestUnlistedLoader:
    def test_maps_unlisted_company(self):
        row = multi_source.load_unlisted(
            "Unlisted Equity/test-co.json",
            {
                "identity": {
                    "company_id": "test-co",
                    "name": "Test Co Ltd",
                    "incorporation_date": "1990-05-15",
                    "status": "Active",
                }
            },
        )
        assert row is not None
        assert row["vehicle_type"] == "unlisted_equity"
        assert row["asset_class"] == "equity"
        assert row["status"] == "active"
        assert row["inception_date"] == date(1990, 5, 15)

    def test_skips_records_without_name(self):
        row = multi_source.load_unlisted(
            "Unlisted Equity/no-name.json", {"identity": {"company_id": "x"}}
        )
        assert row is None


class TestMacroLoader:
    def test_extracts_indicator_values(self):
        snap = multi_source.load_macro(
            {
                "data_snapshot": {
                    "dimensions": [
                        {
                            "dimension": "DIMENSION 1: ECONOMIC CYCLE",
                            "indicators": [
                                {
                                    "indicator": "GDP Growth (Real, YoY)",
                                    "value": "Q1: 6.7%, Q2: 8.4%",
                                },
                                {
                                    "indicator": "CPI Headline YoY",
                                    "value": "3.40%",
                                },
                            ],
                        },
                        {
                            "dimension": "DIMENSION 2: RBI MONETARY POLICY",
                            "indicators": [
                                {"indicator": "Repo Rate", "value": "5.25%"},
                                {
                                    "indicator": "10Y G-Sec Yield",
                                    "value": "6.99%",
                                },
                            ],
                        },
                    ]
                }
            }
        )
        # GDP regex picks 6.7 (the first %-suffixed number), not 1 (the trailing
        # digit of "Q1").
        assert snap["gdp_growth_pct"] == 6.7
        assert snap["cpi_inflation_pct"] == 3.4
        assert snap["repo_rate_pct"] == 5.25
        assert snap["bond_yield_10y_pct"] == 6.99
        assert snap["country_code"] == "IN"
        assert snap["snapshot_period"] == "2026-Q1"
        assert "DIMENSION 1: ECONOMIC CYCLE" in snap["themes"]
        assert "DIMENSION 2: RBI MONETARY POLICY" in snap["themes"]


class TestIndustryLoader:
    def test_builds_industry_report(self):
        report = multi_source.load_industry(
            "Industry data (JSON)/Sectoral_deployment_of_bank_credit_Jan_2026.json",
            {
                "filename": "Sectoral_deployment_of_bank_credit_Jan_2026.pdf",
                "pages": [
                    {
                        "page_number": 1,
                        "text": "Bank credit grew by 14.3% in Jan 2026.",
                    }
                ],
            },
        )
        assert report["industry_code"].startswith("sectoral")
        assert report["outlook"] == "neutral"
        assert "credit" in report["summary"].lower()
        assert report["report_period"] == "2026-Q1"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestFlattenOrchestrator:
    def test_returns_three_sections(self):
        result = multi_source.flatten_multi_source({})
        assert set(result.keys()) == {
            "instruments",
            "macro_snapshots",
            "industry_reports",
        }
        assert all(isinstance(result[k], list) for k in result)

    def test_combines_all_source_sections(self):
        fixture = {
            "nifty500_fundamentals.json": {
                "companies": [{"name": "Reliance"}, {"name": "TCS"}]
            },
            "SAMRIDDHI_MF_Database.json": {
                "Large Cap Fund": [
                    {"Fund Name": "ABC LC", "SEBI Category": "Large Cap Fund"}
                ]
            },
            "pms_full_513_funds.json": {
                "funds": [
                    {
                        "identity": {
                            "fund_name": "PMS X",
                            "fund_manager": "Mgr",
                            "strategy_type": "equity",
                        }
                    }
                ]
            },
            "AIF_Extracted_Data_Mar2026.json": {
                "Fund Profiles": [
                    {
                        "Fund Name": "AIF Y",
                        "AMC / Investment Manager": "Mgr",
                        "SEBI Category": "CAT I",
                    }
                ]
            },
            "Macro_Data_Snapshot.json": {
                "data_snapshot": {"dimensions": []}
            },
            "Unlisted Equity/foo.json": {
                "identity": {"name": "Foo Ltd", "company_id": "foo"}
            },
            "Industry data (JSON)/test.json": {
                "filename": "test.pdf",
                "pages": [{"text": "content"}],
            },
        }
        result = multi_source.flatten_multi_source(fixture)
        # 2 nifty + 1 mf + 1 pms + 1 aif + 1 unlisted = 6
        assert len(result["instruments"]) == 6
        assert len(result["macro_snapshots"]) == 1
        assert len(result["industry_reports"]) == 1


# ---------------------------------------------------------------------------
# End-to-end integration with JSONFixtureAdapter
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


def _synthetic_multi_source_fixture() -> dict:
    """A small but representative multi-source fixture for fast tests."""
    return {
        "nifty500_fundamentals.json": {
            "companies": [
                {"name": "Reliance Industries"},
                {"name": "TCS"},
                {"name": "HDFC Bank"},
            ]
        },
        "SAMRIDDHI_MF_Database.json": {
            "Large Cap Fund": [
                {
                    "Fund Name": "SBI Bluechip",
                    "ISIN": "INFA1",
                    "AMFI Code": 1001,
                    "SEBI Category": "Large Cap Fund",
                }
            ],
            "Liquid Fund": [
                {
                    "Fund Name": "Mirae Liquid",
                    "ISIN": "INFA2",
                    "AMFI Code": 1002,
                    "SEBI Category": "Liquid Fund",
                }
            ],
            "ETFs- Gold": [
                {
                    "Fund Name": "Nippon Gold ETF",
                    "ISIN": "INFA3",
                    "AMFI Code": 1003,
                    "SEBI Category": "ETFs- Gold",
                    "Asset Class": "Commodity",
                }
            ],
        },
        "pms_full_513_funds.json": {
            "funds": [
                {
                    "identity": {
                        "fund_name": "PMS Alpha",
                        "fund_manager": "Manager A",
                        "strategy_type": "equity",
                    }
                }
            ]
        },
        "AIF_Extracted_Data_Mar2026.json": {
            "Fund Profiles": [
                {
                    "Fund Name": "AIF Beta",
                    "AMC / Investment Manager": "Manager B",
                    "SEBI Category": "CAT II",
                }
            ]
        },
        "Macro_Data_Snapshot.json": {
            "data_snapshot": {
                "dimensions": [
                    {
                        "dimension": "ECONOMIC CYCLE",
                        "indicators": [
                            {
                                "indicator": "GDP Growth (Real, YoY)",
                                "value": "Q3: 7.8%",
                            }
                        ],
                    }
                ]
            }
        },
        "Unlisted Equity/test-co.json": {
            "identity": {
                "name": "Test Co Ltd",
                "company_id": "test-co",
                "status": "Active",
            }
        },
        "Industry data (JSON)/test_report.json": {
            "filename": "test_report.pdf",
            "pages": [{"text": "Industry analysis content."}],
        },
    }


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_adapter_loads_synthetic_multi_source(self, db):
        adapter = JSONFixtureAdapter(
            fixture_name="synthetic", fixture=_synthetic_multi_source_fixture()
        )
        result = await adapter.run(db)
        await db.commit()

        assert result.status == "success"
        assert result.errors == []

        i_count = (
            await db.execute(select(func.count()).select_from(Instrument))
        ).scalar()
        m_count = (
            await db.execute(select(func.count()).select_from(MacroSnapshot))
        ).scalar()
        r_count = (
            await db.execute(select(func.count()).select_from(IndustryReport))
        ).scalar()

        # 3 stocks + 3 mf-or-etf + 1 pms + 1 aif + 1 unlisted = 9
        assert i_count == 9
        assert m_count == 1
        assert r_count == 1

        # Verify vehicle distribution
        for vt in ("stock", "pms", "aif", "unlisted_equity"):
            n = (
                await db.execute(
                    select(func.count())
                    .select_from(Instrument)
                    .where(Instrument.vehicle_type == vt)
                )
            ).scalar()
            assert n >= 1, f"expected at least one {vt} instrument"

    @pytest.mark.asyncio
    async def test_run_metadata_records_multi_source_shape(self, db):
        adapter = JSONFixtureAdapter(
            fixture_name="synthetic", fixture=_synthetic_multi_source_fixture()
        )
        result = await adapter.run(db)
        await db.commit()
        assert result.metadata["fixture_shape"] == "multi_source"

    @pytest.mark.asyncio
    async def test_run_with_sectioned_shape_still_works(self, db):
        # Sanity check: backward compatibility — the chunk-3.2/3.3 sectioned
        # shape continues to work without going through the multi-source
        # flatten path.
        adapter = JSONFixtureAdapter(
            fixture_name="legacy",
            fixture={
                "instruments": [
                    {
                        "isin": "INF999",
                        "name": "Legacy Fund",
                        "sebi_category": "large_cap",
                    }
                ]
            },
        )
        result = await adapter.run(db)
        await db.commit()
        assert result.status == "success"
        assert result.metadata["fixture_shape"] == "sectioned"
        assert result.canonical_entities_created.get("Instrument") == 1


# ---------------------------------------------------------------------------
# Idempotency on synthetic identifiers
# ---------------------------------------------------------------------------


class TestSyntheticTickerIdempotency:
    @pytest.mark.asyncio
    async def test_re_run_updates_pms_records_in_place(self, db):
        adapter = JSONFixtureAdapter(
            fixture_name="t", fixture=_synthetic_multi_source_fixture()
        )
        await adapter.run(db)
        await db.commit()

        r2 = await adapter.run(db)
        await db.commit()

        # Total instrument count after two runs equals the count after one.
        i_count = (
            await db.execute(select(func.count()).select_from(Instrument))
        ).scalar()
        assert i_count == 9
        # Second run should have no creations and 9 updates.
        assert r2.canonical_entities_created.get("Instrument", 0) == 0
        assert r2.canonical_entities_updated.get("Instrument", 0) == 9


# ---------------------------------------------------------------------------
# SEBI mapping addendum tests
# ---------------------------------------------------------------------------


class TestSebiAddendumExtensions:
    def test_50_canonical_categories(self):
        assert len(sebi_mapping.SEBI_CATEGORY_MAP) == 50

    def test_addendum_categories_resolve(self):
        assert sebi_mapping.classify("Debt Index Funds") == ("debt", "mutual_fund")
        assert sebi_mapping.classify("ETFs- Commodity") == ("alternatives", "etf")
        assert sebi_mapping.classify("ETFs- Global") == ("equity", "etf")
        assert sebi_mapping.classify("Sectoral- Foreign Equity") == (
            "equity",
            "mutual_fund",
        )

    def test_display_aliases_resolve(self):
        assert sebi_mapping.classify("Passive ELSS") == ("equity", "mutual_fund")
        assert sebi_mapping.classify("Dynamic Asset Allocation or Bal") == (
            "equity",
            "mutual_fund",
        )
        assert sebi_mapping.classify("Sectoral- Banking") == ("equity", "mutual_fund")

    def test_extended_vehicle_vocabulary(self):
        for vt in ("pms", "aif", "unlisted_equity"):
            assert vt in sebi_mapping.VEHICLE_TYPES

    def test_to_canonical_key_strips_fund_suffix(self):
        assert sebi_mapping.to_canonical_key("Large Cap Fund") == "large_cap"
        assert sebi_mapping.to_canonical_key("Liquid Fund") == "liquid"
        # "_fund" suffix on canonical-keys is preserved (those that have it).
        assert sebi_mapping.to_canonical_key("Index Fund") == "index_fund"
        assert sebi_mapping.to_canonical_key("Retirement Fund") == "retirement_fund"

    def test_to_canonical_key_handles_apostrophes(self):
        assert sebi_mapping.to_canonical_key("Children's Fund") == "childrens_fund"

    def test_to_canonical_key_handles_ampersand(self):
        assert sebi_mapping.to_canonical_key("Large & Mid Cap Fund") == (
            "large_and_mid_cap"
        )
