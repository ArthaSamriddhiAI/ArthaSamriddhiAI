"""Audit query repository."""

from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from artha.accountability.models import TraceNodeRow


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_decisions(self, limit: int = 50) -> list[str]:
        """List unique decision IDs, most recent first."""
        stmt = (
            select(TraceNodeRow.decision_id)
            .group_by(TraceNodeRow.decision_id)
            .order_by(func.max(TraceNodeRow.created_at).desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]
