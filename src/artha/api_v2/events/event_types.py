"""Event type catalogue for the SSE multiplex channel.

Per FR Entry 18.0 §3, the v1 multiplex schema defines eleven event types.
Cluster 0 implements four:

- ``connection_established``: emitted once per connection open (always fires).
- ``connection_heartbeat``: periodic keepalive every 30 seconds (always fires).
- ``token_refresh_required``: mechanism scaffolded; fires from a per-connection
  timer 60 seconds before the access JWT's expiry.
- ``connection_terminating``: mechanism scaffolded; fires when the underlying
  session is about to expire and re-auth is required.

The remaining seven event types are reserved for the clusters that introduce
their emitters. Their per-payload schemas live in those clusters' FR entries
(e.g., ``n0_alert_created`` payload schema lives in FR 14.1, authored when
cluster 11 ships).
"""

from __future__ import annotations

from typing import Final

# ----- Implemented in cluster 0 -----
CONNECTION_ESTABLISHED: Final = "connection_established"
CONNECTION_HEARTBEAT: Final = "connection_heartbeat"
TOKEN_REFRESH_REQUIRED: Final = "token_refresh_required"
CONNECTION_TERMINATING: Final = "connection_terminating"

# ----- Implemented in subsequent clusters (reserved names) -----
N0_ALERT_CREATED: Final = "n0_alert_created"  # cluster 11
N0_ALERT_UPDATED: Final = "n0_alert_updated"  # cluster 11
CASE_PROGRESS_UPDATE: Final = "case_progress_update"  # cluster 5
CLARIFICATION_QUESTION_POSED: Final = "clarification_question_posed"  # cluster 5
SYSTEM_STATUS_CHANGE: Final = "system_status_change"  # cluster 4 / 7 / 16
MODEL_PORTFOLIO_VERSION_ACTIVATED: Final = "model_portfolio_version_activated"  # cluster 4
RULE_CORPUS_VERSION_UPDATED: Final = "rule_corpus_version_updated"  # cluster 8

# Full v1 catalogue, in declaration order. Useful for consumers that need
# to enumerate "what does the contract say is possible."
ALL_EVENT_TYPES: Final = (
    CONNECTION_ESTABLISHED,
    CONNECTION_HEARTBEAT,
    TOKEN_REFRESH_REQUIRED,
    CONNECTION_TERMINATING,
    N0_ALERT_CREATED,
    N0_ALERT_UPDATED,
    CASE_PROGRESS_UPDATE,
    CLARIFICATION_QUESTION_POSED,
    SYSTEM_STATUS_CHANGE,
    MODEL_PORTFOLIO_VERSION_ACTIVATED,
    RULE_CORPUS_VERSION_UPDATED,
)

# Subset that a cluster 0 connection actually subscribes to. Per FR 18.0 §4.1:
# "In cluster 0, the subscribed_event_types only includes the four event types
#  implemented (connection_established, connection_heartbeat,
#  token_refresh_required, connection_terminating)."
CLUSTER_0_SUBSCRIBED: Final = (
    CONNECTION_ESTABLISHED,
    CONNECTION_HEARTBEAT,
    TOKEN_REFRESH_REQUIRED,
    CONNECTION_TERMINATING,
)
