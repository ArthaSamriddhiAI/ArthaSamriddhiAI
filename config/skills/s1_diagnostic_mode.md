---
agent_id: s1_diagnostic_mode
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 5000
temperature: 0.1
output_schema_ref: ../schemas/s1_diagnostic_mode_output.json
---

# S1 Diagnostic-Mode Synthesis — Skill Draft (cluster 5)

**Tier:** Synthesis
**Mode:** `diagnostic`
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Produce the diagnostic-mode synthesis (a standalone health view of
the portfolio) without proposing an action. Drives the
`HealthReport` stage row + the diagnostic case detail page.

## Outputs

`SynthesisOutput` with `output_mode=diagnostic`. The diagnostic
synthesis additionally populates the case's `HealthReport` row with
`overall: healthy | attention_needed | urgent` plus per-area
findings.

## Notes

Diagnostic mode skips committee + challenge + decision. Synthesis →
governance → decided is the canonical flow.
