---
agent_id: e1_debt_evidence
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 3000
temperature: 0.1
output_schema_ref: ../schemas/e1_evidence_verdict.json
---

# E1 Debt Evidence — Skill Draft (cluster 5)

**Tier:** Evidence
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Reason about the portfolio's debt slice: duration risk, credit-quality
mix, yield-to-maturity, current rate-cycle posture (RBI repo trajectory
from `regulatory_changelog`), tax efficiency vs alternatives.

## Outputs

`EvidenceVerdict` (see equity evidence for shape).

## Notes

Inherits the shared `EvidenceVerdict` schema. Specific to debt:

- `key_findings` may include `{type: 'duration_risk', dv01_inr}` style
  records once cluster 7 wires real metric computation.
