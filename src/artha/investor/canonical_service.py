"""Pure-function service over the canonical InvestorContextProfile (Section 6).

This module is the integration seam between the canonical profile schema
(Pass 2) and the model portfolio operations (Pass 3). It owns:

  * `assigned_bucket_for(profile)` — bucket lookup (validator-enforced)
  * `structural_flag_summary(profile)` — propagated flag set for downstream agents
  * `cat_ii_aif_structurally_appropriate(profile)` — propagation contract for
    Section 6.7 tests 2 + 4 (the actual gate decision is E6.Gate's job in Pass 6+)
  * `detect_remapping(old, new)` — bucket-change detection for re-mapping events
  * `BucketRemapping` — structured T1 payload for bucket re-mapping events
  * `emit_remapping_event(remapping, repo, ...)` — append the event to T1
  * `check_conflicts_at_activation(profile, mandate, model)` — Section 5.10 / 6.6

By design this module does NOT perform any database writes against the legacy
`investor` ORM (that's where this package's `service.py` lives). New code paths
that operate on the canonical profile import from here; the legacy router and
service stay untouched until later passes wire them through.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from artha.canonical.holding import ConflictReport
from artha.canonical.investor import InvestorContextProfile
from artha.canonical.mandate import MandateObject
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.common.standards import T1EventType
from artha.common.types import (
    Bucket,
    CapacityTrajectory,
    RiskProfile,
    TimeHorizon,
    VersionPins,
)
from artha.model_portfolio.conflict import detect_mandate_vs_model_conflicts

if TYPE_CHECKING:  # avoid runtime cycle; T1Repository is async-DB-bound
    from artha.accountability.t1 import T1Event, T1Repository


# ===========================================================================
# Bucket assignment
# ===========================================================================


def assigned_bucket_for(profile: InvestorContextProfile) -> Bucket:
    """Return the bucket pinned to this profile (Section 6.3).

    The pin is validator-enforced at model construction time — `assigned_bucket`
    must equal `derive_bucket(risk_profile, time_horizon)`. So this accessor is
    cheap, but it gives downstream code a single named entry point rather than
    reaching into the profile fields directly.
    """
    return profile.assigned_bucket


# ===========================================================================
# Structural flag propagation
# ===========================================================================


class StructuralFlagSummary(BaseModel):
    """Section 6.5 — the structural flags that downstream agents read.

    These flags are *informational* at the integration layer; they do not block
    products on their own. The actual blocking is E6.Gate's job (Pass 6+), but
    every gate that reads structural flags must consume them through this
    summary so the propagation contract is consistent.
    """

    model_config = ConfigDict(extra="forbid")

    capacity_trajectory: CapacityTrajectory
    capacity_constrained: bool
    intermediary_conflict_present: bool
    beneficiary_agency_gap: bool


def structural_flag_summary(profile: InvestorContextProfile) -> StructuralFlagSummary:
    """Return the structural flag summary for `profile` (Section 6.5)."""
    return StructuralFlagSummary(
        capacity_trajectory=profile.capacity_trajectory,
        capacity_constrained=profile.capacity_trajectory
        != CapacityTrajectory.STABLE_OR_GROWING,
        intermediary_conflict_present=profile.intermediary_present,
        beneficiary_agency_gap=not profile.beneficiary_can_operate_current_structure,
    )


def cat_ii_aif_structurally_appropriate(
    profile: InvestorContextProfile,
) -> tuple[bool, list[str]]:
    """Section 6.7 tests 2 + 4 propagation contract.

    Returns `(appropriate, blocking_reasons)`:
      * `appropriate=True` ⇒ no structural flag warrants a Cat II AIF block.
      * `appropriate=False` ⇒ the listed reasons are the structural concerns
        that a downstream gate (E6.Gate in Pass 6+) should respect with
        SOFT_BLOCK or stricter scrutiny.

    The reasons are stable identifiers so that T2 calibration can correlate
    block patterns to outcomes. They are not user-facing copy.
    """
    reasons: list[str] = []
    if profile.capacity_trajectory in (
        CapacityTrajectory.DECLINING_MODERATE,
        CapacityTrajectory.DECLINING_SEVERE,
    ):
        reasons.append("capacity_trajectory_declining")
    if not profile.beneficiary_can_operate_current_structure:
        reasons.append("beneficiary_agency_gap")
    return (len(reasons) == 0, reasons)


# ===========================================================================
# Bucket re-mapping (Section 6.3)
# ===========================================================================


class BucketRemapping(BaseModel):
    """Structured payload for a T1 BUCKET_REMAPPING event (Section 6.3).

    Emitted whenever an investor's `risk_profile` or `time_horizon` changes
    and the deterministic bucket mapping shifts. Pass 6+ will wire the N0
    alert that converts this T1 event into an advisor-facing notification
    with the implied allocation deltas.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str
    firm_id: str
    from_bucket: Bucket
    to_bucket: Bucket
    from_risk_profile: RiskProfile
    to_risk_profile: RiskProfile
    from_time_horizon: TimeHorizon
    to_time_horizon: TimeHorizon
    triggered_at: datetime
    triggered_by: str = "system"  # advisor_id or "system" for automated detection


def detect_remapping(
    old: InvestorContextProfile,
    new: InvestorContextProfile,
    *,
    triggered_by: str = "system",
) -> BucketRemapping | None:
    """Return a `BucketRemapping` if `new`'s bucket differs from `old`'s.

    Both profiles must reference the same client (different versions).

    Returns `None` when the bucket is unchanged — even if other active fields
    moved, no re-mapping fires unless the bucket pin moves. (Wealth tier
    changes, capacity-trajectory changes, etc. are profile updates but not
    re-mapping events under Section 6.3.)
    """
    if old.client_id != new.client_id:
        raise ValueError(
            f"re-mapping must compare versions of the same client; "
            f"got old={old.client_id} new={new.client_id}"
        )
    if old.assigned_bucket == new.assigned_bucket:
        return None
    return BucketRemapping(
        client_id=new.client_id,
        firm_id=new.firm_id,
        from_bucket=old.assigned_bucket,
        to_bucket=new.assigned_bucket,
        from_risk_profile=old.risk_profile,
        to_risk_profile=new.risk_profile,
        from_time_horizon=old.time_horizon,
        to_time_horizon=new.time_horizon,
        triggered_at=new.updated_at,
        triggered_by=triggered_by,
    )


async def emit_remapping_event(
    remapping: BucketRemapping,
    repo: T1Repository,
    *,
    version_pins: VersionPins | None = None,
) -> T1Event:
    """Append a BUCKET_REMAPPING event to T1.

    Returns the persisted `T1Event`. The N0 alert that this should trigger
    (Section 6.3 Test 5) is deferred to Pass 6+ when N0 is wired.
    """
    from artha.accountability.t1 import T1Event  # local import: async DB-bound

    event = T1Event.build(
        event_type=T1EventType.BUCKET_REMAPPING,
        firm_id=remapping.firm_id,
        timestamp=remapping.triggered_at,
        client_id=remapping.client_id,
        payload=remapping.model_dump(mode="json"),
        version_pins=version_pins,
    )
    return await repo.append(event)


# ===========================================================================
# Mandate-vs-model conflict at activation (Section 5.10 / 6.6)
# ===========================================================================


def check_conflicts_at_activation(
    profile: InvestorContextProfile,
    mandate: MandateObject,
    model: ModelPortfolioObject,
) -> list[ConflictReport]:
    """Run mandate-vs-model conflict detection for the investor's bucket.

    Per Section 6.6, this fires at investor activation and at every model
    portfolio version change. The caller decides how to surface the result —
    Section 5.10 path 1 (amend mandate), path 2 (clip model), or path 3
    (flag out-of-bucket).

    Pre-conditions:
      * `model.bucket == profile.assigned_bucket` (we don't enforce; the
        caller is responsible for fetching the right model version).
      * `mandate.client_id == profile.client_id` (same — caller's job).
    """
    return detect_mandate_vs_model_conflicts(mandate, model)
