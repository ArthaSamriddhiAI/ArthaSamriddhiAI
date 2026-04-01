"""Approval persistence."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.types import ApprovalID, DecisionID
from artha.accountability.models import ApprovalRecordRow
from artha.accountability.approval.models import ApprovalAction, ApprovalRecord


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_approval(
        self,
        decision_id: DecisionID,
        approver: str,
        action: ApprovalAction,
        rationale: str | None = None,
        conditions: str | None = None,
    ) -> ApprovalRecord:
        approval_id = ApprovalID(str(uuid.uuid4()))
        now = get_clock().now()

        row = ApprovalRecordRow(
            id=approval_id,
            decision_id=decision_id,
            approver=approver,
            action=action.value,
            rationale=rationale,
            conditions=conditions,
            created_at=now,
        )
        self._session.add(row)
        await self._session.flush()

        return ApprovalRecord(
            id=approval_id,
            decision_id=decision_id,
            approver=approver,
            action=action,
            rationale=rationale,
            conditions=conditions,
            created_at=now,
        )

    async def get_approvals(self, decision_id: DecisionID) -> list[ApprovalRecord]:
        stmt = (
            select(ApprovalRecordRow)
            .where(ApprovalRecordRow.decision_id == decision_id)
            .order_by(ApprovalRecordRow.created_at)
        )
        result = await self._session.execute(stmt)
        return [
            ApprovalRecord(
                id=row.id,
                decision_id=row.decision_id,
                approver=row.approver,
                action=ApprovalAction(row.action),
                rationale=row.rationale,
                conditions=row.conditions,
                created_at=row.created_at,
            )
            for row in result.scalars()
        ]
