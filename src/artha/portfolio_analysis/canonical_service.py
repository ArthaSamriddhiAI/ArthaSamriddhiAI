"""Section 8.9.6 — query service with snapshot-keyed caching.

PortfolioAnalyticsService is the entry point for M0.PortfolioAnalytics queries.
Per Section 8.9.6, results are cached at `(client_id, as_of_date, metric_category)`
for the duration of the case; a new context (different inputs) produces a new
snapshot id and a fresh computation.

The service is in-memory and case-scoped. Pass 6+ wires it to T1 for replay
and to a per-case lifetime manager. For now, callers construct one service
per case and let it be garbage-collected when the case completes.

Determinism: same context → same snapshot_id → same cached result.
"""

from __future__ import annotations

from artha.canonical.portfolio_analytics import (
    AnalyticsQueryInput,
    AnalyticsQueryResult,
    DeploymentMetrics,
    MetricCategory,
    ReturnsMetrics,
)
from artha.common.hashing import payload_hash
from artha.common.types import InputsUsedManifest
from artha.portfolio_analysis.canonical_metrics import (
    PortfolioAnalyticsContext,
    compute_concentration,
    compute_deployment,
    compute_fees,
    compute_liquidity,
    compute_profitability,
    compute_returns,
    compute_tax,
    compute_vintage,
)


def _compute_snapshot_id(context: PortfolioAnalyticsContext) -> str:
    """Hash the canonical JSON form of the context. Same inputs → same id."""
    return payload_hash(context.model_dump(mode="json"))


def _build_inputs_used_manifest(
    context: PortfolioAnalyticsContext, snapshot_id: str
) -> InputsUsedManifest:
    """Section 15.2 — capture the input identifiers and shapes for replay."""
    return InputsUsedManifest(
        inputs={
            "snapshot_id": {"hash": snapshot_id},
            "holdings": {"count": str(len(context.holdings))},
            "look_through": {"count": str(len(context.look_through))},
            "fee_schedules": {"count": str(len(context.fee_schedules))},
            "cash_flow_history": {"count": str(len(context.cash_flow_history))},
            "as_of_date": {"value": context.as_of_date.isoformat()},
        }
    )


class PortfolioAnalyticsService:
    """In-memory snapshot-keyed cache for M0.PortfolioAnalytics queries.

    Cache key: `(snapshot_id, metric_category)`. Two queries with the same
    context produce the same snapshot_id and reuse cached metric outputs.
    A query with a modified context (any input change) produces a fresh
    snapshot_id and recomputes from scratch.

    `cache_hit` on the result is True only when EVERY requested category was
    served from cache (i.e. this is at least the second identical query for
    this set of categories). The first query for a context is always False.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, MetricCategory], object] = {}

    def query(
        self,
        query: AnalyticsQueryInput,
        context: PortfolioAnalyticsContext,
    ) -> AnalyticsQueryResult:
        snapshot_id = _compute_snapshot_id(context)
        result_kwargs: dict = {
            "client_id": query.client_id,
            "as_of_date": query.as_of_date,
            "snapshot_id": snapshot_id,
            "inputs_used_manifest": _build_inputs_used_manifest(context, snapshot_id),
        }

        all_hit = True
        for category in query.metric_categories:
            cache_key = (snapshot_id, category)
            cached = self._cache.get(cache_key)
            if cached is not None:
                metric = cached
            else:
                metric = self._compute(category, context, query)
                self._cache[cache_key] = metric
                all_hit = False
            result_kwargs[category.value] = metric

        result = AnalyticsQueryResult(**result_kwargs)
        # cache_hit semantics: True only if every requested category was already cached.
        # First-time query is always False even when categories list is empty.
        return result.model_copy(update={"cache_hit": all_hit and bool(query.metric_categories)})

    def _compute(
        self,
        category: MetricCategory,
        context: PortfolioAnalyticsContext,
        query: AnalyticsQueryInput,
    ):
        match category:
            case MetricCategory.DEPLOYMENT:
                return compute_deployment(context)
            case MetricCategory.RETURNS:
                # Standard period defaults are 1Y/3Y/5Y/since-inception per Section 8.9.2;
                # for Pass 5 we compute since-inception plus any explicit overrides.
                if query.period_overrides:
                    return compute_returns(context, period_overrides=query.period_overrides)
                return compute_returns(context)
            case MetricCategory.PROFITABILITY:
                return compute_profitability(context)
            case MetricCategory.FEES:
                return compute_fees(context)
            case MetricCategory.CONCENTRATION:
                return compute_concentration(context)
            case MetricCategory.LIQUIDITY:
                return compute_liquidity(context)
            case MetricCategory.TAX:
                return compute_tax(context)
            case MetricCategory.VINTAGE:
                return compute_vintage(context)

    def clear(self) -> None:
        """Drop all cached entries (e.g. at case end)."""
        self._cache.clear()


__all__ = [
    "PortfolioAnalyticsService",
    # Re-export so callers don't reach into compute module
    "DeploymentMetrics",
    "ReturnsMetrics",
]
