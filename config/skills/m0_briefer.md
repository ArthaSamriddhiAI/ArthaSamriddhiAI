---
agent_id: m0_briefer
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 4000
temperature: 0.2
output_schema_ref: ../schemas/m0_briefer_output.json
---

# M0 Briefer — Slim Draft, Deferred

**Tier:** M0 LLM sub-agent
**Status:** Slim draft (cluster 5.2). **Deferred** — runtime stays in
stub mode through cluster 6.

## Purpose

LLM-assisted briefing-mode synthesis helper. Drafts the meeting-prep
note for an investor when the case mode is `briefing`.

## Inputs

- portfolio state
- recent activity / case history for the investor
- mandate constraints
- household context

## Outputs

A markdown note suitable for the briefing UI. Schema enforced by
`output_schema_ref`.

## Notes

The S1 briefing-mode synthesizer (`s1_briefing_mode`) covers the
critical path in cluster 5.4 stubs; m0_briefer becomes the active
agent when cluster 13's briefing UI ships.
