---
agent_id: e1_sentiment_evidence
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 2500
temperature: 0.2
output_schema_ref: ../schemas/e1_evidence_verdict.json
---

# E1 Sentiment Evidence — Skill Draft (cluster 5)

**Tier:** Evidence
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Read recent market commentary, news flow, and FII/DII positioning to
produce a sentiment verdict on the case's relevant assets.

## Notes

Higher temperature (0.2) than other evidence agents — sentiment
needs interpretive flexibility. Cluster 7 wires this to a real
news-and-flow data feed; cluster 5.4 stub seeds from
`regulatory_changelog`.
