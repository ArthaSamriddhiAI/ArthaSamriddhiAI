---
agent_id: e1_macro_evidence
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 3000
temperature: 0.1
output_schema_ref: ../schemas/e1_evidence_verdict.json
---

# E1 Macro Evidence — Skill Draft (cluster 5)

**Tier:** Evidence
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Reason about the macro backdrop relevant to the case: RBI policy
posture, inflation trajectory, INR / USD, GDP nowcasts, key sector
flows. Cluster 3.3 ships `MacroSnapshot`; this agent reads that.

## Notes

Macro evidence is consumed by every other evidence agent — produced
first in the pipeline (the router orders it after equity / debt
because synthesis prefers asset-specific verdicts up top, but the
boss can run them in parallel since the macro snapshot is shared).
