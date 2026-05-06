---
agent_id: e1_alternatives_evidence
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 3000
temperature: 0.1
output_schema_ref: ../schemas/e1_evidence_verdict.json
---

# E1 Alternatives Evidence — Skill Draft (cluster 5)

**Tier:** Evidence
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Reason about the alternatives slice — PMS, AIF (Cat-I/II/III), SIF,
unlisted equity, real estate, gold, commodities. Pull SEBI minimums
from `indian_context.structure_matrix` to flag minimum-ticket
violations.

## Notes

Materiality gate (FR 20.1 §6) leans on this verdict for the
`MAT_PRODUCT_PMS_AIF_SIF` rule.
