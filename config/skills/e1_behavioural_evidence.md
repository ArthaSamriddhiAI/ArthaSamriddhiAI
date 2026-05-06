---
agent_id: e1_behavioural_evidence
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 2500
temperature: 0.1
output_schema_ref: ../schemas/e1_evidence_verdict.json
---

# E1 Behavioural Evidence — Skill Draft (cluster 5)

**Tier:** Evidence
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Read the investor's recent case + decision history to flag behavioural
patterns: chasing recent performance, panic selling, mandate drift
(repeated near-band-edge proposals), confirmation bias.

## Inputs

- recent decided cases for the investor
- mandate amendment history (FR 12.2)
- alert response history (cluster 11)

## Notes

This evidence agent is special — it's the only one that reads
*beyond the snapshot bundle* into the investor's case ledger. Cluster
5.4 stub returns canned patterns; cluster 7 wires real history reads.
