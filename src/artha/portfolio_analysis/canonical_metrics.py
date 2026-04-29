"""Section 8.9.2 — deterministic compute functions for the M0.PortfolioAnalytics layer.

Every function takes a `PortfolioAnalyticsContext` plus optional config and
returns the canonical Pydantic output. All formulas are explicit; no LLM, no
randomness. Same inputs → same outputs (Section 8.9.3 determinism rule).

Per Section 8.9.3:
  * Returns are reported to two decimal places as fractions; presentation
    layer multiplies by 100 for percent display.
  * HHI is reported to four decimal places (we keep full float precision in
    the output object; rounding is presentation's job).
  * Currency is INR throughout; lakh-crore formatting is the presentation
    layer's responsibility.
  * Look-through metrics report their depth via `look_through_depth` on the
    output so consumers can decide whether to act on partial data.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.holding import Holding, LookThroughEntry
from artha.canonical.l4_manifest import FeeSchedule
from artha.canonical.portfolio_analytics import (
    AifVintageEntry,
    CashflowEntryAnalytics,
    ConcentrationMetrics,
    DeploymentMetrics,
    FeeBreakdown,
    FeeMetrics,
    LiquidityBucket,
    LiquidityMetrics,
    MetricFlags,
    ProfitabilityMetrics,
    ReturnsMetrics,
    TaxMetrics,
    TopNConcentration,
    VintageMetrics,
)
from artha.common.types import VehicleType

# Indian equity holding-period rule per Section 8.9.2 — ≥365 days = long-term.
# Other asset classes (debt MFs, gold, etc.) have different rules; consumers
# can override via `tax_holding_period_threshold_days`.
_DEFAULT_LONG_TERM_THRESHOLD_DAYS = 365

# Standard top-N values per Section 8.9.2.
_DEFAULT_TOP_N = (1, 5, 10, 20)


# ===========================================================================
# Compute context
# ===========================================================================


class HoldingCommitment(BaseModel):
    """Capital-call data for an AIF or commitment-based holding."""

    model_config = ConfigDict(extra="forbid")

    committed_inr: float = 0.0
    called_inr: float = 0.0


class PortfolioAnalyticsContext(BaseModel):
    """Substrate for every M0.PortfolioAnalytics computation.

    Each metric reads the fields it needs and uses safe defaults for absent
    inputs (e.g. zero look-through gives `look_through_unavailable_pct=1.0`).
    Pass 5's contract is purity: same context produces the same outputs.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str
    as_of_date: date
    holdings: list[Holding] = Field(default_factory=list)

    # Operational cash buffer per Section 5.6 — cash up to this threshold is
    # the household buffer; cash beyond it is undeployed investable AUM.
    cash_buffer_threshold_inr: float = 0.0

    # Instrument-level metadata (sector, AMC, etc.) for concentration HHI.
    instrument_sectors: dict[str, str] = Field(default_factory=dict)

    # Look-through holdings: parent instrument_id → entries with weight_in_portfolio
    # already factored in. Section 8.9.3 — the look-through depth is reported
    # alongside the metric so consumers know whether the view is partial.
    look_through: dict[str, list[LookThroughEntry]] = Field(default_factory=dict)
    look_through_depth: int = 1

    # Fee schedules from L4 (instrument_id → FeeSchedule).
    fee_schedules: dict[str, FeeSchedule] = Field(default_factory=dict)

    # Forecast cash flow events (used by liquidity_metrics.cashflow_schedule).
    forecast_cash_flows: list[CashflowEntryAnalytics] = Field(default_factory=list)

    # Historical cash flow series for XIRR (date, signed_amount). Convention:
    # outflows from client (purchases) negative, inflows to client (distributions,
    # terminal value) positive.
    cash_flow_history: list[tuple[date, float]] = Field(default_factory=list)

    # CPI series for real return computation (date, level).
    cpi_series: list[tuple[date, float]] = Field(default_factory=list)

    # Tax basis freshness window. If None or not stale, no flag.
    tax_basis_as_of: date | None = None
    tax_holding_period_threshold_days: int = _DEFAULT_LONG_TERM_THRESHOLD_DAYS

    # Mandate liquidity floor (used by liquidity_floor_compliance check).
    liquidity_floor: float = 0.0

    # AIF / commitment data, keyed by holding instrument_id.
    holding_commitments: dict[str, HoldingCommitment] = Field(default_factory=dict)
    holding_vintage_year: dict[str, int] = Field(default_factory=dict)
    holding_in_commitment_period: dict[str, bool] = Field(default_factory=dict)
    holding_in_distribution_period: dict[str, bool] = Field(default_factory=dict)


# ===========================================================================
# Helpers
# ===========================================================================


def _hhi(weights: list[float]) -> float:
    """Herfindahl-Hirschman Index — sum of squared weights. Range [0, 1]."""
    return sum(w * w for w in weights)


def _top_n_weight(sorted_weights_desc: list[float], n: int) -> float:
    """Combined weight of the top N entries from a pre-sorted (descending) list."""
    return sum(sorted_weights_desc[: max(0, n)])


def _holding_weights(holdings: list[Holding]) -> dict[str, float]:
    """Per-holding weight as a fraction of total market value.

    If total market value is 0, every weight is 0 (avoids divide-by-zero on
    zero-AUM portfolios per Section 8.9.7 edge case).
    """
    total = sum(h.market_value for h in holdings)
    if total <= 0:
        return {h.instrument_id: 0.0 for h in holdings}
    return {h.instrument_id: h.market_value / total for h in holdings}


def _aggregate_by(
    weights_by_id: dict[str, float], group_of: dict[str, str]
) -> dict[str, float]:
    """Sum weights into groups; instruments without a group land in `_unknown`."""
    out: dict[str, float] = {}
    for instrument_id, weight in weights_by_id.items():
        group = group_of.get(instrument_id, "_unknown")
        out[group] = out.get(group, 0.0) + weight
    return out


def _liquidity_bucket(
    lock_in_expiry: date | None,
    as_of: date,
) -> LiquidityBucket:
    """Map an instrument's lock-in to one of the seven liquidity buckets.

    Open-ended instruments (lock_in_expiry=None) and any past-expiry holdings
    sit in the most-liquid bucket. The standard bucket boundaries (7d, 30d,
    90d, 365d, 3y, 7y) are per Section 8.9.2.
    """
    if lock_in_expiry is None:
        return LiquidityBucket.DAYS_0_7
    days = (lock_in_expiry - as_of).days
    if days <= 7:
        return LiquidityBucket.DAYS_0_7
    if days <= 30:
        return LiquidityBucket.DAYS_7_30
    if days <= 90:
        return LiquidityBucket.DAYS_30_90
    if days <= 365:
        return LiquidityBucket.DAYS_90_365
    if days <= 365 * 3:
        return LiquidityBucket.YEARS_1_3
    if days <= 365 * 7:
        return LiquidityBucket.YEARS_3_7
    return LiquidityBucket.BEYOND_7_YEARS


def _holding_period(holding: Holding, as_of: date) -> Literal["short", "long"]:
    """Section 8.9.2 — short-term vs long-term holding-period classification."""
    days_held = (as_of - holding.acquisition_date).days
    return "long" if days_held >= _DEFAULT_LONG_TERM_THRESHOLD_DAYS else "short"


# ===========================================================================
# Deployment
# ===========================================================================


def compute_deployment(context: PortfolioAnalyticsContext) -> DeploymentMetrics:
    """Section 8.9.2 deployment metrics."""
    total_aum = sum(h.market_value for h in context.holdings)

    cash_holdings = [h for h in context.holdings if h.vehicle_type == VehicleType.CASH]
    cash_total = sum(h.market_value for h in cash_holdings)
    cash_buffer = min(cash_total, context.cash_buffer_threshold_inr)
    undeployed = max(0.0, cash_total - cash_buffer)

    committed = sum(c.committed_inr for c in context.holding_commitments.values())
    called = sum(c.called_inr for c in context.holding_commitments.values())
    uncalled = max(0.0, committed - called)
    deployment_ratio = (called / committed) if committed > 0 else 0.0

    return DeploymentMetrics(
        total_aum_inr=total_aum,
        committed_capital_inr=committed,
        called_capital_inr=called,
        uncalled_capital_inr=uncalled,
        deployment_ratio=min(1.0, max(0.0, deployment_ratio)),
        cash_buffer_inr=cash_buffer,
        undeployed_investable_assets_inr=undeployed,
        flags=MetricFlags(),
    )


# ===========================================================================
# Concentration
# ===========================================================================


def compute_concentration(
    context: PortfolioAnalyticsContext,
    *,
    top_n_values: tuple[int, ...] = _DEFAULT_TOP_N,
) -> ConcentrationMetrics:
    """Section 8.9.2 multi-level concentration.

    Direct-holding HHI uses the holdings' market values directly. Sector and
    manager HHIs aggregate by instrument_sectors and amc_or_issuer respectively.
    Look-through stock HHI sums each underlying's `weight_in_portfolio` across
    parents and merges with any direct holding of the same instrument.
    """
    weights_by_id = _holding_weights(context.holdings)
    weight_values = list(weights_by_id.values())

    # Holding-level
    hhi_holding = _hhi(weight_values)

    # Manager-level (by AMC / issuer)
    manager_groups: dict[str, str] = {h.instrument_id: h.amc_or_issuer for h in context.holdings}
    hhi_manager = _hhi(list(_aggregate_by(weights_by_id, manager_groups).values()))

    # Sector-level (look-through-aware via instrument_sectors)
    hhi_sector: float | None = None
    if context.instrument_sectors:
        hhi_sector = _hhi(list(_aggregate_by(weights_by_id, context.instrument_sectors).values()))

    # Look-through stock-level: for each holding, expand into its underlyings
    # using `weight_in_portfolio` (already factored). Direct holdings count
    # themselves at their own weight when they have no look-through expansion.
    hhi_lookthrough: float | None = None
    look_through_pct_unavailable: float = 0.0
    look_through_weights: list[float] = []
    if context.holdings:
        # Sum weight_in_portfolio per underlying instrument across parents,
        # plus any direct holding of the same underlying.
        underlying_weights: dict[str, float] = {}
        unavailable_total = 0.0
        for h in context.holdings:
            entries = context.look_through.get(h.instrument_id)
            if entries:
                for e in entries:
                    underlying_weights[e.underlying_holding_id] = (
                        underlying_weights.get(e.underlying_holding_id, 0.0)
                        + e.weight_in_portfolio
                    )
            else:
                # No look-through entries — this holding is a leaf at this depth.
                # It contributes itself at its own weight.
                w = weights_by_id.get(h.instrument_id, 0.0)
                if h.look_through_unavailable:
                    unavailable_total += w
                underlying_weights[h.instrument_id] = (
                    underlying_weights.get(h.instrument_id, 0.0) + w
                )
        look_through_weights = list(underlying_weights.values())
        hhi_lookthrough = _hhi(look_through_weights)
        look_through_pct_unavailable = unavailable_total

    # Top-N concentrations
    sorted_holding_weights = sorted(weight_values, reverse=True)
    top_holding = [
        TopNConcentration(n=n, weight=_top_n_weight(sorted_holding_weights, n))
        for n in top_n_values
    ]

    sorted_lookthrough = sorted(look_through_weights, reverse=True)
    top_lookthrough = [
        TopNConcentration(n=n, weight=_top_n_weight(sorted_lookthrough, n))
        for n in top_n_values
    ]

    return ConcentrationMetrics(
        hhi_holding_level=hhi_holding,
        hhi_sector_level=hhi_sector,
        hhi_manager_level=hhi_manager,
        hhi_lookthrough_stock_level=hhi_lookthrough,
        top_n_holding_level=top_holding,
        top_n_lookthrough_level=top_lookthrough,
        look_through_depth=context.look_through_depth,
        flags=MetricFlags(look_through_unavailable_pct=look_through_pct_unavailable),
    )


# ===========================================================================
# Liquidity
# ===========================================================================


def compute_liquidity(context: PortfolioAnalyticsContext) -> LiquidityMetrics:
    """Section 8.9.2 liquidity profile."""
    weights_by_id = _holding_weights(context.holdings)

    bucket_weights: dict[LiquidityBucket, float] = {b: 0.0 for b in LiquidityBucket}
    for h in context.holdings:
        bucket = _liquidity_bucket(h.lock_in_expiry, context.as_of_date)
        bucket_weights[bucket] = (
            bucket_weights[bucket] + weights_by_id.get(h.instrument_id, 0.0)
        )

    # Compliance: most-liquid bucket weight ≥ liquidity_floor
    most_liquid = bucket_weights[LiquidityBucket.DAYS_0_7]
    compliance = most_liquid >= context.liquidity_floor - 1e-9

    return LiquidityMetrics(
        liquidity_buckets=bucket_weights,
        liquidity_floor_compliance=compliance,
        cashflow_schedule=list(context.forecast_cash_flows),
        flags=MetricFlags(),
    )


# ===========================================================================
# Tax
# ===========================================================================


def compute_tax(context: PortfolioAnalyticsContext) -> TaxMetrics:
    """Section 8.9.2 tax position.

    Holding-period split uses Indian equity rule (≥365 days = long-term) by
    default; non-equity asset classes inherit the same rule unless the caller
    overrides via `tax_holding_period_threshold_days`.

    `tax_basis_stale_days` flag fires when `tax_basis_as_of` is older than
    `as_of_date` (per Section 8.9.7).
    """
    threshold = context.tax_holding_period_threshold_days
    short_total = 0.0
    long_total = 0.0
    short_loss = 0.0
    long_loss = 0.0

    for h in context.holdings:
        days_held = (context.as_of_date - h.acquisition_date).days
        is_long = days_held >= threshold
        gain_loss = h.unrealised_gain_loss
        if is_long:
            long_total += gain_loss
            if gain_loss < 0:
                long_loss += -gain_loss
        else:
            short_total += gain_loss
            if gain_loss < 0:
                short_loss += -gain_loss

    total = short_total + long_total

    # Tax basis staleness flag
    tax_basis_stale_days: int | None = None
    if context.tax_basis_as_of is not None:
        delta_days = (context.as_of_date - context.tax_basis_as_of).days
        if delta_days > 0:
            tax_basis_stale_days = delta_days

    # Also set the flag if any holding has tax_basis_stale=True
    other_flags: list[str] = []
    if any(h.tax_basis_stale for h in context.holdings):
        other_flags.append("holding_level_tax_basis_stale")

    return TaxMetrics(
        unrealised_gain_loss_total_inr=total,
        unrealised_short_term_inr=short_total,
        unrealised_long_term_inr=long_total,
        harvestable_short_term_loss_inr=short_loss,
        harvestable_long_term_loss_inr=long_loss,
        flags=MetricFlags(tax_basis_stale_days=tax_basis_stale_days, other_flags=other_flags),
    )


# ===========================================================================
# Fees
# ===========================================================================


def compute_fees(context: PortfolioAnalyticsContext) -> FeeMetrics:
    """Section 8.9.2 cost/fee aggregation.

    Aggregate fee in basis points is the AUM-weighted average of management +
    performance + structure fees from each holding's L4 fee schedule. Holdings
    without a registered fee schedule mark `fee_data_incomplete` true.
    """
    holdings_by_id = {h.instrument_id: h for h in context.holdings}
    weights_by_id = _holding_weights(context.holdings)

    weighted_bps_sum = 0.0
    breakdown_by_vehicle: dict[str, dict[str, float]] = {}
    fee_data_incomplete = False

    for instrument_id, weight in weights_by_id.items():
        h = holdings_by_id[instrument_id]
        sched = context.fee_schedules.get(instrument_id)
        if sched is None:
            fee_data_incomplete = True
            continue
        bps = sched.management_fee_bps + sched.performance_fee_bps + sched.structure_costs_bps
        weighted_bps_sum += weight * bps

        v_key = h.vehicle_type.value
        v_entry = breakdown_by_vehicle.setdefault(v_key, {"bps_sum": 0.0, "contribution_inr": 0.0})
        v_entry["bps_sum"] += weight * bps
        v_entry["contribution_inr"] += h.market_value * (bps / 10_000.0)

    aggregate_bps = int(round(weighted_bps_sum))

    breakdown: list[FeeBreakdown] = []
    for v, d in breakdown_by_vehicle.items():
        vehicle_weight = weights_by_id_for_vehicle(weights_by_id, holdings_by_id, v)
        avg_bps = int(round(d["bps_sum"] / max(vehicle_weight, 1e-9)))
        breakdown.append(
            FeeBreakdown(
                vehicle_type=v,
                fee_bps=avg_bps,
                contribution_inr=d["contribution_inr"],
            )
        )

    return FeeMetrics(
        aggregate_fee_bps=aggregate_bps,
        fee_breakdown=breakdown,
        fee_drag_annualised_bps=aggregate_bps,
        fee_efficiency_ratio=None,  # caller can compute given gross_return
        flags=MetricFlags(fee_data_incomplete=fee_data_incomplete),
    )


def weights_by_id_for_vehicle(
    weights_by_id: dict[str, float],
    holdings_by_id: dict[str, Holding],
    vehicle_value: str,
) -> float:
    """Sum of weights for holdings of a given vehicle type. Helper used by fee breakdown."""
    return sum(
        w
        for iid, w in weights_by_id.items()
        if holdings_by_id[iid].vehicle_type.value == vehicle_value
    )


# ===========================================================================
# Vintage
# ===========================================================================


_AIF_VEHICLES = {VehicleType.AIF_CAT_1, VehicleType.AIF_CAT_2, VehicleType.AIF_CAT_3}


def compute_vintage(context: PortfolioAnalyticsContext) -> VintageMetrics:
    """Section 8.9.2 AIF vintage profile + PMS inception dates."""
    aif_holdings = [h for h in context.holdings if h.vehicle_type in _AIF_VEHICLES]
    pms_holdings = [h for h in context.holdings if h.vehicle_type == VehicleType.PMS]

    weights = _holding_weights(context.holdings)
    aif_total_weight = sum(weights.get(h.instrument_id, 0.0) for h in aif_holdings)

    aif_entries: list[AifVintageEntry] = []
    vintage_distribution: dict[int, float] = {}

    for h in aif_holdings:
        vintage_year = context.holding_vintage_year.get(h.instrument_id, h.acquisition_date.year)
        in_commit = context.holding_in_commitment_period.get(h.instrument_id, True)
        in_dist = context.holding_in_distribution_period.get(h.instrument_id, False)
        aif_entries.append(
            AifVintageEntry(
                holding_id=h.instrument_id,
                instrument_name=h.instrument_name,
                vintage_year=vintage_year,
                in_commitment_period=in_commit,
                in_distribution_period=in_dist,
            )
        )
        if aif_total_weight > 0:
            w = weights.get(h.instrument_id, 0.0) / aif_total_weight
            vintage_distribution[vintage_year] = vintage_distribution.get(vintage_year, 0.0) + w

    pms_inception = {h.instrument_id: h.acquisition_date for h in pms_holdings}

    return VintageMetrics(
        aif_vintages=aif_entries,
        pms_inception_dates=pms_inception,
        vintage_distribution=vintage_distribution,
        flags=MetricFlags(),
    )


# ===========================================================================
# Returns (XIRR + structure)
# ===========================================================================


def compute_xirr(
    cash_flows: list[tuple[date, float]],
    *,
    guess: float = 0.1,
    max_iterations: int = 100,
    tolerance: float = 1e-7,
) -> float | None:
    """Newton-Raphson XIRR per Section 8.9.2 returns_metrics.

    `cash_flows` is a list of `(date, signed_amount)` pairs. Convention:
    outflows from the client (purchases) are negative, inflows (distributions,
    terminal liquidation) are positive. Must contain at least one positive and
    one negative flow; otherwise returns None.

    Returns the annualised IRR as a fraction (e.g. 0.124 for 12.4%) or None
    on non-convergence.
    """
    if len(cash_flows) < 2:
        return None
    has_positive = any(amt > 0 for _, amt in cash_flows)
    has_negative = any(amt < 0 for _, amt in cash_flows)
    if not (has_positive and has_negative):
        return None

    base_date = min(d for d, _ in cash_flows)

    def npv(rate: float) -> float:
        return sum(
            amt / pow(1.0 + rate, (d - base_date).days / 365.0)
            for d, amt in cash_flows
        )

    def dnpv(rate: float) -> float:
        # First derivative w.r.t. rate.
        total = 0.0
        for d, amt in cash_flows:
            years = (d - base_date).days / 365.0
            total += -amt * years / pow(1.0 + rate, years + 1.0)
        return total

    rate = guess
    for _ in range(max_iterations):
        try:
            f = npv(rate)
            df = dnpv(rate)
        except (ZeroDivisionError, OverflowError):
            return None
        if abs(df) < 1e-15:
            return None
        new_rate = rate - f / df
        if math.isnan(new_rate) or math.isinf(new_rate):
            return None
        if new_rate <= -1.0:  # rate < -100% is non-physical
            new_rate = -0.999
        if abs(new_rate - rate) < tolerance:
            return new_rate
        rate = new_rate
    return None


def compute_returns(
    context: PortfolioAnalyticsContext,
    *,
    period_overrides: list[tuple[date, date]] | None = None,
) -> ReturnsMetrics:
    """Section 8.9.2 returns metrics.

    For Pass 5 we compute XIRR over the full cash flow history when present,
    plus per-period XIRR for each (start, end) override window. TWR requires
    per-period valuations which we don't currently take as input — Pass 6+
    extends this once the historical NAV substrate is in place.

    The result's PeriodReturn entries always populate `xirr` when computable;
    `gross_return`, `net_of_costs_return`, etc. are placeholders for now.
    """
    period_returns: list = []
    if context.cash_flow_history:
        # Since-inception XIRR
        rate = compute_xirr(context.cash_flow_history)
        if rate is not None:
            min_d = min(d for d, _ in context.cash_flow_history)
            period_returns.append(
                _make_period_return("since_inception", min_d, context.as_of_date, xirr=rate)
            )

    for start, end in period_overrides or []:
        flows = [(d, amt) for d, amt in context.cash_flow_history if start <= d <= end]
        rate = compute_xirr(flows) if flows else None
        if rate is not None:
            period_returns.append(
                _make_period_return(f"{start}_{end}", start, end, xirr=rate)
            )

    return ReturnsMetrics(period_returns=period_returns, flags=MetricFlags())


def _make_period_return(
    label: str,
    start: date,
    end: date,
    *,
    xirr: float | None = None,
):
    """Build a PeriodReturn with explicit nullable returns."""
    from artha.canonical.portfolio_analytics import PeriodReturn

    return PeriodReturn(
        period_label=label,
        start_date=start,
        end_date=end,
        xirr=xirr,
    )


# ===========================================================================
# Profitability (skeleton — needs upstream fundamental data)
# ===========================================================================


def compute_profitability(context: PortfolioAnalyticsContext) -> ProfitabilityMetrics:
    """Section 8.9.2 profitability metrics.

    Pass 5 ships the schema and the function signature; the actual computation
    requires upstream fundamental data (per-company ROCE, PAT margin, earnings
    growth) which Pass 6+ wires through E2's industry database. For now this
    returns the metric with all fields None and a flag indicating the gap.
    """
    return ProfitabilityMetrics(
        flags=MetricFlags(other_flags=["fundamental_data_unavailable"]),
    )
