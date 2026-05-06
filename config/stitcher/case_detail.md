# {{ case.title }}

**Case ID:** {{ case.case_id }}
**Status:** {{ case.status }}
**Mode:** {{ case.mode }}
**Investor:** {{ case.investor_name }}
**Created:** {{ case.created_at }}

## Summary

{{ synthesis.headline }}

{{ synthesis.narrative }}

## Evidence Verdicts

{% for verdict in evidence_verdicts %}
### {{ verdict.agent_id }}

- **Verdict:** {{ verdict.verdict }}
- **Confidence:** {{ verdict.confidence_score }}
- **Risk Level:** {{ verdict.risk_level }}

{{ verdict.verdict_summary }}

{% endfor %}

## Risk Analytics

- **Volatility (12m):** {{ risk_analytics.volatility_pct }}%
- **VaR-95:** {{ risk_analytics.var_95_pct }}%
- **Max Drawdown:** {{ risk_analytics.max_drawdown_pct }}%
- **Sharpe Ratio:** {{ risk_analytics.sharpe_ratio }}
- **Beta to Nifty 50:** {{ risk_analytics.beta_to_nifty50 }}
- **Concentration Score:** {{ risk_analytics.concentration_score }}
- **Liquidity Score:** {{ risk_analytics.liquidity_score }}

## Governance

{% for result in governance_results %}
### {{ result.gate }}

**Outcome:** {{ result.outcome }}

{{ result.summary }}

{% endfor %}

## Challenge

{{ a1_challenge.headline_objection }}

{{ a1_challenge.worst_case_scenario }}

**Recommendation:** {{ a1_challenge.recommendation }}

## Decision

{{ decision.verdict }} — {{ decision.rationale }}

**Decided By:** {{ decision.cio_user_id }}
**Decided At:** {{ decision.decided_at }}
