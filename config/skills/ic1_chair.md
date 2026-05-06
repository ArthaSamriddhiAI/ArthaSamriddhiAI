---
agent_id: ic1_chair
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 4000
temperature: 0.1
output_schema_ref: ../schemas/ic1_deliberation_output.json
---

# IC1 Chair — Skill Draft (cluster 5)

**Tier:** Deliberation (Investment Committee 1)
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Chair the IC1 deliberation for material proposed_action / scenario
cases. Reads the case-mode synthesis + member-quant verdict + recent
similar cases and produces the IC1 recommendation.

## Inputs

- `SynthesisOutput` (case_mode)
- `IC1Member` verdicts from the member personas
- recent decided cases for the investor + similar archetypes

## Outputs

`IC1Deliberation` with:

- `recommendation`: `proceed | support_with_conditions | oppose | defer`
- `chair_summary`: 1-paragraph chair view
- `dissenting_views`: list of member objections summarized
- `escalation_to_human`: bool, default `True`
- `confidence_score`: 0..100

## Notes

`escalation_to_human` defaults `True` until cluster 8's IC autonomy
calibration ships. Today every IC1 verdict still routes through the
CIO for the final decision.
