"""§10.3.2 — FORM onboarding path (deterministic).

The form handler ingests `OnboardingFormPayload`, applies the form-specific
discipline (structural-flag confirmation, signoff captured at submit time),
builds the canonical objects via `build_canonical_objects`, runs the
optional mandate-vs-model conflict check, and writes the T1
`INVESTOR_ACTIVATED` event with `confirmation_method=FORM_SUBMIT`.

Per §10.3.2 form-discipline:
  * Required fields are non-skippable — the payload schema enforces this.
  * Structural-flag defaults must be EXPLICITLY confirmed by the advisor
    (`structural_flags_advisor_confirmed=True`); otherwise we surface the
    fields as `data_gaps_flagged` and refuse activation.
  * `confidence` is 1.0 since every required field was supplied via the form.
"""

from __future__ import annotations

import logging
from typing import Any

from artha.canonical.investor import DataSource
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.canonical.onboarding import (
    ConfirmationMethod,
    OnboardingActivationStatus,
    OnboardingFormPayload,
    OnboardingResult,
)
from artha.common.clock import get_clock
from artha.common.ulid import new_ulid
from artha.onboarding.canonical_common import (
    OnboardingError,
    build_canonical_objects,
    detect_conflicts_against_model,
    emit_activation_event,
)

logger = logging.getLogger(__name__)


class StructuralFlagsNotConfirmedError(OnboardingError):
    """Raised when the form payload doesn't carry advisor confirmation of
    structural-flag defaults (per §10.3.2 form discipline)."""


class FormOnboardingHandler:
    """§10.3.2 deterministic FORM intake."""

    handler_id = "onboarding.form"

    def __init__(
        self,
        *,
        t1_repository: Any | None = None,
    ) -> None:
        self._t1 = t1_repository

    async def submit(
        self,
        payload: OnboardingFormPayload,
        *,
        model_portfolio: ModelPortfolioObject | None = None,
    ) -> OnboardingResult:
        """Submit a form and produce an activated `OnboardingResult`."""
        if not payload.structural_flags_advisor_confirmed:
            raise StructuralFlagsNotConfirmedError(
                "form payload missing structural_flags_advisor_confirmed=True; "
                "advisor must confirm defaults before submit"
            )

        now = get_clock().now()
        profile, mandate = build_canonical_objects(
            client_id=payload.client_id,
            firm_id=payload.firm_id,
            risk_profile=payload.risk_profile,
            time_horizon=payload.time_horizon,
            wealth_tier=payload.wealth_tier,
            capacity_trajectory=payload.capacity_trajectory,
            intermediary_present=payload.intermediary_present,
            intermediary_metadata=payload.intermediary_metadata,
            beneficiary_can_operate=payload.beneficiary_can_operate_current_structure,
            beneficiary_metadata=payload.beneficiary_metadata,
            family_member_overrides=list(payload.family_member_overrides),
            mandate_intake=payload.mandate,
            data_source=DataSource.FORM,
            data_source_metadata={"form_session_id": payload.form_session_id},
            confidence=1.0,
            data_gaps_flagged=[],
            signoff_method=payload.signoff_method,
            signoff_evidence_id=payload.signoff_evidence_id,
            signoff_captured_at=payload.signoff_captured_at,
            signed_by=payload.signed_by,
            now=now,
        )

        conflicts = detect_conflicts_against_model(profile, mandate, model_portfolio)
        activation_status = (
            OnboardingActivationStatus.PENDING_CONFLICT_RESOLUTION
            if conflicts
            else OnboardingActivationStatus.ACTIVATED
        )

        confirmed_at = payload.submitted_at
        t1_event_id: str | None = None
        if self._t1 is not None and not conflicts:
            t1_event_id = await emit_activation_event(
                repo=self._t1,
                onboarding_id=new_ulid(),
                client_id=payload.client_id,
                firm_id=payload.firm_id,
                advisor_id=payload.submitted_by_advisor_id,
                profile=profile,
                mandate=mandate,
                confirmation_method=ConfirmationMethod.FORM_SUBMIT,
                confirmed_at=confirmed_at,
            )

        return OnboardingResult(
            onboarding_id=new_ulid(),
            client_id=payload.client_id,
            firm_id=payload.firm_id,
            advisor_id=payload.submitted_by_advisor_id,
            data_source=DataSource.FORM,
            data_source_metadata={"form_session_id": payload.form_session_id},
            confirmation_method=ConfirmationMethod.FORM_SUBMIT,
            confirmed_at=confirmed_at if not conflicts else None,
            activation_status=activation_status,
            investor_profile_payload=profile.model_dump(mode="json"),
            mandate_payload=mandate.model_dump(mode="json"),
            conflicts=conflicts,
            t1_confirmation_event_id=t1_event_id,
        )


__all__ = [
    "FormOnboardingHandler",
    "StructuralFlagsNotConfirmedError",
]
