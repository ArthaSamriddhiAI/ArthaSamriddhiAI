# Samriddhi AI: Master Data Fixture

This directory holds the indicative master data fixture used by the
JSONFixtureAdapter in demo deployments of Samriddhi AI.

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
