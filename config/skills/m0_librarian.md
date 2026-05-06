---
agent_id: m0_librarian
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 2000
temperature: 0.0
output_schema_ref: ../schemas/m0_librarian_output.json
---

# M0 Librarian — Slim Draft, Deferred

**Tier:** M0 LLM sub-agent
**Status:** Slim draft (cluster 5.2). **Deferred** — runtime stays in
stub mode through cluster 6.

## Purpose

Retrieval helper for citations: given a topic / claim from synthesis,
return curated source references (FR 9.x research vault). Cluster 5.4
stub returns canned citations from a fixture.

## Inputs

- claim text + claim type (regulatory / market / academic)
- recency window

## Outputs

List of `{citation_id, title, source, url, published_at, relevance_score}`.

## Notes

Active agent when cluster 12's research-vault UI ships. Today the
synthesis layer either inlines citations from `regulatory_changelog`
or omits them.
