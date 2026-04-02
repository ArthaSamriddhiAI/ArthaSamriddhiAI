"""SQLAlchemy ORM models for the Investor Risk Profile module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class InvestorRow(Base):
    """Core investor record."""

    __tablename__ = "investors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    investor_type: Mapped[str] = mapped_column(String(32), nullable=False)  # individual, hni, family_office, nri
    family_office_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FamilyOfficeRow(Base):
    """Family/Family Office record for HNI 5Cr+ clients."""

    __tablename__ = "family_offices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    office_type: Mapped[str] = mapped_column(String(32), nullable=False)  # single_family, multi_family, informal_joint
    total_aum_band: Mapped[str | None] = mapped_column(String(32), nullable=True)
    complexity_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    governance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuestionnaireResponseRow(Base):
    """Individual question response from risk profiling questionnaire."""

    __tablename__ = "questionnaire_responses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    selected_option: Mapped[str] = mapped_column(String(1), nullable=False)  # a, b, c, d
    score: Mapped[int] = mapped_column(Integer, nullable=False)  # 10, 20, 30, 40
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FamilyOfficeResponseRow(Base):
    """Family/FO section questionnaire responses."""

    __tablename__ = "family_office_responses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    family_office_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    selected_option: Mapped[str] = mapped_column(String(1), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvestorRiskProfileRow(Base):
    """Computed risk profile — output of the scoring engine."""

    __tablename__ = "investor_risk_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_category: Mapped[str] = mapped_column(String(32), nullable=False)
    category_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    family_complexity_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    family_constraints_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    questionnaire_version: Mapped[str] = mapped_column(String(16), default="1.0")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # AI-generated narrative and flags
    ai_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_flags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assessment_context: Mapped[str | None] = mapped_column(String(64), nullable=True)  # annual_review, onboarding, ad_hoc, regulatory


class AssessmentHistoryRow(Base):
    """Immutable historical log of all risk profile assessments."""

    __tablename__ = "assessment_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessment_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assessment_context: Mapped[str] = mapped_column(String(64), nullable=False)
    assessed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_category: Mapped[str] = mapped_column(String(32), nullable=False)
    category_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    effective_constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    family_complexity_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_flags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    responses_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)  # Full Q&A snapshot
    score_change_from_previous: Mapped[float | None] = mapped_column(Float, nullable=True)
    category_change_from_previous: Mapped[str | None] = mapped_column(String(32), nullable=True)
