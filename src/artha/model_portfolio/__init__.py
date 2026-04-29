"""Model Portfolio — the canonical 9-bucket strategic-allocation backbone.

Per Section 5 of the consolidation spec, the model portfolio is the most
consequential single object in the system. Every drift detection, counterfactual,
Mode-1 rebalance, and Mode-2 alignment check derives from it.

This package owns:

  * `buckets`   — the 9-bucket grid (3 risk profiles x 3 time horizons) and the
                  deterministic mapping from investor active fields to bucket id.
  * `tolerance` — drift detection at L1/L2/L3 (Section 5.5).
  * `conflict`  — mandate-vs-model conflict detection (Section 5.10).
  * `service`   — AUM-eligibility filter and version pin helper (Section 3.7, 5.3.2).

The Pydantic schemas for `model_portfolio_object`, `fund_universe_l4_entry`, and
`l4_manifest_version` live in `artha.canonical.model_portfolio` and
`artha.canonical.l4_manifest` (per Section 15.5).
"""

from artha.model_portfolio.buckets import (
    BUCKET_RISK_PROFILE,
    BUCKET_TIME_HORIZON,
    bucket_components,
    derive_bucket,
)
from artha.model_portfolio.conflict import (
    RESOLUTION_PATHS,
    detect_mandate_vs_model_conflicts,
    is_irreconcilable,
)
from artha.model_portfolio.service import (
    DEFAULT_VEHICLE_MIN_TIER,
    ModelPortfolioRegistry,
    apply_aum_eligibility_filter,
    model_portfolio_version_pin,
    vehicle_accessible,
)
from artha.model_portfolio.tolerance import (
    DriftDimension,
    DriftEvent,
    DriftSeverity,
    PortfolioAllocationSnapshot,
    detect_drift_events,
    detect_l1_drift,
    detect_l2_drift,
    detect_l3_drift,
    has_l1_breach,
)

__all__ = [
    # buckets
    "BUCKET_RISK_PROFILE",
    "BUCKET_TIME_HORIZON",
    "bucket_components",
    "derive_bucket",
    # tolerance
    "DriftDimension",
    "DriftEvent",
    "DriftSeverity",
    "PortfolioAllocationSnapshot",
    "detect_drift_events",
    "detect_l1_drift",
    "detect_l2_drift",
    "detect_l3_drift",
    "has_l1_breach",
    # conflict
    "RESOLUTION_PATHS",
    "detect_mandate_vs_model_conflicts",
    "is_irreconcilable",
    # service
    "DEFAULT_VEHICLE_MIN_TIER",
    "ModelPortfolioRegistry",
    "apply_aum_eligibility_filter",
    "model_portfolio_version_pin",
    "vehicle_accessible",
]
