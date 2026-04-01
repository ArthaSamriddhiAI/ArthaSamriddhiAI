"""SQLAlchemy ORM models for the Accountability layer."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class TraceNodeRow(Base):
    """A node in the decision trace DAG."""

    __tablename__ = "trace_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_node_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalRecordRow(Base):
    """Record of a human approval or override."""

    __tablename__ = "approval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    approver: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # approve, reject, override
    rationale: Mapped[str] = mapped_column(Text, nullable=True)
    conditions: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
