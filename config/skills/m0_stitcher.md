---
agent_id: m0_stitcher
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: deterministic
max_tokens: 1
temperature: 0.0
output_schema_ref: ../schemas/m0_stitcher_output.json
---

# M0 Stitcher — Skill Draft (cluster 5)

**Tier:** M0 deterministic sub-agent
**Status:** Draft (cluster 5.2). Markdown template renderer, no LLM.

## Purpose

Render markdown templates against a context dict for three case-pipeline
output surfaces:

- `case_detail` — case detail UI body (chunk 5.5)
- `health_report` — diagnostic-mode body
- `briefing_note` — briefing-mode body

## Syntax

- `{{ key }}` substitution with dot-traversal (`a.b.c`)
- `{% for x in xs %}...{% endfor %}` loop blocks
- Missing keys render as `[unknown:key]` so output bugs surface in review

## Notes

Anything more sophisticated (Jinja2, sandboxing) is deferred to a
later cluster. Templates live under `config/stitcher/`.
