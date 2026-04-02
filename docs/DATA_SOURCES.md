# ArthaSamriddhiAI — Data Sources Matrix

## Overview
Complete mapping of every asset class to its data sources, pipeline status, Bloomberg Terminal opportunities, and implementation roadmap.

**Last Updated:** April 2026

---

## Master Data Sources Matrix

| # | Asset Class | Primary Free Source | Bloomberg Source | Pipeline Status | Connector | Update Freq | Scheduler (Y/N) | Data Format | Bloomberg Value | Bloomberg Tickers / Fields | Notes |
|---|------------|-------------------|-----------------|----------------|-----------|-------------|-----------------|-------------|----------------|---------------------------|-------|
| 1 | **Stocks (NSE/BSE)** | Yahoo Finance (`yfinance`) | BDH: `PX_LAST`, `VOLUME` | **CONNECTED** | `stock_pipeline.py` | Daily | **Y** (4AM IST) | symbol, date, adj_close, volume | **HIGH** — Fundamentals (PE, PB, ROE, EPS), analyst consensus, insider holdings, short interest not available from yfinance | `RELIANCE IN Equity` / `PX_LAST`, `PE_RATIO`, `BEST_EPS`, `RETURN_COM_EQY`, `VOLATILITY_260D`, `BETA_RAW_OVERRIDABLE`, `SHORT_INT` | 452 of 501 Nifty 500 loaded. 1M+ records. 10yr backfill done. Bloomberg adds fundamentals + analyst layer. |
| 2 | **ETFs** | Yahoo Finance (`yfinance`) | BDH: `FUND_NET_ASSET_VAL` | **Partial** — tickers need adding to `stock_universe` | Same `stock_pipeline.py` | Daily | **Y** (same pipeline) | symbol, date, adj_close, volume | **MEDIUM** — NAV vs market price discount/premium, tracking error, AUM, expense ratio | `NIFTYBEES IN Equity`, `GOLDBEES IN Equity`, `BANKBEES IN Equity` / `FUND_NET_ASSET_VAL`, `FUND_TOTAL_ASSETS`, `FUND_EXPENSE_RATIO` | Zero new code needed — just add ETF tickers (NIFTYBEES.NS, GOLDBEES.NS, BANKBEES.NS, etc.) to stock_universe table. |
| 3 | **Mutual Funds** | MFAPI (`api.mfapi.in`) | `FUND <GO>` search | **CONNECTED** | `mf_pipeline.py` | Daily NAV | **Y** (4AM IST) | scheme_code, date, nav | **HIGH** — Risk metrics (Sharpe, Sortino, Info Ratio, max drawdown), portfolio holdings, sector allocation, AUM history, expense ratio trends — none available from MFAPI | `SBIMCEQ IN Equity` (SBI Bluechip), `HABOREG IN Equity` (HDFC Top 100) / `FUND_SHARPE_RATIO`, `FUND_SORTINO_RATIO`, `FUND_MAX_DRAWDOWN`, `FUND_HOLDINGS`, `FUND_SECTOR_ALLOCATION` | 50 schemes seeded. 72K+ NAV records. Bloomberg adds risk-adjusted metrics. Expand universe by adding scheme codes to `universe.py`. |
| 4 | **Gold** | Metals-API / GoldAPI.io (free tier) | BDH: `XAU Curncy` | **NOT CONNECTED** | Needs `commodity_pipeline.py` | Daily (EOD spot) | **N** | date, price_per_gram_inr, price_per_oz_usd | **HIGH** — MCX Gold futures, LBMA London Fix, COMEX open interest, Gold/Silver ratio, central bank gold reserves, Gold ETF fund flows | `XAU Curncy` (spot USD/oz), `GOLDINR Index` (INR/10g), `MAUGOLD Index` (MCX near-month) / `PX_LAST`, `OPEN_INT` | Free API: GoldAPI.io (no auth, JSON). Also available via GOLDBEES.NS in yfinance (Gold ETF proxy). Bloomberg gives MCX futures + institutional flows. |
| 5 | **Silver** | Metals-API / MetalpriceAPI (free tier) | BDH: `XAG Curncy` | **NOT CONNECTED** | Same `commodity_pipeline.py` | Daily (EOD spot) | **N** | date, price_per_kg_inr, price_per_oz_usd | **HIGH** — MCX Silver futures, LBMA fix, Gold/Silver ratio | `XAG Curncy` (spot USD/oz), `SLVR IN Equity` (Silver ETF), `MAUSILVE Index` (MCX) / `PX_LAST` | Same adapter as Gold. SILVERBEES.NS available as yfinance proxy. |
| 6 | **Other Commodities** (Crude, Copper, Natural Gas, Aluminum) | Metals.Dev (100 req/mo free) | BDH: `CO1 Comdty`, `CL1 Comdty` | **NOT CONNECTED** | Needs `commodity_pipeline.py` | Daily | **N** | commodity, date, price, currency | **HIGH** — Full MCX/NCDEX futures curves, Brent/WTI crude, copper, aluminum, natural gas. Open interest, contango/backwardation analysis | `CO1 Comdty` (Brent), `CL1 Comdty` (WTI), `HG1 Comdty` (Copper), `NG1 Comdty` (Nat Gas), `LA1 Comdty` (Aluminum) / `PX_LAST`, `OPEN_INT`, `FUT_CUR_GEN_TICKER` | Limited free APIs for Indian MCX data. Bloomberg is the primary source for futures curves and commodity analytics. |
| 7 | **Govt Bonds / G-Secs** | FRED API (free, 10Y yield only) | `GC <GO>` yield curves | **NOT CONNECTED** | Needs `bond_pipeline.py` | FRED: Monthly. Bloomberg: Daily | **N** | tenor, date, yield_pct | **CRITICAL** — Bloomberg is the gold standard. Full yield curve (1Y to 40Y), real-time NDS-OM prices, OIS rates, repo rate history, T-bill rates. No adequate free alternative for the full curve | `GIND1YR Index` through `GIND30YR Index` (full tenor curve), `INRPYLDP Index` (RBI repo rate), `INROIS1Y Index` (OIS) / `PX_LAST`, `YLD_YTM_MID`, `PX_BID`, `PX_ASK` | FRED gives only 10Y benchmark (monthly). RBI DBIE has some data but no API. CCIL publishes daily but no free API. Bloomberg is the only practical source for the full yield curve. |
| 8 | **Corporate Bonds** | No free API available | `SRCH <GO>` with India filter | **NOT CONNECTED** | Manual CSV upload + `/api/v1/data/upload` (planned) | Ad hoc / Monthly | **N** | isin, issuer, coupon, ytm, oas, rating, maturity, issue_size | **CRITICAL** — Bloomberg is the primary source. YTM, OAS, Z-spread, credit rating history (S&P, Moody's, Fitch, CRISIL, CARE), issue size, callability, sector classification | `[ISIN] Corp` / `YLD_YTM_MID`, `CRNCY_ADJ_OAS`, `RTG_SP`, `RTG_MOODY`, `RTG_FITCH`, `CPN`, `MATURITY`, `ISSUE_SZ`, `CALLABLE` | No free API exists for Indian corporate bonds. Bloomberg + CSV upload is the only viable path. Student extracts via `SRCH <GO>`, exports to CSV, uploads to platform. |
| 9 | **Fixed Deposits** | RBI website / Individual bank websites | Limited | **NOT CONNECTED** | Manual reference table | Monthly | **N** | bank, tenor_months, rate_pct, effective_date, senior_citizen_rate | **LOW** — Bloomberg has limited FD data for India. Better sourced directly from bank websites or RBI master circulars | N/A | FD rates change infrequently. Maintain a static reference table with ~15-20 major banks. Manual update monthly. Not a pipeline candidate. |
| 10 | **PMS (Portfolio Mgmt Services)** | PMS Bazaar / SEBI monthly disclosures | `FUND <GO>` (partial) | **NOT CONNECTED** | Manual CSV upload | Monthly (performance) | **N** | pms_name, manager, strategy, aum_cr, returns_1m/3m/6m/1yr/3yr/5yr, min_investment, benchmark | **MEDIUM** — Top PMS houses (ASK, Marcellus, Unifi, IIFL, Kotak) may have Bloomberg tickers. Use `FUND <GO>` filter: country=India, type=Portfolio Management | `[PMS ticker] IN Equity` (if listed) / `FUND_NET_ASSET_VAL`, `FUND_TOTAL_ASSETS`, `FUND_YTD_RETURN`, `FUND_1_YEAR_RETURN` | No free API. SEBI mandates monthly disclosure. PMS Bazaar aggregates data. Student checks Bloomberg for available tickers, supplements with SEBI/PMS Bazaar CSV. |
| 11 | **AIF (Alternative Investment Funds)** | SEBI quarterly disclosures | `FUND <GO>` (limited) | **NOT CONNECTED** | Manual CSV upload | Quarterly | **N** | aif_name, category (I/II/III), manager, vintage_year, irr, tvpi, dpi, commitment_cr, drawdown_pct | **LOW-MEDIUM** — Category III AIFs (long-short, hedge funds) more likely on Bloomberg. Cat I (infra, social) and Cat II (PE, debt) limited | Search via `FUND <GO>` | SEBI quarterly reports are the primary source. Bloomberg coverage of Indian AIFs is sparse. Manual CSV upload from SEBI filings. |
| 12 | **Unlisted Equity / Pre-IPO** | No standard source | `EQUITY <GO>`, `IPO <GO>` | **NOT CONNECTED** | Manual entry only | Ad hoc (per valuation event) | **N** | company_name, valuation_date, price_per_share, implied_valuation_cr, valuation_method, source_document | **MEDIUM** — Bloomberg has some unlisted company data (revenue, headcount, funding rounds) via private company database. For pre-IPO, use `IPO <GO>` for DRHP filings. Limited pricing data | `[Company] IN Equity` (if available) / `SALES_REV_TURN`, `NUM_OF_EMPLOYEES`, `LATEST_DEAL_AMOUNT` | Inherently non-standard. Valuations from placement documents, DRHP filings, or broker estimates. Manual entry is the only reliable method. Bloomberg adds context but not pricing. |
| 13 | **Real Estate** | NHB RESIDEX (index), Manual (property-level) | REITs only: `EMBASSY IN Equity` | **NOT CONNECTED** | Manual entry | Quarterly (index) / Ad hoc (property) | **N** | property_id/index_name, location, type, area_sqft, current_value_cr, rental_yield_pct, occupancy_pct | **LOW** — Bloomberg has Indian REITs (Embassy, Mindspace, Brookfield) with full financial data. For residential/commercial property, NHB RESIDEX index is better. No property-level Bloomberg data | `EMBASSY IN Equity`, `MINDSP IN Equity` / `PX_LAST`, `DVD_YLD_IND`, `OCCUPANCY_RATE` | NHB RESIDEX for city-level residential index. REIT data from Bloomberg/yfinance. Individual property valuations are manual. |
| 14 | **Insurance (ULIP NAVs)** | Individual insurer websites (LIC, HDFC Life, ICICI Pru, etc.) | Very limited | **NOT CONNECTED** | Needs per-insurer scraper | Daily (NAV) | **N** | insurer, policy_name, fund_option, nav, date | **LOW** — Most ULIP fund NAVs not tracked on Bloomberg. Direct insurer websites or IRDA aggregated data preferred. Insurance company stocks available (`HDFCLIFE IN Equity`) but not ULIP fund NAVs | N/A | Low priority. Each insurer publishes NAVs on their website. No unified API exists. Consider building only if significant client exposure to ULIPs. |
| 15 | **Crypto** | CoinGecko API (free, 30 calls/min) | BDH: `XBTUSD Curncy` | **NOT CONNECTED** | Needs `crypto_pipeline.py` | Daily / Hourly (if needed) | **N** | coin_id, date, price_inr, price_usd, market_cap_usd, volume_24h | **MEDIUM** — Bloomberg tracks major crypto (BTC, ETH, SOL, etc.) with institutional-grade OHLCV. More reliable than free APIs for historical data | `XBTUSD Curncy` (Bitcoin), `XETUSD Curncy` (Ethereum) / `PX_LAST`, `VOLUME`, `CUR_MKT_CAP` | CoinGecko free tier is adequate for daily prices. Bloomberg adds institutional-grade data quality and derivatives (BTC futures, options). Only needed if HNI clients have crypto exposure. |
| 16 | **Forex (Currency Pairs)** | ExchangeRate-API (free) / FRED | BDH: `USDINR Curncy` | **NOT CONNECTED** | Needs `forex_pipeline.py` | Daily | **N** | pair, date, rate | **HIGH** — Bloomberg is definitive for FX. Spot rates, forward points (1W to 5Y), NDF rates, implied volatility, cross-currency basis. Essential for NRI client portfolios | `USDINR Curncy`, `EURINR Curncy`, `GBPINR Curncy`, `DXY Curncy` (Dollar Index) / `PX_LAST`, `FWD_RATE`, `IVOL_MID` | Free APIs give spot only. Bloomberg gives forward curves, NDF, and vol — critical for NRI hedging analysis. |
| 17 | **Indices** (Nifty 50, Sensex, Sectoral, Factor) | Yahoo Finance (`yfinance`) | BDH: `NIFTY Index` | **Partial** — tickers need adding | Same `stock_pipeline.py` | Daily | **Y** (same pipeline) | index, date, close_value | **HIGH** — Nifty 50 constituents with weights, sector indices, factor indices (momentum, quality, value). Index-level PE, PB, dividend yield, earnings growth | `NIFTY Index`, `SENSEX Index`, `NSEMDCP50 Index` (Midcap), `NSEIT Index` (IT) / `PX_LAST`, `INDX_MWEIGHT` (constituent weights), `PE_RATIO`, `DVD_YLD_IND` | Add index tickers to stock_universe: ^NSEI, ^BSESN, ^NSEMDCP50. Bloomberg adds constituent weights and index-level fundamentals. |
| 18 | **Derivatives (F&O)** | NSE website (bhav copy) / Manual | `OMON <GO>`, `OVDV <GO>` | **NOT CONNECTED** | Needs adapter (NSE bhav copy or Bloomberg CSV) | Daily | **N** | symbol, expiry, strike, option_type, oi, volume, premium, iv, delta | **CRITICAL** — Bloomberg provides full options chains, implied volatility surfaces (term structure, skew, smile), Greeks, historical open interest. No adequate free API | `NIFTY IN Index` (then `OMON <GO>` for chain) / `IVOL_MID`, `OPEN_INT`, `OPT_DELTA`, `OPT_GAMMA`, `OPT_VEGA` | NSE publishes daily bhav copies (CSV) for F&O but no API. Bloomberg is the only practical source for vol surface, Greeks, and historical IV. India VIX: `INVIXN Index`. |
| 19 | **Macro / Economic Indicators** | RBI DBIE (download) / FRED API | `ECST <GO>` | **NOT CONNECTED** | Needs `macro_pipeline.py` | Monthly / Quarterly | **N** | indicator_name, date, value, unit | **CRITICAL** — Bloomberg ECST has comprehensive India macro dashboard: GDP, CPI, IIP, PMI, forex reserves, FII/DII flows, money supply, current account, fiscal deficit — all in one place with history | `INGDPY% Index` (GDP), `INFUTOTY Index` (CPI), `INPMMI Index` (PMI), `INRPYLDP Index` (Repo rate), `MAHESSION Index` (FII flows), `INFORRES Index` (Forex reserves) / `PX_LAST` | FRED has some India indicators (free API). RBI DBIE has comprehensive data but no REST API (download only). Bloomberg consolidates everything with consistent formatting and history. |
| 20 | **ESG Scores & Sustainability** | No free source for India | `ESG <GO>` | **NOT CONNECTED** | Bloomberg CSV upload | Quarterly | **N** | symbol, env_score, social_score, gov_score, esg_combined, carbon_intensity | **HIGH** (Bloomberg exclusive) — Bloomberg ESG disclosure scores, carbon emissions (Scope 1/2/3), governance metrics, controversies. Essential for ESG-mandated HNI clients (like Ms. Ananya Bhat scenario) | `[Ticker]` then `ESG <GO>` / `ESG_DISCLOSURE_SCORE`, `ENVIRON_DISCLOSURE_SCORE`, `SOCIAL_DISCLOSURE_SCORE`, `GOVNCE_DISCLOSURE_SCORE`, `CARBON_EMISSIONS_SCOPE_1` | No free ESG data source for Indian companies. Bloomberg is the primary source. MSCI ESG and Sustainalytics are paid alternatives. Student extracts quarterly for Nifty 500. |
| 21 | **Analyst Consensus & Ratings** | No free source | `ANR <GO>` | **NOT CONNECTED** | Bloomberg CSV upload | Monthly | **N** | symbol, target_price, consensus_rating, buy_count, hold_count, sell_count, eps_estimate | **HIGH** (Bloomberg exclusive) — Consensus target prices, EPS estimates, buy/sell/hold from 30+ brokerages per stock. Critical for agent reasoning on fair value | `[Ticker]` then `ANR <GO>` / `BEST_TARGET_PRICE`, `BEST_ANALYST_RATING`, `TOT_BUY_REC`, `TOT_SELL_REC`, `BEST_EPS`, `BEST_EBITDA` | Not available from any free source. Student extracts monthly for top 100-200 stocks. Feeds directly into allocation and risk agents. |
| 22 | **Institutional Ownership** (FII/DII/MF/Promoter) | NSE/BSE bulk deals (partial) | `OWN <GO>` | **NOT CONNECTED** | Bloomberg CSV upload | Monthly / Quarterly | **N** | symbol, promoter_pct, fii_pct, dii_pct, mf_pct, insurance_pct, top_holders | **HIGH** (Bloomberg exclusive) — Full ownership breakdown with quarter-over-quarter changes. FII/DII/MF/Insurance/Promoter splits. Top 20 institutional holders by name | `[Ticker]` then `OWN <GO>` / `EQY_INST_PCT_SH_OUT`, `INSIDER_HOLDING_PCT`, `EQY_SH_OUT_TOT` + `BDS("TOP_20_HOLDERS_PUBLIC_FILINGS")` | SEBI shareholding patterns available quarterly (free) but fragmented. Bloomberg consolidates ownership data cleanly. |
| 23 | **Credit Risk (CDS Spreads)** | No free source | `CDSW <GO>` | **NOT CONNECTED** | Bloomberg CSV upload | Weekly | **N** | entity, tenor, spread_bps, date | **CRITICAL** (Bloomberg exclusive) — 5Y CDS spreads for Indian sovereign and top corporates. Market-implied credit risk — far more responsive than rating agency changes | `INDIA CDS USD SR 5Y Corp` (sovereign), `[Entity] CDS` / `PX_LAST` | Available only on Bloomberg. Critical for corporate bond analysis and credit risk interpretation agent. |
| 24 | **Supply Chain / Revenue Exposure** | No free source | `SPLC <GO>` | **NOT CONNECTED** | Bloomberg CSV upload | Quarterly | **N** | company, customer/supplier, revenue_pct, relationship_type | **MEDIUM** (Bloomberg exclusive) — Revenue exposure by customer/supplier for any listed company. Useful for concentration risk analysis in portfolios | `[Ticker]` then `SPLC <GO>` | Unique Bloomberg dataset. Useful for understanding portfolio-level supply chain concentration risk. Ad hoc extraction. |

---

## Summary by Status

| Status | Count | Asset Classes |
|--------|-------|--------------|
| **CONNECTED** (pipeline live, scheduler active) | 3 | Stocks, Mutual Funds, Indices (partial via same pipeline) |
| **Partial** (pipeline exists, needs ticker expansion) | 2 | ETFs, Indices |
| **NOT CONNECTED — Free API available** | 5 | Gold, Silver, Other Commodities, Crypto, Forex |
| **NOT CONNECTED — Bloomberg primary source** | 7 | Govt Bonds, Corporate Bonds, Derivatives, Macro, ESG, Analyst Consensus, Ownership |
| **NOT CONNECTED — Bloomberg exclusive** | 2 | CDS Spreads, Supply Chain |
| **NOT CONNECTED — Manual only** | 5 | FDs, PMS, AIF, Unlisted Equity, Real Estate |
| **NOT CONNECTED — Low priority** | 1 | Insurance/ULIP |

---

## Bloomberg Terminal Value Rating

| Rating | Count | Asset Classes | Action |
|--------|-------|--------------|--------|
| **CRITICAL** (no adequate free alternative) | 5 | Govt Bonds, Corporate Bonds, Derivatives/F&O, Macro Economic, CDS Spreads | Student must extract from Bloomberg — no other viable source |
| **HIGH** (Bloomberg adds unique enrichment) | 8 | Stocks, MFs, Gold, Silver, Commodities, Forex, Indices, ESG, Analyst Consensus, Ownership | Free API for basic data + Bloomberg for enrichment layer |
| **MEDIUM** (Bloomberg has partial coverage) | 4 | ETFs, PMS, Unlisted/Pre-IPO, Crypto, Supply Chain | Check Bloomberg availability first, supplement with manual |
| **LOW** (better sourced elsewhere) | 4 | FDs, AIF, Real Estate, Insurance/ULIP | Bloomberg not the primary path |

---

## Bloomberg Terminal Unique Data (Not Available from Any Free Source)

| # | Data Type | Bloomberg Function | Why It's Cutting-Edge | Extraction Frequency |
|---|-----------|-------------------|----------------------|---------------------|
| 1 | **Analyst Consensus** | `ANR <GO>` | Buy/sell/hold ratings, target prices, EPS estimates from 30+ brokerages | Monthly |
| 2 | **Institutional Ownership** | `OWN <GO>` | FII/DII/MF/Insurance holding patterns, quarter-over-quarter changes | Quarterly |
| 3 | **ESG Scores** | `ESG <GO>` | Bloomberg ESG disclosure scores, carbon intensity, governance metrics per company | Quarterly |
| 4 | **Credit Risk (CDS Spreads)** | `CDSW <GO>` | 5Y CDS spreads for Indian corporates and sovereign — market-priced credit risk | Weekly |
| 5 | **Implied Volatility Surface** | `OVDV <GO>` | Full vol surface for Nifty options — term structure, skew, smile, historical IV | Daily |
| 6 | **Fund Flow Data** | `FLOW <GO>` | Real-time FII/DII daily flows, sector-wise allocation shifts | Daily |
| 7 | **Supply Chain Mapping** | `SPLC <GO>` | Revenue exposure by customer/supplier for any company | Quarterly |
| 8 | **Earnings Transcripts** | `NT <GO>` | Full text of earnings call transcripts — can feed into NLP analysis | Per earnings |
| 9 | **M&A / Deal Analytics** | `MA <GO>` | Transaction comps, premium analysis, deal pipeline for Indian M&A | Ad hoc |
| 10 | **Custom Screening** | `EQS <GO>` | Multi-factor stock screening with 5000+ fields across all Indian stocks | Ad hoc |
| 11 | **Portfolio Analytics** | `PORT <GO>` | Upload portfolio, get risk decomposition, factor exposure, VaR, stress testing | Ad hoc |
| 12 | **Full Yield Curve** | `GC <GO>` | Indian G-Sec yield curve (1Y-40Y), OIS curve, T-bill rates — definitive source | Weekly |

---

## Data Pipeline Architecture

```
                        ┌─────────────────────────────────┐
                        │   Bloomberg Terminal (Student)    │
                        │   IMT CFM Lab Access             │
                        └───────────┬─────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             Excel BDH/BDP    Python xbbg     Manual Export
             → CSV Export     → Direct API    → SRCH/EQS
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
                          CSV Upload Pipeline
                          /api/v1/data/upload
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              fundamentals    yield_curve     corp_bonds
              esg_scores      macro_data      ownership
              analyst_recs    cds_spreads     vol_surface

    ════════════════════════════════════════════════════════

                    ┌───────────────────────────┐
                    │   Free APIs (24/7 Auto)    │
                    └───────────┬───────────────┘
                                │
         ┌──────────┬──────────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼
      yfinance   MFAPI    Metals-API   FRED    CoinGecko
         │          │          │          │          │
         ▼          ▼          ▼          ▼          ▼
    stock_prices mf_navs  commodity  macro_ind  crypto
    (CONNECTED) (CONNECTED) (PLANNED) (PLANNED) (PLANNED)

    ════════════════════════════════════════════════════════

                    ┌───────────────────────────┐
                    │   Manual Entry / CSV       │
                    │   (No API Available)        │
                    └───────────┬───────────────┘
                                │
         ┌──────────┬──────────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼
       PMS       AIF      Unlisted   Real Estate   FDs
     (Monthly) (Quarterly) (Ad hoc)  (Quarterly) (Monthly)
```

---

## Implementation Status & Next Steps

### What Is Done (Live in Production)

| # | Item | Detail |
|---|------|--------|
| 1 | **Nifty 500 Stock Prices** | 10 years of daily adjusted close + volume for 452 NSE stocks. Pipeline: `stock_pipeline.py`. Source: Yahoo Finance (`yfinance`). 1,069,338 records loaded. |
| 2 | **Nifty 500 Universe Management** | Automated refresh of Nifty 500 constituent list via `niftystocks` library. 501 symbols tracked in `stock_universe` table. |
| 3 | **Mutual Fund NAVs** | 10 years of daily NAV for 50 popular Indian mutual fund schemes (large cap, mid cap, small cap, ELSS, index, debt, hybrid, international). Pipeline: `mf_pipeline.py`. Source: MFAPI. 72,430 records loaded. |
| 4 | **Daily Scheduler** | Systemd timer (`artha-pipeline.timer`) runs at 4:00 AM IST every day. Executes incremental stock and MF pipelines automatically. Audit trail in `data_pipeline_runs` table. |
| 5 | **Yahoo Finance Adapter** | Evidence layer reads from `stock_prices` table. When a governance intent is submitted, the adapter fetches latest price, 52-week high/low, volume, and daily change for any Nifty 500 symbol. |
| 6 | **Mock Data Adapter** | Fallback adapter generating deterministic test prices for any symbol. Used when real data is unavailable or for testing. |
| 7 | **Pipeline CLI** | `scripts/run_pipeline.py` with flags: `--stocks`, `--mf`, `--initial` (full backfill), `--refresh-universe`, `--seed-mf`. Can be run manually or via scheduler. |
| 8 | **Pipeline Audit Log** | Every pipeline execution logged with: run ID, pipeline name, status, records added, start/end timestamps, error message (if any). Table: `data_pipeline_runs`. |

### What Is Needed Next

| # | Item | What Needs to Happen | Source | Effort | Dependency |
|---|------|---------------------|--------|--------|------------|
| **A** | **ETF Price Data** | Add ETF tickers to `stock_universe` table: NIFTYBEES.NS, GOLDBEES.NS, BANKBEES.NS, LIQUIDBEES.NS, JUNIORBEES.NS, SILVERBEES.NS, CPSEETF.NS, ICICIB22.NS. No code changes — the existing stock pipeline will pick them up automatically on next run. | Yahoo Finance (existing pipeline) | Minimal (DB insert only) | None |
| **B** | **Market Index Data** | Add index tickers to `stock_universe`: ^NSEI (Nifty 50), ^BSESN (Sensex), ^NSEMDCP50 (Midcap 50), ^CNXIT (IT Index), ^CNXPHARMA (Pharma), ^CNXFIN (Financial Services). Same pipeline handles these. | Yahoo Finance (existing pipeline) | Minimal (DB insert only) | None |
| **C** | **Expanded MF Universe** | Add more scheme codes to `universe.py` TOP_MF_SCHEMES dictionary. Currently 50 schemes — expand to 150-200 covering more fund houses and categories (sectoral, thematic, target maturity, gilt, liquid). | MFAPI (existing pipeline) | Minimal (code edit to add scheme codes) | None |
| **D** | **Gold & Silver Prices** | Build `commodity_pipeline.py` — new adapter calling GoldAPI.io or Metals-API free tier. Store in new `commodity_prices` table (commodity, date, price_inr, price_usd). Add to daily scheduler. | GoldAPI.io (free, no auth) or Metals-API (free tier) | New pipeline (~100 lines) | API key for Metals-API (free signup) |
| **E** | **Forex Rates** | Build `forex_pipeline.py` — adapter calling ExchangeRate-API or similar. Pairs: USDINR, EURINR, GBPINR, JPYINR. Store in new `forex_rates` table. Add to daily scheduler. | ExchangeRate-API (free) or FRED | New pipeline (~80 lines) | None (free APIs) |
| **F** | **Macro Economic Indicators** | Build `macro_pipeline.py` — adapter calling FRED API for India indicators: GDP growth, CPI inflation, PMI, RBI repo rate, forex reserves. Store in new `macro_indicators` table. Monthly/quarterly updates. | FRED API (free, needs API key) | New pipeline (~100 lines) | FRED API key (free signup at fred.stlouisfed.org) |
| **G** | **Crypto Prices** | Build `crypto_pipeline.py` — adapter calling CoinGecko API. Coins: BTC, ETH, SOL (expandable). Store in new `crypto_prices` table. Daily updates. | CoinGecko API (free, 30 calls/min) | New pipeline (~80 lines) | None |
| **H** | **CSV Upload Endpoint** | Build `POST /api/v1/data/upload` — generic CSV upload endpoint that accepts a file + data type identifier, validates columns against expected schema, and inserts into the appropriate table. Needed for all Bloomberg-sourced and manual data. | N/A (infrastructure) | New endpoint + validation (~200 lines) | None |
| **I** | **Bloomberg Data Templates** | Define CSV column schemas for each Bloomberg extraction task: stock fundamentals (17 columns), MF risk metrics (12 columns), yield curve (8 tenors), corporate bonds (11 columns), ESG scores (6 columns), analyst consensus (7 columns), ownership (7 columns). Templates stored as reference in `docs/bloomberg_templates/`. | N/A (documentation) | Template definitions | None |
| **J** | **Government Bond Yield Curve** | Two paths: (1) FRED API for 10Y benchmark yield (free, automated), (2) Bloomberg terminal for full 1Y-40Y curve (manual CSV upload via item H). Both should feed into a new `bond_yields` table. | FRED API (10Y only) + Bloomberg (full curve) | New table + FRED adapter (~80 lines) | Item H for Bloomberg data |
| **K** | **Corporate Bond Database** | No free API exists. Requires Bloomberg terminal: use `SRCH <GO>` with India + INR + Corp filter, export to CSV, upload via item H. New `corporate_bonds` table with: ISIN, issuer, coupon, YTM, OAS, rating, maturity, issue size. | Bloomberg terminal (CSV export) | New table + upload validation | Item H |
| **L** | **ESG Scores** | No free source for India. Requires Bloomberg terminal: extract using BDP for Nifty 500 stocks (env/social/gov/combined scores, carbon emissions). Upload via item H. New `esg_scores` table. | Bloomberg terminal (CSV export) | New table + upload validation | Item H |
| **M** | **Analyst Consensus Data** | No free source. Requires Bloomberg terminal: extract target prices, EPS estimates, buy/hold/sell counts for top 200 stocks. Upload via item H. New `analyst_consensus` table. | Bloomberg terminal (CSV export) | New table + upload validation | Item H |
| **N** | **Institutional Ownership** | Partial free data from SEBI quarterly filings. Bloomberg provides cleaner consolidated view. Extract FII/DII/MF/Promoter splits for Nifty 500. Upload via item H. New `ownership_data` table. | Bloomberg terminal + SEBI filings | New table + upload validation | Item H |
| **O** | **Derivatives / F&O Data** | NSE publishes daily bhav copies (CSV files) for F&O segment — downloadable but no API. Bloomberg provides options chains, IV surface, Greeks. Two approaches: (1) NSE bhav copy scraper for OI and volume, (2) Bloomberg for IV surface and Greeks via CSV. New `derivatives_data` table. | NSE bhav copies + Bloomberg terminal | New scraper + table (~150 lines) | Item H for Bloomberg data |
| **P** | **PMS Performance Data** | No API. Sources: PMS Bazaar website (aggregated monthly data) or SEBI monthly disclosures. Manual CSV preparation and upload via item H. New `pms_data` table. | PMS Bazaar / SEBI website | New table + upload validation | Item H |
| **Q** | **AIF Quarterly Data** | No API. Source: SEBI quarterly AIF disclosures (PDF/Excel on SEBI website). Manual extraction to CSV, upload via item H. New `aif_data` table. | SEBI quarterly reports | New table + upload validation | Item H |
| **R** | **Unlisted Equity Valuations** | No standard source. Valuations from placement documents, DRHP filings, or broker estimates. Manual entry via a form or CSV upload. New `unlisted_equity` table. | Manual (placement docs, DRHP, brokers) | New table + entry form | Item H |
| **S** | **Fixed Deposit Rates** | No API. Source: RBI circulars and individual bank websites. Static reference table with ~20 major banks, updated monthly. New `fd_rates` table. | Bank websites / RBI | New table (simple) | None |
| **T** | **Real Estate Data** | Two components: (1) NHB RESIDEX city-level index (downloadable from NHB website), (2) Individual property valuations (manual entry). REIT data available via existing stock pipeline (EMBASSY.NS, MINDSP.NS). | NHB RESIDEX + Manual | New table + REIT tickers in stock_universe | None for REITs |
| **U** | **CDS Spreads** | Bloomberg exclusive. Extract 5Y CDS spreads for Indian sovereign and top 20 corporates weekly. Upload via item H. New `cds_spreads` table. | Bloomberg terminal only | New table + upload validation | Item H |

### Dependency Chain

```
Items A, B, C, S, T(REITs) ──→ No dependency. Can be done immediately.

Items D, E, F, G ──→ No dependency. Need new pipeline code (free APIs).

Item H (CSV Upload Endpoint) ──→ Must be built before items I through U.

Items I through U ──→ All depend on Item H.
                  ──→ Items K, L, M, N, O(partial), U require Bloomberg terminal access.
                  ──→ Items P, Q, R are manual data collection.
```
