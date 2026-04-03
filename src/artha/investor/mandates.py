"""Per-investor mandates — custom governance rules editable by the advisor.

Mandates are stored per investor and injected into the governance pipeline
at decision time. They override or tighten global rules.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from artha.common.db.base import Base


class InvestorMandateRow(Base):
    """Per-investor governance mandate."""

    __tablename__ = "investor_mandates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    mandate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), default="advisor")


# ── Predefined Mandate Types ──

MANDATE_TYPES = {
    "max_single_position_pct": {
        "label": "Max Single Position %",
        "description": "Maximum weight any single holding can have in the portfolio",
        "value_type": "number",
        "default": 25,
        "unit": "%",
        "category": "concentration",
    },
    "max_sector_exposure_pct": {
        "label": "Max Sector Exposure %",
        "description": "Maximum allocation to any single sector",
        "value_type": "number",
        "default": 40,
        "unit": "%",
        "category": "concentration",
    },
    "min_positions": {
        "label": "Minimum Number of Positions",
        "description": "Portfolio must hold at least this many positions",
        "value_type": "number",
        "default": 5,
        "unit": "positions",
        "category": "diversification",
    },
    "max_equity_pct": {
        "label": "Max Equity Allocation %",
        "description": "Maximum percentage in equities (stocks + equity MFs)",
        "value_type": "number",
        "default": 70,
        "unit": "%",
        "category": "allocation",
    },
    "min_debt_pct": {
        "label": "Min Debt/FD Allocation %",
        "description": "Minimum percentage in debt instruments (FDs, bonds, debt MFs)",
        "value_type": "number",
        "default": 0,
        "unit": "%",
        "category": "allocation",
    },
    "max_crypto_pct": {
        "label": "Max Crypto Allocation %",
        "description": "Maximum allocation to cryptocurrency",
        "value_type": "number",
        "default": 5,
        "unit": "%",
        "category": "allocation",
    },
    "max_single_pms_aif_pct": {
        "label": "Max Single PMS/AIF %",
        "description": "Maximum allocation to any single PMS or AIF",
        "value_type": "number",
        "default": 15,
        "unit": "%",
        "category": "concentration",
    },
    "excluded_symbols": {
        "label": "Excluded Symbols",
        "description": "Symbols that cannot be held (e.g., tobacco, oil stocks)",
        "value_type": "list",
        "default": [],
        "unit": "",
        "category": "exclusion",
    },
    "excluded_sectors": {
        "label": "Excluded Sectors",
        "description": "Sectors excluded from the portfolio (e.g., Tobacco, Alcohol, Coal)",
        "value_type": "list",
        "default": [],
        "unit": "",
        "category": "exclusion",
    },
    "allowed_universe": {
        "label": "Allowed Stock Universe",
        "description": "Restrict stocks to a specific universe (e.g., Nifty 100, Nifty 500)",
        "value_type": "choice",
        "choices": ["any", "nifty_50", "nifty_100", "nifty_200", "nifty_500"],
        "default": "any",
        "unit": "",
        "category": "universe",
    },
    "min_esg_score": {
        "label": "Minimum ESG Score",
        "description": "Only allow companies with ESG score above this threshold",
        "value_type": "number",
        "default": 0,
        "unit": "score",
        "category": "esg",
    },
    "max_drawdown_pct": {
        "label": "Max Acceptable Drawdown %",
        "description": "Maximum portfolio drawdown the client can tolerate",
        "value_type": "number",
        "default": 25,
        "unit": "%",
        "category": "risk",
    },
    "require_committee_approval": {
        "label": "Require Committee Approval",
        "description": "All rebalance decisions require committee/family approval",
        "value_type": "boolean",
        "default": False,
        "unit": "",
        "category": "governance",
    },
    "max_international_pct": {
        "label": "Max International Exposure %",
        "description": "Maximum allocation to international/foreign investments",
        "value_type": "number",
        "default": 20,
        "unit": "%",
        "category": "allocation",
    },
    "custom_note": {
        "label": "Custom Mandate Note",
        "description": "Free-text mandate instruction for agents to consider",
        "value_type": "text",
        "default": "",
        "unit": "",
        "category": "custom",
    },
}


class MandateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_mandates(self, investor_id: str) -> list[dict]:
        """Get all active mandates for an investor."""
        stmt = (
            select(InvestorMandateRow)
            .where(InvestorMandateRow.investor_id == investor_id, InvestorMandateRow.active == True)
            .order_by(InvestorMandateRow.created_at)
        )
        result = await self._session.execute(stmt)
        return [self._to_dict(r) for r in result.scalars()]

    async def set_mandate(self, investor_id: str, mandate_type: str, value: Any, created_by: str = "advisor") -> dict:
        """Set or update a mandate for an investor. Deactivates previous version."""
        now = datetime.now(UTC)

        # Deactivate existing mandate of same type
        stmt = select(InvestorMandateRow).where(
            InvestorMandateRow.investor_id == investor_id,
            InvestorMandateRow.mandate_type == mandate_type,
            InvestorMandateRow.active == True,
        )
        existing = await self._session.execute(stmt)
        for row in existing.scalars():
            row.active = False

        # Get label from type definition
        type_def = MANDATE_TYPES.get(mandate_type, {})
        label = type_def.get("label", mandate_type)

        row = InvestorMandateRow(
            id=str(uuid.uuid4()),
            investor_id=investor_id,
            mandate_type=mandate_type,
            label=label,
            value_json=json.dumps(value),
            active=True,
            created_at=now,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_dict(row)

    async def delete_mandate(self, mandate_id: str) -> bool:
        stmt = select(InvestorMandateRow).where(InvestorMandateRow.id == mandate_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.active = False
            await self._session.flush()
            return True
        return False

    async def get_mandates_for_governance(self, investor_id: str) -> dict[str, Any]:
        """Get mandates formatted for injection into governance pipeline."""
        mandates = await self.get_mandates(investor_id)
        result = {}
        for m in mandates:
            result[m["mandate_type"]] = m["value"]
        return result

    def _to_dict(self, row: InvestorMandateRow) -> dict:
        type_def = MANDATE_TYPES.get(row.mandate_type, {})
        return {
            "id": row.id,
            "investor_id": row.investor_id,
            "mandate_type": row.mandate_type,
            "label": row.label,
            "value": json.loads(row.value_json),
            "category": type_def.get("category", "custom"),
            "description": type_def.get("description", ""),
            "unit": type_def.get("unit", ""),
            "value_type": type_def.get("value_type", "text"),
            "active": row.active,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
