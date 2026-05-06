---
agent_id: m0_indian_context
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: deterministic
max_tokens: 1
temperature: 0.0
output_schema_ref: ../schemas/m0_indian_context_output.json
---

# M0 Indian Context — Skill Draft (cluster 5)

**Tier:** M0 deterministic sub-agent
**Status:** Draft (cluster 5.2). YAML lookup, no LLM.

## Purpose

Read the six YAML knowledge stores under `config/indian_context/` and
expose `lookup(store, *path_keys, default=None)`.

## Stores

- `tax_matrix` — STCG / LTCG rates by asset class + holding period
- `structure_matrix` — PMS / AIF / SIF / MF minimums + demat rules
- `sebi_boundaries` — concentration / single-issuer / sector caps
- `gift_city_routing` — IFSC GIFT-City flags for international assets
- `demat_mechanics` — settlement T+N + demat tagging
- `regulatory_changelog` — recent SEBI / RBI / FEMA changes

## Notes

Cluster 6 enrichment may add `regulatory_changelog` deltas; the
loader caches the parsed dicts process-wide.
