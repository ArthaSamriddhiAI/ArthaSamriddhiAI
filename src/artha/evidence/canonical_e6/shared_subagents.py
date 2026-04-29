"""§11.7.2 — E6 shared sub-agents (deterministic helpers).

  * `compute_normalised_returns` — E6.FeeNormalisation
  * `compute_cascade_assessment` — E6.CascadeEngine
  * `compute_liquidity_manager_output` — E6.LiquidityManager

Each helper is pure and deterministic. They run alongside product-specific
sub-agents and are aggregated by the orchestrator into the final verdict.
"""

from __future__ import annotations

from artha.canonical.evidence_verdict import (
    CascadeAssessment,
    LiquidityManagerOutput,
    NormalisedReturns,
)
from artha.canonical.holding import CascadeEvent, CascadeEventType
from artha.canonical.l4_manifest import FeeSchedule
from artha.portfolio_analysis.canonical_metrics import HoldingCommitment

# ===========================================================================
# E6.FeeNormalisation
# ===========================================================================


def compute_normalised_returns(
    *,
    gross_return: float,
    fee_schedule: FeeSchedule | None = None,
    tax_rate: float = 0.0,
    counterfactual_model_portfolio_return: float | None = None,
) -> NormalisedReturns:
    """§11.7.2 / §15.7.6 — derive net-of-costs and net-of-all returns.

    Formulas:
      * `net_of_costs_return` = gross − (mgmt + perf + structure) bps / 10_000
      * `net_of_costs_and_taxes_return` = net_of_costs × (1 − tax_rate)
      * `counterfactual_delta` = proposed_net_of_all − model_portfolio_return

    The `counterfactual_model_portfolio_return` is what the model portfolio for
    the client's bucket would return at the same horizon (caller computes this
    from the model's `expected_return_profile`). If absent, the delta is None.
    """
    if fee_schedule is None:
        return NormalisedReturns(
            gross_return=gross_return,
            counterfactual_model_portfolio_return=counterfactual_model_portfolio_return,
        )

    fee_drag = (
        fee_schedule.management_fee_bps
        + fee_schedule.performance_fee_bps
        + fee_schedule.structure_costs_bps
    ) / 10_000.0

    net_of_costs = gross_return - fee_drag
    net_of_all = net_of_costs * (1.0 - tax_rate)

    delta: float | None = None
    if counterfactual_model_portfolio_return is not None:
        delta = net_of_all - counterfactual_model_portfolio_return

    return NormalisedReturns(
        gross_return=gross_return,
        net_of_costs_return=net_of_costs,
        net_of_costs_and_taxes_return=net_of_all,
        counterfactual_model_portfolio_return=counterfactual_model_portfolio_return,
        counterfactual_delta=delta,
    )


# ===========================================================================
# E6.CascadeEngine
# ===========================================================================


def compute_cascade_assessment(
    cash_flow_schedule: list[CascadeEvent] | None = None,
    *,
    deployment_modelling: dict[str, float] | None = None,
) -> CascadeAssessment:
    """§11.7.2 / §15.7.6 — model capital calls + distributions for the proposal.

    `cash_flow_schedule` is the deterministic projection (typically from
    M0.PortfolioState.get_cascade or AIF/PMS commitment data). The engine
    aggregates the schedule into expected-distribution and expected-call totals
    so consumers can size liquidity buffers.
    """
    schedule = list(cash_flow_schedule or [])

    expected_distributions = 0.0
    expected_calls = 0.0
    for event in schedule:
        if event.event_type in (
            CascadeEventType.DISTRIBUTION,
            CascadeEventType.MATURITY,
            CascadeEventType.REDEMPTION,
        ):
            expected_distributions += event.expected_amount_inr
        elif event.event_type == CascadeEventType.CAPITAL_CALL:
            expected_calls += event.expected_amount_inr

    return CascadeAssessment(
        cash_flow_schedule=schedule,
        deployment_modelling=deployment_modelling or {},
        expected_distribution_inr=expected_distributions,
        expected_capital_calls_inr=expected_calls,
    )


# ===========================================================================
# E6.LiquidityManager
# ===========================================================================


def compute_liquidity_manager_output(
    *,
    holding_commitments: dict[str, HoldingCommitment] | None = None,
    most_liquid_bucket_share: float = 0.0,
    mandate_liquidity_floor: float = 0.0,
    proposed_uncalled_inr: float = 0.0,
) -> LiquidityManagerOutput:
    """§11.7.2 / §15.7.6 — track unfunded commitments + check liquidity floor.

    Args:
      * `holding_commitments` — existing commitment-period AIFs etc.; we sum
        their uncalled portions.
      * `most_liquid_bucket_share` — fraction of portfolio in the 0-7-day
        liquidity bucket (from `LiquidityMetrics.liquidity_buckets`).
      * `mandate_liquidity_floor` — required min from the client's mandate.
      * `proposed_uncalled_inr` — uncalled portion the proposed action would
        add (for an AIF Cat II proposal, the commitment minus expected called).

    Returns:
      * `cumulative_unfunded_commitment_inr` — total uncalled across existing +
        proposed.
      * `liquidity_floor_check_result` — True iff the most-liquid bucket
        meets-or-exceeds the mandate floor (independent of unfunded; the
        unfunded amount surfaces separately for the synthesis layer to weigh).
    """
    existing_uncalled = sum(
        max(0.0, c.committed_inr - c.called_inr)
        for c in (holding_commitments or {}).values()
    )
    cumulative_unfunded = existing_uncalled + max(0.0, proposed_uncalled_inr)

    floor_compliance = most_liquid_bucket_share >= mandate_liquidity_floor - 1e-9

    return LiquidityManagerOutput(
        cumulative_unfunded_commitment_inr=cumulative_unfunded,
        liquidity_floor_check_result=floor_compliance,
        most_liquid_bucket_share=most_liquid_bucket_share,
    )
