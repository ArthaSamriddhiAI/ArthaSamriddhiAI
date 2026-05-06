# Portfolio Health Report — {{ investor.name }}

**Report Date:** {{ generated_at }}
**Overall Health:** {{ health_report.overall }}
**Case ID:** {{ case.case_id }}

## Executive Summary

{{ synthesis.headline }}

{{ synthesis.narrative }}

## Portfolio Overview

- **Total Value:** ₹{{ portfolio_state.total_value_inr }}
- **Holdings:** {{ portfolio_state.holding_count }}

### Asset Class Allocation

{% for slice in portfolio_state.asset_class_slices %}
- {{ slice.asset_class }}: {{ slice.allocation_pct }}% (₹{{ slice.market_value_inr }})
{% endfor %}

### Top Sectors

{% for slice in portfolio_state.sector_slices %}
- {{ slice.sector }}: {{ slice.allocation_pct }}%
{% endfor %}

## Health Findings

{% for finding in health_report.findings %}
### {{ finding.area }}

- **Status:** {{ finding.status }}
- **Severity:** {{ finding.severity }}

{{ finding.detail }}

**Recommended Action:** {{ finding.recommended_action }}

{% endfor %}

## Risk Snapshot

- **Volatility:** {{ risk_analytics.volatility_pct }}%
- **VaR-95:** {{ risk_analytics.var_95_pct }}%
- **Max Drawdown:** {{ risk_analytics.max_drawdown_pct }}%
- **Concentration:** HHI {{ analytics.hhi }} / Top-5 share {{ analytics.top_n_share_pct }}%

## Mandate Compliance

{{ governance.summary }}
