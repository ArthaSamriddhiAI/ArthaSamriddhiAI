"""DecisionTraceBuilder — fluent API for constructing the causal DAG."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.types import DecisionID, TraceNodeID
from artha.accountability.models import TraceNodeRow
from artha.accountability.trace.models import DecisionTrace, TraceNode, TraceNodeType


class DecisionTraceBuilder:
    """Builds a decision trace DAG incrementally during orchestration."""

    def __init__(self, session: AsyncSession, decision_id: DecisionID) -> None:
        self._session = session
        self._decision_id = decision_id
        self._nodes: list[TraceNode] = []
        self._root_id: str | None = None

    async def add_node(
        self,
        node_type: TraceNodeType,
        data: dict[str, Any] | None = None,
        parent_ids: list[str] | None = None,
    ) -> TraceNodeID:
        """Add a node to the trace DAG."""
        node_id = TraceNodeID(str(uuid.uuid4()))
        now = get_clock().now()

        node = TraceNode(
            id=node_id,
            decision_id=self._decision_id,
            node_type=node_type,
            parent_node_ids=parent_ids or [],
            data=data or {},
            created_at=now,
        )
        self._nodes.append(node)

        if self._root_id is None:
            self._root_id = node_id

        # Persist
        row = TraceNodeRow(
            id=node_id,
            decision_id=self._decision_id,
            node_type=node_type.value,
            parent_node_ids_json=json.dumps(parent_ids or []),
            data_json=json.dumps(data or {}, default=str),
            created_at=now,
        )
        self._session.add(row)
        await self._session.flush()

        return node_id

    def build(self) -> DecisionTrace:
        """Return the complete decision trace."""
        return DecisionTrace(
            decision_id=self._decision_id,
            nodes=self._nodes,
            root_node_id=self._root_id,
        )
