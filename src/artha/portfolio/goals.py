"""Goal-Based Planning — financial goals with progress tracking and SIP computation."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select, String, Date, Float, Integer, Text, DateTime, Boolean
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class FinancialGoalRow(Base):
    __tablename__ = "financial_goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    goal_name: Mapped[str] = mapped_column(String(128), nullable=False)
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    current_allocation: Mapped[float] = mapped_column(Float, default=0.0)
    priority: Mapped[str] = mapped_column(String(16), default="medium")  # high, medium, low
    expected_return_pct: Mapped[float] = mapped_column(Float, default=12.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def compute_goal_metrics(goal: dict, portfolio_value: float = 0) -> dict:
    """Compute progress, monthly SIP needed, and time to goal."""
    target = goal.get("target_amount", 0)
    current = goal.get("current_allocation", 0)
    target_date_str = str(goal.get("target_date", ""))
    expected_return = goal.get("expected_return_pct", 12.0)

    # Parse target date
    try:
        parts = target_date_str.split("-")
        td = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        td = date.today().replace(year=date.today().year + 5)

    today = date.today()
    months_remaining = max(1, (td.year - today.year) * 12 + (td.month - today.month))
    years_remaining = months_remaining / 12

    # Progress
    progress_pct = min(100, (current / target * 100)) if target > 0 else 0

    # Gap
    gap = max(0, target - current)

    # Monthly SIP needed to close gap (using FV of annuity formula)
    monthly_rate = expected_return / 100 / 12
    if monthly_rate > 0 and months_remaining > 0:
        # FV = PMT * ((1+r)^n - 1) / r → PMT = FV * r / ((1+r)^n - 1)
        factor = ((1 + monthly_rate) ** months_remaining - 1) / monthly_rate
        monthly_sip = gap / factor if factor > 0 else gap / months_remaining
    else:
        monthly_sip = gap / months_remaining if months_remaining > 0 else gap

    return {
        **goal,
        "progress_pct": round(progress_pct, 1),
        "gap_amount": round(gap, 0),
        "months_remaining": months_remaining,
        "years_remaining": round(years_remaining, 1),
        "monthly_sip_required": round(monthly_sip, 0),
        "on_track": progress_pct >= (100 - (months_remaining / max(1, (td - date(td.year - 10, td.month, td.day)).days / 30) * 100)),
    }


class GoalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_goal(self, investor_id: str, data: dict) -> dict:
        now = datetime.now(UTC)
        row = FinancialGoalRow(
            id=str(uuid.uuid4()),
            investor_id=investor_id,
            goal_name=data.get("goal_name", ""),
            target_amount=float(data.get("target_amount", 0)),
            target_date=data.get("target_date"),
            current_allocation=float(data.get("current_allocation", 0)),
            priority=data.get("priority", "medium"),
            expected_return_pct=float(data.get("expected_return_pct", 12.0)),
            notes=data.get("notes"),
            created_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_dict(row)

    async def get_goals(self, investor_id: str) -> list[dict]:
        stmt = select(FinancialGoalRow).where(
            FinancialGoalRow.investor_id == investor_id,
            FinancialGoalRow.active == True,
        ).order_by(FinancialGoalRow.target_date)
        result = await self._session.execute(stmt)
        goals = [self._to_dict(r) for r in result.scalars()]
        return [compute_goal_metrics(g) for g in goals]

    async def delete_goal(self, goal_id: str) -> bool:
        stmt = select(FinancialGoalRow).where(FinancialGoalRow.id == goal_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.active = False
            await self._session.flush()
            return True
        return False

    def _to_dict(self, row: FinancialGoalRow) -> dict:
        return {
            "id": row.id,
            "investor_id": row.investor_id,
            "goal_name": row.goal_name,
            "target_amount": row.target_amount,
            "target_date": str(row.target_date),
            "current_allocation": row.current_allocation,
            "priority": row.priority,
            "expected_return_pct": row.expected_return_pct,
            "notes": row.notes,
        }
