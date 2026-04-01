"""Decision persistence."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.types import DecisionID
from artha.decision.models import DecisionRecord
from artha.governance.models import GovernanceDecisionRow


class DecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: DecisionRecord) -> None:
        row = GovernanceDecisionRow(
            id=record.decision_id,
            intent_id=record.intent_id,
            intent_type=record.intent_type,
            status=record.status,
            rule_set_version_id=record.boundary.rule_set_version_id if record.boundary else None,
            evidence_snapshot_id=record.boundary.evidence_snapshot.id if record.boundary else None,
            result_json=json.dumps(record.result, default=str),
            created_at=record.created_at,
            completed_at=record.completed_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def get(self, decision_id: DecisionID) -> DecisionRecord | None:
        stmt = select(GovernanceDecisionRow).where(GovernanceDecisionRow.id == decision_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        return DecisionRecord(
            decision_id=row.id,
            intent_id=row.intent_id,
            intent_type=row.intent_type,
            status=row.status,
            result=json.loads(row.result_json) if row.result_json else {},
            created_at=row.created_at,
            completed_at=row.completed_at,
        )
