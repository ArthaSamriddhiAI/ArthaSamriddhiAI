"""Model portfolio service operations: AUM-eligibility filter, version pin, registry.

The AUM-eligibility filter (Section 5.3.2) suppresses vehicles the investor's
wealth tier doesn't grant access to and proportionally redistributes the
suppressed weight to the remaining accessible vehicles within the same asset
class. Per Section 5.3.2 the redistributed targets travel with the investor's
case in T1.

Default vehicle-tier requirements are Indian-market sensible (PMS @ ₹50L,
AIF Cat I/II/III @ ₹1Cr, etc.) but can be overridden per firm by passing a
custom `vehicle_min_tier` mapping.

`ModelPortfolioRegistry` is an in-memory catalog of model portfolio versions
keyed by (firm_id, bucket). Pass 6+ replaces it with a DB-backed implementation;
for now it lets Pass 4's investor service look up "the model in force at
as_of" without requiring a database round trip.
"""

from __future__ import annotations

from datetime import UTC, datetime

from artha.canonical.model_portfolio import ModelPortfolioObject, TargetWithTolerance
from artha.common.types import Bucket, VehicleType, WealthTier

# Wealth tiers in increasing order; rank is index. Per Section 6.2.
_TIER_ORDER: tuple[WealthTier, ...] = (
    WealthTier.UP_TO_25K_SIP,
    WealthTier.SIP_25K_TO_2CR_AUM,
    WealthTier.AUM_2CR_TO_5CR,
    WealthTier.AUM_5CR_TO_10CR,
    WealthTier.AUM_10CR_TO_25CR,
    WealthTier.AUM_25CR_TO_100CR,
    WealthTier.AUM_BEYOND_100CR,
)
_TIER_RANK: dict[WealthTier, int] = {tier: idx for idx, tier in enumerate(_TIER_ORDER)}


# Default minimum wealth tier required to access each vehicle type (Section 5.3.2).
# Vehicles not in this map have no tier requirement (accessible at all tiers).
DEFAULT_VEHICLE_MIN_TIER: dict[VehicleType, WealthTier] = {
    # PMS minimums are ₹50 L → SIP_25K_TO_2CR_AUM tier (encompasses ₹50L-₹2Cr range)
    VehicleType.PMS: WealthTier.SIP_25K_TO_2CR_AUM,
    # AIF minimums are ₹1 Cr — same tier band
    VehicleType.AIF_CAT_1: WealthTier.SIP_25K_TO_2CR_AUM,
    VehicleType.AIF_CAT_2: WealthTier.SIP_25K_TO_2CR_AUM,
    VehicleType.AIF_CAT_3: WealthTier.SIP_25K_TO_2CR_AUM,
    # SIF minimums are firm-configurable; default to same band
    VehicleType.SIF: WealthTier.SIP_25K_TO_2CR_AUM,
    # Direct unlisted equity is typically restricted to higher tiers
    VehicleType.UNLISTED_EQUITY: WealthTier.AUM_2CR_TO_5CR,
}


def vehicle_accessible(
    vehicle: VehicleType,
    investor_tier: WealthTier,
    *,
    vehicle_min_tier: dict[VehicleType, WealthTier] | None = None,
) -> bool:
    """True if `investor_tier` grants access to `vehicle` per the firm's tier policy."""
    mapping = vehicle_min_tier if vehicle_min_tier is not None else DEFAULT_VEHICLE_MIN_TIER
    min_tier = mapping.get(vehicle)
    if min_tier is None:
        return True
    return _TIER_RANK[investor_tier] >= _TIER_RANK[min_tier]


def apply_aum_eligibility_filter(
    model: ModelPortfolioObject,
    investor_tier: WealthTier,
    *,
    vehicle_min_tier: dict[VehicleType, WealthTier] | None = None,
) -> ModelPortfolioObject:
    """Return a copy of `model` with vehicles outside `investor_tier` suppressed
    and the suppressed weight redistributed proportionally across surviving
    vehicles in the same asset class (Section 5.3.2).

    L1 targets are unaffected (tier eligibility is purely a vehicle-level filter).
    L3 targets are unaffected for now — Pass 6+ may extend if specific sub-asset
    classes turn out to need wealth-tier filtering.

    The returned model preserves all other fields including version pin; a
    derived "filtered model" should not be confused with a new model portfolio
    version. The redistribution is per-investor-case and lives in T1, not in
    the firm-level catalog.
    """
    new_l2: dict = {}
    for asset_class, vehicle_targets in model.l2_targets.items():
        accessible: dict[VehicleType, TargetWithTolerance] = {}
        suppressed_weight = 0.0

        for vehicle, target_band in vehicle_targets.items():
            if vehicle_accessible(
                vehicle, investor_tier, vehicle_min_tier=vehicle_min_tier
            ):
                accessible[vehicle] = target_band
            else:
                suppressed_weight += target_band.target

        # Redistribute suppressed weight proportionally to the accessible vehicles
        # in this asset class. If no accessible vehicles remain, we keep the empty
        # dict (caller will see a hole in the model and can decide what to do).
        if accessible and suppressed_weight > 1e-12:
            accessible_sum = sum(tw.target for tw in accessible.values())
            if accessible_sum > 1e-12:
                scale = (accessible_sum + suppressed_weight) / accessible_sum
                accessible = {
                    v: TargetWithTolerance(
                        target=min(1.0, tw.target * scale),
                        tolerance_band=tw.tolerance_band,
                    )
                    for v, tw in accessible.items()
                }

        new_l2[asset_class] = accessible

    return model.model_copy(update={"l2_targets": new_l2}, deep=False)


def model_portfolio_version_pin(model: ModelPortfolioObject) -> str:
    """Format the version pin string captured in T1's `version_pins.model_portfolio_version`
    per Section 3.7.

    The pin combines model_id and version so that replay can locate the exact
    bucket-version-firm combination. Pass 6+ may add timestamp components if the
    catalog ends up storing multiple snapshots per (model_id, version).
    """
    return f"{model.model_id}@{model.version}"


# ===========================================================================
# In-memory model portfolio catalog (Pass 4 stub for Pass 6+ persistence)
# ===========================================================================


class ModelPortfolioRegistry:
    """In-memory catalog of model portfolio versions keyed by (firm_id, bucket).

    Per Section 3.7 every component that reads the model portfolio uses a
    version-pinned reference. Cases use the version in force at decision time;
    replay reads the captured version, not the current. The registry's
    `active_for(firm, bucket, as_of)` query implements this lookup.

    For Pass 4 the registry is in-memory only — tests construct one directly,
    inject portfolios via `register`, and call `active_for` to mimic what
    Pass 6+ will route through a database table. The interface is intentionally
    minimal so the DB-backed swap is a drop-in replacement.

    Active-version semantics: a portfolio is active at `as_of` when
    `effective_at <= as_of < superseded_at` (or `superseded_at is None`).
    If multiple portfolios match (rare; typically a misconfiguration), the
    one with the latest `effective_at` wins.
    """

    def __init__(self) -> None:
        self._portfolios: dict[tuple[str, Bucket], list[ModelPortfolioObject]] = {}

    def register(self, mp: ModelPortfolioObject) -> None:
        """Add a portfolio to the catalog. No version-conflict check — callers
        registering a version that supersedes an existing one are responsible
        for setting the prior version's `superseded_at` first.
        """
        key = (mp.firm_id, mp.bucket)
        self._portfolios.setdefault(key, []).append(mp)

    def active_for(
        self,
        firm_id: str,
        bucket: Bucket,
        *,
        as_of: datetime | None = None,
    ) -> ModelPortfolioObject | None:
        """Return the model portfolio in force for `(firm_id, bucket)` at `as_of`.

        Returns None if no portfolio exists for the (firm, bucket) pair, or if
        no version is active at the given time.
        """
        ts = as_of if as_of is not None else datetime.now(UTC)
        candidates = self._portfolios.get((firm_id, bucket), [])
        active = [
            mp
            for mp in candidates
            if mp.effective_at <= ts and (mp.superseded_at is None or mp.superseded_at > ts)
        ]
        if not active:
            return None
        return max(active, key=lambda mp: mp.effective_at)

    def all_versions(
        self, firm_id: str, bucket: Bucket
    ) -> list[ModelPortfolioObject]:
        """Return every version registered for `(firm_id, bucket)`, in insertion order."""
        return list(self._portfolios.get((firm_id, bucket), []))
