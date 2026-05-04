# Foundation Reference Entry 12.1: Mandate Schema and Constraints

**Topic:** 12 Mandate Management
**Entry:** 12.1
**Title:** Mandate Schema and Constraints
**Status:** Locked (cluster 2)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 10.7 (Canonical Entity Schemas; Mandate and MandateVersion definitions)
- FR Entry 12.0 (M1 Overview; uses these constraint definitions)
- FR Entry 12.2 (Amendment Workflow; constraints are the units of change)
- CP Chunk 2.1, 2.2, 2.3 (form, conversational, amendment chunks)
- Future cluster references (cluster 8 governance gate evaluates proposed actions against these constraints; cluster 10 portfolio analytics monitors drift against these constraints)

## Cross-references Out

- FR Entry 11.1 (I0 Active Layer; provides defaults for liquidity_floor and asset allocation)
- FR Entry 10.7 (the schema-level definition of MandateVersion fields)

---

## 1. Purpose

This entry specifies the five constraint families that comprise a mandate in cluster 2 scope. Each family defines a distinct dimension of investment policy that downstream components evaluate against. The five families together provide enough constraint surface to demonstrate meaningful mandate compliance (cluster 8 governance gate) and drift monitoring (cluster 10 portfolio analytics) without modelling every conceivable IPS constraint.

The constraint families:

1. Asset allocation bands.
2. Single-position concentration limit.
3. Liquidity floor.
4. Sector exposure cap.
5. Prohibited instruments list.

Production-readiness phase or future clusters may add additional constraint families (ESG screens, derivatives policies, leverage limits, geographic restrictions, currency exposure rules). The five locked here are the cluster 2 demo-stage scope.

## 2. Constraint Family 1: Asset Allocation Bands

### 2.1 Definition

Asset allocation bands define minimum and maximum percentages of the investor's portfolio that should be allocated to each major asset class. The bands constrain rebalancing decisions: a portfolio that drifts outside the bands is non-compliant and triggers rebalancing recommendations.

In cluster 2, three asset classes are modelled: equity, debt, and alternatives. Alternatives is a catch-all for non-equity-non-debt instruments (gold, real estate, REITs, structured products, alternative investment funds).

### 2.2 Schema Fields

```
equity_min_pct (integer, 0-100)
equity_max_pct (integer, 0-100; >= equity_min_pct)
debt_min_pct (integer, 0-100)
debt_max_pct (integer, 0-100; >= debt_min_pct)
alternatives_min_pct (integer, 0-100)
alternatives_max_pct (integer, 0-100; >= alternatives_min_pct)
```

### 2.3 Validation Rules

Within-class: max >= min for each pair.

Cross-class:
- Sum of minimums must be <= 100. Otherwise the portfolio cannot be fully allocated within the minimums.
- Sum of maximums must be >= 100. Otherwise the portfolio cannot reach 100% within the maximums.

These are hard validation rules; failures block submission.

### 2.4 I0 Defaults

Defaults pre-populate based on the investor's risk_appetite (from cluster 1 I0):

| Risk Appetite | Equity (min-max) | Debt (min-max) | Alternatives (min-max) |
|---|---|---|---|
| aggressive | 70-90 | 5-25 | 5-15 |
| moderate | 50-70 | 20-40 | 5-15 |
| conservative | 30-50 | 40-60 | 5-15 |

The defaults are starting points; the advisor can adjust during creation or amendment.

### 2.5 Downstream Use

The governance gate (cluster 8) checks: when a proposed action (buy, sell, rebalance) is evaluated, the resulting portfolio's asset allocation must fall within the bands. Actions that would push the portfolio outside the bands are flagged.

The portfolio analytics (cluster 10) monitors: daily, the portfolio's current allocation is computed and compared against the bands. Drift outside the bands triggers alerts.

## 3. Constraint Family 2: Single-Position Concentration Limit

### 3.1 Definition

Maximum percentage of the investor's portfolio held in any single instrument (single ticker, single mutual fund, single PMS, etc.). Limits concentration risk by preventing over-exposure to any single position.

### 3.2 Schema Fields

```
single_position_max_pct (integer, 0-100)
```

### 3.3 Validation Rules

Hard rule: integer between 0 and 100.

Soft warning: warn if the value is outside the typical 3-10% range. Values like 1% are very restrictive (might be intentional for highly diversified portfolios but unusual for HNI clients); values like 20% are very permissive (might be intentional for concentrated value strategies but elevate concentration risk).

### 3.4 Defaults

Default: 5%. This reflects industry-standard practice for HNI portfolios. Not derived from I0; uses a fixed default.

The advisor can adjust during creation or amendment.

### 3.5 Downstream Use

Governance gate (cluster 8): when a proposed buy would result in a single position exceeding this percentage, the action is flagged. When a holding is currently above this limit, recommendations to add to that position are blocked.

Portfolio analytics (cluster 10): daily check of largest position size against the limit; alerts if exceeded.

## 4. Constraint Family 3: Liquidity Floor

### 4.1 Definition

Minimum percentage of the investor's portfolio held in highly liquid instruments. Highly liquid instruments are defined per a deployment-level configuration but typically include: cash equivalents, money market funds, short-duration debt funds with no exit load, liquid mutual fund schemes.

The floor ensures the investor has accessible reserves matching their I0-determined liquidity needs.

### 4.2 Schema Fields

```
liquidity_floor_pct (integer, 0-100)
```

### 4.3 Validation Rules

Hard rule: integer between 0 and 100.

Soft warning: warn if significantly different from I0-suggested default (more than 10 percentage points off in either direction). The warning text explains the I0 source and the suggested value, asking the advisor to confirm if the divergence is intentional.

### 4.4 I0 Defaults

Defaults pre-populate based on the investor's liquidity_tier (from I0):

| Liquidity Tier | Default liquidity_floor_pct |
|---|---|
| essential | 10 |
| secondary | 20 |
| deep | 30 |

These match the percentage ranges I0 communicates for each tier (per FR Entry 11.1 §3.3): essential is 5-15%, secondary 15-30%, deep 30%+. The defaults pick the midpoint or the floor of the range.

### 4.5 Downstream Use

Governance gate (cluster 8): proposed actions that would reduce portfolio liquidity below the floor are flagged or blocked depending on the magnitude of the breach.

Portfolio analytics (cluster 10): daily check of portfolio's liquid asset percentage against the floor; alerts if breached.

## 5. Constraint Family 4: Sector Exposure Cap

### 5.1 Definition

Maximum percentage of the investor's portfolio in any single sector. Sectors are defined using GICS Sector classification (the 11 top-level sectors): Energy, Materials, Industrials, Consumer Discretionary, Consumer Staples, Health Care, Financials, Information Technology, Communication Services, Utilities, Real Estate.

The cap limits sector concentration risk. A portfolio overweight in any single sector is more vulnerable to sector-specific shocks.

### 5.2 Schema Fields

```
sector_max_pct (integer, 0-100)
```

### 5.3 Validation Rules

Hard rule: integer between 0 and 100.

Soft warning: warn if outside the typical 15-40% range. Values below 15% are very restrictive (would force a portfolio across many sectors which may not match the investor's conviction); values above 40% are permissive (concentration risk is high).

### 5.4 Defaults

Default: 25%. Industry-standard practice for HNI portfolios; reflects a moderate constraint that prevents excessive sector concentration without forcing over-diversification. Not derived from I0.

### 5.5 Downstream Use

Governance gate (cluster 8): proposed actions that would increase a sector's exposure above the cap are flagged. When sector exposure is currently above the cap, additions to that sector are blocked.

Portfolio analytics (cluster 10): daily computation of per-sector exposure; alerts on caps breached.

### 5.6 Sector Classification Source

In cluster 2, sector classification per instrument is not yet implemented (because holdings don't exist yet; cluster 4 ships them). The mandate's sector_max_pct field exists and is validated, but the runtime check (computing actual sector exposure of a portfolio) is a cluster 4-onward concern.

The sector classification per instrument is a D0 concern (cluster 3 D0 data foundation). Each holding will have an associated GICS Sector classification; portfolio analytics aggregates across holdings.

## 6. Constraint Family 5: Prohibited Instruments List

### 6.1 Definition

A list of specific instruments or instrument categories the investor explicitly excludes from their portfolio. Used as a hard exclusion: the governance gate blocks any action that would add a prohibited instrument to the portfolio.

The prohibited list captures investor preferences that go beyond standard asset allocation: ethical exclusions (tobacco, alcohol, weapons, gambling), thematic exclusions (fossil fuels, deforestation), specific instrument exclusions (a particular company the investor distrusts), or category exclusions (private equity, derivatives).

### 6.2 Schema Fields

```
prohibited_instruments (JSON array of strings; max 50 items, each 1-200 characters)
```

### 6.3 Validation Rules

Hard rules:
- Array can be empty (no prohibitions).
- Maximum 50 items.
- Each item is a string of 1-200 characters.

No soft warnings on the list itself; advisor judgement determines what's appropriate.

### 6.4 Defaults

Default: empty array. Investors who want no prohibitions have nothing in this list. The advisor adds entries during creation or amendment as the investor's preferences dictate.

### 6.5 String Format and Matching Strategy

Each entry in the prohibited list is a free-form string. In cluster 2, the strings are stored verbatim and compared by substring matching during governance gate evaluation:

- Specific tickers: "ITC Limited" matches the holding "ITC Limited" exactly.
- Categories: "tobacco stocks" matches holdings whose sector classification or category metadata includes "tobacco".
- Thematic: "fossil fuel companies" matches holdings tagged with "fossil fuel" in their metadata.

The matching strategy is a cluster 8 governance gate concern (when actually checking compliance against proposed actions). Cluster 2's mandate just stores the strings; the matching logic is implemented when the governance gate consumes them.

In cluster 2, the form/C0 path can suggest common prohibitions as auto-complete options (tobacco, alcohol, weapons, gambling, fossil fuels, etc.) but doesn't enforce a specific format.

### 6.6 Downstream Use

Governance gate (cluster 8): every proposed buy is checked against the prohibited list. A match (per the matching strategy) blocks the action.

Portfolio analytics (cluster 10): existing holdings are checked against the prohibited list; if a holding is in the list (e.g., a stock added to prohibited list after it was purchased), the holding is flagged for advisor review.

## 7. Constraint Family Interactions

The five constraint families are largely independent but have a few cross-constraint relationships:

### 7.1 Asset Allocation and Liquidity Floor

If the asset allocation's debt minimum is high (e.g., debt_min=50) and the investor's liquidity_floor is also high (e.g., 30), the constraints are compatible because debt instruments can be liquid. But if the debt minimum is the primary path to meeting both, the actual debt holdings need to be in liquid debt (money market, short duration), not illiquid debt.

This isn't enforced by the mandate validation; it's something the governance gate (cluster 8) and portfolio analytics (cluster 10) compute when monitoring actual holdings.

### 7.2 Sector Cap and Asset Allocation

Sector cap limits within an asset class. For equity, the sector cap is meaningful (max 25% in any GICS sector). For debt, the sector concept is less applicable (debt sectors are typically duration buckets, not GICS sectors). For alternatives, the sector concept varies (REITs have sector classification; gold doesn't).

In cluster 2, the sector cap applies to the equity portion of the portfolio. Cluster 4 onwards may extend sector concepts to other asset classes; cluster 2 leaves this as a future concern.

### 7.3 Prohibited Instruments and Asset Allocation

Prohibited instruments don't reduce the available asset allocation; they just exclude specific instruments. If an investor prohibits all tobacco companies, the portfolio still allocates 50-70% to equity (per the band), just selecting non-tobacco equities.

If the prohibited list is so extensive that it makes the asset allocation unachievable, that's a real product-level concern but not something the mandate validation catches in cluster 2.

## 8. Constraint Updates and Amendment Behavior

When an amendment is proposed, the constraint values from the active version are copied into the draft as starting points. The advisor edits values that should change. On submission, the validation rules apply to the final values.

The "amendment" is conceptually a delta from the active version, but technically the new MandateVersion stores the full constraint values (not just the changes). This makes the amendment self-contained: any version can be read independently to know the full constraint state.

The diff view (in the CIO's amendment review surface) computes the visual diff at display time by comparing the proposed version's values against the active version's values.

## 9. Acceptance Criteria for Cluster 2

The constraint specification is considered locked when:

1. All five constraint families are correctly captured in the MandateVersion schema (per FR Entry 10.7 §3.2).

2. Validation rules in §2.3, §3.3, §4.3, §5.3, §6.3 are enforced at the server-side validation layer. Hard rules block submission; soft warnings are returned in a `warnings` array.

3. I0 defaults per §2.4, §4.4 are correctly computed based on investor's risk_appetite and liquidity_tier.

4. Form path (chunk 2.1) and C0 conversational path (chunk 2.2) display I0 source labels alongside default values.

5. Soft warnings on I0 divergence are surfaced to the advisor without blocking submission.

6. The prohibited instruments list correctly stores up to 50 items, each up to 200 characters.

7. Amendment proposal copies all constraint values from the active version into the draft as starting points.

8. Diff view correctly displays changed vs unchanged constraints across the five families.

## 10. Open Questions

Whether to add constraint families incrementally during cluster 2 or stick to the locked five is open. Working answer: stick to five. Future clusters add more.

Whether the sector cap should be defined per-sector (different caps for different sectors, e.g., max 20% in IT, max 30% in Financials) or as a single global cap is open. Working answer: single global cap in cluster 2; per-sector caps are a richer feature deferred to future clusters.

Whether the prohibited instruments list should support exact-match-only or fuzzy-match (e.g., "tobacco stocks" matching multiple tobacco-related holdings) is open. Working answer: cluster 2 stores the strings; cluster 8 governance gate decides the matching strategy when consuming them. Cluster 8 will likely use substring-and-keyword matching; cluster 2 doesn't pre-impose a format.

Whether the asset allocation should support more than three asset classes (e.g., adding cash, REITs, foreign equity as separate classes) is open. Working answer: three classes (equity, debt, alternatives) in cluster 2. The "alternatives" class is intentionally broad to absorb anything non-equity-non-debt. Future clusters may split alternatives further if needed.

## 11. Revision History

April 2026 (cluster 2 drafting pass): Initial entry authored. Five constraint families fully specified. Validation rules, I0 defaults, downstream uses, cross-constraint interactions all locked.

---

**End of FR Entry 12.1.**
