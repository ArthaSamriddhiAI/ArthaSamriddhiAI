"""Section 15.6.8 — M0.PortfolioAnalytics canonical schemas.

The eight metric categories per Section 8.9.2 each have a typed Pydantic output.
Every category carries a `MetricFlags` sub-object for quality propagation
(`look_through_unavailable_pct`, `tax_basis_stale_days`, `fee_data_incomplete`).
The query envelope (`AnalyticsQueryInput`) names the categories the caller
wants; the response (`AnalyticsQueryResult`) populates only those.

Per Section 8.9 PortfolioAnalytics is deterministic and queryable, never prompted.
This module is schemas only; compute lives in `portfolio_analysis.canonical_metrics`.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import (
    BasisPointsField,
    InputsUsedManifest,
    INRAmountField,
    PercentageField,
)


class MetricCategory(str, Enum):
    """Section 8.9.2 — the eight metric categories the caller can request."""

    DEPLOYMENT = "deployment"
    RETURNS = "returns"
    PROFITABILITY = "profitability"
    FEES = "fees"
    CONCENTRATION = "concentration"
    LIQUIDITY = "liquidity"
    TAX = "tax"
    VINTAGE = "vintage"


class MetricFlags(BaseModel):
    """Per-metric quality flags propagated to consumers (Section 8.9.2 / 8.9.7).

    `look_through_unavailable_pct` — fraction of portfolio with no look-through.
    `tax_basis_stale_days` — None if fresh; integer days if stale.
    `fee_data_incomplete` — true if any holding lacks fee data.
    `other_flags` — free-form named flags for specific edge cases.
    """

    model_config = ConfigDict(extra="forbid")

    look_through_unavailable_pct: PercentageField = 0.0
    tax_basis_stale_days: int | None = None
    fee_data_incomplete: bool = False
    other_flags: list[str] = Field(default_factory=list)


# ===========================================================================
# Per-category output schemas
# ===========================================================================


class DeploymentMetrics(BaseModel):
    """Section 8.9.2 — deployment metrics.

    `total_aum_inr` is the headline. `cash_buffer_inr` is the operational cash
    buffer per Section 5.6 (kept *outside* the model portfolio's L1 sum).
    `undeployed_investable_assets_inr` is cash beyond the buffer that's
    available for deployment.
    """

    model_config = ConfigDict(extra="forbid")

    total_aum_inr: INRAmountField
    committed_capital_inr: INRAmountField = 0.0
    called_capital_inr: INRAmountField = 0.0
    uncalled_capital_inr: INRAmountField = 0.0
    deployment_ratio: PercentageField = 0.0  # called / committed; 0 if no commitments
    cash_buffer_inr: INRAmountField = 0.0
    undeployed_investable_assets_inr: INRAmountField = 0.0
    flags: MetricFlags = Field(default_factory=MetricFlags)


class PeriodReturn(BaseModel):
    """Returns for a single period with explicit net-of disclosures (Section 3.3, 8.9.3)."""

    model_config = ConfigDict(extra="forbid")

    period_label: str  # "1Y" | "3Y" | "5Y" | "since_inception" | "<start>_<end>"
    start_date: date
    end_date: date
    twr: float | None = None  # time-weighted return (fraction)
    xirr: float | None = None  # money-weighted return (fraction)
    gross_return: float | None = None
    net_of_costs_return: float | None = None
    net_of_costs_and_taxes_return: float | None = None
    real_return: float | None = None  # net-of-all minus inflation


class ReturnsMetrics(BaseModel):
    """Section 8.9.2 — normalised returns. Period breakdowns are dict-keyed
    by period_label → axis_value → return."""

    model_config = ConfigDict(extra="forbid")

    period_returns: list[PeriodReturn] = Field(default_factory=list)
    period_breakdown_by_asset_class: dict[str, dict[str, float]] = Field(default_factory=dict)
    period_breakdown_by_vehicle: dict[str, dict[str, float]] = Field(default_factory=dict)
    period_breakdown_by_sub_asset_class: dict[str, dict[str, float]] = Field(default_factory=dict)
    flags: MetricFlags = Field(default_factory=MetricFlags)


class ProfitabilityMetrics(BaseModel):
    """Section 8.9.2 — aggregated profitability via look-through.

    `equity_quality_score` is a 0–100 composite of ROCE, PAT margin, and 3-year
    earnings growth (Section 8.9.2). The exact composite formula is the firm's
    calibration; in MVP it's a placeholder consumers can fill from upstream
    fundamental data.
    """

    model_config = ConfigDict(extra="forbid")

    weighted_roce: float | None = None
    weighted_pat_margin: float | None = None
    weighted_earnings_growth_3y: float | None = None
    equity_quality_score: float | None = None  # 0-100
    flags: MetricFlags = Field(default_factory=MetricFlags)


class FeeBreakdown(BaseModel):
    """Per-vehicle fee contribution row (Section 8.9.2)."""

    model_config = ConfigDict(extra="forbid")

    vehicle_type: str
    fee_bps: BasisPointsField
    contribution_inr: INRAmountField


class FeeMetrics(BaseModel):
    """Section 8.9.2 — cost and fee aggregation."""

    model_config = ConfigDict(extra="forbid")

    aggregate_fee_bps: BasisPointsField = 0
    fee_breakdown: list[FeeBreakdown] = Field(default_factory=list)
    fee_drag_annualised_bps: BasisPointsField = 0
    fee_efficiency_ratio: float | None = None  # gross_return / fees_as_fraction
    flags: MetricFlags = Field(default_factory=MetricFlags)


class TopNConcentration(BaseModel):
    """A `top_N` row: combined weight of the largest N positions (Section 8.9.2)."""

    model_config = ConfigDict(extra="forbid")

    n: int
    weight: PercentageField


class ConcentrationMetrics(BaseModel):
    """Section 8.9.2 — multi-level concentration.

    HHI is the Herfindahl-Hirschman Index (sum of squared weights). Range [0, 1];
    higher = more concentrated. A monopoly (single 100% holding) has HHI=1.0;
    perfectly even N-way splits have HHI=1/N.

    `look_through_depth` is the depth used to compute look-through metrics
    (1 for AMC-published holdings; deeper if the firm has access to PMS or AIF
    look-through). Per Section 8.9.3 every look-through metric reports its depth.
    """

    model_config = ConfigDict(extra="forbid")

    hhi_holding_level: float = 0.0
    hhi_sector_level: float | None = None
    hhi_manager_level: float = 0.0
    hhi_lookthrough_stock_level: float | None = None
    top_n_holding_level: list[TopNConcentration] = Field(default_factory=list)
    top_n_lookthrough_level: list[TopNConcentration] = Field(default_factory=list)
    look_through_depth: int = 1
    flags: MetricFlags = Field(default_factory=MetricFlags)


class LiquidityBucket(str, Enum):
    """Section 8.9.2 — the seven liquidity buckets by horizon."""

    DAYS_0_7 = "0_7_days"
    DAYS_7_30 = "7_30_days"
    DAYS_30_90 = "30_90_days"
    DAYS_90_365 = "90_365_days"
    YEARS_1_3 = "1_3_years"
    YEARS_3_7 = "3_7_years"
    BEYOND_7_YEARS = "beyond_7_years"


class CashflowEntryAnalytics(BaseModel):
    """Forecast cash flow event (Section 8.9.2 cashflow_schedule)."""

    model_config = ConfigDict(extra="forbid")

    expected_date: date
    expected_amount_inr: float  # signed: positive = inflow to client, negative = outflow
    source_holding_id: str
    event_type: str  # "redemption" | "distribution" | "capital_call" | "maturity"


class LiquidityMetrics(BaseModel):
    """Section 8.9.2 — liquidity profile.

    `liquidity_buckets` map bucket → fraction of portfolio AUM in that bucket
    (sums to 1.0 across buckets, within float epsilon).
    `liquidity_floor_compliance` is true if the most-liquid (0–7 day) bucket
    meets or exceeds the mandate's liquidity floor; the floor itself is
    threaded in by the caller.
    """

    model_config = ConfigDict(extra="forbid")

    liquidity_buckets: dict[LiquidityBucket, PercentageField] = Field(default_factory=dict)
    liquidity_floor_compliance: bool = True
    cashflow_schedule: list[CashflowEntryAnalytics] = Field(default_factory=list)
    flags: MetricFlags = Field(default_factory=MetricFlags)


class TaxMetrics(BaseModel):
    """Section 8.9.2 — tax position.

    Short-term vs long-term split uses the standard Indian holding-period rule
    for equities (≥1 year = long-term). For other asset classes the caller can
    pass overrides; default is the equity rule.
    """

    model_config = ConfigDict(extra="forbid")

    unrealised_gain_loss_total_inr: INRAmountField = 0.0
    unrealised_short_term_inr: INRAmountField = 0.0
    unrealised_long_term_inr: INRAmountField = 0.0
    harvestable_short_term_loss_inr: INRAmountField = 0.0  # |negative gain| portion
    harvestable_long_term_loss_inr: INRAmountField = 0.0
    taxable_distribution_estimate_next_12m_inr: INRAmountField = 0.0
    flags: MetricFlags = Field(default_factory=MetricFlags)


class AifVintageEntry(BaseModel):
    """Per-AIF vintage entry (Section 8.9.2)."""

    model_config = ConfigDict(extra="forbid")

    holding_id: str
    instrument_name: str
    vintage_year: int
    in_commitment_period: bool = True
    in_distribution_period: bool = False


class VintageMetrics(BaseModel):
    """Section 8.9.2 — AIF and PMS vintage profile."""

    model_config = ConfigDict(extra="forbid")

    aif_vintages: list[AifVintageEntry] = Field(default_factory=list)
    pms_inception_dates: dict[str, date] = Field(default_factory=dict)
    vintage_distribution: dict[int, PercentageField] = Field(default_factory=dict)
    flags: MetricFlags = Field(default_factory=MetricFlags)


# ===========================================================================
# Query input / output envelope (Section 15.6.8)
# ===========================================================================


class AnalyticsQueryInput(BaseModel):
    """Section 15.6.8 input envelope.

    `period_overrides` lets the caller request returns over arbitrary windows
    in addition to the standard 1Y/3Y/5Y/since-inception periods. Each entry
    is `(start_date, end_date)` — both inclusive.

    `look_through_depth` is the maximum depth the caller wants: None means
    "use whatever the firm has". Section 8.9.3 says every look-through metric
    reports its actual depth via `look_through_depth` on the output.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str
    as_of_date: date
    metric_categories: list[MetricCategory]
    period_overrides: list[tuple[date, date]] = Field(default_factory=list)
    look_through_depth: int | None = None


class AnalyticsQueryResult(BaseModel):
    """Section 15.6.8 output envelope.

    Only categories the caller requested are populated; the rest stay None.
    `snapshot_id` is a deterministic hash of the input bundle — equal IDs
    mean equal inputs; consumers can cache on this.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str
    as_of_date: date
    snapshot_id: str  # SHA-256 of the canonicalised input context
    deployment: DeploymentMetrics | None = None
    returns: ReturnsMetrics | None = None
    profitability: ProfitabilityMetrics | None = None
    fees: FeeMetrics | None = None
    concentration: ConcentrationMetrics | None = None
    liquidity: LiquidityMetrics | None = None
    tax: TaxMetrics | None = None
    vintage: VintageMetrics | None = None
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    cache_hit: bool = False
