"""Trace persistence and query."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.types import DecisionID
from artha.accountability.models import TraceNodeRow
from artha.accountability.trace.models import DecisionTrace, TraceNode, TraceNodeType


class TraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_trace(self, decision_id: DecisionID) -> DecisionTrace:
        """Retrieve the full decision trace for a decision."""
        stmt = (
            select(TraceNodeRow)
            .where(TraceNodeRow.decision_id == decision_id)
            .order_by(TraceNodeRow.created_at)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        nodes = [
            TraceNode(
                id=row.id,
                decision_id=row.decision_id,
                node_type=TraceNodeType(row.node_type),
                parent_node_ids=json.loads(row.parent_node_ids_json),
                data=json.loads(row.data_json),
                created_at=row.created_at,
            )
            for row in rows
        ]

        root_id = nodes[0].id if nodes else None
        return DecisionTrace(decision_id=decision_id, nodes=nodes, root_node_id=root_id)

    async def get_node(self, node_id: str) -> TraceNode | None:
        """Get a single trace node."""
        stmt = select(TraceNodeRow).where(TraceNodeRow.id == node_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return TraceNode(
            id=row.id,
            decision_id=row.decision_id,
            node_type=TraceNodeType(row.node_type),
            parent_node_ids=json.loads(row.parent_node_ids_json),
            data=json.loads(row.data_json),
            created_at=row.created_at,
        )
