---
agent_id: m0_portfolio_analytics
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: deterministic
max_tokens: 1
temperature: 0.0
output_schema_ref: ../schemas/m0_portfolio_analytics_output.json
---

# M0 Portfolio Analytics — Skill Draft (cluster 5)

**Tier:** M0 deterministic sub-agent
**Status:** Draft (cluster 5.2). Decimal-precision computations.

## Purpose

Compute deterministic concentration metrics on a `PortfolioState`:

- HHI (Herfindahl-Hirschman Index) over instrument allocations
- Top-N share (cumulative top-N allocation)
- Max single-position share
- Max sector share
- Per-asset-class deviation vs. a target dict

## Notes

Empty state returns zero across the board rather than raising.
Outputs feed:

- the materiality gate (chunk 5.4) — `MAT_CONCENTRATION` rule
- the case-mode synthesizer
- the governance gates (FR 20.3 §3)
