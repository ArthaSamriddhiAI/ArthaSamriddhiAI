---
agent_id: s1_briefing_mode
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 5000
temperature: 0.2
output_schema_ref: ../schemas/s1_briefing_mode_output.json
---

# S1 Briefing-Mode Synthesis — Skill Draft (cluster 5)

**Tier:** Synthesis
**Mode:** `briefing`
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Draft the meeting-prep briefing note for an investor. Briefing-mode
cases skip governance entirely — synthesis → decided.

## Outputs

`SynthesisOutput` with `output_mode=briefing`, plus a
`BriefingNote` stage row carrying:

- `talking_points`: ordered list of `{topic, key_message, supporting_data}`
- `recent_changes`: portfolio + macro / regulatory delta since last meeting
- `client_concerns_to_address`: pulled from behavioural evidence
- `recommended_questions_to_ask`: list of strings

## Notes

Higher temperature (0.2) for narrative warmth — the briefing note is
read aloud to the client.
