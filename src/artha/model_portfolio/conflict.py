"""Mandate-vs-model conflict detection (Section 5.10).

A conflict exists when the bucket's model portfolio cannot be applied to a
specific client without violating their mandate. The three resolution paths
(Section 5.10) are surfaced alongside each conflict:

  1. amend_mandate    — update the mandate to fit the model
  2. clip_model       — derive a per-client clipped model that fits the mandate
  3. out_of_bucket    — flag the client and run a single-client construction case

This module produces the structured conflict signal. It does NOT decide which
path to take — that's the advisor's call (Pass 4 + advisor surface).
"""

from __future__ import annotations

from artha.canonical.holding import ConflictReport, ConflictType
from artha.canonical.mandate import MandateObject
from artha.canonical.model_portfolio import ModelPortfolioObject

# Section 5.10 — every conflict surface offers the same three paths.
RESOLUTION_PATHS: tuple[str, ...] = ("amend_mandate", "clip_model", "out_of_bucket")


def _l1_asset_class_conflict(
    mandate: MandateObject,
    model: ModelPortfolioObject,
) -> list[ConflictReport]:
    """For each model L1 asset class, check the model's tolerance envelope fits
    inside the mandate's [min_pct, max_pct] range.

    The envelope edges are computed with floor=0 and ceiling=1 (allocations
    can't go negative or exceed 100%); any portion of the envelope outside
    the mandate range is a conflict.
    """
    conflicts: list[ConflictReport] = []
    for asset_class, target_band in model.l1_targets.items():
        if asset_class not in mandate.asset_class_limits:
            # Mandate doesn't constrain this class — model is free.
            continue
        limits = mandate.asset_class_limits[asset_class]
        lower_edge = max(0.0, target_band.target - target_band.tolerance_band)
        upper_edge = min(1.0, target_band.target + target_band.tolerance_band)

        # Conflict if any portion of the envelope falls outside the mandate range.
        # Use small epsilon to avoid spurious conflicts from float precision.
        eps = 1e-9
        if lower_edge < limits.min_pct - eps or upper_edge > limits.max_pct + eps:
            conflicts.append(
                ConflictReport(
                    conflict_type=ConflictType.MANDATE_VS_MODEL,
                    dimension=f"asset_class.{asset_class.value}",
                    mandate_value={
                        "min_pct": limits.min_pct,
                        "target_pct": limits.target_pct,
                        "max_pct": limits.max_pct,
                    },
                    model_value={
                        "target": target_band.target,
                        "tolerance_band": target_band.tolerance_band,
                    },
                    resolution_paths=list(RESOLUTION_PATHS),
                )
            )
    return conflicts


def _l2_vehicle_conflict(
    mandate: MandateObject,
    model: ModelPortfolioObject,
) -> list[ConflictReport]:
    """For each L2 vehicle target, check it doesn't violate mandate vehicle limits.

    Two failure modes:
      * Mandate disallows the vehicle (`allowed=False`) but model has nonzero target.
      * Mandate allows the vehicle with a `max_pct` cap that the model exceeds.
    """
    conflicts: list[ConflictReport] = []
    for asset_class, vehicle_targets in model.l2_targets.items():
        for vehicle, target_band in vehicle_targets.items():
            if vehicle not in mandate.vehicle_limits:
                continue
            v_limit = mandate.vehicle_limits[vehicle]
            dimension = f"vehicle.{asset_class.value}.{vehicle.value}"

            if not v_limit.allowed and target_band.target > 0:
                conflicts.append(
                    ConflictReport(
                        conflict_type=ConflictType.MANDATE_VS_MODEL,
                        dimension=dimension,
                        mandate_value={"allowed": False},
                        model_value={"target": target_band.target},
                        resolution_paths=list(RESOLUTION_PATHS),
                    )
                )
                continue

            # Mandate allows the vehicle; check max_pct cap if specified.
            if (
                v_limit.allowed
                and v_limit.max_pct is not None
                and target_band.target > v_limit.max_pct + 1e-9
            ):
                conflicts.append(
                    ConflictReport(
                        conflict_type=ConflictType.MANDATE_VS_MODEL,
                        dimension=dimension,
                        mandate_value={
                            "allowed": True,
                            "max_pct": v_limit.max_pct,
                        },
                        model_value={"target": target_band.target},
                        resolution_paths=list(RESOLUTION_PATHS),
                    )
                )
    return conflicts


def detect_mandate_vs_model_conflicts(
    mandate: MandateObject,
    model: ModelPortfolioObject,
) -> list[ConflictReport]:
    """Section 5.10 — detect every dimension where the bucket's model conflicts with
    the client's mandate.

    Empty list ⇒ the client can be safely bucketed against this model. A non-empty
    list ⇒ surface to the advisor with the three resolution paths (Section 14.2.1).

    Deterministic: same inputs produce the same outputs in the same order.
    """
    return [
        *_l1_asset_class_conflict(mandate, model),
        *_l2_vehicle_conflict(mandate, model),
    ]


def is_irreconcilable(conflicts: list[ConflictReport]) -> bool:
    """Heuristic for Section 5.10 path 3 — true if any conflict has zero overlap
    between the mandate range and the model envelope.

    A path-2 clip is feasible only when there's at least *some* overlap between
    the mandate's allowed range and the model's tolerance envelope. If a conflict
    surface has no overlap (e.g. mandate caps equity at 30% but the model's lowest
    envelope edge is 65%), there's no clip that produces a coherent bucketed model
    and the client should be flagged out-of-bucket instead.

    For Pass 3 this is a heuristic on L1 conflicts only — vehicle conflicts are
    always reconcilable by clipping the offending vehicle to 0.
    """
    for conflict in conflicts:
        if not conflict.dimension.startswith("asset_class."):
            continue
        m = conflict.mandate_value or {}
        v = conflict.model_value or {}
        try:
            mandate_min = float(m.get("min_pct", 0.0))
            mandate_max = float(m.get("max_pct", 1.0))
            model_target = float(v["target"])
            model_band = float(v["tolerance_band"])
        except (KeyError, TypeError, ValueError):
            continue
        envelope_lower = max(0.0, model_target - model_band)
        envelope_upper = min(1.0, model_target + model_band)
        # Zero overlap ⇒ irreconcilable
        if envelope_upper < mandate_min or envelope_lower > mandate_max:
            return True
    return False
