---
agent_id: ic1_member_quant
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: claude-sonnet-4-5
max_tokens: 3000
temperature: 0.1
output_schema_ref: ../schemas/ic1_member_verdict.json
---

# IC1 Member — Quantitative — Skill Draft (cluster 5)

**Tier:** Deliberation (IC1 member persona)
**Status:** Draft. Stub-served in cluster 5.4.

## Purpose

Quant-leaning IC1 member. Re-reads the evidence + portfolio risk
analytics with a quant lens (HHI, sharpe, max drawdown, beta to
nifty, var-95) and produces a member verdict the chair aggregates.

## Outputs

`IC1MemberVerdict` with:

- `verdict`: `support | concerns | oppose | abstain`
- `key_concerns`: list of strings
- `supporting_metrics`: dict of metric_name → value
- `confidence_score`: 0..100

## Notes

Cluster 5 ships only one member persona (quant). Cluster 8 will add
qualitative + behavioural members for richer deliberations.
