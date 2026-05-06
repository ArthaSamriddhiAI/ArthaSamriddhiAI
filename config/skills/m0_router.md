---
agent_id: m0_router
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: deterministic
max_tokens: 1
temperature: 0.0
output_schema_ref: ../schemas/m0_router_output.json
---

# M0 Router — Skill Draft (cluster 5)

**Tier:** M0 deterministic sub-agent
**Owner:** M0 boss
**Status:** Draft (cluster 5.2). No LLM call; pure-Python routing table.

## Purpose

Given a case mode + intent + dominant lens, return the ordered tuple
of evidence agent_ids the case pipeline should run before synthesis.
Persisted on the case row as `applicable_evidence_agents` so replay is
reproducible.

## Inputs

- `case_mode`: one of `proposed_action | scenario | diagnostic | briefing`
- `case_intent`: optional `CaseIntent` enum value
- `dominant_lens`: optional `portfolio_shift | proposal_evaluation`
- `manual_override`: optional CIO-curated tuple that bypasses the table

## Outputs

A `RouterDecision { applicable_evidence_agents, reason }` record. The
reason string is `+`-joined keys (`mode=...+intent=...+lens=...`) or
`manual_override`.

## Cluster 7 swap

Cluster 7+ may replace the lookup table with an LLM-routed variant
that calls `claude-sonnet-4-5` with the case shape + a few-shot prompt.
This skill.md draft already pins the schema_ref so the swap is purely
runtime.
