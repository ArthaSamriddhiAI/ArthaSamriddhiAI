"""§5.9.3 / §7.6 — cascade workflow schemas.

Two cascade workflows live here:

  * **L4 manifest cascade** (§5.9.3) — when an L4 manifest version removes
    or substitutes an instrument, M0 spawns one Mode-1-dominant case per
    affected client. `L4CascadeCase` carries the per-client case stub +
    recommended substitution; `L4CascadeRun` aggregates all cases for one
    L4 version transition.

  * **Mandate amendment** (§7.6) — advisor proposes amendment, M1 generates
    diff, client signs off, new mandate version activates. If the amendment
    changes the client's bucket (via `risk_profile` / `time_horizon`), a
    `BucketRemappingEvent` is emitted. If the new mandate fits no standard
    bucket, the result carries an `out_of_bucket_flag=True` triggering a
    single-client construction case (§5.8.1).

T1 dispatch: `L4_MANIFEST_VERSION_PIN`, `MANDATE_AMENDMENT`, `BUCKET_REMAPPING`
event types already exist in `T1EventType` (§15.11.1). This module ships the
structured payloads those events carry.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.construction import L4SubstitutionImpact
from artha.canonical.mandate import MandateObject
from artha.common.types import (
    Bucket,
    InputsUsedManifest,
    INRAmountField,
    RiskProfile,
    TimeHorizon,
)

# ===========================================================================
# §5.9.3 — L4 cascade
# ===========================================================================


class L4CascadeCaseStatus(str, Enum):
    """Lifecycle of a per-client Mode-1-dominant case spawned by L4 cascade."""

    OPEN = "open"
    ADVISOR_REVIEWED = "advisor_reviewed"
    APPROVED = "approved"
    DECLINED = "declined"


class L4CascadeCase(BaseModel):
    """§5.9.3 — one per-client Mode-1-dominant case from an L4 substitution.

    The case stub is created when the L4 manifest version activates. The
    title + body follow the §5.13 Test 7 phrasing: "Fund A [removed] —
    substitute to Fund B [recommended alternative]."
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str  # ULID
    client_id: str
    firm_id: str
    advisor_id: str | None = None
    case_mode: Literal["mode_1_dominant"] = "mode_1_dominant"
    action_type: Literal["substitution"] = "substitution"
    removed_instrument_id: str
    replacement_instrument_id: str
    affected_aum_inr: INRAmountField = 0.0
    title: str
    body: str
    n0_alert_id: str | None = None
    status: L4CascadeCaseStatus = L4CascadeCaseStatus.OPEN
    created_at: datetime


class L4CascadeRun(BaseModel):
    """§5.9.3 — aggregate of all per-client cases spawned by an L4 version transition."""

    model_config = ConfigDict(extra="forbid")

    run_id: str  # ULID
    firm_id: str
    l4_manifest_version: str  # the new manifest version that triggered the cascade
    triggered_at: datetime
    impacts: list[L4SubstitutionImpact] = Field(default_factory=list)
    spawned_cases: list[L4CascadeCase] = Field(default_factory=list)
    n0_alert_ids: list[str] = Field(default_factory=list)
    t1_event_id: str | None = None
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


# ===========================================================================
# §7.6 — mandate amendment
# ===========================================================================


class MandateDiffField(BaseModel):
    """One field that changed between prior + proposed mandate versions."""

    model_config = ConfigDict(extra="forbid")

    path: str  # dotted path, e.g. "asset_class_limits.equity.max_pct"
    prior_value: Any | None = None
    proposed_value: Any | None = None
    change_kind: Literal["added", "removed", "modified"] = "modified"


class MandateAmendmentDiff(BaseModel):
    """§7.6 step 2 — structured diff M1 generates from the proposed amendment."""

    model_config = ConfigDict(extra="forbid")

    amendment_id: str
    client_id: str
    prior_version: int
    proposed_version: int
    field_changes: list[MandateDiffField] = Field(default_factory=list)
    risk_profile_changed: bool = False
    time_horizon_changed: bool = False
    bucket_will_change: bool = False  # filled by `compute_bucket_change`


class BucketRemappingEvent(BaseModel):
    """§6.3 / §7.6 step 6 — emitted when an amendment changes the client's bucket.

    Captures the deterministic diff of L1 allocations between the prior and
    new bucket's model portfolios so the advisor sees implied rebalance
    recommendations alongside the re-mapping notice.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str  # ULID
    client_id: str
    firm_id: str
    triggered_by_amendment_id: str
    prior_bucket: Bucket
    new_bucket: Bucket
    prior_risk_profile: RiskProfile
    new_risk_profile: RiskProfile
    prior_time_horizon: TimeHorizon
    new_time_horizon: TimeHorizon
    prior_model_portfolio_id: str | None = None
    new_model_portfolio_id: str | None = None
    l1_allocation_deltas: dict[str, float] = Field(default_factory=dict)  # asset_class → delta
    timestamp: datetime


class MandateAmendmentResult(BaseModel):
    """§7.6 — full activation outcome.

    `out_of_bucket_flag=True` triggers single-client construction per §5.8.1.
    `remapping_event` is non-null only when the amendment changes the bucket.
    """

    model_config = ConfigDict(extra="forbid")

    amendment_id: str
    client_id: str
    firm_id: str
    diff: MandateAmendmentDiff
    prior_mandate: MandateObject
    new_mandate: MandateObject
    activated_at: datetime
    remapping_event: BucketRemappingEvent | None = None
    out_of_bucket_flag: bool = False
    out_of_bucket_reasons: list[str] = Field(default_factory=list)
    n0_alert_ids: list[str] = Field(default_factory=list)
    t1_amendment_event_id: str | None = None
    t1_remapping_event_id: str | None = None
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


__all__ = [
    "BucketRemappingEvent",
    "L4CascadeCase",
    "L4CascadeCaseStatus",
    "L4CascadeRun",
    "MandateAmendmentDiff",
    "MandateAmendmentResult",
    "MandateDiffField",
]
