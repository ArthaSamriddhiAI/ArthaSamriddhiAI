# Foundation Reference Entry 11.0: I0 Investor Context Engine Overview

**Topic:** 11 Investor Context Engine
**Entry:** 11.0
**Title:** I0 Investor Context Engine Overview
**Status:** Locked overview (cluster 1 chunk 1.1 shipped May 2026); active layer specified + implemented, dormant layer and pattern library deferred
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 10.7 (Canonical Entity Schemas; I0 enriches Investor records)
- FR Entry 11.1 (I0 Active Layer; the cluster 1 implementation of I0)
- CP Chunk 1.1, 1.2 (form and conversational onboarding chunks; both call I0 enrichment after investor creation)
- Future cluster references (cluster 5 case pipeline reads I0 enrichment; cluster 8 governance reads I0 for mandate compliance context; cluster 10 portfolio analytics reads I0 for liquidity tier comparison)

## Cross-references Out

- Principles §3.1 through §3.10 (agent architecture; I0 sits adjacent to but is not part of the evidence agent layer)
- Principles §4.1 (D0 as data layer; I0 is downstream of D0 in the data flow)

---

## 1. Purpose

The I0 Investor Context Engine is the system's specialised reasoning layer for investor-specific context. Where the evidence agent layer (E1 through E7) reasons about portfolios, holdings, and market conditions, I0 reasons about *the investor themselves*: their life stage, their liquidity needs, their patterns of behaviour over time, their structural circumstances that frame how investment recommendations should be tailored.

I0 is what makes Samriddhi AI client-aware rather than just portfolio-aware. A 35-year-old in accumulation life stage with strong liquidity reserves is a fundamentally different recommendation context than a 70-year-old in legacy life stage with modest liquidity reserves, even if their portfolios are identical. I0 makes that distinction structured and consumable.

I0 has three layers in the production architecture: an active layer (current state of the investor), a dormant layer (long-term patterns that emerge over time), and a pattern library (cross-investor pattern recognition that lets the system learn what kinds of investors exhibit what kinds of behaviours). Cluster 1 ships only the active layer; the dormant layer and pattern library are deferred to later clusters because they require accumulated case history and behavioural data that don't exist at cluster 1.

## 2. Architecture

I0 is a service that lives alongside D0 in the data layer architecture. D0 produces canonical investor records; I0 enriches those records with derived signals. Conceptually, I0 is to investors what signal extractors in D0.Normalization are to text-based source data: it transforms raw input into structured signals consumable by downstream components.

I0 does not reason about portfolios, holdings, market conditions, or instruments. Those are evidence agents' concerns. I0 reasons only about the investor as an individual: their demographics, their stated preferences, their temporal patterns, their household context.

I0's outputs are written to the Investor record (per FR Entry 10.7 §2.1) as enrichment fields: `life_stage`, `liquidity_tier`, `enriched_at`, `enrichment_version`. These fields become inputs to every subsequent cluster's reasoning that touches the investor.

### 2.1 Active Layer

The active layer (specified in FR Entry 11.1) is rule-based heuristic enrichment that produces life_stage and liquidity_tier from advisor-entered investor fields. It runs synchronously as part of investor creation and re-runs whenever enrichment-relevant fields change.

The active layer has no dependencies on other system state, no LLM calls, no external API calls. It is pure computation over the investor's own fields, which makes it deterministic, fast, and replayable.

### 2.2 Dormant Layer (Deferred)

The dormant layer holds long-term patterns that emerge from observing the investor over time: their actual liquidity events versus their stated liquidity tier, their decision patterns versus their stated risk appetite, their wealth trajectory versus their stated time horizon. The dormant layer is meant to identify when stated profile diverges from observed reality.

This layer requires accumulated case history (cluster 5 onwards), accumulated behavioural data (cluster 4 onwards as PM1 monitors holdings), and accumulated decision outcomes (cluster 9 onwards as override patterns emerge). All of that data accumulates as the system runs; the dormant layer becomes meaningful after months of system operation.

For demo stage, the dormant layer is reserved as a deferred capability. The Investor schema includes timestamp fields (enriched_at, last_modified_at) that will support dormant layer historical analysis when it comes. No active code, no schema changes pending; just deferred work.

### 2.3 Pattern Library (Deferred)

The pattern library is cross-investor pattern recognition. After observing many investors, the system learns: "investors who present as X often turn out to be Y" or "investors with profile X tend to make decision Y under stress" or "household structure X correlates with decision pattern Y." These cross-investor patterns enrich individual investor classifications by triangulating against population-level observations.

Pattern library work depends on having a large enough population of observed investors plus longitudinal data on each. It is unambiguously a future-cluster capability and may not be in scope for v1.0 at all; it might be a v2 feature. For cluster 1, the pattern library is documented here only to make the I0 architectural picture complete.

## 3. I0 Active Layer Outputs (Cluster 1)

The I0 active layer produces two enrichment outputs:

**life_stage** is the investor's current life stage classification: `accumulation`, `transition`, `distribution`, or `legacy`. The classification reflects where the investor is in the wealth lifecycle. Accumulation is wealth-building (typically pre-retirement working years with growth-oriented horizons). Transition is wealth-preservation onset (typically late-career or peri-retirement, balancing growth and preservation). Distribution is wealth-drawdown (typically retirement, prioritising income and preservation). Legacy is wealth-transfer (typically estate-planning age, prioritising tax-efficient inter-generational transfer).

**liquidity_tier** is the recommended share of the investor's portfolio that should be readily accessible: `essential`, `secondary`, or `deep`. Essential is 5-15% in highly liquid instruments (suitable for long-horizon investors with stable income). Secondary is 15-30% (suitable for moderate-horizon or transitional investors). Deep is 30%+ (suitable for short-horizon investors with significant liquidity needs).

Both outputs come with a confidence flag: `life_stage_confidence` is `high`, `medium`, or `low`. High confidence means the investor's profile is a clean match to the heuristic for their assigned tier; low confidence means the profile is borderline or unusual (e.g., a young investor with conservative risk and short horizon, which is unusual and warrants advisor judgement).

The complete heuristic specification is in FR Entry 11.1.

## 4. Integration Points

### 4.1 Reads From

I0 active layer reads from the canonical Investor record fields entered by the advisor: age, time_horizon, risk_appetite. It does not read from any other system state in cluster 1.

In future clusters, the dormant layer will read from accumulated case history, behavioural events, decision outcomes, and PM1 portfolio events. The pattern library will read from cross-investor anonymised statistics.

### 4.2 Writes To

I0 active layer writes to the Investor record fields: life_stage, life_stage_confidence, liquidity_tier, liquidity_tier_range, enriched_at, enrichment_version.

I0 active layer emits T1 telemetry: `investor_enrichment_completed` event with the investor_id, the enrichment_version, and the resulting life_stage and liquidity_tier values.

### 4.3 Read By

The advisor's investor profile UI surface (cluster 1 chunk 1.1 inline display, future cluster surfaces) reads life_stage and liquidity_tier for display.

Future clusters consume I0 enrichment more substantively:

- Cluster 5 (case pipeline) passes I0 enrichment to evidence agents as part of the case context, so agents reason about portfolio recommendations in the context of the investor's life stage and liquidity needs.
- Cluster 8 (governance gate) checks proposed actions against the investor's liquidity tier (e.g., a recommendation that would drop the investor below their liquidity tier triggers an escalation).
- Cluster 10 (portfolio analytics) computes liquidity coverage of the actual portfolio against the I0-recommended liquidity tier, surfacing drift.
- Cluster 14 (briefings) includes life stage and liquidity context in client briefings.

## 5. Operational Properties

I0 active layer is:

**Deterministic.** Same inputs always produce same outputs. The heuristics are rule-based with no randomness.

**Fast.** Pure computation over a small number of fields; sub-millisecond. No network calls, no database queries beyond the investor record itself, no LLM inference.

**Replayable.** Given the investor's stored field values, the active layer's outputs can be recomputed exactly. Audit replay reconstructs enrichment correctly.

**Versioned.** The `enrichment_version` field captures which version of the active layer's heuristics produced the values. When heuristics evolve (life stage rules refine, liquidity tier ranges adjust), older records remain valid (their values reflect the heuristics at the time) while new investors and re-enriched investors use the new heuristics.

**Idempotent.** Running enrichment twice on the same investor record produces the same outputs. There are no side effects beyond writing the enrichment fields.

## 6. Failure Modes and EX1 Contract

I0 active layer's failure modes are minimal because of its operational simplicity.

### 6.1 Missing Required Field

If an investor record is missing one of the required fields (age, time_horizon, risk_appetite), enrichment cannot run. The active layer returns `null` for life_stage and liquidity_tier, sets life_stage_confidence to `low`, and emits a T1 telemetry event indicating which field was missing.

EX1 routing: this is a data quality issue, not a system failure. The investor record was created in an invalid state; the data layer should have caught it during validation. EX1 alerts on this as a data integrity issue.

### 6.2 Out-of-Range Values

If an investor's age is outside the valid range (under 18 or over 100), or if any enum field has a value not in the enum, validation should have caught this at investor creation. If somehow it slipped through, the active layer returns null outputs and emits a T1 event.

EX1 routing: data integrity issue, same as 6.1.

### 6.3 Re-enrichment Conflicts

If an investor is being re-enriched (because age changed, or risk_appetite was updated), and re-enrichment runs concurrently with another update on the same investor, there's a potential for data race. The implementation handles this by locking the investor record for the duration of enrichment (a brief lock, sub-millisecond) and ensuring the enrichment writes are atomic.

EX1 routing: not a routine concern in cluster 1 because the active layer is so fast that races are essentially impossible. Future async enrichment may need more robust race handling.

## 7. Acceptance Criteria for Cluster 1

I0 active layer is considered functional in cluster 1 when:

1. Creating an investor through any path (form, conversational, API) triggers I0 enrichment that runs synchronously within the investor creation transaction.

2. The enrichment correctly produces life_stage and liquidity_tier per the heuristics in FR Entry 11.1 for inputs that match the standard cases.

3. Edge case inputs (young + conservative + short horizon, old + aggressive + long horizon, etc.) produce a classification with `life_stage_confidence: low` rather than failing.

4. The investor record after creation has all enrichment fields populated: life_stage, life_stage_confidence, liquidity_tier, liquidity_tier_range, enriched_at, enrichment_version.

5. The advisor sees the enriched values in the investor profile UI immediately after creation, without needing to refresh.

6. Re-enrichment (e.g., advisor edits the investor's age) recomputes the values correctly with the new inputs.

7. T1 telemetry captures the enrichment event with all relevant fields.

8. Invalid investor records (missing required enrichment-input fields) handle gracefully without crashing.

## 8. Open Questions

Whether to expose enrichment as an API surface for re-enrichment (so the advisor can manually trigger re-enrichment from the UI without editing fields) is open. Working answer: not in cluster 1; re-enrichment happens automatically on field changes. A manual re-enrichment button can be added later if needed.

Whether the dormant layer's eventual implementation should be a new sub-component (FR Entry 11.2) or an extension of the active layer is open. Working answer: separate sub-component with its own foundation reference entry, because the active and dormant layers have substantially different operational properties (sync vs async, deterministic vs probabilistic, real-time vs batch).

The pattern library's eventual existence (whether v1.0 or v2 capability) is open. Working answer: deferred decision; revisit when accumulated cross-investor data justifies it.

## 9. Revision History

April 2026 (cluster 1 drafting pass): Initial overview entry authored. Active layer specified in FR Entry 11.1. Dormant layer and pattern library reserved as deferred capabilities.

May 2026 (cluster 1 chunk 1.1 shipped): Active layer ships at `i0_active_layer_v1.0` per FR 11.1; runs synchronously inside the investor creation transaction in `src/artha/api_v2/investors/service.py:create_investor`. T1 events `investor_enrichment_completed` (initial) emitted per §4.2; the `investor_enrichment_recomputed` event from §8 is wired but only fires when the future investor-edit surface lands (chunk-scope-out per Demo-Stage Addendum §1.5). Dormant layer + pattern library remain deferred per §2.2 / §2.3.

---

**End of FR Entry 11.0.**
