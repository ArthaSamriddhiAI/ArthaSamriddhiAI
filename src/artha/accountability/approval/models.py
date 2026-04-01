"""Approval record models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ApprovalAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    OVERRIDE = "override"


class ApprovalRecord(BaseModel):
    id: str
    decision_id: str
    approver: str
    action: ApprovalAction
    rationale: str | None = None
    conditions: str | None = None
    created_at: datetime
