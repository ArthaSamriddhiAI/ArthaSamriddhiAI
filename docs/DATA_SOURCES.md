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
    stock_prices mf_navs  commodity  macro_ind  crypto   forex
    (CONNECTED) (CONNECTED) (CONNECTED) (CONNECTED) (CONNECTED) (CONNECTED)

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
| 1 | **Nifty 500 Stock Prices** | 10 years of daily adjusted close + volume for 453 NSE stocks. Pipeline: `stock_pipeline.py`. Source: Yahoo Finance. **1,069,341 records.** |
| 2 | **ETF Prices (Item A)** | 20 ETF tickers added: NIFTYBEES, GOLDBEES, BANKBEES, SILVERBEES, JUNIORBEES, LIQUIDBEES, ITBEES, PHARMABEES, etc. Same pipeline — zero new code. |
| 3 | **Market Index Data (Item B)** | 16 indices added: Nifty 50, Sensex, Nifty Midcap, Bank Nifty, IT, Pharma, FMCG, Energy, Auto, Metal, Infra, Realty, PSE, Nifty 100, Nifty 500. Same pipeline. |
| 4 | **REIT Data (Item T)** | 4 REIT tickers added: Embassy, Mindspace, Brookfield, Nexus Select. Same stock pipeline. |
| 5 | **Universe Management** | 541 total tickers in `stock_universe` (501 Nifty 500 + 20 ETFs + 16 Indices + 4 REITs). Auto-refresh via `niftystocks`. |
| 6 | **Mutual Fund NAVs (Item C expanded)** | Expanded from 50 to 126 schemes: large cap, mid cap, small cap, ELSS, sectoral (IT/Pharma/Banking/Infra), flexi cap, focused, value/contra, gilt, liquid, ultra short, credit risk, hybrid, balanced, multi-asset, arbitrage, international, retirement. **76,340 records.** |
| 7 | **Commodity Prices (Item D)** | Pipeline: `commodity_pipeline.py`. Gold futures, Silver futures, Crude WTI, Crude Brent, Copper, Natural Gas via yfinance. **15,090 records.** 10-year history. |
| 8 | **Forex Rates (Item E)** | Pipeline: `forex_pipeline.py`. USD/INR, EUR/INR, GBP/INR, JPY/INR, Dollar Index via yfinance. **12,921 records.** 10-year history. |
| 9 | **Macro Indicators (Item F)** | Pipeline: `macro_pipeline.py`. India VIX, US 10Y yield, Gold USD, Brent Crude, USD/INR, DXY via yfinance. **15,109 records.** 10-year history. |
| 10 | **Crypto Prices (Item G)** | Pipeline: `crypto_pipeline.py`. Bitcoin, Ethereum, Solana, Ripple, Cardano via yfinance. **9,130 records.** 5-year history. |
| 11 | **CSV Upload Endpoint (Item H)** | `POST /api/v1/data/upload` with schema validation for 12 data types: stock_fundamentals, mf_risk_metrics, yield_curve, corporate_bonds, esg_scores, analyst_consensus, ownership_data, pms_data, aif_data, fd_rates, cds_spreads, generic. Audit trail in `data_uploads` table. |
| 12 | **Bloomberg CSV Templates (Item I)** | 9 template CSV files in `docs/bloomberg_templates/`: stock_fundamentals, mf_risk_metrics, yield_curve, corporate_bonds, esg_scores, analyst_consensus, ownership_data, fd_rates, cds_spreads. Each with exact column headers matching upload validation. |
| 13 | **Daily Scheduler** | Systemd timer runs at 4:00 AM IST. Executes all pipelines (stocks, MFs, commodities, forex, macro, crypto). Audit trail logged. |
| 14 | **Pipeline CLI** | `scripts/run_pipeline.py` with flags: `--stocks`, `--mf`, `--commodities`, `--forex`, `--macro`, `--crypto`, `--all`, `--initial`, `--refresh-universe`, `--seed-mf`. |
| 15 | **Pipeline Audit Log** | Every execution logged with: run ID, pipeline name, status, records added, timestamps, error. Table: `data_pipeline_runs`. |
| | | **Total: 1,197,931 records across 6 asset class tables + 541 tickers + 126 MF schemes** |

### What Is Needed Next (Remaining Items — Require Bloomberg Terminal or Manual Data)

| # | Item | Status | Detail |
|---|------|--------|--------|
| **A** | **ETF Price Data** | **DONE** | 20 ETF tickers added and data loaded (NIFTYBEES, GOLDBEES, BANKBEES, SILVERBEES, etc.) |
| **B** | **Market Index Data** | **DONE** | 16 index tickers added (Nifty 50, Sensex, Bank Nifty, IT, Pharma, FMCG, Auto, Metal, etc.) |
| **C** | **Expanded MF Universe** | **DONE** | Expanded from 50 to 126 schemes (sectoral, thematic, gilt, liquid, debt, hybrid, multi-asset, arbitrage, international) |
| **D** | **Gold & Silver Prices** | **DONE** | `commodity_pipeline.py` built. Gold, Silver, Crude WTI/Brent, Copper, Natural Gas. 15,090 records. |
| **E** | **Forex Rates** | **DONE** | `forex_pipeline.py` built. USD/INR, EUR/INR, GBP/INR, JPY/INR, DXY. 12,921 records. |
| **F** | **Macro Economic Indicators** | **DONE** | `macro_pipeline.py` built. India VIX, US 10Y yield, Gold, Brent, USD/INR, DXY. 15,109 records. |
| **G** | **Crypto Prices** | **DONE** | `crypto_pipeline.py` built. Bitcoin, Ethereum, Solana, Ripple, Cardano via yfinance. 9,130 records. |
| **H** | **CSV Upload Endpoint** | **DONE** | `POST /api/v1/data/upload` live. Schema validation for 12 data types. Audit trail in `data_uploads` table. |
| **I** | **Bloomberg CSV Templates** | **DONE** | 9 template files in `docs/bloomberg_templates/`: stock_fundamentals, mf_risk_metrics, yield_curve, corporate_bonds, esg_scores, analyst_consensus, ownership_data, fd_rates, cds_spreads. |
| **S** | **Fixed Deposit Rates** | **DONE** | Template ready. Upload via CSV endpoint with `data_type=fd_rates`. |
| **T** | **Real Estate (REITs)** | **DONE** | 4 REIT tickers added (Embassy, Mindspace, Brookfield, Nexus). NHB RESIDEX needs manual upload. |
| **J** | **Govt Bond Yield Curve** | **PENDING** | Needs Bloomberg terminal for full 1Y-40Y curve. Upload via CSV endpoint with `data_type=yield_curve`. Template ready. |
| **K** | **Corporate Bond Database** | **PENDING** | Needs Bloomberg terminal. Use `SRCH <GO>` with India filter, export CSV, upload with `data_type=corporate_bonds`. Template ready. |
| **L** | **ESG Scores** | **PENDING** | Needs Bloomberg terminal. Extract via BDP for Nifty 500. Upload with `data_type=esg_scores`. Template ready. |
| **M** | **Analyst Consensus** | **PENDING** | Needs Bloomberg terminal. Extract target prices, EPS, buy/hold/sell. Upload with `data_type=analyst_consensus`. Template ready. |
| **N** | **Institutional Ownership** | **PENDING** | Needs Bloomberg terminal + SEBI filings. Upload with `data_type=ownership_data`. Template ready. |
| **O** | **Derivatives / F&O Data** | **PENDING** | Needs NSE bhav copy scraper + Bloomberg for IV surface. No template yet. |
| **P** | **PMS Performance Data** | **PENDING** | Needs manual CSV from PMS Bazaar / SEBI. Upload with `data_type=pms_data`. Template ready. |
| **Q** | **AIF Quarterly Data** | **PENDING** | Needs manual extraction from SEBI quarterly reports. Upload with `data_type=aif_data`. Template ready. |
| **R** | **Unlisted Equity** | **PENDING** | Needs manual entry from placement docs / DRHP. Upload with `data_type=generic`. |
| **U** | **CDS Spreads** | **PENDING** | Needs Bloomberg terminal exclusively. Upload with `data_type=cds_spreads`. Template ready. |

### Status Summary

- **DONE: 11 items** (A, B, C, D, E, F, G, H, I, S, T) — all automated pipelines running, CSV upload live, templates ready
- **PENDING: 10 items** (J, K, L, M, N, O, P, Q, R, U) — all require either Bloomberg terminal access or manual data collection
- **All PENDING items have CSV upload infrastructure ready** — just need the data extracted and uploaded

### For PENDING Items: What to Do

All pending items follow the same workflow:
1. Extract data from Bloomberg terminal (per BLOOMBERG_GUIDE.md) or manual source
2. Format as CSV matching the template in `docs/bloomberg_templates/`
3. Upload via `POST /api/v1/data/upload?data_type={type}&uploaded_by={name}`
4. Verify upload via `GET /api/v1/data/uploads`
