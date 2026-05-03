# Foundation Reference Entry 11.1: I0 Active Layer

**Topic:** 11 Investor Context Engine
**Entry:** 11.1
**Title:** I0 Active Layer
**Status:** Locked (cluster 1 chunk 1.1 shipped May 2026)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 11.0 (I0 Investor Context Engine Overview; this entry implements the active layer)
- FR Entry 10.7 (Canonical Entity Schemas; the active layer reads investor fields and writes enrichment fields)
- CP Chunk 1.1, 1.2 (form and conversational onboarding chunks; both call active layer enrichment)

## Cross-references Out

- FR Entry 11.0 (I0 overall architecture)
- FR Entry 10.7 (Investor schema definition)

---

## 1. Purpose

The I0 active layer is the cluster 1 implementation of investor enrichment. It produces life_stage and liquidity_tier classifications from advisor-entered investor fields using rule-based heuristics. The layer runs synchronously as part of investor creation and re-runs whenever enrichment-relevant fields change.

The active layer's design priorities are: deterministic outputs, transparent reasoning, fast computation, defensible classifications. Each is a deliberate choice that reflects the demo-stage context and the production-readiness path.

Deterministic outputs mean the same inputs always produce the same classification. No randomness, no LLM inference, no external API calls. This makes the enrichment replayable, auditable, and debuggable.

Transparent reasoning means the advisor can see why a particular classification was made. The heuristics are stated in plain rules; an advisor encountering an unusual classification can trace back to which rule produced it.

Fast computation means enrichment completes in well under a millisecond per investor. This permits synchronous enrichment as part of the creation transaction without noticeable latency, which simplifies the UX.

Defensible classifications means the rules align with established wealth advisory frameworks. An experienced advisor reviewing the classifications recognises them as reasonable defaults, even if they would refine further with their own judgement.

## 2. Life Stage Inference

### 2.1 Life Stage Classification Rules

The active layer assigns one of four life stage values to each investor, based on age and time_horizon (with risk_appetite as a tiebreaker for edge cases):

**accumulation** life stage applies when the investor is in their wealth-building years, typically pre-retirement with a growth-oriented investment horizon. The rule:

```
IF age in [25, 45] AND time_horizon in [over_5_years, 3_to_5_years]
THEN life_stage = accumulation, confidence = high
```

**transition** life stage applies when the investor is approaching retirement or in a transitional life event, balancing growth with preservation. The rule:

```
IF age in [45, 55] AND any time_horizon
   OR age in [25, 45] AND time_horizon = under_3_years
THEN life_stage = transition
   confidence = high if age in [45, 55], else medium (for the cross-rule case)
```

**distribution** life stage applies when the investor is drawing on accumulated wealth, prioritising preservation and income. The rule:

```
IF age in [55, 70] AND time_horizon in [under_3_years, 3_to_5_years]
THEN life_stage = distribution, confidence = high
```

**legacy** life stage applies when the investor is focused on estate planning and inter-generational transfer. The rule:

```
IF age > 70
   OR (any age AND risk_appetite = conservative AND time_horizon = under_3_years AND age >= 55)
THEN life_stage = legacy
   confidence = high if age > 70, else medium
```

### 2.2 Default and Edge Case Handling

When an investor's profile doesn't cleanly match any rule, the active layer applies the most-restrictive matching rule and flags the classification with `life_stage_confidence: low`.

The most-restrictive ordering, from least to most restrictive: accumulation, transition, distribution, legacy. "Most restrictive" reflects which life stage implies the most caution in investment recommendations.

Specific edge cases:

**Young investor with conservative risk and short horizon** (e.g., age 28, conservative, under_3_years): Unusual profile. Default to `transition` with `confidence: low`. This protects against putting a cautious young investor in growth-oriented recommendations they wouldn't be comfortable with.

**Older investor with aggressive risk and long horizon** (e.g., age 72, aggressive, over_5_years): Unusual profile. Default to `legacy` with `confidence: low`. The age is dominant; the system flags this for advisor judgement.

**Borderline ages** (exactly 45, exactly 55, exactly 70): Inclusive on the lower bound, exclusive on the upper bound, except for the legacy rule which is strictly greater than 70. So age 45 maps to accumulation if horizons match, age 55 maps to transition, age 70 maps to distribution if horizons match.

The `confidence: low` flag is visible to the advisor in the investor profile, signalling that the system's classification deserves human review.

### 2.3 Life Stage Display Semantics

When displaying life_stage in the investor profile UI, each value has an associated label and brief description:

- **accumulation:** "Wealth Building." Investor is building wealth toward future goals; investment focus is growth-oriented with longer time horizons.

- **transition:** "Wealth Transition." Investor is approaching a life transition (retirement, major expense, business sale, etc.); investment focus balances growth and preservation.

- **distribution:** "Income Generation." Investor is drawing on accumulated wealth for current needs; investment focus prioritises stable income and preservation.

- **legacy:** "Estate Planning." Investor is focused on long-term wealth transfer to next generations; investment focus includes tax efficiency and inter-generational considerations.

These labels appear with the value in the UI, e.g., a badge showing "Accumulation: Wealth Building" rather than just the enum value.

## 3. Liquidity Tier Inference

### 3.1 Liquidity Tier Classification Rules

The active layer assigns one of three liquidity_tier values, based on time_horizon and risk_appetite:

**essential** liquidity tier applies when the investor can afford to lock most assets in growth instruments with minimal liquid reserve (5-15% of portfolio in highly liquid instruments). The rule:

```
IF time_horizon = over_5_years AND risk_appetite in [aggressive, moderate]
THEN liquidity_tier = essential, range = "5-15%"
```

**secondary** liquidity tier applies when the investor needs moderate liquid reserves (15-30% of portfolio in liquid-to-semi-liquid instruments). The rule:

```
IF time_horizon = 3_to_5_years
   OR (time_horizon = over_5_years AND risk_appetite = conservative)
THEN liquidity_tier = secondary, range = "15-30%"
```

**deep** liquidity tier applies when the investor needs substantial liquid reserves (30%+ of portfolio in highly liquid instruments). The rule:

```
IF time_horizon = under_3_years
THEN liquidity_tier = deep, range = "30%+"
```

### 3.2 Liquidity Tier Default Handling

The three rules above cover all combinations of time_horizon and risk_appetite, so there are no edge cases requiring fallback. Every valid investor profile maps to exactly one liquidity_tier.

The `liquidity_tier_range` field stores the human-readable range string ("5-15%", "15-30%", "30%+") for display alongside the tier label.

### 3.3 Liquidity Tier Display Semantics

When displaying liquidity_tier in the investor profile UI, each value has an associated label and explanation:

- **essential** (5-15%): "Minimum Liquidity." The investor has long horizons and growth-oriented risk appetite, so most assets can be deployed in growth instruments. Reserve is for emergencies and tactical opportunities.

- **secondary** (15-30%): "Moderate Liquidity." The investor balances growth with the need for accessible reserves. Reserve covers transitional needs and provides flexibility.

- **deep** (30%+): "High Liquidity." The investor has significant near-term needs or conservative profile requiring substantial accessible reserves. Reserve is the primary structure of the portfolio.

These labels and explanations appear with the tier value in the UI.

## 4. Cluster 1 Heuristic Rationale

The heuristics above are not arbitrary; they reflect established wealth advisory frameworks. A few notes on the choices made:

The age boundaries (25, 45, 55, 70) reflect typical career and life event boundaries in Indian high-net-worth contexts. 25 is roughly post-graduation; 45 is mid-career; 55 is approaching retirement; 70 is post-retirement and typically estate-planning age. Other markets might use different boundaries; the boundaries are configurable per deployment if a firm wants to refine.

The liquidity tier ranges (5-15%, 15-30%, 30%+) are common defaults in Indian wealth advisory practice. They are not regulatory; they're practitioner defaults. A firm with a different liquidity framework can override the ranges in deployment configuration.

Risk_appetite as a tiebreaker for life_stage edge cases (specifically the older + conservative + short-horizon edge case mapping to legacy) reflects the principle that in genuinely ambiguous cases, the system errs on the side of preservation.

The decision to use rule-based heuristics rather than LLM inference for I0 active layer is deliberate. LLM-based classification would be more flexible (could handle nuanced edge cases the rules miss) but less defensible, less deterministic, and slower. For demo stage, the rules are sufficient. If production work later wants LLM-augmented classification (e.g., narrative inputs from advisor about the investor's specific circumstances), that's a future cluster's enrichment capability and can be added without disrupting the rule-based foundation.

## 5. Implementation Specification

### 5.1 Active Layer Function Signature

```python
def i0_active_layer_enrich(
    investor: Investor
) -> EnrichmentResult:
    """
    Enrich an investor record with life_stage and liquidity_tier signals.
    
    Pure function over investor.age, investor.risk_appetite, investor.time_horizon.
    Returns an EnrichmentResult with the classifications and confidence.
    """
```

The function is deterministic and side-effect-free. The calling code (in the investor creation transaction) writes the result back to the investor record and emits the T1 telemetry event.

### 5.2 EnrichmentResult Structure

```python
class EnrichmentResult:
    life_stage: Literal["accumulation", "transition", "distribution", "legacy"]
    life_stage_confidence: Literal["high", "medium", "low"]
    liquidity_tier: Literal["essential", "secondary", "deep"]
    liquidity_tier_range: str  # "5-15%" | "15-30%" | "30%+"
    enrichment_version: str  # "i0_active_layer_v1.0"
```

### 5.3 Enrichment Version

The current active layer version is `i0_active_layer_v1.0`. This identifier is written to the Investor record's `enrichment_version` field. When heuristics evolve (the rules change, new tiers are added, age boundaries shift), the version increments.

Records enriched at older versions retain their old classifications until re-enrichment is triggered. This preserves audit replay correctness: a case opened against an investor at enrichment_version v1.0 reasons against the v1.0 classifications, even if v1.1 has been deployed since.

When re-enrichment occurs (advisor edits an enrichment-relevant field), the new version is written.

## 6. Integration with Investor Creation Flow

The active layer integrates with investor creation as follows:

1. Form submission (chunk 1.1) or C0 onboarding (chunk 1.2) or API call (cluster 1 stub) produces an investor record with advisor-entered fields populated.

2. The investor creation service writes the investor record to the database with enrichment fields null.

3. The active layer is called immediately after the write, with the just-created investor as input.

4. The active layer returns the EnrichmentResult.

5. The investor record is updated with the enrichment fields populated, plus enriched_at = current timestamp, enrichment_version = "i0_active_layer_v1.0".

6. T1 telemetry emits `investor_enrichment_completed` with the investor_id and the enrichment result.

7. The UI displays the enriched investor profile to the advisor.

The entire flow from form submission to enriched profile display is sub-second, dominated by network round-trips rather than computation.

## 7. Re-Enrichment Triggers

The active layer re-runs when any of its input fields changes:

- age (e.g., the advisor corrects a typo or the investor has a birthday and the system updates age)
- risk_appetite (e.g., the advisor updates after a re-profiling conversation)
- time_horizon (e.g., the investor's circumstances change and the advisor updates)

The re-enrichment is triggered by an investor update operation that includes any of these fields. The update transaction:

1. Validates the new field values.
2. Updates the investor record.
3. Calls active layer enrichment.
4. Updates enrichment fields in the same transaction.
5. Emits T1 telemetry event `investor_enrichment_recomputed` with old and new values for diff visibility.

Other field updates (name, email, phone, household_id, advisor_id, etc.) do not trigger re-enrichment because they are not inputs to the active layer.

## 8. Telemetry

The active layer emits two T1 event types:

`investor_enrichment_completed`: emitted on initial enrichment after investor creation. Payload includes investor_id, enrichment_version, life_stage, life_stage_confidence, liquidity_tier, liquidity_tier_range, enriched_at.

`investor_enrichment_recomputed`: emitted on re-enrichment after field updates. Payload includes investor_id, enrichment_version, the new values, the old values (for diff), the field that changed, and the actor who changed it.

These events are visible to the audit role in cluster 15 and can be queried for "show me all investors whose life_stage changed in the last quarter" type analyses.

## 9. Acceptance Criteria

The active layer is considered functional when:

1. The standard test cases produce the expected classifications:
   - 30-year-old, moderate, over_5_years → accumulation, essential
   - 50-year-old, moderate, 3_to_5_years → transition, secondary
   - 60-year-old, conservative, under_3_years → distribution, deep
   - 75-year-old, any, any → legacy, tier per horizon-and-risk
   
2. Edge cases produce classifications with `confidence: low` rather than failing:
   - 28-year-old, conservative, under_3_years → transition with low confidence
   - 72-year-old, aggressive, over_5_years → legacy with low confidence
   
3. The enrichment_version field is correctly populated as `i0_active_layer_v1.0`.

4. Synchronous enrichment completes in under 50 milliseconds end-to-end (well within sub-second total flow).

5. Re-enrichment triggered by field changes produces correctly updated values.

6. T1 telemetry events fire with correct payload structure.

7. Determinism: running the same investor through enrichment twice produces identical outputs.

8. Idempotency: calling the active layer on an already-enriched investor produces the same outputs (the function doesn't depend on prior enrichment state).

## 10. Open Questions

Whether the age boundaries (25, 45, 55, 70) and liquidity ranges (5-15%, 15-30%, 30%+) should be deployment-configurable in cluster 1 is open. Working answer: hardcode in cluster 1 for simplicity; allow deployment override in a future cluster if a firm requests different defaults.

Whether the active layer should produce a textual rationale alongside the classifications (e.g., "Classified as accumulation because age 30 and time_horizon over_5_years matches the standard accumulation rule") is open. Working answer: not in cluster 1; the rules are simple enough that the classification is self-explanatory. Future enrichment with LLM augmentation could include rationales.

Whether to support partial re-enrichment (e.g., only recompute liquidity_tier when only time_horizon changes) versus always recomputing both is open. Working answer: always recompute both; the cost is negligible and the simpler code is easier to maintain.

## 11. Revision History

April 2026 (cluster 1 drafting pass): Initial entry authored. Active layer locked at version `i0_active_layer_v1.0`. Heuristics and acceptance criteria specified.

May 2026 (cluster 1 chunk 1.1 shipped): Implementation in `src/artha/api_v2/i0/active_layer.py` — pure-Python deterministic functions, no external dependencies. All 31 unit tests in `tests/test_unit/test_api_v2_i0_active_layer.py` pass: 4 standard cases (FR §9 acceptance test 1), 2 edge cases (acceptance test 2), 4 borderline-age tests (§2.2), 9 liquidity-tier combo tests (§3), 4 operational-property tests (§9 acceptance tests 7 + 8). One implementation note documented in the module docstring: rule precedence resolves an FR §2.1 internal ambiguity around the older-conservative-short-horizon legacy cross-rule (we treat §9 acceptance criteria as the test contract — 60-year-old conservative under_3_years → distribution, not legacy).

---

**End of FR Entry 11.1.**
