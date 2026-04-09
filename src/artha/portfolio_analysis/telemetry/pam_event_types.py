"""Pydantic models for PAM telemetry events and recording helper."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.types import DecisionID


class PortfolioReviewCompleteEvent(BaseModel):
    """Telemetry event recorded when Phase 1 (CPR) completes."""

    portfolio_review_id: str
    portfolio_id: str
    client_id: str
    canonical_portfolio: dict[str, Any] = Field(default_factory=dict)
    agent_outputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Condensed per-holding summaries from the analysis layer.",
    )
    cpr_sections: dict[str, Any] = Field(
        default_factory=dict,
        description="All 10 CPR sections.",
    )
    component_versions: dict[str, str] = Field(default_factory=dict)
    data_quality_summary: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: get_clock().now())


class SuggestionSetGeneratedEvent(BaseModel):
    """Telemetry event recorded when Phase 2 (ISE) completes."""

    portfolio_review_id: str
    exit_candidates: list[dict[str, Any]] = Field(default_factory=list)
    total_redeployable_inr: float = 0.0
    suggestion_set: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: get_clock().now())


async def record_pam_event(
    session: AsyncSession,
    decision_id: DecisionID,
    event_type: str,
    event_data: dict[str, Any],
) -> str:
    """Record a PAM telemetry event as a trace node via DecisionTraceBuilder.

    Parameters
    ----------
    session : AsyncSession
        Active DB session.
    decision_id : DecisionID
        The decision/review ID this event belongs to.
    event_type : str
        Either ``"portfolio_review_complete"`` or ``"suggestion_set_generated"``.
    event_data : dict
        Full event payload (validated externally or raw dict).

    Returns
    -------
    str — the trace node ID.
    """
    from artha.accountability.trace.graph import DecisionTraceBuilder
    from artha.accountability.trace.models import TraceNodeType

    # Map PAM event types to trace node types
    node_type_map = {
        "portfolio_review_complete": TraceNodeType.PORTFOLIO_REVIEW_COMPLETE,
        "suggestion_set_generated": TraceNodeType.SUGGESTION_SET_GENERATED,
    }

    node_type = node_type_map.get(event_type)
    if node_type is None:
        raise ValueError(f"Unknown PAM event type: {event_type}")

    trace = DecisionTraceBuilder(session, decision_id)
    node_id = await trace.add_node(
        node_type=node_type,
        data=event_data,
    )
    return node_id
