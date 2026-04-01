"""SQLAlchemy ORM models for the Governance layer."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class RuleSetVersionRow(Base):
    """Persisted rule set version for audit trail."""

    __tablename__ = "rule_set_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rules_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GovernanceDecisionRow(Base):
    """Record of a governance decision outcome."""

    __tablename__ = "governance_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    intent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # pending, approved, rejected, escalated
    rule_set_version_id: Mapped[str] = mapped_column(String(36), nullable=True)
    evidence_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
