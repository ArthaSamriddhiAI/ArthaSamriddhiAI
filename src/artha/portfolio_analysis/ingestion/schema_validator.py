"""Pydantic models and validation for the canonical portfolio JSON."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AssetClass(str, Enum):
    LISTED_EQUITY = "listed_equity"
    MUTUAL_FUND = "mutual_fund"
    PMS = "pms"
    AIF_CAT1 = "aif_cat1"
    AIF_CAT2 = "aif_cat2"
    AIF_CAT3 = "aif_cat3"
    UNLISTED_EQUITY = "unlisted_equity"
    CASH = "cash"


class HoldingItem(BaseModel):
    """A single holding in the canonical portfolio."""

    holding_id: str
    instrument_name: str
    isin_or_cin: str | None = None
    asset_class: AssetClass
    current_value_inr: float = 0.0
    purchase_date: str | None = None
    purchase_price_per_unit: float | None = None
    quantity_or_units: float | None = None
    folio_or_account_no: str | None = None
    cost_basis: float | None = None
    weight_pct: float = 0.0
    holding_period_days: int | None = None
    ltcg_eligible: bool | None = None
    data_gaps: list[str] = Field(default_factory=list)

    # ECAS-specific optional fields
    amfi_code: str | None = None
    current_nav: float | None = None
    current_units: float | None = None

    @field_validator("asset_class", mode="before")
    @classmethod
    def _coerce_asset_class(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v


class AssetClassBreakdown(BaseModel):
    """Aggregated view of a single asset class within the portfolio."""

    asset_class: str
    total_value_inr: float = 0.0
    weight_pct: float = 0.0
    holdings_count: int = 0


class DataQualitySummary(BaseModel):
    """Summary of data completeness and quality issues."""

    total_holdings: int = 0
    holdings_with_gaps: int = 0
    total_data_gaps: int = 0
    gap_details: list[dict[str, Any]] = Field(default_factory=list)
    source: str | None = None
    note: str | None = None


class CanonicalPortfolio(BaseModel):
    """The canonical portfolio structure used throughout the PAM pipeline."""

    holdings: list[HoldingItem] = Field(default_factory=list)
    asset_class_breakdown: list[AssetClassBreakdown] = Field(default_factory=list)
    data_quality_summary: DataQualitySummary = Field(default_factory=DataQualitySummary)
    total_value_inr: float = 0.0


def validate_portfolio(data: dict) -> CanonicalPortfolio:
    """Validate a raw dict and return a typed CanonicalPortfolio.

    Raises ``pydantic.ValidationError`` if the data does not conform.
    """
    return CanonicalPortfolio.model_validate(data)


def check_preconditions(portfolio: CanonicalPortfolio, has_mandate: bool) -> list[str]:
    """Check whether a portfolio meets all preconditions for analysis.

    Returns a list of failed precondition descriptions.
    An empty list means all preconditions pass.
    """
    failures: list[str] = []

    # P1: Must have at least one holding
    if not portfolio.holdings:
        failures.append("Portfolio has no holdings.")

    # P2: Total AUM must be positive
    if portfolio.total_value_inr <= 0:
        failures.append("Portfolio total value is zero or negative.")

    # P3: Mandate must be present
    if not has_mandate:
        failures.append("No active investment mandate found for this client.")

    # P4: Data quality — at most 30% of holdings may have critical data gaps
    if portfolio.holdings:
        critical_gap_count = sum(
            1 for h in portfolio.holdings
            if "current_value_inr" in h.data_gaps or "asset_class" in h.data_gaps
        )
        gap_ratio = critical_gap_count / len(portfolio.holdings)
        if gap_ratio > 0.30:
            failures.append(
                f"Too many critical data gaps: {critical_gap_count}/{len(portfolio.holdings)} "
                f"holdings ({gap_ratio:.0%}) are missing current_value or asset_class."
            )

    # P5: At least one non-cash holding
    non_cash = [h for h in portfolio.holdings if h.asset_class != AssetClass.CASH]
    if not non_cash:
        failures.append("Portfolio contains only cash holdings — no analysis needed.")

    return failures
