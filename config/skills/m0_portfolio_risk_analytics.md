---
agent_id: m0_portfolio_risk_analytics
skill_md_version: v0.1
draft_version: 1
authored_in_cluster: 5
finalised_in_cluster: null
llm_model: deterministic
max_tokens: 1
temperature: 0.0
output_schema_ref: ../schemas/m0_portfolio_risk_analytics_output.json
---

# M0 Portfolio Risk Analytics — Skill Draft (cluster 5)

**Tier:** M0 deterministic sub-agent
**Status:** Draft (cluster 5.2). Per-case stage row producer.

## Purpose

Compute risk metrics for a case and persist them to
`v2_case_portfolio_risk_analytics`. Cluster 5.4 stub layer seeds the
row from a fixture; cluster 7+ swaps in real metric computations.

## Outputs (FR 20.1 §2.4)

- `volatility_pct` — trailing 12-month portfolio volatility
- `var_95_pct` — 95% Value at Risk
- `max_drawdown_pct` — peak-to-trough drawdown
- `sharpe_ratio` — risk-adjusted return
- `beta_to_nifty50` — equity beta to Nifty 50
- `concentration_score` — HHI-derived score
- `liquidity_score` — weighted-average days-to-liquidate

## Notes

Stage row is `UNIQUE` per case; only one risk-analytics output per
case, immutable once written.
