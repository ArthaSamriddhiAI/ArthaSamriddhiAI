# Samriddhi AI: Master Data + Model Portfolio Fixtures

This directory holds two indicative fixtures used by demo deployments:

1. **`SamriddhiAI_data_merged.json`** — the cluster 3 master data
   fixture (instruments, macro snapshot, industry reports). The
   JSONFixtureAdapter reads this into the canonical entity tables.
2. **`default_model_portfolio.json`** — the cluster 4 default model
   portfolio fixture (preferred portfolio entries across 9 cells). The
   model-portfolio default loader reads this and inserts
   PreferredPortfolioEntry rows.

Together they let a fresh `git clone` produce a fully populated demo
deployment: 3000+ instruments tagged into the 3x3 client-profile matrix,
~70 hand-curated preferred portfolio entries spread across 9 cells, ready
for advisor + CIO walkthroughs.

---

## 1. SamriddhiAI_data_merged.json (cluster 3)

## What this fixture contains

`SamriddhiAI_data_merged.json` is a merged JSON file containing:

- **5 root data files** (around 5 MB): the bulk of the evidence universe
  - `nifty500_fundamentals.json`: 500 Nifty companies with 37 fundamental columns each
  - `SAMRIDDHI_MF_Database.json`: 46 SEBI mutual fund categories with full fund data
  - `pms_full_513_funds.json`: 513 PMS funds from PMS Bazaar
  - `AIF_Extracted_Data_Mar2026.json`: 162 AIF funds with fee structures
  - `Macro_Data_Snapshot.json`: macro indicators across 5 dimensions

- **14 industry data files** (around 3 MB): RBI and industry survey reports
  - Banking sector NPAs, capital adequacy, sectoral credit deployment
  - Financial Stability Report (Dec 2025)
  - Inflation expectations, household surveys, manufacturing outlook
  - Each file has filename, source format, num pages, pages array

- **100 unlisted equity files** (around 1.6 MB): private/unlisted companies
  - Each with identity, classification, financials, funding history,
    governance, exit assessment, data quality

Total: around 13 MB, 119 keys, representing the cluster 3 evidence universe.

## What this fixture does NOT contain

- Per-investor holdings (custodian sync arrives in cluster 17)
- Live news article feeds (separate news pipeline arrives later)
- Real-time market prices (live adapters arrive in cluster 17)
- E4 behavioural data (accumulates as the system runs)

## Fixture effective date

Roughly March-April 2026. Specific dates vary per source file.

## How to refresh the fixture

When the team produces an updated indicative data extraction:

1. Replace `SamriddhiAI_data_merged.json` with the new file.
2. Update this README's effective date if the new file has a different cut.
3. Commit and push.
4. Subsequent application startups will atomic-replace canonical entities
   with the new content via the JSONFixtureAdapter.

## Loading

The JSONFixtureAdapter reads from this path by default. The configuration
env var is `SAMRIDDHI_JSON_FIXTURE_PATH`; default value is
`./data/fixtures/SamriddhiAI_data_merged.json`.

On application startup with `SAMRIDDHI_FIXTURE_AUTO_LOAD=true` (the demo
default), the adapter runs automatically and loads the fixture's contents
into the canonical entity tables (instruments, macro_snapshots,
industry_reports).

## Known limitations

This is an INDICATIVE snapshot. Vehicle types not represented in the JSON
(debt vehicles like government bonds and corporate bonds, cash vehicles
like savings accounts and FDs, several alternatives vehicles) exist as
canonical entity schemas but have zero records in the demo deployment.
Admin views show stub indicators for these.

This is intentional per cluster 3 ideation: the architecture must
accommodate the broader investment universe; the JSON populates whatever
slices it has data for.

---

## 2. default_model_portfolio.json (cluster 4)

`default_model_portfolio.json` is the hand-curated default model portfolio
shipped with Samriddhi AI. Each entry references one instrument by
external identifier (AMFI scheme code, ISIN, SEBI registration, or
internal lookup) and assigns it into a cell of the 3x3 client-profile
matrix with a role and rank.

### What this fixture contains

- **~70 preferred portfolio entries** across 9 cells of the
  ``(risk_profile, horizon)`` matrix.
- Per cell typically: 3-5 core entries (foundational holdings the firm
  strongly recommends), 3-7 satellite entries (complementary tilts), 1-3
  optional entries (conditional add-ons like gold or retirement-mapped
  funds).
- Curation rationale for each entry in the `notes` field — short reason
  why the fund is in this cell with this role.

### Curation provenance

Hand-curated by Shubham Sahamate (April-May 2026) against the cluster 3
master data fixture. Curation favours established AMCs (HDFC, ICICI Pru,
Mirae, Parag Parikh, SBI) for cores; mixes in higher-tilt schemes
(Quant, Motilal Oswal, focused funds) as satellites; uses gold ETFs and
retirement / equity-savings funds as optional add-ons.

### Loading behaviour

The chunk 4.1 default loader reads this fixture at startup when
`SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_PREFERRED=true` (the demo
default). For each entry:

1. Look up the instrument by external identifier (AMFI code → ISIN →
   SEBI registration → internal name lookup).
2. If the instrument exists locally, insert a PreferredPortfolioEntry
   row with the entry's role + rank + notes.
3. If the instrument doesn't exist, log a warning + emit
   `default_preferred_entry_skipped_missing_instrument` T1 event and skip.
4. Idempotency: skip entries whose `(risk_profile, horizon, instrument)`
   triple already exists.

CIO customisations are preserved across restarts — the loader never
overwrites entries that already exist.

### How to refresh

When the team produces an updated curated default:

1. Replace `default_model_portfolio.json` with the new content.
2. Update `_metadata.version` and `_metadata.curated_at`.
3. Commit and push.
4. On the next startup, the loader inserts only the entries that don't
   yet exist locally. To force a complete refresh, run a "reset to
   default" admin action (chunks 4.2 / 4.3).

### Configuration env vars

```
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_TAGS=true
SAMRIDDHI_MODEL_PORTFOLIO_AUTO_DEFAULT_PREFERRED=true
SAMRIDDHI_DEFAULT_MODEL_PORTFOLIO_PATH=./data/fixtures/default_model_portfolio.json
```

The first applies SEBI category + vehicle type rules to instruments with
empty tag arrays. The second loads the default preferred portfolio.
Both default to False so test environments don't trigger; demos turn
both to True.
