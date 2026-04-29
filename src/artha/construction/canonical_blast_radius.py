"""§5.13 Test 5 — deterministic blast-radius + version-diff computation.

`compute_version_diff` walks two `ModelPortfolioObject` versions and emits
the cells that changed (target / band) at each level.

`compute_blast_radius` reads client portfolio slices and counts:
  * clients in the bucket
  * clients currently within prior bands who'd breach proposed bands
  * total AUM moved (sum of |actual - proposed_target| × AUM)
  * estimated transaction + tax cost (deterministic stubs in Pass 16;
    production wires this through the firm's cost model)
  * day-1 N0 alert count (clients_in_tolerance_who_breach by default)
"""

from __future__ import annotations

from artha.canonical.construction import (
    BlastRadius,
    BucketVersionDiff,
    CellChange,
    ClientPortfolioSlice,
)
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.common.types import (
    AssetClass,
    Bucket,
    PercentageField,
)


def compute_version_diff(
    *,
    bucket: Bucket,
    prior_model: ModelPortfolioObject | None,
    proposed_model: ModelPortfolioObject,
) -> BucketVersionDiff:
    """Walk both models and surface every cell whose target or band changed."""
    cell_changes: list[CellChange] = []

    # ---- L1 ----
    prior_l1 = prior_model.l1_targets if prior_model else {}
    seen_l1: set[AssetClass] = set()
    for ac, proposed_t in proposed_model.l1_targets.items():
        seen_l1.add(ac)
        prior_t = prior_l1.get(ac)
        if prior_t is None or (
            prior_t.target != proposed_t.target
            or prior_t.tolerance_band != proposed_t.tolerance_band
        ):
            cell_changes.append(
                CellChange(
                    level="l1",
                    cell_key=ac.value,
                    prior_target=prior_t.target if prior_t else None,
                    proposed_target=proposed_t.target,
                    prior_band=prior_t.tolerance_band if prior_t else None,
                    proposed_band=proposed_t.tolerance_band,
                    delta=(
                        proposed_t.target - prior_t.target
                        if prior_t is not None
                        else None
                    ),
                )
            )
    # Removed L1 cells
    for ac, prior_t in prior_l1.items():
        if ac in seen_l1:
            continue
        cell_changes.append(
            CellChange(
                level="l1",
                cell_key=ac.value,
                prior_target=prior_t.target,
                proposed_target=None,
                prior_band=prior_t.tolerance_band,
                proposed_band=None,
                delta=-prior_t.target,
            )
        )

    # ---- L2 ----
    prior_l2 = prior_model.l2_targets if prior_model else {}
    for ac, vehicle_map in proposed_model.l2_targets.items():
        prior_vehicle_map = prior_l2.get(ac, {})
        for vehicle, proposed_t in vehicle_map.items():
            prior_t = prior_vehicle_map.get(vehicle)
            if prior_t is None or (
                prior_t.target != proposed_t.target
                or prior_t.tolerance_band != proposed_t.tolerance_band
            ):
                cell_changes.append(
                    CellChange(
                        level="l2",
                        cell_key=f"{ac.value}.{vehicle.value}",
                        prior_target=prior_t.target if prior_t else None,
                        proposed_target=proposed_t.target,
                        prior_band=prior_t.tolerance_band if prior_t else None,
                        proposed_band=proposed_t.tolerance_band,
                        delta=(
                            proposed_t.target - prior_t.target
                            if prior_t is not None
                            else None
                        ),
                    )
                )

    # ---- L3 ---- (composite key already serialised as "asset_class.vehicle")
    prior_l3 = prior_model.l3_targets if prior_model else {}
    for cell_key, sub_map in proposed_model.l3_targets.items():
        prior_sub_map = prior_l3.get(cell_key, {})
        for sub_class, proposed_t in sub_map.items():
            prior_t = prior_sub_map.get(sub_class)
            if prior_t is None or (
                prior_t.target != proposed_t.target
                or prior_t.tolerance_band != proposed_t.tolerance_band
            ):
                cell_changes.append(
                    CellChange(
                        level="l3",
                        cell_key=f"{cell_key}.{sub_class}",
                        prior_target=prior_t.target if prior_t else None,
                        proposed_target=proposed_t.target,
                        prior_band=prior_t.tolerance_band if prior_t else None,
                        proposed_band=proposed_t.tolerance_band,
                        delta=(
                            proposed_t.target - prior_t.target
                            if prior_t is not None
                            else None
                        ),
                    )
                )

    return BucketVersionDiff(
        bucket=bucket,
        prior_model_id=prior_model.model_id if prior_model else None,
        prior_version=prior_model.version if prior_model else None,
        proposed_model_id=proposed_model.model_id,
        proposed_version=proposed_model.version,
        cell_changes=cell_changes,
        cell_changes_count=len(cell_changes),
    )


def compute_blast_radius(
    *,
    bucket: Bucket,
    prior_model: ModelPortfolioObject | None,
    proposed_model: ModelPortfolioObject,
    client_slices: list[ClientPortfolioSlice],
    txn_cost_pct: float = 0.005,
    tax_cost_pct: float = 0.10,
) -> BlastRadius:
    """Deterministic blast-radius computation per §5.13 Test 5."""
    in_bucket = [s for s in client_slices if s.bucket is bucket]
    clients_in_bucket = len(in_bucket)

    breach_count = 0
    aum_moved = 0.0
    for slice_ in in_bucket:
        currently_in_tolerance = _within_tolerance(
            l1_weights=slice_.current_l1_weights,
            model=prior_model,
        )
        proposed_breach = not _within_tolerance(
            l1_weights=slice_.current_l1_weights,
            model=proposed_model,
        )
        if currently_in_tolerance and proposed_breach:
            breach_count += 1

        # AUM moved: aggregate signed L1 delta × AUM
        moved = 0.0
        for ac, proposed_t in proposed_model.l1_targets.items():
            actual = float(slice_.current_l1_weights.get(ac.value, 0.0))
            delta = abs(actual - proposed_t.target)
            moved += delta * float(slice_.aum_inr)
        aum_moved += moved

    # Symmetric trade cost stub: txn_cost on AUM moved, tax on the gain leg.
    txn_cost = aum_moved * txn_cost_pct
    tax_cost = (aum_moved * tax_cost_pct) / 2.0  # only half the moved AUM is a gain

    blast_share = (
        breach_count / clients_in_bucket if clients_in_bucket > 0 else 0.0
    )

    return BlastRadius(
        bucket=bucket,
        clients_in_bucket_count=clients_in_bucket,
        clients_in_tolerance_who_breach=breach_count,
        total_aum_moved_inr=aum_moved,
        estimated_txn_cost_inr=txn_cost,
        estimated_tax_cost_inr=tax_cost,
        day_one_n0_alert_count=breach_count,
        blast_radius_share=min(blast_share, 1.0),
    )


def should_use_shadow_mode(
    *,
    blast_radius: BlastRadius,
    threshold: PercentageField = 0.25,
) -> bool:
    """§5.8.3.3 — shadow mode triggers when blast share exceeds threshold."""
    return blast_radius.blast_radius_share > threshold + 1e-9


# --------------------- Helpers ----------------------------------


def _within_tolerance(
    *,
    l1_weights: dict[str, float],
    model: ModelPortfolioObject | None,
) -> bool:
    """Inside ALL L1 cells' tolerance bands?"""
    if model is None:
        return True  # no prior — vacuously in tolerance
    for ac, target_band in model.l1_targets.items():
        actual = float(l1_weights.get(ac.value, 0.0))
        if abs(actual - target_band.target) > target_band.tolerance_band + 1e-9:
            return False
    return True


__all__ = [
    "compute_blast_radius",
    "compute_version_diff",
    "should_use_shadow_mode",
]
