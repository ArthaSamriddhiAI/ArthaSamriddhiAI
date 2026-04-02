# Bloomberg Terminal Data Extraction Guide
### For ArthaSamriddhiAI Data Pipeline

**Prepared for:** Student Research Assistants
**Purpose:** Systematic extraction of financial data from Bloomberg Terminal for the ArthaSamriddhiAI Portfolio Operating System
**Prerequisite:** Access to a Bloomberg Terminal (IMT CFM Lab or equivalent)

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Bloomberg Navigation Basics](#2-bloomberg-navigation-basics)
3. [Excel Add-In Setup](#3-excel-add-in-setup)
4. [Core Functions: BDP, BDH, BDS](#4-core-functions-bdp-bdh-bds)
5. [Data Extraction Tasks](#5-data-extraction-tasks)
   - Task A: Stock Fundamentals (Nifty 500)
   - Task B: Mutual Fund Risk Metrics
   - Task C: Government Bond Yield Curve
   - Task D: Corporate Bond Universe
   - Task E: Gold & Commodities
   - Task F: Forex Rates
   - Task G: Derivatives & Volatility
   - Task H: Macro Economic Indicators
   - Task I: ESG Scores
   - Task J: Analyst Consensus & Ownership
   - Task K: PMS / AIF Data
6. [Python API Method (Advanced)](#6-python-api-method-advanced)
7. [File Naming & Delivery](#7-file-naming--delivery)
8. [Troubleshooting & Limits](#8-troubleshooting--limits)

---

## 1. Getting Started

### Before You Begin
- [ ] Log into the Bloomberg Terminal using your institution credentials
- [ ] Ensure Microsoft Excel is installed on the same machine
- [ ] Create a working folder: `C:\BBG_Data\ArthaSamriddhi\`
- [ ] Have the Nifty 500 ticker list ready (provided separately as CSV)

### Bloomberg Terminal Login
1. Double-click the Bloomberg icon on the desktop
2. Press **ENTER** to activate
3. Type your Bloomberg login credentials
4. Press **ENTER** twice to reach the main screen

### Important Rules
- **Download limits exist.** Academic terminals have monthly data caps. Be efficient.
- **One security at a time** for large historical downloads to avoid timeouts.
- **Save frequently.** Bloomberg sessions can disconnect.
- **No screenshots of Bloomberg data.** Export only via Excel or CSV.

---

## 2. Bloomberg Navigation Basics

### Key Concepts
- **Yellow Keys:** Market sector selectors on the keyboard — `EQUITY`, `GOVT`, `CORP`, `CMDTY`, `CURNCY`, `INDEX`
- **Green Key (GO):** Executes a command. Same as pressing ENTER.
- **Security Identifier:** Ticker + market sector. Examples:
  - `RELIANCE IN Equity` (Reliance Industries on NSE)
  - `GIND10YR Index` (India 10-Year G-Sec Yield)
  - `XAU Curncy` (Gold spot price)
  - `USDINR Curncy` (USD/INR exchange rate)

### Essential Navigation Commands

| Command | What It Does |
|---------|-------------|
| `RELIANCE IN Equity <GO>` | Load Reliance Industries security |
| `DES <GO>` | Description page for loaded security |
| `GP <GO>` | Price graph |
| `FA <GO>` | Financial analysis (income statement, balance sheet) |
| `ANR <GO>` | Analyst recommendations |
| `OWN <GO>` | Ownership structure |
| `GC <GO>` | Government bond yield curve |
| `SRCH <GO>` | Multi-asset search/screening |
| `EQS <GO>` | Equity screening |
| `FLDS <GO>` | Field search (find data field mnemonics) |
| `FUND <GO>` | Fund/MF/PMS search |
| `ECST <GO>` | Economic statistics |
| `ESG <GO>` | ESG scores and data |
| `HELP HELP <GO>` | Live chat with Bloomberg helpdesk |

---

## 3. Excel Add-In Setup

### Step 1: Open Bloomberg Excel Add-In
1. Open Microsoft Excel
2. Go to **Bloomberg** tab in the ribbon (top menu)
3. If no Bloomberg tab, go to: File > Options > Add-Ins > Manage: COM Add-ins > Go > Check "Bloomberg Excel Tools"
4. Click **Bloomberg** tab > **Import Data**

### Step 2: Verify Connection
1. In any cell, type: `=BDP("RELIANCE IN Equity","PX_LAST")`
2. Press ENTER
3. If you see a price (e.g., 1285.50), the connection is working
4. If you see `#N/A`, check that the Bloomberg Terminal is running

### Step 3: Enable Real-Time Updates (Optional)
- Bloomberg tab > Real-Time/Historical > Select "Historical" for batch downloads
- This prevents unnecessary real-time data calls that count against your limit

---

## 4. Core Functions: BDP, BDH, BDS

### BDP — Bloomberg Data Point (Single Value)
```
=BDP("RELIANCE IN Equity", "PX_LAST")           → Current price
=BDP("RELIANCE IN Equity", "PE_RATIO")           → P/E ratio
=BDP("RELIANCE IN Equity", "CUR_MKT_CAP")        → Market cap
=BDP("RELIANCE IN Equity", "BEST_TARGET_PRICE")   → Analyst target price
```

### BDH — Bloomberg Data History (Time Series)
```
=BDH("RELIANCE IN Equity", "PX_LAST", "01/01/2016", "03/31/2026")
=BDH("RELIANCE IN Equity", "PX_LAST", "01/01/2016", "", "per=M")    → Monthly
=BDH("RELIANCE IN Equity", "PE_RATIO", "01/01/2020", "")             → Daily PE
```
**Key optional parameters:**
- `"per=D"` — Daily (default)
- `"per=W"` — Weekly
- `"per=M"` — Monthly
- `"per=Q"` — Quarterly
- `"CDR=5D"` — Calendar: 5-day week (skip weekends)
- `"FILL=P"` — Fill missing dates with previous value

### BDS — Bloomberg Data Set (Tabular Data)
```
=BDS("RELIANCE IN Equity", "BEST_ANALYST_RECS_BULK")    → All analyst recs
=BDS("NIFTY Index", "INDX_MWEIGHT")                      → Index constituents + weights
=BDS("RELIANCE IN Equity", "ERN_ANN_DT_AND_PER")         → Earnings dates
```

---

## 5. Data Extraction Tasks

### TASK A: Stock Fundamentals (Nifty 500)

**Purpose:** Enrich stock data beyond price/volume with fundamental metrics.

**Output file:** `nifty500_fundamentals_YYYYMMDD.csv`

#### Step-by-Step:
1. Open a new Excel workbook
2. In column A, list all Nifty 500 tickers in Bloomberg format:
   ```
   A1: RELIANCE IN Equity
   A2: TCS IN Equity
   A3: HDFCBANK IN Equity
   ... (500 rows)
   ```
   **Tip:** If you have NSE symbols, convert by appending ` IN Equity`. E.g., `RELIANCE` → `RELIANCE IN Equity`

3. In row 1, starting B1, add these BDP formulas for the first ticker:
   ```
   B1: =BDP(A1, "PX_LAST")              → Last price
   C1: =BDP(A1, "PE_RATIO")             → P/E ratio
   D1: =BDP(A1, "PX_TO_BOOK_RATIO")     → P/B ratio
   E1: =BDP(A1, "RETURN_COM_EQY")       → Return on equity
   F1: =BDP(A1, "BEST_EPS")             → Consensus EPS
   G1: =BDP(A1, "BEST_TARGET_PRICE")    → Analyst target price
   H1: =BDP(A1, "CUR_MKT_CAP")          → Market cap (local currency)
   I1: =BDP(A1, "TRAIL_12M_GROSS_REV")  → Revenue TTM
   J1: =BDP(A1, "EBITDA")               → EBITDA
   K1: =BDP(A1, "TOT_DEBT_TO_TOT_EQY")  → Debt/Equity
   L1: =BDP(A1, "DVD_YLD_IND")          → Dividend yield
   M1: =BDP(A1, "VOLATILITY_260D")      → 260-day volatility
   N1: =BDP(A1, "BETA_RAW_OVERRIDABLE")  → Beta
   O1: =BDP(A1, "SHORT_INT")            → Short interest
   P1: =BDP(A1, "GICS_SECTOR_NAME")     → Sector name
   Q1: =BDP(A1, "GICS_INDUSTRY_NAME")   → Industry name
   ```

4. Drag formulas down to row 500
5. **Wait for all cells to populate** (may take 5-10 minutes for 500 stocks)
6. Copy all data > Paste Values (Ctrl+Shift+V) to remove formulas
7. Save as CSV: `nifty500_fundamentals_YYYYMMDD.csv`

#### Frequency: Monthly (first week of each month)

---

### TASK B: Mutual Fund Risk Metrics

**Purpose:** Get risk-adjusted return metrics not available from MFAPI.

**Output file:** `mf_risk_metrics_YYYYMMDD.csv`

#### Step-by-Step:
1. Find Bloomberg tickers for Indian MFs:
   - On terminal: `FUND <GO>`
   - Filter: Country = India, Fund Type = Open-End
   - Export the list

2. Common Bloomberg tickers for Indian MFs:
   ```
   SBIMCEQ IN Equity    (SBI Bluechip)
   HABOREG IN Equity    (HDFC Top 100)
   MPFCGDI IN Equity    (Mirae Asset Large Cap)
   ```
   **Note:** Not all AMFI scheme codes map to Bloomberg tickers. Search by fund house name.

3. For each fund, extract:
   ```
   =BDP(A1, "FUND_NET_ASSET_VAL")        → NAV
   =BDP(A1, "FUND_TOTAL_ASSETS")          → AUM
   =BDP(A1, "FUND_SHARPE_RATIO")          → Sharpe ratio
   =BDP(A1, "FUND_STANDARD_DEVIATION")    → Std deviation
   =BDP(A1, "FUND_MAX_DRAWDOWN")          → Max drawdown
   =BDP(A1, "FUND_INFORMATION_RATIO")     → Information ratio
   =BDP(A1, "FUND_SORTINO_RATIO")         → Sortino ratio
   =BDP(A1, "FUND_ALPHA")                 → Alpha
   =BDP(A1, "FUND_BETA")                  → Beta
   =BDP(A1, "FUND_EXPENSE_RATIO")         → Expense ratio
   =BDP(A1, "FUND_INCEPT_DT")             → Inception date
   ```

4. For holdings:
   ```
   =BDS(A1, "FUND_HOLDINGS")              → Top holdings table
   =BDS(A1, "FUND_SECTOR_ALLOCATION")     → Sector breakdown
   ```

5. Save as CSV: `mf_risk_metrics_YYYYMMDD.csv`

#### Frequency: Monthly

---

### TASK C: Government Bond Yield Curve

**Purpose:** Full Indian G-Sec yield curve for fixed income analysis.

**Output file:** `gsec_yield_curve_YYYYMMDD.csv`

#### Step-by-Step:
1. On terminal: `GC <GO>` → Select India → View the yield curve
2. In Excel, extract yields for standard tenors:
   ```
   =BDP("GIND1YR Index", "PX_LAST")     → 1Y yield
   =BDP("GIND2YR Index", "PX_LAST")     → 2Y yield
   =BDP("GIND3YR Index", "PX_LAST")     → 3Y yield
   =BDP("GIND5YR Index", "PX_LAST")     → 5Y yield
   =BDP("GIND7YR Index", "PX_LAST")     → 7Y yield
   =BDP("GIND10YR Index", "PX_LAST")    → 10Y yield
   =BDP("GIND15YR Index", "PX_LAST")    → 15Y yield
   =BDP("GIND30YR Index", "PX_LAST")    → 30Y yield
   ```

3. For historical yield curve (10Y):
   ```
   =BDH("GIND10YR Index", "PX_LAST", "01/01/2016", "", "per=D")
   ```

4. RBI policy rate:
   ```
   =BDP("INRPYLDP Index", "PX_LAST")    → RBI repo rate
   ```

5. Save as CSV: `gsec_yield_curve_YYYYMMDD.csv`

#### Frequency: Weekly (every Monday)

---

### TASK D: Corporate Bond Universe

**Purpose:** Build Indian corporate bond database with credit metrics.

**Output file:** `corp_bonds_india_YYYYMMDD.csv`

#### Step-by-Step:
1. On terminal: `SRCH <GO>`
2. Set filters:
   - Security Type: Corporate Bond
   - Country: India
   - Currency: INR
   - Amount Outstanding: > 100 Cr
   - Maturity: > 1 year
3. Click **Search** → You'll get a list of bonds
4. Click **Export to Excel** (Actions menu > Export)

5. For each bond, add columns:
   ```
   =BDP([ISIN] & " Corp", "YLD_YTM_MID")           → Yield to maturity
   =BDP([ISIN] & " Corp", "CRNCY_ADJ_OAS")          → Option-adjusted spread
   =BDP([ISIN] & " Corp", "RTG_SP")                  → S&P rating
   =BDP([ISIN] & " Corp", "RTG_MOODY")               → Moody's rating
   =BDP([ISIN] & " Corp", "RTG_FITCH")               → Fitch rating
   =BDP([ISIN] & " Corp", "ISSUE_SZ")                → Issue size
   =BDP([ISIN] & " Corp", "CPN")                     → Coupon rate
   =BDP([ISIN] & " Corp", "MATURITY")                → Maturity date
   =BDP([ISIN] & " Corp", "CALLABLE")                → Is callable?
   =BDP([ISIN] & " Corp", "ISSUER")                  → Issuer name
   =BDP([ISIN] & " Corp", "INDUSTRY_SECTOR")         → Sector
   ```

6. Save as CSV: `corp_bonds_india_YYYYMMDD.csv`

#### Frequency: Monthly

---

### TASK E: Gold & Commodities

**Purpose:** Commodity price history and MCX-relevant data.

**Output file:** `commodities_history_YYYYMMDD.csv`

#### Step-by-Step:
1. Historical prices (10 years, daily):
   ```
   =BDH("XAU Curncy", "PX_LAST", "01/01/2016", "")       → Gold (USD/oz)
   =BDH("XAG Curncy", "PX_LAST", "01/01/2016", "")       → Silver (USD/oz)
   =BDH("CO1 Comdty", "PX_LAST", "01/01/2016", "")       → Brent Crude
   =BDH("CL1 Comdty", "PX_LAST", "01/01/2016", "")       → WTI Crude
   =BDH("HG1 Comdty", "PX_LAST", "01/01/2016", "")       → Copper
   =BDH("NG1 Comdty", "PX_LAST", "01/01/2016", "")       → Natural Gas
   ```

2. MCX-specific (India):
   ```
   =BDH("MAUGOLD Index", "PX_LAST", "01/01/2020", "")    → MCX Gold Near Month
   =BDH("MAUSILVE Index", "PX_LAST", "01/01/2020", "")   → MCX Silver
   ```

3. Gold in INR per 10 grams:
   ```
   =BDH("GOLDINR Index", "PX_LAST", "01/01/2016", "")
   ```
   If not available, calculate: Gold USD/oz * USDINR / 31.1035 * 10

4. Save as CSV

#### Frequency: Daily (if possible) or Weekly

---

### TASK F: Forex Rates

**Purpose:** Exchange rate data for NRI clients and international exposure.

**Output file:** `forex_rates_YYYYMMDD.csv`

#### Step-by-Step:
```
=BDH("USDINR Curncy", "PX_LAST", "01/01/2016", "")     → USD/INR
=BDH("EURINR Curncy", "PX_LAST", "01/01/2016", "")     → EUR/INR
=BDH("GBPINR Curncy", "PX_LAST", "01/01/2016", "")     → GBP/INR
=BDH("JPYINR Curncy", "PX_LAST", "01/01/2016", "")     → JPY/INR
=BDH("DXY Curncy", "PX_LAST", "01/01/2016", "")         → Dollar Index
```

#### Frequency: Daily

---

### TASK G: Derivatives & Volatility

**Purpose:** Options data, implied volatility, India VIX.

**Output file:** `volatility_data_YYYYMMDD.csv`

#### Step-by-Step:
1. India VIX history:
   ```
   =BDH("INVIXN Index", "PX_LAST", "01/01/2016", "")    → India VIX
   ```

2. Nifty options implied volatility (on terminal):
   - Type `NIFTY IN Index <GO>` then `OVDV <GO>`
   - Select: ATM implied vol, 1M/3M/6M/1Y tenors
   - Export to Excel

3. Nifty futures basis:
   ```
   =BDH("NFZ6 Index", "PX_LAST", "01/01/2026", "")     → Nifty near-month future
   ```

4. Put-Call ratio (on terminal):
   - `PCR <GO>` for Nifty options

#### Frequency: Daily for VIX, Weekly for vol surface

---

### TASK H: Macro Economic Indicators

**Purpose:** India macroeconomic data for regime detection and context.

**Output file:** `macro_india_YYYYMMDD.csv`

#### Step-by-Step:
1. On terminal: `ECST <GO>` → Select India
2. In Excel:
   ```
   =BDH("INGDPY% Index", "PX_LAST", "01/01/2010", "", "per=Q")     → GDP growth %
   =BDH("INFUTOTY Index", "PX_LAST", "01/01/2016", "", "per=M")     → CPI inflation
   =BDH("INPMMI Index", "PX_LAST", "01/01/2016", "", "per=M")       → Manufacturing PMI
   =BDH("INRPYLDP Index", "PX_LAST", "01/01/2010", "")              → RBI repo rate
   =BDH("INBANKNR Index", "PX_LAST", "01/01/2016", "", "per=M")     → Bank Nifty
   =BDH("MAHESSION Index", "PX_LAST", "01/01/2016", "", "per=W")    → FII net investment
   ```

3. Forex reserves:
   ```
   =BDH("INFORRES Index", "PX_LAST", "01/01/2016", "", "per=W")
   ```

#### Frequency: Monthly (first week)

---

### TASK I: ESG Scores

**Purpose:** ESG data for ESG-conscious HNI clients.

**Output file:** `esg_scores_nifty500_YYYYMMDD.csv`

#### Step-by-Step:
1. For each Nifty 500 stock:
   ```
   =BDP(A1, "ENVIRON_DISCLOSURE_SCORE")    → Environmental score
   =BDP(A1, "SOCIAL_DISCLOSURE_SCORE")     → Social score
   =BDP(A1, "GOVNCE_DISCLOSURE_SCORE")     → Governance score
   =BDP(A1, "ESG_DISCLOSURE_SCORE")        → Combined ESG score
   =BDP(A1, "CARBON_EMISSIONS_SCOPE_1")    → Direct carbon emissions
   ```

2. On terminal for deeper analysis: Load a stock, then `ESG <GO>`

#### Frequency: Quarterly

---

### TASK J: Analyst Consensus & Ownership

**Purpose:** Institutional ownership patterns and analyst views.

**Output file:** `analyst_ownership_YYYYMMDD.csv`

#### Step-by-Step:
1. Analyst consensus:
   ```
   =BDP(A1, "BEST_TARGET_PRICE")           → Consensus target price
   =BDP(A1, "BEST_ANALYST_RATING")         → Avg rating (1=Buy, 5=Sell)
   =BDP(A1, "TOT_BUY_REC")                → # Buy recommendations
   =BDP(A1, "TOT_SELL_REC")               → # Sell recommendations
   =BDP(A1, "TOT_HOLD_REC")               → # Hold recommendations
   ```

2. Ownership:
   ```
   =BDP(A1, "EQY_INST_PCT_SH_OUT")        → Institutional ownership %
   =BDP(A1, "EQY_SH_OUT_TOT")             → Total shares outstanding
   =BDP(A1, "INSIDER_HOLDING_PCT")         → Insider/promoter holding %
   ```

3. FII/DII holdings (BDS for detail):
   ```
   =BDS(A1, "TOP_20_HOLDERS_PUBLIC_FILINGS")   → Top 20 holders
   ```

#### Frequency: Monthly

---

### TASK K: PMS / AIF Data

**Purpose:** Track PMS and AIF performance where available on Bloomberg.

**Output file:** `pms_aif_data_YYYYMMDD.csv`

#### Step-by-Step:
1. On terminal: `FUND <GO>`
2. Set filters:
   - Domicile: India
   - Fund Type: try "Portfolio Management" or "Alternative Investment"
   - Search by name: ASK, Marcellus, Unifi, IIFL, Kotak PMS, etc.
3. For any fund found:
   ```
   =BDP([Ticker], "FUND_NET_ASSET_VAL")
   =BDP([Ticker], "FUND_TOTAL_ASSETS")
   =BDP([Ticker], "FUND_YTD_RETURN")
   =BDP([Ticker], "FUND_1_YEAR_RETURN")
   =BDP([Ticker], "FUND_3_YEAR_RETURN")
   ```
4. **Note:** Coverage may be limited. Document which PMS/AIFs ARE and ARE NOT available.

#### Frequency: Monthly

---

## 6. Python API Method (Advanced)

If the Bloomberg Terminal is on the same machine where Python is installed:

### Setup
```bash
pip install xbbg
# OR for lighter footprint:
pip install blpapi --index-url=https://bcms.bloomberg.com/pip/simple/
pip install bbg-fetch
```

### Example: Bulk Historical Download
```python
from xbbg import blp
import pandas as pd

# Nifty 50 components — historical prices
tickers = ["RELIANCE IN Equity", "TCS IN Equity", "HDFCBANK IN Equity"]
df = blp.bdh(
    tickers=tickers,
    flds=["PX_LAST", "VOLUME"],
    start_date="2016-01-01",
    end_date="2026-03-31"
)
df.to_csv("nifty_prices_bbg.csv")

# Fundamentals snapshot
fund_df = blp.bdp(
    tickers=tickers,
    flds=["PE_RATIO", "PX_TO_BOOK_RATIO", "RETURN_COM_EQY", "CUR_MKT_CAP"]
)
fund_df.to_csv("fundamentals_bbg.csv")

# Yield curve
tenors = ["GIND1YR Index", "GIND2YR Index", "GIND5YR Index", "GIND10YR Index", "GIND30YR Index"]
yc = blp.bdh(tenors, "PX_LAST", "2020-01-01")
yc.to_csv("yield_curve_bbg.csv")
```

### Important:
- Bloomberg Terminal **must be running** on the same machine
- Python connects to `localhost:8194`
- Respect data download limits

---

## 7. File Naming & Delivery

### Naming Convention
```
{dataset}_{YYYYMMDD}.csv
```
Examples:
- `nifty500_fundamentals_20260401.csv`
- `gsec_yield_curve_20260401.csv`
- `corp_bonds_india_20260401.csv`
- `commodities_history_20260401.csv`
- `esg_scores_nifty500_20260401.csv`

### Delivery
1. Save all CSV files to the shared folder
2. Upload to ArthaSamriddhiAI via the data upload endpoint (when available):
   ```
   POST /api/v1/data/upload
   ```
3. Or place in the designated Google Drive / shared folder for manual ingestion

### CSV Format Requirements
- **Encoding:** UTF-8
- **Delimiter:** Comma
- **Header row:** Always include column names in row 1
- **Date format:** YYYY-MM-DD (e.g., 2026-04-01)
- **Numbers:** No thousand separators. Decimals with period (e.g., 1285.50)
- **Missing values:** Leave cell empty (not "N/A" or "#N/A")

---

## 8. Troubleshooting & Limits

### Common Issues

| Issue | Solution |
|-------|----------|
| `#N/A` in cells | Check ticker format. Use `SECF <GO>` on terminal to verify. |
| Cells show `#NAME?` | Bloomberg Excel Add-In not loaded. Check Add-Ins. |
| Very slow response | Reduce number of securities per batch. Do 50-100 at a time. |
| "Request limit reached" | You've hit the monthly download cap. Wait until next month. |
| Wrong prices | Check currency. Use `=BDP(ticker, "CRNCY")` to verify. |
| Missing Indian securities | Try both formats: `RELIANCE IN Equity` and `500325 IS Equity` (BSE code). |

### Download Limits (Academic Terminals)
- **Daily limit:** ~5,000 data points (approximate, varies by institution)
- **Monthly limit:** ~100,000 data points (approximate)
- **Tip:** BDH counts as 1 request per security per field per date. 500 stocks × 1 field × 250 days = 125,000 points. **Batch carefully.**

### Efficient Batching Strategy
1. **Fundamentals (BDP):** Do all 500 stocks at once (500 × 15 fields = 7,500 points)
2. **Historical prices (BDH):** Do 50 stocks at a time, save, then next 50
3. **Yield curve:** Only ~8 tenors — very lightweight
4. **Corporate bonds:** Screen first (SRCH), then extract details for filtered list only
5. **Save immediately** after each batch completes

### Getting Help
- On terminal: `HELP HELP <GO>` → Live chat with Bloomberg support
- Bloomberg University: `BU <GO>` → Free training courses
- Ask your librarian or Bloomberg campus representative

---

## Quick Reference Card

| Data Need | Bloomberg Command | Excel Function | Frequency |
|-----------|------------------|----------------|-----------|
| Stock price | `GP <GO>` | `=BDH(ticker, "PX_LAST", start, end)` | Daily |
| Fundamentals | `FA <GO>` | `=BDP(ticker, "PE_RATIO")` | Monthly |
| Yield curve | `GC <GO>` | `=BDP("GIND10YR Index", "PX_LAST")` | Weekly |
| Corp bonds | `SRCH <GO>` | `=BDP(isin+" Corp", "YLD_YTM_MID")` | Monthly |
| Gold/Silver | `XAU Curncy <GO>` | `=BDH("XAU Curncy", "PX_LAST", start, end)` | Daily |
| India VIX | `INVIXN Index <GO>` | `=BDH("INVIXN Index", "PX_LAST", start, end)` | Daily |
| ESG scores | `ESG <GO>` | `=BDP(ticker, "ESG_DISCLOSURE_SCORE")` | Quarterly |
| Analyst recs | `ANR <GO>` | `=BDP(ticker, "BEST_TARGET_PRICE")` | Monthly |
| Macro data | `ECST <GO>` | `=BDH("INFUTOTY Index", "PX_LAST", start, end)` | Monthly |
| Fund search | `FUND <GO>` | `=BDP(fund_ticker, "FUND_SHARPE_RATIO")` | Monthly |
| Ownership | `OWN <GO>` | `=BDP(ticker, "EQY_INST_PCT_SH_OUT")` | Monthly |
| FX rates | `USDINR Curncy <GO>` | `=BDH("USDINR Curncy", "PX_LAST", start, end)` | Daily |
