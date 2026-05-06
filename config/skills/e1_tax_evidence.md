---
agent_id: e1_tax_evidence
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 2500
temperature: 0.0
output_schema_ref: ../schemas/e1_evidence_verdict.json
---

# E1 Tax Evidence — Skill Draft (cluster 5)

**Tier:** Evidence
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Reason about tax implications of a proposed action: STCG vs LTCG
holding-period thresholds, harvesting opportunities, set-off rules,
DTAA flags, GIFT-City routing impact.

## Inputs

- proposed action details
- `indian_context.tax_matrix`
- `indian_context.gift_city_routing`
- holding-period data from snapshot bundle

## Notes

Temperature pinned at 0.0 — tax outputs must be deterministic (the
client repeats the same action twice, expects the same tax view).
