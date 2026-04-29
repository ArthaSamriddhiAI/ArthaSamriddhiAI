"""§4.2 / §5.8 — construction-pipeline schemas.

The construction pipeline is a sibling orchestrator to the case pipeline. It
runs E1–E6 + S1 + IC1 + governance with `run_mode=CONSTRUCTION` over a firm
policy + macro assumptions + L4 manifest, and produces:

  * `BucketConstructionProposal` — proposed `ModelPortfolioObject` for one
    of the 9 buckets, with a `BlastRadius` + `BucketVersionDiff` + S1 thesis
    + IC1 deliberation + G3 governance verdict.
  * `SingleClientConstructionProposal` — custom model for an out-of-bucket
    client (§5.13 Test 8 / §7.10 Test 10).
  * `L4SubstitutionImpact` — clients holding a removed L4 instrument with
    the proposed replacement (§5.13 Test 7).
  * `ConstructionRun` — the full run envelope, written to T1.

Per §5.8.3.3 high-blast-radius rollouts: `RolloutMode.SHADOW_30D` triggers
a 30-day shadow window where PM1 computes drift against both prior +
proposed model but only prior fires N0 alerts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.canonical.synthesis import IC1Deliberation, S1Synthesis
from artha.common.types import (
    Bucket,
    InputsUsedManifest,
    INRAmountField,
    PercentageField,
)

# ===========================================================================
# Triggers + rollout modes (§5.8.1, §5.8.3.3)
# ===========================================================================


class ConstructionTrigger(str, Enum):
    """§5.8.1 — what kicked off a construction run."""

    SCHEDULED = "scheduled"
    MACRO_SHIFT = "macro_shift"
    REGULATORY = "regulatory"
    FUND_UNIVERSE = "fund_universe"
    FIRM_DECISION = "firm_decision"
    SINGLE_CLIENT = "single_client"


class RolloutMode(str, Enum):
    """§5.8.3.3 — how a new model portfolio version rolls out."""

    IMMEDIATE = "immediate"
    SHADOW_30D = "shadow_30d"


# ===========================================================================
# Blast radius + version diff (§5.13 Test 5)
# ===========================================================================


class CellChange(BaseModel):
    """One cell that changed between prior + proposed model versions."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["l1", "l2", "l3"]
    cell_key: str  # e.g. "equity" or "equity.mutual_fund.large_cap"
    prior_target: PercentageField | None = None
    proposed_target: PercentageField | None = None
    prior_band: PercentageField | None = None
    proposed_band: PercentageField | None = None
    delta: float | None = None  # signed: proposed - prior


class BucketVersionDiff(BaseModel):
    """§5.13 Test 5 — full diff displayed on the construction approval surface."""

    model_config = ConfigDict(extra="forbid")

    bucket: Bucket
    prior_model_id: str | None = None  # null on first version
    prior_version: str | None = None
    proposed_model_id: str
    proposed_version: str
    cell_changes: list[CellChange] = Field(default_factory=list)
    cell_changes_count: int = 0


class BlastRadius(BaseModel):
    """§5.13 Test 5 — clients impacted by a model portfolio version change.

    `clients_in_tolerance_who_breach` is the number of clients currently
    inside the prior model's tolerance bands who'd be outside the proposed
    bands at activation. Day-1 N0 alerts equals this when no other guards
    apply (PM1 fires on action-required L1 breaches).
    """

    model_config = ConfigDict(extra="forbid")

    bucket: Bucket
    clients_in_bucket_count: int = 0
    clients_in_tolerance_who_breach: int = 0
    total_aum_moved_inr: INRAmountField = 0.0
    estimated_txn_cost_inr: INRAmountField = 0.0
    estimated_tax_cost_inr: INRAmountField = 0.0
    day_one_n0_alert_count: int = 0
    blast_radius_share: PercentageField = 0.0  # breach_count / clients_in_bucket


# ===========================================================================
# Per-bucket + single-client proposals (§5.13 Tests 5, 6, 8)
# ===========================================================================


class BucketConstructionProposal(BaseModel):
    """§5.13 Test 5 / Test 6 — proposed model + supporting artefacts for one bucket."""

    model_config = ConfigDict(extra="forbid")

    bucket: Bucket
    proposed_model: ModelPortfolioObject
    prior_model_id: str | None = None
    version_diff: BucketVersionDiff
    blast_radius: BlastRadius
    rollout_mode: RolloutMode = RolloutMode.IMMEDIATE

    # Run artefacts produced by the agent stack
    s1_synthesis: S1Synthesis | None = None
    ic1_deliberation: IC1Deliberation | None = None
    governance_g3_input_hash: str | None = None  # G3Evaluation.input_hash
    a1_input_hash: str | None = None              # A1Challenge.input_hash

    # Decision outcome
    approved_for_rollout: bool = False
    approval_rationale: str = ""


class SingleClientConstructionProposal(BaseModel):
    """§5.13 Test 8 / §7.10 Test 10 — custom model for an out-of-bucket client."""

    model_config = ConfigDict(extra="forbid")

    client_id: str
    firm_id: str
    proposed_model: ModelPortfolioObject
    rationale: str = ""
    advisor_escalation_required: bool = True  # always per §7.10 Test 10
    s1_synthesis: S1Synthesis | None = None
    ic1_deliberation: IC1Deliberation | None = None


# ===========================================================================
# §5.13 Test 7 — L4 substitution cascade
# ===========================================================================


class L4SubstitutionImpact(BaseModel):
    """One L4 substitution and the clients it affects."""

    model_config = ConfigDict(extra="forbid")

    removed_instrument_id: str
    replacement_instrument_id: str
    affected_client_ids: list[str] = Field(default_factory=list)
    total_aum_affected_inr: INRAmountField = 0.0


# ===========================================================================
# Run envelope + status
# ===========================================================================


class ConstructionRunStatus(str, Enum):
    """Lifecycle of a construction run."""

    DRAFT = "draft"
    AGENTS_RUNNING = "agents_running"
    PENDING_APPROVAL = "pending_approval"
    SHADOW_ACTIVE = "shadow_active"
    APPROVED_FOR_IMMEDIATE = "approved_for_immediate"
    REJECTED = "rejected"


class ConstructionRun(BaseModel):
    """§5.8.4 — the construction-run envelope persisted to T1."""

    model_config = ConfigDict(extra="forbid")

    run_id: str  # ULID
    firm_id: str
    initiated_by: str  # CIO advisor_id
    initiated_at: datetime
    trigger: ConstructionTrigger
    scoped_buckets: list[Bucket] = Field(default_factory=list)
    status: ConstructionRunStatus = ConstructionRunStatus.DRAFT

    # Per-bucket proposals (when bucket-level run)
    bucket_proposals: list[BucketConstructionProposal] = Field(default_factory=list)

    # Single-client proposal (when trigger is SINGLE_CLIENT)
    single_client_proposal: SingleClientConstructionProposal | None = None

    # L4 substitution cascade impacts (when trigger is FUND_UNIVERSE)
    l4_substitution_impacts: list[L4SubstitutionImpact] = Field(default_factory=list)

    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


# ===========================================================================
# Inputs the orchestrator reads
# ===========================================================================


class ClientPortfolioSlice(BaseModel):
    """Minimal per-client snapshot the construction orchestrator reads.

    Production wires this from M0.PortfolioState; tests can drive it directly.
    `current_l1_weights` is what the client actually holds today; the
    orchestrator compares against the prior + proposed models to compute
    blast radius.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str
    firm_id: str
    bucket: Bucket
    aum_inr: INRAmountField
    current_l1_weights: dict[str, PercentageField] = Field(default_factory=dict)
    holdings_by_instrument_id: dict[str, INRAmountField] = Field(default_factory=dict)


class ConstructionInputs(BaseModel):
    """Top-level inputs the orchestrator consumes."""

    model_config = ConfigDict(extra="forbid")

    firm_id: str
    initiated_by: str
    trigger: ConstructionTrigger
    scoped_buckets: list[Bucket] = Field(default_factory=list)

    # Prior models per bucket (None if first version for that bucket)
    prior_models: dict[Bucket, ModelPortfolioObject] = Field(default_factory=dict)

    # Per-bucket client snapshots (for blast-radius computation)
    client_slices: list[ClientPortfolioSlice] = Field(default_factory=list)

    # L4 substitutions (for FUND_UNIVERSE trigger)
    l4_removed_instrument_ids: list[str] = Field(default_factory=list)
    l4_replacement_map: dict[str, str] = Field(default_factory=dict)

    # Single-client trigger inputs
    single_client_id: str | None = None
    single_client_aum_inr: INRAmountField | None = None

    # Configurable thresholds
    shadow_blast_threshold: PercentageField = 0.25  # §5.8.3.3 default
    txn_cost_pct: PercentageField = 0.005           # 50bps deterministic stub
    tax_cost_pct: PercentageField = 0.10            # LTCG-style stub


__all__ = [
    "BlastRadius",
    "BucketConstructionProposal",
    "BucketVersionDiff",
    "CellChange",
    "ClientPortfolioSlice",
    "ConstructionInputs",
    "ConstructionRun",
    "ConstructionRunStatus",
    "ConstructionTrigger",
    "L4SubstitutionImpact",
    "RolloutMode",
    "SingleClientConstructionProposal",
]
