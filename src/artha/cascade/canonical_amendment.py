"""§7.6 — Mandate Amendment Service (deterministic).

Workflow per §7.6:

  1. **propose** — advisor submits an amendment proposal carrying the
     proposed mandate fields + justification. Service generates a
     `MandateAmendmentDiff` over the prior `MandateObject` and returns a
     `MandateAmendmentRequest` in `PENDING_SIGNOFF`.
  2. **capture_signoff** — client signs off; request advances to
     `PENDING_COMPLIANCE_REVIEW` (compliance is an out-of-band step in MVP)
     or directly to ready-for-activation when compliance is auto-attested.
  3. **activate** — produce a new `MandateObject` version with
     `effective_at = signoff_timestamp`, supersede the prior version, emit
     T1 `MANDATE_AMENDMENT` event. If the amendment changes
     `risk_profile` or `time_horizon`, emit a `BucketRemappingEvent` and
     T1 `BUCKET_REMAPPING` event. If the new mandate fits no standard
     bucket (per `_is_out_of_bucket`), set `out_of_bucket_flag=True`.

Pure deterministic. No LLM. The amendment workflow does NOT run G1
governance — G1 is the case-pipeline gate (§13.2). Compliance review is
a per-firm out-of-band hook (§7.6.4); the service exposes
`mark_compliance_reviewed` for that path.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from artha.canonical.cascade import (
    BucketRemappingEvent,
    MandateAmendmentDiff,
    MandateAmendmentResult,
    MandateDiffField,
)
from artha.canonical.investor import InvestorContextProfile
from artha.canonical.mandate import (
    MandateAmendmentRequest,
    MandateAmendmentStatus,
    MandateObject,
    SignoffEvidence,
)
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.canonical.monitoring import (
    AlertTier,
    N0Alert,
    N0AlertCategory,
    N0Originator,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.standards import T1EventType
from artha.common.types import (
    Bucket,
    InputsUsedManifest,
)
from artha.common.ulid import new_ulid

logger = logging.getLogger(__name__)


class MandateAmendmentError(ArthaError):
    """Base for mandate-amendment workflow failures."""


class SignoffMissingError(MandateAmendmentError):
    """Raised when activation is attempted without client signoff."""


class AlreadyActivatedError(MandateAmendmentError):
    """Raised when activation is attempted on an already-activated request."""


class MandateAmendmentService:
    """§7.6 deterministic mandate-amendment service."""

    agent_id = "mandate_amendment"

    def __init__(
        self,
        *,
        t1_repository: Any | None = None,
        agent_version: str = "0.1.0",
    ) -> None:
        self._t1 = t1_repository
        self._agent_version = agent_version

    # --------------------- §7.6 step 1+2: propose + diff -----------------

    def propose(
        self,
        *,
        client_id: str,
        firm_id: str,
        proposed_by: str,
        prior_mandate: MandateObject,
        proposed_mandate: MandateObject,
        amendment_type: Any,  # MandateAmendmentType
        justification: str,
        prior_profile: InvestorContextProfile | None = None,
        proposed_profile: InvestorContextProfile | None = None,
    ) -> tuple[MandateAmendmentRequest, MandateAmendmentDiff]:
        """Generate the structured diff + return a PENDING_SIGNOFF request."""
        amendment_id = new_ulid()
        diff = self._compute_diff(
            amendment_id=amendment_id,
            client_id=client_id,
            prior_mandate=prior_mandate,
            proposed_mandate=proposed_mandate,
            prior_profile=prior_profile,
            proposed_profile=proposed_profile,
        )

        request = MandateAmendmentRequest(
            amendment_id=amendment_id,
            client_id=client_id,
            proposed_at=self._now(),
            proposed_by=proposed_by,
            amendment_type=amendment_type,
            diff={
                "old_mandate_subset": prior_mandate.model_dump(mode="json"),
                "new_mandate_subset": proposed_mandate.model_dump(mode="json"),
                "field_changes": [c.model_dump(mode="json") for c in diff.field_changes],
            },
            justification=justification,
            activation_status=MandateAmendmentStatus.PENDING_SIGNOFF,
        )
        return request, diff

    # --------------------- §7.6 step 3: signoff -------------------------

    def capture_signoff(
        self,
        request: MandateAmendmentRequest,
        *,
        signoff: SignoffEvidence,
        compliance_auto_attested: bool = True,
    ) -> MandateAmendmentRequest:
        """Attach client signoff to the request.

        `compliance_auto_attested=True` advances directly to ready-for-activation.
        `False` parks the request in PENDING_COMPLIANCE_REVIEW until
        `mark_compliance_reviewed` is called.
        """
        next_status = (
            MandateAmendmentStatus.PENDING_COMPLIANCE_REVIEW
            if not compliance_auto_attested
            else MandateAmendmentStatus.PENDING_COMPLIANCE_REVIEW
        )
        return request.model_copy(
            update={
                "client_signoff": signoff,
                "activation_status": next_status,
            }
        )

    def mark_compliance_reviewed(
        self,
        request: MandateAmendmentRequest,
        *,
        compliance_check_result: dict[str, Any] | None = None,
    ) -> MandateAmendmentRequest:
        """Advance compliance-reviewed request toward activation.

        We don't introduce a separate READY status; we keep the request in
        PENDING_COMPLIANCE_REVIEW with a populated `compliance_check_result`
        and let `activate()` handle the transition. Tests can call this
        directly to simulate the compliance hook.
        """
        return request.model_copy(
            update={"compliance_check_result": dict(compliance_check_result or {})}
        )

    # --------------------- §7.6 step 4–6: activation --------------------

    async def activate(
        self,
        request: MandateAmendmentRequest,
        *,
        firm_id: str,
        prior_mandate: MandateObject,
        proposed_mandate: MandateObject,
        prior_profile: InvestorContextProfile | None = None,
        proposed_profile: InvestorContextProfile | None = None,
        prior_model_portfolio: ModelPortfolioObject | None = None,
        new_model_portfolio: ModelPortfolioObject | None = None,
        bucket_models: dict[Bucket, ModelPortfolioObject] | None = None,
    ) -> MandateAmendmentResult:
        """Produce a new mandate version + bucket remapping (if applicable)."""
        if request.client_signoff is None:
            raise SignoffMissingError(
                f"amendment {request.amendment_id} cannot activate without client_signoff"
            )
        if request.activation_status is MandateAmendmentStatus.ACTIVATED:
            raise AlreadyActivatedError(
                f"amendment {request.amendment_id} already activated"
            )
        if request.activation_status is MandateAmendmentStatus.REJECTED:
            raise AlreadyActivatedError(
                f"amendment {request.amendment_id} was rejected; cannot activate"
            )

        activated_at = request.client_signoff.captured_at
        new_version = prior_mandate.version + 1

        # Build the activated new mandate version.
        new_mandate = proposed_mandate.model_copy(
            update={
                "mandate_id": prior_mandate.mandate_id,
                "client_id": request.client_id,
                "firm_id": firm_id,
                "version": new_version,
                "created_at": prior_mandate.created_at,
                "effective_at": activated_at,
                "superseded_at": None,
                "signoff_evidence": request.client_signoff,
                "signed_by": request.proposed_by,
            }
        )

        # Recompute the structured diff (it's stable across activate calls).
        diff = self._compute_diff(
            amendment_id=request.amendment_id,
            client_id=request.client_id,
            prior_mandate=prior_mandate,
            proposed_mandate=new_mandate,
            prior_profile=prior_profile,
            proposed_profile=proposed_profile,
        )

        # Bucket re-mapping (§6.3 / §7.6 step 6).
        remapping_event: BucketRemappingEvent | None = None
        if (
            prior_profile is not None
            and proposed_profile is not None
            and diff.bucket_will_change
        ):
            remapping_event = self._build_remapping_event(
                amendment_id=request.amendment_id,
                client_id=request.client_id,
                firm_id=firm_id,
                prior_profile=prior_profile,
                proposed_profile=proposed_profile,
                prior_model_portfolio=prior_model_portfolio,
                new_model_portfolio=new_model_portfolio,
                timestamp=activated_at,
            )

        # Out-of-bucket detection (§7.10 Test 10).
        out_of_bucket, reasons = self._detect_out_of_bucket(
            new_mandate=new_mandate,
            bucket_models=bucket_models or {},
        )

        # Emit T1 events.
        amendment_event_id: str | None = None
        remapping_event_id: str | None = None
        if self._t1 is not None:
            amendment_event_id = await self._emit_amendment_event(
                amendment_id=request.amendment_id,
                client_id=request.client_id,
                firm_id=firm_id,
                advisor_id=request.proposed_by,
                prior_mandate=prior_mandate,
                new_mandate=new_mandate,
                diff=diff,
                activated_at=activated_at,
            )
            if remapping_event is not None:
                remapping_event_id = await self._emit_remapping_event(
                    remapping_event=remapping_event,
                    advisor_id=request.proposed_by,
                )

        signals_input = self._collect_input_for_hash(
            request_id=request.amendment_id,
            client_id=request.client_id,
            firm_id=firm_id,
            prior_mandate=prior_mandate,
            new_mandate=new_mandate,
            remapping_event=remapping_event,
            out_of_bucket=out_of_bucket,
        )

        # Build a confirmation N0 alert (informational tier per §7.6).
        confirmation_alert = self._build_confirmation_alert(
            client_id=request.client_id,
            firm_id=firm_id,
            amendment_id=request.amendment_id,
            new_version=new_version,
            out_of_bucket=out_of_bucket,
            timestamp=activated_at,
        )

        return MandateAmendmentResult(
            amendment_id=request.amendment_id,
            client_id=request.client_id,
            firm_id=firm_id,
            diff=diff,
            prior_mandate=prior_mandate.model_copy(update={"superseded_at": activated_at}),
            new_mandate=new_mandate,
            activated_at=activated_at,
            remapping_event=remapping_event,
            out_of_bucket_flag=out_of_bucket,
            out_of_bucket_reasons=reasons,
            n0_alert_ids=[confirmation_alert.alert_id],
            t1_amendment_event_id=amendment_event_id,
            t1_remapping_event_id=remapping_event_id,
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            agent_version=self._agent_version,
        )

    # --------------------- Diff generation -----------------------------

    def _compute_diff(
        self,
        *,
        amendment_id: str,
        client_id: str,
        prior_mandate: MandateObject,
        proposed_mandate: MandateObject,
        prior_profile: InvestorContextProfile | None,
        proposed_profile: InvestorContextProfile | None,
    ) -> MandateAmendmentDiff:
        prior = prior_mandate.model_dump(mode="json")
        proposed = proposed_mandate.model_dump(mode="json")
        field_changes: list[MandateDiffField] = []
        # Skip identity / lifecycle fields when computing structural diff.
        skip_keys = {
            "mandate_id", "client_id", "firm_id", "version",
            "created_at", "effective_at", "superseded_at",
            "signoff_method", "signoff_evidence", "signed_by",
        }
        for key in sorted(set(prior.keys()) | set(proposed.keys())):
            if key in skip_keys:
                continue
            old_value = prior.get(key)
            new_value = proposed.get(key)
            if old_value == new_value:
                continue
            change_kind: str
            if key not in prior:
                change_kind = "added"
            elif key not in proposed:
                change_kind = "removed"
            else:
                change_kind = "modified"
            field_changes.append(
                MandateDiffField(
                    path=key,
                    prior_value=old_value,
                    proposed_value=new_value,
                    change_kind=change_kind,
                )
            )

        risk_changed = False
        horizon_changed = False
        bucket_will_change = False
        if prior_profile is not None and proposed_profile is not None:
            risk_changed = prior_profile.risk_profile != proposed_profile.risk_profile
            horizon_changed = prior_profile.time_horizon != proposed_profile.time_horizon
            bucket_will_change = (
                prior_profile.assigned_bucket != proposed_profile.assigned_bucket
            )

        return MandateAmendmentDiff(
            amendment_id=amendment_id,
            client_id=client_id,
            prior_version=prior_mandate.version,
            proposed_version=prior_mandate.version + 1,
            field_changes=field_changes,
            risk_profile_changed=risk_changed,
            time_horizon_changed=horizon_changed,
            bucket_will_change=bucket_will_change,
        )

    # --------------------- Re-mapping --------------------------------

    def _build_remapping_event(
        self,
        *,
        amendment_id: str,
        client_id: str,
        firm_id: str,
        prior_profile: InvestorContextProfile,
        proposed_profile: InvestorContextProfile,
        prior_model_portfolio: ModelPortfolioObject | None,
        new_model_portfolio: ModelPortfolioObject | None,
        timestamp: datetime,
    ) -> BucketRemappingEvent:
        """Compute L1 allocation deltas between the prior + new bucket models."""
        deltas: dict[str, float] = {}
        prior_l1 = prior_model_portfolio.l1_targets if prior_model_portfolio else {}
        new_l1 = new_model_portfolio.l1_targets if new_model_portfolio else {}
        all_classes = set(prior_l1.keys()) | set(new_l1.keys())
        for ac in all_classes:
            old_t = prior_l1.get(ac).target if prior_l1.get(ac) else 0.0
            new_t = new_l1.get(ac).target if new_l1.get(ac) else 0.0
            deltas[ac.value] = new_t - old_t

        return BucketRemappingEvent(
            event_id=new_ulid(),
            client_id=client_id,
            firm_id=firm_id,
            triggered_by_amendment_id=amendment_id,
            prior_bucket=prior_profile.assigned_bucket,
            new_bucket=proposed_profile.assigned_bucket,
            prior_risk_profile=prior_profile.risk_profile,
            new_risk_profile=proposed_profile.risk_profile,
            prior_time_horizon=prior_profile.time_horizon,
            new_time_horizon=proposed_profile.time_horizon,
            prior_model_portfolio_id=(
                prior_model_portfolio.model_id if prior_model_portfolio else None
            ),
            new_model_portfolio_id=(
                new_model_portfolio.model_id if new_model_portfolio else None
            ),
            l1_allocation_deltas=deltas,
            timestamp=timestamp,
        )

    # --------------------- Out-of-bucket detection --------------------

    def _detect_out_of_bucket(
        self,
        *,
        new_mandate: MandateObject,
        bucket_models: dict[Bucket, ModelPortfolioObject],
    ) -> tuple[bool, list[str]]:
        """Check whether any standard bucket fits the new mandate.

        A bucket fits when each of its L1 targets sits within the mandate's
        [min_pct, max_pct] for the same asset class. If no bucket fits,
        return out_of_bucket=True with a reason per failed bucket.
        """
        if not bucket_models:
            return False, []

        reasons: list[str] = []
        for bucket, model in bucket_models.items():
            failures = self._bucket_failures(model=model, mandate=new_mandate)
            if not failures:
                # At least one bucket fits → not out-of-bucket.
                return False, []
            reasons.append(f"{bucket.value}: {','.join(failures)}")

        return True, reasons

    def _bucket_failures(
        self,
        *,
        model: ModelPortfolioObject,
        mandate: MandateObject,
    ) -> list[str]:
        """Return the asset-class names whose model target falls outside mandate bounds."""
        failures: list[str] = []
        for ac, target_band in model.l1_targets.items():
            limits = mandate.asset_class_limits.get(ac)
            if limits is None:
                continue  # mandate doesn't constrain this class — bucket free to use it
            if (
                target_band.target < limits.min_pct - 1e-9
                or target_band.target > limits.max_pct + 1e-9
            ):
                failures.append(ac.value)
        return failures

    # --------------------- T1 emission --------------------------------

    async def _emit_amendment_event(
        self,
        *,
        amendment_id: str,
        client_id: str,
        firm_id: str,
        advisor_id: str,
        prior_mandate: MandateObject,
        new_mandate: MandateObject,
        diff: MandateAmendmentDiff,
        activated_at: datetime,
    ) -> str:
        from artha.accountability.t1.models import T1Event

        payload = {
            "amendment_id": amendment_id,
            "prior_version": prior_mandate.version,
            "new_version": new_mandate.version,
            "diff": diff.model_dump(mode="json"),
            "prior_mandate_id": prior_mandate.mandate_id,
            "new_mandate_id": new_mandate.mandate_id,
            "activated_at": activated_at.isoformat(),
        }
        event = T1Event(
            event_type=T1EventType.MANDATE_AMENDMENT,
            timestamp=activated_at,
            firm_id=firm_id,
            client_id=client_id,
            advisor_id=advisor_id,
            payload=payload,
            payload_hash=payload_hash(payload),
        )
        appended = await self._t1.append(event)
        return appended.event_id

    async def _emit_remapping_event(
        self,
        *,
        remapping_event: BucketRemappingEvent,
        advisor_id: str,
    ) -> str:
        from artha.accountability.t1.models import T1Event

        payload = remapping_event.model_dump(mode="json")
        event = T1Event(
            event_type=T1EventType.BUCKET_REMAPPING,
            timestamp=remapping_event.timestamp,
            firm_id=remapping_event.firm_id,
            client_id=remapping_event.client_id,
            advisor_id=advisor_id,
            payload=payload,
            payload_hash=payload_hash(payload),
        )
        appended = await self._t1.append(event)
        return appended.event_id

    def _build_confirmation_alert(
        self,
        *,
        client_id: str,
        firm_id: str,
        amendment_id: str,
        new_version: int,
        out_of_bucket: bool,
        timestamp: datetime,
    ) -> N0Alert:
        if out_of_bucket:
            tier = AlertTier.MUST_RESPOND
            title = f"Out-of-bucket flag set for client {client_id}"
            body = (
                f"Mandate amendment {amendment_id} activated version {new_version}; "
                "new mandate fits no standard bucket. Single-client construction case required."
            )
            expected = "Open single-client construction case per §5.8.1."
        else:
            tier = AlertTier.INFORMATIONAL
            title = f"Mandate amendment activated for {client_id}"
            body = (
                f"Mandate version {new_version} active per amendment {amendment_id}."
            )
            expected = "No further action required."
        return N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.M1,
            tier=tier,
            category=N0AlertCategory.MANDATE_BREACH,
            client_id=client_id,
            firm_id=firm_id,
            created_at=timestamp,
            title=title,
            body=body,
            expected_action=expected,
            related_constraint_id=f"mandate_amendment:{amendment_id}",
        )

    # --------------------- Helpers ----------------------------------

    def _collect_input_for_hash(
        self,
        *,
        request_id: str,
        client_id: str,
        firm_id: str,
        prior_mandate: MandateObject,
        new_mandate: MandateObject,
        remapping_event: BucketRemappingEvent | None,
        out_of_bucket: bool,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "amendment_id": request_id,
            "client_id": client_id,
            "firm_id": firm_id,
            "prior_mandate_version": prior_mandate.version,
            "new_mandate_version": new_mandate.version,
            "remapping_event_id": (
                remapping_event.event_id if remapping_event else None
            ),
            "out_of_bucket": out_of_bucket,
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


__all__ = [
    "AlreadyActivatedError",
    "MandateAmendmentError",
    "MandateAmendmentService",
    "SignoffMissingError",
]
