"""§4.2 / §5.8 — `ConstructionOrchestrator`.

Pass 16 ships the deterministic orchestration over already-produced
synthesis / deliberation / governance artefacts. The orchestrator:

  * Runs the bucket-construction flow per scoped bucket — wraps the
    proposed `ModelPortfolioObject` together with `BucketVersionDiff`,
    `BlastRadius`, `RolloutMode` (immediate vs shadow), the run's
    S1 / IC1 / G3 / A1 artefact pointers, and an approval flag.
  * Runs the single-client path when the trigger is `SINGLE_CLIENT` —
    produces a `SingleClientConstructionProposal` with
    `advisor_escalation_required=True` per §7.10 Test 10.
  * Runs the L4 substitution cascade (§5.13 Test 7).
  * Composes the final `ConstructionRun` envelope.

The agent stack itself (E1–E6 + S1 + IC1 + governance) runs externally
with `run_mode=CONSTRUCTION` envelopes; tests pass already-produced
artefacts directly into `propose_bucket()` to keep the surface small.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from artha.canonical.construction import (
    BucketConstructionProposal,
    ClientPortfolioSlice,
    ConstructionInputs,
    ConstructionRun,
    ConstructionRunStatus,
    ConstructionTrigger,
    L4SubstitutionImpact,
    RolloutMode,
    SingleClientConstructionProposal,
)
from artha.canonical.governance import G3Evaluation
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.canonical.synthesis import IC1Deliberation, S1Synthesis
from artha.common.clock import get_clock
from artha.common.hashing import payload_hash
from artha.common.types import (
    Bucket,
    InputsUsedManifest,
    Permission,
)
from artha.common.ulid import new_ulid
from artha.construction.canonical_blast_radius import (
    compute_blast_radius,
    compute_version_diff,
    should_use_shadow_mode,
)
from artha.construction.canonical_substitution import compute_substitution_impacts

logger = logging.getLogger(__name__)


class ConstructionOrchestrator:
    """§4.2 / §5.8 deterministic construction orchestrator."""

    agent_id = "construction_orchestrator"

    def __init__(self, *, agent_version: str = "0.1.0") -> None:
        self._agent_version = agent_version

    # --------------------- Public API --------------------------------

    def propose_bucket(
        self,
        *,
        bucket: Bucket,
        proposed_model: ModelPortfolioObject,
        prior_model: ModelPortfolioObject | None,
        client_slices: list[ClientPortfolioSlice],
        s1_synthesis: S1Synthesis | None = None,
        ic1_deliberation: IC1Deliberation | None = None,
        g3_evaluation: G3Evaluation | None = None,
        a1_input_hash: str | None = None,
        shadow_blast_threshold: float = 0.25,
        txn_cost_pct: float = 0.005,
        tax_cost_pct: float = 0.10,
    ) -> BucketConstructionProposal:
        """Build the per-bucket construction proposal."""
        diff = compute_version_diff(
            bucket=bucket, prior_model=prior_model, proposed_model=proposed_model
        )
        blast = compute_blast_radius(
            bucket=bucket,
            prior_model=prior_model,
            proposed_model=proposed_model,
            client_slices=client_slices,
            txn_cost_pct=txn_cost_pct,
            tax_cost_pct=tax_cost_pct,
        )
        rollout = (
            RolloutMode.SHADOW_30D
            if should_use_shadow_mode(blast_radius=blast, threshold=shadow_blast_threshold)
            else RolloutMode.IMMEDIATE
        )

        approved = self._is_approved(g3_evaluation)
        rationale = self._approval_rationale(
            g3=g3_evaluation,
            ic1=ic1_deliberation,
            rollout=rollout,
            blast=blast,
        )

        return BucketConstructionProposal(
            bucket=bucket,
            proposed_model=proposed_model,
            prior_model_id=prior_model.model_id if prior_model else None,
            version_diff=diff,
            blast_radius=blast,
            rollout_mode=rollout,
            s1_synthesis=s1_synthesis,
            ic1_deliberation=ic1_deliberation,
            governance_g3_input_hash=g3_evaluation.input_hash if g3_evaluation else None,
            a1_input_hash=a1_input_hash,
            approved_for_rollout=approved,
            approval_rationale=rationale,
        )

    def propose_single_client(
        self,
        *,
        client_id: str,
        firm_id: str,
        proposed_model: ModelPortfolioObject,
        rationale: str = "",
        s1_synthesis: S1Synthesis | None = None,
        ic1_deliberation: IC1Deliberation | None = None,
    ) -> SingleClientConstructionProposal:
        """Build the out-of-bucket / single-client custom proposal."""
        return SingleClientConstructionProposal(
            client_id=client_id,
            firm_id=firm_id,
            proposed_model=proposed_model,
            rationale=rationale,
            advisor_escalation_required=True,  # §7.10 Test 10
            s1_synthesis=s1_synthesis,
            ic1_deliberation=ic1_deliberation,
        )

    def run(
        self,
        *,
        inputs: ConstructionInputs,
        bucket_proposed_models: dict[Bucket, ModelPortfolioObject] | None = None,
        bucket_artefacts: dict[Bucket, dict[str, Any]] | None = None,
        single_client_proposed_model: ModelPortfolioObject | None = None,
        single_client_artefacts: dict[str, Any] | None = None,
    ) -> ConstructionRun:
        """Compose the full `ConstructionRun` envelope.

        `bucket_proposed_models` maps `Bucket` → proposed `ModelPortfolioObject`.
        `bucket_artefacts` maps `Bucket` → optional artefacts dict supplying
        `s1_synthesis`, `ic1_deliberation`, `g3_evaluation`, `a1_input_hash`.
        """
        bucket_proposed_models = bucket_proposed_models or {}
        bucket_artefacts = bucket_artefacts or {}
        bucket_proposals: list[BucketConstructionProposal] = []

        for bucket in inputs.scoped_buckets:
            proposed = bucket_proposed_models.get(bucket)
            if proposed is None:
                continue
            artefacts = bucket_artefacts.get(bucket, {})
            slices = [s for s in inputs.client_slices if s.bucket is bucket]
            bucket_proposals.append(
                self.propose_bucket(
                    bucket=bucket,
                    proposed_model=proposed,
                    prior_model=inputs.prior_models.get(bucket),
                    client_slices=slices,
                    s1_synthesis=artefacts.get("s1_synthesis"),
                    ic1_deliberation=artefacts.get("ic1_deliberation"),
                    g3_evaluation=artefacts.get("g3_evaluation"),
                    a1_input_hash=artefacts.get("a1_input_hash"),
                    shadow_blast_threshold=inputs.shadow_blast_threshold,
                    txn_cost_pct=inputs.txn_cost_pct,
                    tax_cost_pct=inputs.tax_cost_pct,
                )
            )

        single_client_proposal: SingleClientConstructionProposal | None = None
        if (
            inputs.trigger is ConstructionTrigger.SINGLE_CLIENT
            and single_client_proposed_model is not None
            and inputs.single_client_id is not None
        ):
            single_artefacts = single_client_artefacts or {}
            single_client_proposal = self.propose_single_client(
                client_id=inputs.single_client_id,
                firm_id=inputs.firm_id,
                proposed_model=single_client_proposed_model,
                rationale=single_artefacts.get("rationale", ""),
                s1_synthesis=single_artefacts.get("s1_synthesis"),
                ic1_deliberation=single_artefacts.get("ic1_deliberation"),
            )

        l4_impacts: list[L4SubstitutionImpact] = []
        if (
            inputs.trigger is ConstructionTrigger.FUND_UNIVERSE
            and inputs.l4_removed_instrument_ids
        ):
            l4_impacts = compute_substitution_impacts(
                client_slices=inputs.client_slices,
                removed_instrument_ids=inputs.l4_removed_instrument_ids,
                replacement_map=inputs.l4_replacement_map,
            )

        status = self._derive_status(
            bucket_proposals=bucket_proposals,
            single_client_proposal=single_client_proposal,
        )

        signals_input = self._collect_input_for_hash(
            inputs=inputs,
            bucket_proposed_models=bucket_proposed_models,
            single_client_proposed_model=single_client_proposed_model,
        )

        return ConstructionRun(
            run_id=new_ulid(),
            firm_id=inputs.firm_id,
            initiated_by=inputs.initiated_by,
            initiated_at=self._now(),
            trigger=inputs.trigger,
            scoped_buckets=list(inputs.scoped_buckets),
            status=status,
            bucket_proposals=bucket_proposals,
            single_client_proposal=single_client_proposal,
            l4_substitution_impacts=l4_impacts,
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            agent_version=self._agent_version,
        )

    # --------------------- Helpers ----------------------------------

    def _is_approved(self, g3: G3Evaluation | None) -> bool:
        if g3 is None:
            return False
        return g3.permission is Permission.APPROVED

    def _approval_rationale(
        self,
        *,
        g3: G3Evaluation | None,
        ic1: IC1Deliberation | None,
        rollout: RolloutMode,
        blast: Any,
    ) -> str:
        if g3 is None:
            return "G3 governance not yet evaluated; awaiting approval."
        if g3.permission is Permission.BLOCKED:
            return f"G3 BLOCKED: {','.join(g3.blocking_reasons) or 'unspecified'}"
        if g3.permission is Permission.ESCALATION_REQUIRED:
            return (
                f"G3 ESCALATION_REQUIRED: "
                f"{','.join(g3.escalation_reasons) or 'unspecified'}"
            )
        if rollout is RolloutMode.SHADOW_30D:
            return (
                f"Approved for shadow rollout per §5.8.3.3: "
                f"blast_share={blast.blast_radius_share:.4f} exceeds threshold."
            )
        ic1_note = (
            f" IC1 recommendation: {ic1.recommendation.value}" if ic1 else ""
        )
        return f"G3 APPROVED for immediate rollout.{ic1_note}"

    def _derive_status(
        self,
        *,
        bucket_proposals: list[BucketConstructionProposal],
        single_client_proposal: SingleClientConstructionProposal | None,
    ) -> ConstructionRunStatus:
        if not bucket_proposals and single_client_proposal is None:
            return ConstructionRunStatus.DRAFT
        any_shadow = any(
            bp.rollout_mode is RolloutMode.SHADOW_30D for bp in bucket_proposals
        )
        all_approved = all(bp.approved_for_rollout for bp in bucket_proposals)
        any_rejected = any(not bp.approved_for_rollout for bp in bucket_proposals)
        if bucket_proposals:
            if any_rejected:
                return ConstructionRunStatus.REJECTED
            if any_shadow:
                return ConstructionRunStatus.SHADOW_ACTIVE
            if all_approved:
                return ConstructionRunStatus.APPROVED_FOR_IMMEDIATE
            return ConstructionRunStatus.PENDING_APPROVAL
        # Single-client only — always pending advisor escalation
        return ConstructionRunStatus.PENDING_APPROVAL

    def _collect_input_for_hash(
        self,
        *,
        inputs: ConstructionInputs,
        bucket_proposed_models: dict[Bucket, ModelPortfolioObject],
        single_client_proposed_model: ModelPortfolioObject | None,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "firm_id": inputs.firm_id,
            "trigger": inputs.trigger.value,
            "scoped_buckets": sorted(b.value for b in inputs.scoped_buckets),
            "prior_model_ids": {
                b.value: m.model_id for b, m in inputs.prior_models.items()
            },
            "proposed_model_ids": {
                b.value: m.model_id for b, m in bucket_proposed_models.items()
            },
            "single_client_id": inputs.single_client_id,
            "single_client_proposed_model_id": (
                single_client_proposed_model.model_id
                if single_client_proposed_model is not None
                else None
            ),
            "l4_removed_instrument_ids": sorted(inputs.l4_removed_instrument_ids),
            "shadow_blast_threshold": inputs.shadow_blast_threshold,
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = ["ConstructionOrchestrator"]
