"""T1 event names emitted by the SSE channel.

Per FR Entry 18.0 §6. Centralised so router + tests + future query
consumers reference the same constants.
"""

from __future__ import annotations

SSE_CONNECTION_OPENED = "sse_connection_opened"
SSE_CONNECTION_CLOSED = "sse_connection_closed"
# Selective; emitted only for high-priority events. Cluster 0 has none of
# those, but the constant lives here for forward use.
SSE_EVENT_EMITTED = "sse_event_emitted"
