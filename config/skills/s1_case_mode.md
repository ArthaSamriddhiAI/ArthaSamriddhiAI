---
agent_id: s1_case_mode
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 6000
temperature: 0.1
output_schema_ref: ../schemas/s1_case_mode_output.json
---

# S1 Case-Mode Synthesis — Skill Draft (cluster 5)

**Tier:** Synthesis
**Mode:** `proposed_action` / `scenario`
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Read the bundle of evidence verdicts + portfolio risk analytics
output and produce the case-mode synthesis: the institutional view on
the proposed action / scenario, with rationale, alternative paths,
and the materiality preview.

## Inputs

- all `EvidenceVerdict` rows for the case
- `PortfolioRiskAnalyticsOutput`
- the proposed action shape from the case row
- mandate constraints (`m1.MandateVersion`)

## Outputs

`SynthesisOutput` (FR 20.1 §2.5) with:

- `output_mode`: `case_mode`
- `headline`: 1-sentence verdict
- `narrative`: 2-3 paragraph reasoning
- `alternatives`: list of `{description, rationale, score}`
- `risk_callouts`: list of `{risk, severity, citation_ids}`
- `key_assumptions`: list of strings
- `confidence_score`: 0..100

## Notes

This is the *most-called* synthesis skill — proposed_action /
scenario cases are the bulk of the demo flow.
