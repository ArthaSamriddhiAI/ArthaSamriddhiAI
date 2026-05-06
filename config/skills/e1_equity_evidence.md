---
agent_id: e1_equity_evidence
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 3000
temperature: 0.1
output_schema_ref: ../schemas/e1_evidence_verdict.json
---

# E1 Equity Evidence — Skill Draft (cluster 5)

**Tier:** Evidence
**Status:** Draft. Stub-served in cluster 5.4; real LLM call in
cluster 7.

## Purpose

Read the portfolio's equity slice + macro + sentiment context and
produce an `EvidenceVerdict` covering: position-level conviction,
sector concentration risk, recent earnings flags, valuation posture
relative to long-term means.

## Inputs

- `portfolio_state.asset_class_slices[equity]` + top equity positions
- `indian_context.tax_matrix` (LTCG / STCG implications)
- `indian_context.regulatory_changelog` (recent SEBI equity changes)
- macro evidence verdict (consumed if already produced)

## Outputs

`EvidenceVerdict` with:

- `verdict`: `support | concerns | oppose | neutral`
- `confidence_score`: 0..100
- `verdict_summary`: 1-2 sentence headline
- `key_findings`: list of `{finding, severity, citation_ids}`
- `risk_level`: `low | medium | high | critical`

## Notes

Cluster 5.4 stub returns a canned verdict that depends on the case's
seed_archetype_id (see FR 19.0); cluster 7 wires the real LLM call
with this prompt as the system message.
