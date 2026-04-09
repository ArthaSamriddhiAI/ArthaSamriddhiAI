"""Pydantic schemas for portfolio holdings and valuation."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AssetClass(str, Enum):
    EQUITY = "equity"
    MUTUAL_FUND = "mutual_fund"
    GOLD = "gold"
    SILVER = "silver"
    FD = "fd"
    BOND = "bond"
    PMS = "pms"
    AIF = "aif"
    REAL_ESTATE = "real_estate"
    INSURANCE = "insurance"
    CRYPTO = "crypto"
    PPF = "ppf"
    NPS = "nps"
    OTHER = "other"


ASSET_CLASS_LABELS = {
    "equity": "Equity", "mutual_fund": "Mutual Funds", "gold": "Gold",
    "silver": "Silver", "fd": "Fixed Deposits", "bond": "Bonds",
    "pms": "PMS", "aif": "AIF", "real_estate": "Real Estate",
    "insurance": "Insurance", "crypto": "Crypto", "ppf": "PPF/EPF",
    "nps": "NPS", "other": "Other",
}


class AddHoldingRequest(BaseModel):
    asset_class: str
    symbol_or_id: str
    description: str
    quantity: float
    acquisition_date: date
    acquisition_price: float
    current_price: float | None = None
    notes: str | None = None


class HoldingResponse(BaseModel):
    id: str
    investor_id: str
    asset_class: str
    asset_class_label: str = ""
    symbol_or_id: str
    description: str
    quantity: float
    acquisition_date: date
    acquisition_price: float
    cost_value: float = 0.0
    current_price: float | None = None
    current_value: float | None = None
    gain_loss: float | None = None
    gain_loss_pct: float | None = None
    notes: str | None = None


class AllocationItem(BaseModel):
    asset_class: str
    label: str
    current_value: float
    cost_value: float
    percentage: float
    holdings_count: int


class PortfolioSummary(BaseModel):
    investor_id: str
    investor_name: str = ""
    portfolio_status: str = "draft"  # draft | live
    portfolio_version: int = 1
    onboarding_type: str | None = None  # existing | partial | new_capital
    frozen_at: str | None = None
    frozen_by: str | None = None
    total_invested: float = 0.0
    current_value: float = 0.0
    total_gain_loss: float = 0.0
    total_gain_loss_pct: float = 0.0
    holdings_count: int = 0
    asset_classes_count: int = 0
    allocation: list[AllocationItem] = Field(default_factory=list)
    holdings: list[HoldingResponse] = Field(default_factory=list)


class UpdateHoldingRequest(BaseModel):
    """Update fields on an existing holding (DRAFT only)."""
    asset_class: str | None = None
    symbol_or_id: str | None = None
    description: str | None = None
    quantity: float | None = None
    acquisition_date: date | None = None
    acquisition_price: float | None = None
    current_price: float | None = None
    notes: str | None = None


class FreezeRequest(BaseModel):
    """Request to freeze (DRAFT→LIVE) a portfolio."""
    frozen_by: str = "advisor"


class UnfreezeRequest(BaseModel):
    """Request to unfreeze (LIVE→DRAFT) a portfolio."""
    unfrozen_by: str = "advisor"
    reason: str = ""


class PortfolioStatusResponse(BaseModel):
    investor_id: str
    status: str  # draft | live
    version: int
    onboarding_type: str | None = None
    frozen_at: str | None = None
    frozen_by: str | None = None
    is_editable: bool = True


class EditLogEntry(BaseModel):
    id: str
    action: str
    holding_id: str | None = None
    field_changed: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    actor: str = ""
    detail: str | None = None
    created_at: str = ""
