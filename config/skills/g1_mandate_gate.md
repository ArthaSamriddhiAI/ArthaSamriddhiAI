---
agent_id: g1_mandate_gate
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 2500
temperature: 0.0
output_schema_ref: ../schemas/governance_gate_output.json
---

# G1 Mandate Gate — Skill Draft (cluster 5)

**Tier:** Deliberation (governance gate 1)
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Check the proposed action against the active mandate version: asset
allocation bands, single-position cap, sector cap, prohibited
instruments, liquidity floor.

## Inputs

- proposed action shape
- post-action portfolio state (computed by deterministic preview)
- `MandateVersion` constraints

## Outputs

`GovernanceResult` with `gate=g1_mandate`:

- `outcome`: `approved | blocked | escalation_required`
- `findings`: list of `{constraint, observed_value, threshold, breach: bool}`
- `summary`: 1-sentence outcome
- `confidence_score`: 0..100

## Notes

Temperature pinned at 0.0 — mandate breaches are deterministic
arithmetic; the LLM only narrates. Cluster 7 may move this to a
deterministic Python check entirely with the LLM only generating the
summary.
