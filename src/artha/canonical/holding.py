"""Section 15.3.3/4 — Holding and PortfolioState response objects.

These are the structured query outputs M0.PortfolioState exposes to downstream
agents. Pass 5 (M0.PortfolioAnalytics) will consume these as substrate.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import (
    AssetClass,
    INRAmountField,
    PercentageField,
    VehicleType,
)


class Holding(BaseModel):
    """Per Section 15.3.3 — one position in a client's portfolio."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    instrument_name: str
    units: float
    cost_basis: INRAmountField
    market_value: INRAmountField
    unrealised_gain_loss: INRAmountField
    amc_or_issuer: str
    vehicle_type: VehicleType
    asset_class: AssetClass
    sub_asset_class: str
    acquisition_date: date
    as_of_date: date

    lock_in_expiry: date | None = None
    tax_basis_per_unit: INRAmountField | None = None
    life_event_tags: list[str] = Field(default_factory=list)

    # Quality flags propagated to downstream agents
    tax_basis_stale: bool = False
    look_through_unavailable: bool = False


class SliceResponse(BaseModel):
    """Per Section 15.3.4 — a slice of holdings plus aggregate fields."""

    model_config = ConfigDict(extra="forbid")

    holdings: list[Holding]
    total_value_inr: INRAmountField
    total_units_by_amc: dict[str, float] = Field(default_factory=dict)


class LookThroughEntry(BaseModel):
    """One row of a look-through view: an underlying exposure and its weight."""

    model_config = ConfigDict(extra="forbid")

    underlying_holding_id: str
    underlying_name: str
    weight_in_portfolio: PercentageField
    weight_in_parent: PercentageField


class LookThroughResponse(BaseModel):
    """Per Section 15.3.4 — the look-through view of a fund/PMS/AIF holding."""

    model_config = ConfigDict(extra="forbid")

    parent_instrument_id: str
    entries: list[LookThroughEntry] = Field(default_factory=list)


class CascadeCertainty(str, Enum):
    """How confident we are about a forecast cash-flow event."""

    CERTAIN = "certain"
    LIKELY = "likely"
    POSSIBLE = "possible"


class CascadeEventType(str, Enum):
    """Per Section 15.3.4."""

    REDEMPTION = "redemption"
    DISTRIBUTION = "distribution"
    CAPITAL_CALL = "capital_call"
    MATURITY = "maturity"


class CascadeEvent(BaseModel):
    """Per Section 15.3.4 — a forecast cash-flow event from holdings."""

    model_config = ConfigDict(extra="forbid")

    event_type: CascadeEventType
    expected_date: date
    expected_amount_inr: INRAmountField
    source_holding_id: str
    certainty_band: CascadeCertainty


class IngestionReport(BaseModel):
    """Per Section 15.3.4 — outcome of external-portfolio ingestion + reconciliation."""

    model_config = ConfigDict(extra="forbid")

    mapped_count: int = 0
    unmappable_list: list[dict[str, Any]] = Field(default_factory=list)
    reconciliation_summary: dict[str, Any] = Field(default_factory=dict)
    pending_advisor_confirmations: list[str] = Field(default_factory=list)


class ConflictType(str, Enum):
    """Per Section 5.10 / 15.3.4 — what kind of conflict was detected."""

    MANDATE_VS_MODEL = "mandate_vs_model"
    OUT_OF_BUCKET = "out_of_bucket"
    WEALTH_TIER_ELIGIBILITY = "wealth_tier_eligibility"


class ConflictReport(BaseModel):
    """Per Section 15.3.4 — surfaced via M0.PortfolioState's conflict_detection query.

    Pass 3 will populate `resolution_paths` from the three options in Section 5.10
    (amend mandate, override-clip the model, flag out-of-bucket). For Pass 2 the
    schema is shipped; the population logic comes with the model_portfolio service.
    """

    model_config = ConfigDict(extra="forbid")

    conflict_type: ConflictType
    dimension: str  # e.g. "asset_class.equity"
    mandate_value: Any | None = None
    model_value: Any | None = None
    resolution_paths: list[str] = Field(default_factory=list)
