# Meeting Brief — {{ investor.name }}

**Meeting Date:** {{ meeting_date }}
**Prepared By:** {{ advisor_name }}
**Case ID:** {{ case.case_id }}

## Headline

{{ briefing.headline }}

## Talking Points

{% for point in briefing.talking_points %}
### {{ point.topic }}

**Key Message:** {{ point.key_message }}

{{ point.supporting_data }}

{% endfor %}

## Recent Changes Since Last Meeting

{% for change in briefing.recent_changes %}
- {{ change.area }}: {{ change.detail }}
{% endfor %}

## Client Concerns to Address

{% for concern in briefing.client_concerns_to_address %}
- {{ concern }}
{% endfor %}

## Recommended Questions to Ask

{% for question in briefing.recommended_questions_to_ask %}
- {{ question }}
{% endfor %}

## Portfolio Snapshot

- **Total Value:** ₹{{ portfolio_state.total_value_inr }}
- **Top Position:** {{ portfolio_state.top_positions.0.instrument_id }} ({{ portfolio_state.top_positions.0.allocation_pct }}%)
