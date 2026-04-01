"""API schemas for the Accountability layer."""

from __future__ import annotations

from pydantic import BaseModel

from artha.accountability.approval.models import ApprovalAction


class SubmitApprovalRequest(BaseModel):
    decision_id: str
    approver: str
    action: ApprovalAction
    rationale: str | None = None
    conditions: str | None = None
