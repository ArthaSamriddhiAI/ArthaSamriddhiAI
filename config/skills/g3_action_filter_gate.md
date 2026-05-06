---
agent_id: g3_action_filter_gate
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 2500
temperature: 0.0
output_schema_ref: ../schemas/governance_gate_output.json
---

# G3 Action Filter Gate — Skill Draft (cluster 5)

**Tier:** Deliberation (governance gate 3)
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Final action filter before challenge: tax efficiency, settlement
timing (T+N), demat tagging, exit-load + STT, exchange-window check.

## Inputs

- proposed action shape
- `indian_context.tax_matrix`
- `indian_context.demat_mechanics`
- portfolio holding-period data

## Outputs

`GovernanceResult` with `gate=g3_action_filter`. Same shape as G1 / G2.

## Notes

This gate is the last deterministic check before A1 challenge.
Failures here block; warnings escalate to A1.
