---
agent_id: g2_sebi_regulatory_gate
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 2500
temperature: 0.0
output_schema_ref: ../schemas/governance_gate_output.json
---

# G2 SEBI Regulatory Gate — Skill Draft (cluster 5)

**Tier:** Deliberation (governance gate 2)
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Check the proposed action against SEBI / RBI / FEMA constraints:
PMS minimum ticket (₹50 L), AIF Cat-I/II/III minimums (₹1 Cr),
single-issuer cap (10%), sector cap, FEMA cross-border flags.

## Inputs

- proposed action shape
- `indian_context.sebi_boundaries`
- `indian_context.structure_matrix`
- `indian_context.gift_city_routing`
- `indian_context.regulatory_changelog`

## Outputs

`GovernanceResult` with `gate=g2_sebi_regulatory`. Same shape as G1.

## Notes

Temperature 0.0 — same reasoning as G1.
