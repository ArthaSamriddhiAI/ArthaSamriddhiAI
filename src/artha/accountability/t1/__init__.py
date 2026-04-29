"""T1 — the canonical decision telemetry bus.

Per Section 13.7 + 15.11.1 of the consolidation spec, T1 is the system's append-only
ledger of every event of consequence. This package owns:

  * `T1Event` (Pydantic) — the canonical event shape per Section 15.11.1
  * `T1EventRow` (SQLAlchemy) — persistence
  * `T1Repository` — append + read (no update, no delete)
  * `t1_event_from_trace_node` — adapter from the legacy `TraceNode` shape

The legacy `accountability.trace` package continues to operate on the existing
decision-trace DAG without disturbance. New writers should use `T1Repository`
directly; existing trace writers are migrated progressively in subsequent passes.
"""

from artha.accountability.t1.adapter import t1_event_from_trace_node
from artha.accountability.t1.models import T1Event
from artha.accountability.t1.orm import T1EventRow
from artha.accountability.t1.repository import T1AppendError, T1Repository

__all__ = [
    "T1Event",
    "T1EventRow",
    "T1Repository",
    "T1AppendError",
    "t1_event_from_trace_node",
]
