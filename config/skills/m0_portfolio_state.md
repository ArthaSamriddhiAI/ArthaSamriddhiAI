---
agent_id: m0_portfolio_state
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: deterministic
max_tokens: 1
temperature: 0.0
output_schema_ref: ../schemas/m0_portfolio_state_output.json
---

# M0 Portfolio State — Skill Draft (cluster 5)

**Tier:** M0 deterministic sub-agent
**Status:** Draft (cluster 5.2). No LLM; pure aggregation.

## Purpose

Reduce a list of holding rows (instrument_id, asset_class, sector,
market_value, allocation_pct) into the canonical portfolio-state
object: total value, holding count, asset-class slices, sector slices,
top-N positions.

## Inputs

`HoldingInput` records — typically built by the case opening flow
(chunk 5.3) from a pinned snapshot bundle.

## Outputs

`PortfolioState` with sorted slices (descending allocation_pct).

## Notes

Asset classes outside the known set bucket into `other`. Sector slices
exclude positions with `sector=None`.
