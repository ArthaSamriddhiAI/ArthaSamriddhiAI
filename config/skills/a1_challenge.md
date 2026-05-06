---
agent_id: a1_challenge
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 4000
temperature: 0.3
output_schema_ref: ../schemas/a1_challenge_output.json
---

# A1 Challenge — Skill Draft (cluster 5)

**Tier:** Challenge
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Adversarial agent that argues against the synthesis verdict. Reads
the case-mode synthesis + IC1 deliberation + governance results and
produces a tear-down: the strongest case for *not* taking the
proposed action.

## Inputs

- `SynthesisOutput` (case_mode)
- `IC1Deliberation`
- all `GovernanceResult` rows
- the case's evidence verdicts

## Outputs

`A1Challenge` with:

- `headline_objection`: strongest single argument against
- `objections`: list of `{argument, evidence, severity}`
- `worst_case_scenario`: narrative
- `mitigations_proposed`: list of `{mitigation, residual_risk}`
- `recommendation`: `proceed_unmodified | proceed_with_mitigations | reject`
- `confidence_score`: 0..100

## Notes

Temperature 0.3 — the challenge agent benefits from creative
adversarial framing. Output feeds directly into the CIO's decision UI
(chunk 5.5).
