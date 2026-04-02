"""Decision Telemetry Analytics — aggregate patterns, disagreement detection, decision quality."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_telemetry_analytics(session: AsyncSession) -> dict[str, Any]:
    """Aggregate decision telemetry across all decisions."""
    # Decision counts by status
    try:
        r = await session.execute(text(
            "SELECT status, COUNT(*) FROM governance_decisions GROUP BY status"
        ))
        status_counts = {row[0]: row[1] for row in r.all()}
    except Exception:
        status_counts = {}

    # Decision counts by intent type
    try:
        r = await session.execute(text(
            "SELECT intent_type, COUNT(*) FROM governance_decisions GROUP BY intent_type"
        ))
        type_counts = {row[0]: row[1] for row in r.all()}
    except Exception:
        type_counts = {}

    # Trace node distribution
    try:
        r = await session.execute(text(
            "SELECT node_type, COUNT(*) FROM trace_nodes GROUP BY node_type ORDER BY COUNT(*) DESC"
        ))
        node_distribution = {row[0]: row[1] for row in r.all()}
    except Exception:
        node_distribution = {}

    # Total trace nodes
    try:
        total_nodes = (await session.execute(text("SELECT COUNT(*) FROM trace_nodes"))).scalar() or 0
    except Exception:
        total_nodes = 0

    # Decisions with traces
    try:
        traced = (await session.execute(text("SELECT COUNT(DISTINCT decision_id) FROM trace_nodes"))).scalar() or 0
    except Exception:
        traced = 0

    # Agent disagreement analysis
    disagreements = await _analyze_agent_disagreements(session)

    # Recent decisions timeline
    recent = await _get_recent_decisions_timeline(session)

    total_decisions = sum(status_counts.values())

    return {
        "total_decisions": total_decisions,
        "total_trace_nodes": total_nodes,
        "decisions_with_traces": traced,
        "status_distribution": status_counts,
        "type_distribution": type_counts,
        "node_type_distribution": node_distribution,
        "approval_rate": round(status_counts.get("approved", 0) / total_decisions * 100, 1) if total_decisions > 0 else 0,
        "rejection_rate": round(status_counts.get("rejected", 0) / total_decisions * 100, 1) if total_decisions > 0 else 0,
        "escalation_rate": round(status_counts.get("escalation_required", 0) / total_decisions * 100, 1) if total_decisions > 0 else 0,
        "agent_disagreements": disagreements,
        "recent_decisions": recent,
    }


async def _analyze_agent_disagreements(session: AsyncSession) -> list[dict]:
    """Find decisions where agents disagreed on risk level."""
    disagreements = []
    try:
        # Get all decisions that have agent_output trace nodes
        r = await session.execute(text("""
            SELECT decision_id, data_json FROM trace_nodes
            WHERE node_type = 'agent_output' ORDER BY decision_id, created_at
        """))
        rows = r.all()

        # Group by decision
        by_decision = defaultdict(list)
        for row in rows:
            data = json.loads(row[1])
            by_decision[row[0]].append(data)

        for dec_id, agents in by_decision.items():
            if len(agents) < 2:
                continue
            risk_levels = [a.get("risk_level", "unknown") for a in agents]
            if len(set(risk_levels)) > 1:
                disagreements.append({
                    "decision_id": dec_id,
                    "agents": [{"name": a.get("agent_name", "?"), "risk_level": a.get("risk_level", "?"), "confidence": a.get("confidence", 0)} for a in agents],
                    "risk_levels": risk_levels,
                    "consensus": False,
                })
            else:
                # Even if they agree on risk, check confidence spread
                confidences = [a.get("confidence", 0) for a in agents]
                spread = max(confidences) - min(confidences) if confidences else 0
                if spread > 0.2:
                    disagreements.append({
                        "decision_id": dec_id,
                        "agents": [{"name": a.get("agent_name", "?"), "risk_level": a.get("risk_level", "?"), "confidence": a.get("confidence", 0)} for a in agents],
                        "risk_levels": risk_levels,
                        "consensus": True,
                        "confidence_spread": round(spread, 2),
                    })
    except Exception:
        pass

    return disagreements[:20]


async def _get_recent_decisions_timeline(session: AsyncSession) -> list[dict]:
    """Get recent decisions with trace summary."""
    timeline = []
    try:
        r = await session.execute(text("""
            SELECT id, intent_type, status, created_at, completed_at, result_json
            FROM governance_decisions ORDER BY created_at DESC LIMIT 20
        """))
        for row in r.all():
            result = json.loads(row[5]) if row[5] else {}

            # Count trace nodes for this decision
            tn = await session.execute(text("SELECT COUNT(*) FROM trace_nodes WHERE decision_id = :id"), {"id": row[0]})
            node_count = tn.scalar() or 0

            timeline.append({
                "decision_id": row[0],
                "intent_type": row[1],
                "status": row[2],
                "created_at": str(row[3]) if row[3] else None,
                "completed_at": str(row[4]) if row[4] else None,
                "agent_count": result.get("agent_count", 0),
                "rule_count": result.get("rule_count", 0),
                "trace_nodes": node_count,
                "initiator": result.get("initiator", ""),
                "client_name": result.get("parameters", {}).get("client_name", ""),
            })
    except Exception:
        pass

    return timeline
