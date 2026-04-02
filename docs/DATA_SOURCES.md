# ArthaSamriddhiAI — Data Sources Matrix

## Overview
This document maps every asset class to its data sources, pipeline status, and Bloomberg Terminal opportunities.

---

## Data Sources by Asset Class

| # | Asset Class | Primary Source | Status | Connector | Update Freq | Scheduler | Format | Bloomberg Terminal Value |
|---|------------|---------------|--------|-----------|-------------|-----------|--------|------------------------|
| **1** | **Stocks (NSE/BSE)** | Yahoo Finance (`yfinance`) | **CONNECTED** | `stock_pipeline.py` | Daily | **Yes** (4AM IST) | symbol, date, adj_close, volume | **HIGH** — BDH for corporate actions-adjusted prices, fundamental data (PE, PB, ROE, EPS), insider holdings, analyst consensus, short interest. Fields: `PX_LAST`, `PE_RATIO`, `BEST_EPS`, `SHORT_INT`. Tickers: `RELIANCE IN Equity` |
| **2** | **ETFs** | Yahoo Finance (`yfinance`) | **Partial** — needs tickers added | Same pipeline | Daily | **Yes** | Same as stocks | **MEDIUM** — BDH for NAV vs market price discount/premium, tracking error, AUM, expense ratio. Fields: `FUND_NET_ASSET_VAL`, `FUND_TOTAL_ASSETS`. Tickers: `NIFTYBEES IN Equity` |
| **3** | **Mutual Funds** | MFAPI (`api.mfapi.in`) | **CONNECTED** | `mf_pipeline.py` | Daily NAV | **Yes** (4AM IST) | scheme_code, date, nav | **HIGH** — BDH for scheme-level risk metrics (Sharpe, Sortino, Information Ratio, max drawdown), portfolio holdings, sector allocation, AUM history, expense ratio trends. Fields: `FUND_SHARPE_RATIO`, `FUND_HOLDINGS`. Use `FUND <GO>` search. |
| **4** | **Gold** | Metals-API / GoldAPI.io | **NOT CONNECTED** | Needs adapter | Daily | No | date, price_inr, price_usd | **HIGH** — BDH for MCX Gold futures, LBMA fix, Gold ETF flows, COMEX open interest, Gold/Silver ratio, central bank reserves. Tickers: `XAU Curncy`, `GOLD IN Equity`, `MCX Gold`. Fields: `PX_LAST`, `OPEN_INT` |
| **5** | **Silver** | Metals-API / MetalpriceAPI | **NOT CONNECTED** | Needs adapter | Daily | No | date, price_inr, price_usd | **HIGH** — Same as Gold. Tickers: `XAG Curncy`, `SLVR IN Equity`. MCX Silver futures data. |
| **6** | **Other Commodities** | Metals.Dev / MCX data | **NOT CONNECTED** | Needs adapter | Daily | No | commodity, date, price | **HIGH** — BDH for crude oil (Brent/WTI), natural gas, copper, aluminum from MCX/NCDEX. Tickers: `CO1 Comdty` (Brent), `CL1 Comdty` (WTI). Full futures curves available. |
| **7** | **Govt Bonds / G-Secs** | FRED API (10Y yield) | **NOT CONNECTED** | Needs adapter | Monthly/Daily | No | tenor, date, yield_pct | **CRITICAL** — Bloomberg is the gold standard for Indian G-Sec data. Full yield curve (1Y-40Y), real-time NDS-OM prices, OIS rates, repo rates. Tickers: `GIND10YR Index`, `INROIS1Y Index`. BDH fields: `YLD_YTM_MID`, `PX_BID`, `PX_ASK`. Use `GC <GO>` for yield curves. |
| **8** | **Corporate Bonds** | No free API | **NOT CONNECTED** | Manual/CSV upload | Ad hoc | No | isin, issuer, coupon, ytm, rating | **CRITICAL** — Bloomberg is the primary source. Search via `SRCH <GO>` with India filter. BDH for YTM, OAS, Z-spread, credit rating history, issue size, callability. Tickers: `[ISIN] Corp`. Fields: `YLD_YTM_MID`, `RTG_SP`, `RTG_MOODY`, `CRNCY_ADJ_OAS`. |
| **9** | **Fixed Deposits** | RBI / Bank websites | **NOT CONNECTED** | Manual/reference table | Monthly | No | bank, tenor, rate_pct | **LOW** — Bloomberg has limited FD data. Better sourced directly from bank websites or RBI. |
| **10** | **PMS** | PMS Bazaar / SEBI | **NOT CONNECTED** | Manual/CSV upload | Monthly | No | pms_name, strategy, aum, returns | **MEDIUM** — Some PMS strategies are tracked. Use `FUND <GO>` and filter by country=India, fund type=Portfolio Management. Limited but may have top PMS houses (ASK, Marcellus, etc.). Fields: `FUND_NET_ASSET_VAL`, `FUND_TOTAL_ASSETS`. |
| **11** | **AIF** | SEBI disclosures | **NOT CONNECTED** | Manual/CSV upload | Quarterly | No | aif_name, category, irr, tvpi | **LOW-MEDIUM** — Category III AIFs (hedge funds) may have Bloomberg tickers. Cat I/II limited. Use `FUND <GO>` search. SEBI quarterly reports remain primary source. |
| **12** | **Unlisted Equity / Pre-IPO** | No standard source | **NOT CONNECTED** | Manual entry | Ad hoc | No | company, valuation, source | **MEDIUM** — Bloomberg has some unlisted company data via `EQUITY <GO>` search (revenue, employee count, funding rounds). For pre-IPO companies filing DRHP, use `IPO <GO>`. Limited pricing data. |
| **13** | **Real Estate** | NHB RESIDEX / Manual | **NOT CONNECTED** | Manual entry | Quarterly | No | location, value, rental_yield | **LOW** — Bloomberg has REITs (Embassy, Mindspace, Brookfield). Tickers: `EMBASSY IN Equity`. For residential index data, NHB RESIDEX is better. |
| **14** | **Insurance (ULIP NAVs)** | Insurer websites | **NOT CONNECTED** | Needs scraper | Daily | No | fund_name, nav, date | **LOW** — Most ULIP NAVs not on Bloomberg. Direct insurer websites or IRDA data preferred. |
| **15** | **Crypto** | CoinGecko API (free) | **NOT CONNECTED** | Needs adapter | Daily | No | coin, price_inr, market_cap | **MEDIUM** — Bloomberg tracks major crypto. Tickers: `XBTUSD Curncy` (Bitcoin), `XETUSD Curncy` (Ethereum). BDH for institutional-grade OHLCV data. |
| **16** | **Forex** | FRED / ExchangeRate-API | **NOT CONNECTED** | Needs adapter | Daily | No | pair, date, rate | **HIGH** — Bloomberg is definitive for FX. Tickers: `USDINR Curncy`, `EURINR Curncy`. BDH for spot, forward points, NDF, implied vol. Fields: `PX_LAST`, `FWD_RATE`. |
| **17** | **Indices** | Yahoo Finance (`yfinance`) | **Partial** | Same pipeline | Daily | **Yes** | Same as stocks | **HIGH** — Bloomberg has Nifty 50 constituents, sector indices, factor indices. Tickers: `NIFTY Index`, `SENSEX Index`. BDH for index-level PE, PB, dividend yield, earnings growth. Fields: `INDX_MWEIGHT` for constituent weights. |
| **18** | **Derivatives (F&O)** | NSE website / Manual | **NOT CONNECTED** | Needs adapter | Daily | No | symbol, expiry, strike, oi, premium | **CRITICAL** — Bloomberg provides full options chains, implied volatility surfaces, Greeks, open interest. Use `OMON <GO>`. Tickers: `NIFTY IN Index` + option chain. Fields: `IVOL_MID`, `OPEN_INT`, `OPT_DELTA`. |
| **19** | **Macro / Economic** | RBI DBIE / FRED | **NOT CONNECTED** | Needs adapter | Monthly/Quarterly | No | indicator, date, value | **CRITICAL** — Bloomberg ECST function. GDP, CPI, IIP, PMI, forex reserves, FII/DII flows. Tickers: `INGDPY% Index` (GDP), `INFUTOTY Index` (CPI). Use `ECST <GO>` for India economic dashboard. |

---

## Bloomberg Terminal Unique Advantages (Not Available from Free Sources)

| Data Type | Bloomberg Function | Why It's Cutting-Edge |
|-----------|-------------------|----------------------|
| **Analyst Consensus** | `ANR <GO>` | Buy/sell/hold ratings, target prices, EPS estimates from 30+ brokerages |
| **Ownership / Institutional Holdings** | `OWN <GO>` | FII/DII/MF/Insurance holding patterns, changes quarter-over-quarter |
| **ESG Scores** | `ESG <GO>` | Bloomberg ESG scores, carbon intensity, governance metrics per company |
| **Credit Risk (CDS Spreads)** | `CDSW <GO>` | 5Y CDS spreads for Indian corporates and sovereign — real market-priced credit risk |
| **Implied Volatility Surface** | `OVDV <GO>` | Full vol surface for Nifty options — term structure, skew, smile |
| **Fund Flow Data** | `FLOW <GO>` | Real-time FII/DII daily flows, sector-wise allocation shifts |
| **Supply Chain Mapping** | `SPLC <GO>` | Revenue exposure by customer/supplier for any company |
| **Earnings Transcripts** | `NT <GO>` | Full text of earnings call transcripts — can feed into NLP analysis |
| **M&A / Deal Analytics** | `MA <GO>` | Transaction comps, premium analysis, deal pipeline |
| **Custom Screening** | `EQS <GO>` | Multi-factor stock screening with 5000+ fields |
| **Portfolio Analytics** | `PORT <GO>` | Upload portfolio, get risk decomposition, factor exposure, VaR |

---

## Data Pipeline Architecture (Current + Planned)

```
Bloomberg Terminal (Student Access)
  |
  +-- Excel BDH/BDP/BDS --> CSV Export --> Upload Pipeline --> DB Tables
  |
  +-- Python blpapi/xbbg --> Direct API --> Pipeline Scripts --> DB Tables
  |                         (requires terminal running on same machine)

Free APIs (Always Available)
  |
  +-- yfinance -----------> stock_pipeline.py -----> stock_prices (CONNECTED)
  +-- MFAPI --------------> mf_pipeline.py -------> mf_navs (CONNECTED)
  +-- niftystocks --------> universe.py ----------> stock_universe (CONNECTED)
  +-- Metals-API ---------> commodity_pipeline.py -> commodity_prices (PLANNED)
  +-- FRED API -----------> macro_pipeline.py -----> macro_indicators (PLANNED)
  +-- CoinGecko ----------> crypto_pipeline.py ----> crypto_prices (PLANNED)
  +-- ExchangeRate-API ---> forex_pipeline.py -----> forex_rates (PLANNED)

Manual Upload (For Bloomberg-sourced / Non-API data)
  |
  +-- CSV Upload Endpoint -> /api/v1/data/upload --> Appropriate DB Table
  +-- Supports: Corporate bonds, PMS, AIF, Unlisted equity, Real estate
```
