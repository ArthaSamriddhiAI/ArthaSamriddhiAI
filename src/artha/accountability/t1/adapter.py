"""Adapter from the legacy `TraceNode` shape to the canonical `T1Event`.

The pre-consolidation accountability layer captures decision flow as a DAG of
`TraceNode`s. The canonical T1 ledger captures it as an append-only event log
with the Section 15.11.1 shape. Both will coexist for several passes while
writers migrate; this adapter is the bridge.

Approach:

  * Map `TraceNode.node_type` to the closest canonical `T1EventType`. For
    `AGENT_OUTPUT` we look at `data.agent_name` to pick the specific E1–E6
    or S1 sub-type. Where no clean mapping exists (legacy categories like
    `EXECUTION_SUBMITTED`, `SUGGESTION_*` that pre-date the consolidation),
    we route to the closest canonical analogue and preserve the original
    `node_type` in `payload.legacy_node_type` for fidelity.
  * Preserve the original TraceNode id, parent_node_ids, and the full data
    object inside `payload` so that no information is lost in projection.

This is a one-way adapter — TraceNode → T1Event. We do not reverse it; new
writers should produce T1Events directly.
"""

from __future__ import annotations

from typing import Any

from artha.accountability.t1.models import T1Event
from artha.accountability.trace.models import TraceNode, TraceNodeType
from artha.common.standards import T1EventType
from artha.common.types import VersionPins

_AGENT_NAME_TO_EVENT_TYPE: dict[str, T1EventType] = {
    "financial_risk": T1EventType.E1_VERDICT,
    "industry_analyst": T1EventType.E2_VERDICT,
    "macro_policy": T1EventType.E3_VERDICT,
    "behavioural_historical": T1EventType.E4_VERDICT,
    "unlisted_specialist": T1EventType.E5_VERDICT,
    "pms_aif_specialist": T1EventType.E6_ORCHESTRATOR,
    "master_synthesis": T1EventType.S1_SYNTHESIS,
    "investment_committee": T1EventType.IC1_CHAIR,
    "advisory_challenge": T1EventType.A1_CHALLENGE,
    "portfolio_monitoring": T1EventType.PM1_EVENT,
    "mandate_compliance": T1EventType.G1_EVALUATION,
    "regulatory_engine": T1EventType.G2_EVALUATION,
    "permission_filter": T1EventType.G3_EVALUATION,
}


_NODE_TYPE_TO_EVENT_TYPE: dict[TraceNodeType, T1EventType] = {
    TraceNodeType.INTENT_RECEIVED: T1EventType.ROUTER_CLASSIFICATION,
    TraceNodeType.EVIDENCE_FROZEN: T1EventType.PORTFOLIO_STATE_QUERY,
    TraceNodeType.AGENT_INVOKED: T1EventType.STITCHER_COMPOSITION,  # invocation envelope
    # AGENT_OUTPUT is resolved separately via agent_name lookup
    TraceNodeType.RULE_EVALUATED: T1EventType.G3_EVALUATION,
    TraceNodeType.PERMISSION_GRANTED: T1EventType.G3_EVALUATION,
    TraceNodeType.PERMISSION_DENIED: T1EventType.G3_EVALUATION,
    TraceNodeType.ESCALATION_REQUIRED: T1EventType.DECISION,
    TraceNodeType.HUMAN_APPROVAL: T1EventType.DECISION,
    TraceNodeType.EXECUTION_SUBMITTED: T1EventType.DECISION,
    TraceNodeType.ANALYSIS_STARTED: T1EventType.S1_SYNTHESIS,
    TraceNodeType.ANALYSIS_SYNTHESIZED: T1EventType.S1_SYNTHESIS,
    TraceNodeType.PORTFOLIO_REVIEW_STARTED: T1EventType.STITCHER_COMPOSITION,
    TraceNodeType.PORTFOLIO_REVIEW_COMPLETE: T1EventType.STITCHER_COMPOSITION,
    TraceNodeType.SUGGESTION_SET_GENERATED: T1EventType.S1_SYNTHESIS,
    TraceNodeType.SUGGESTION_EGA_RESULT: T1EventType.S1_SYNTHESIS,
    TraceNodeType.ERROR: T1EventType.EX1_EVENT,
}


def _map_event_type(node: TraceNode) -> T1EventType:
    if node.node_type == TraceNodeType.AGENT_OUTPUT:
        agent_name = (node.data or {}).get("agent_name", "")
        return _AGENT_NAME_TO_EVENT_TYPE.get(agent_name, T1EventType.S1_SYNTHESIS)
    return _NODE_TYPE_TO_EVENT_TYPE[node.node_type]


def t1_event_from_trace_node(
    node: TraceNode,
    *,
    firm_id: str,
    client_id: str | None = None,
    advisor_id: str | None = None,
    version_pins: VersionPins | None = None,
) -> T1Event:
    """Project a legacy `TraceNode` onto the canonical `T1Event` shape.

    Preserves the original node id, parent ids, and full data object inside
    `payload` so the projection is information-preserving. The new T1Event
    gets a fresh ULID `event_id`; the legacy `node.id` is in
    `payload.legacy_node_id`.

    `firm_id` is required because Section 15.11.1 mandates it but legacy
    TraceNodes don't carry firm scope. Callers must supply it from context.
    """
    payload: dict[str, Any] = {
        "legacy_node_id": node.id,
        "legacy_node_type": node.node_type.value,
        "legacy_parent_node_ids": list(node.parent_node_ids),
        "data": dict(node.data),
    }

    return T1Event.build(
        event_type=_map_event_type(node),
        firm_id=firm_id,
        timestamp=node.created_at,
        payload=payload,
        case_id=node.decision_id,
        client_id=client_id,
        advisor_id=advisor_id,
        version_pins=version_pins,
    )
