"""§10.3.4 — API onboarding path (deterministic intake + N0 confirmation).

The API handler accepts an `OnboardingApiPayload` already conforming to
canonical shapes, validates it (Pydantic does the heavy lifting), then
issues a MUST_RESPOND `N0Alert` for advisor confirmation. The activation
event is written only on confirmation.

Per §10.3.4:
  * `confidence` is 1.0 (schema-validated payload).
  * Two-phase: `submit()` returns a `PendingApiConfirmation` with the
    pending alert; the orchestrator delivers via N0; advisor responds via
    `confirm()` or `reject()`.
  * Timeout is the orchestrator's responsibility (N0's `check_timeouts`);
    on timeout the orchestrator calls `reject(reason="timeout_expired")`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from artha.canonical.investor import DataSource, InvestorContextProfile
from artha.canonical.mandate import MandateObject
from artha.canonical.monitoring import (
    AlertTier,
    N0Alert,
    N0AlertCategory,
    N0Originator,
)
from artha.canonical.onboarding import (
    ConfirmationMethod,
    OnboardingActivationStatus,
    OnboardingApiPayload,
    OnboardingConflictItem,
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


# Default 7-day window for advisor confirmation per §10.3.4.
DEFAULT_API_CONFIRMATION_WINDOW_DAYS = 7
SUPPORTED_API_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0.0"})


class ApiSchemaValidationError(OnboardingError):
    """Raised when the API payload schema version is unsupported."""


class PendingApiConfirmation(BaseModel):
    """Returned by `submit()` when the API path is waiting on advisor confirmation."""

    model_config = ConfigDict(extra="forbid")

    onboarding_id: str
    api_request_id: str
    advisor_id: str
    confirmation_alert: N0Alert
    investor_profile_payload: dict[str, Any]
    mandate_payload: dict[str, Any]
    conflicts: list[OnboardingConflictItem]


class ApiOnboardingHandler:
    """§10.3.4 deterministic API onboarding handler."""

    handler_id = "onboarding.api"

    def __init__(
        self,
        *,
        t1_repository: Any | None = None,
        confirmation_window_days: int = DEFAULT_API_CONFIRMATION_WINDOW_DAYS,
        supported_schema_versions: frozenset[str] = SUPPORTED_API_SCHEMA_VERSIONS,
    ) -> None:
        self._t1 = t1_repository
        self._confirmation_window_days = confirmation_window_days
        self._supported_schema_versions = supported_schema_versions
        # Pending state: onboarding_id → (profile, mandate, payload, conflicts)
        self._pending: dict[str, tuple[
            InvestorContextProfile, MandateObject, OnboardingApiPayload,
            list[OnboardingConflictItem],
        ]] = {}

    # --------------------- Public API --------------------------------

    async def submit(
        self,
        payload: OnboardingApiPayload,
        *,
        model_portfolio: Any | None = None,
    ) -> PendingApiConfirmation:
        """Validate the API payload and emit a MUST_RESPOND confirmation alert."""
        if payload.api_schema_version not in self._supported_schema_versions:
            raise ApiSchemaValidationError(
                f"unsupported API schema version {payload.api_schema_version!r}; "
                f"supported: {sorted(self._supported_schema_versions)}"
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
            data_source=DataSource.API,
            data_source_metadata={
                "api_request_id": payload.api_request_id,
                "crm_identifier": payload.crm_identifier or "",
                "api_schema_version": payload.api_schema_version,
            },
            confidence=1.0,
            data_gaps_flagged=[],
            signoff_method=payload.signoff_method,
            signoff_evidence_id=payload.signoff_evidence_id,
            signoff_captured_at=payload.signoff_captured_at,
            signed_by=payload.signed_by,
            now=now,
        )

        conflicts = detect_conflicts_against_model(profile, mandate, model_portfolio)

        onboarding_id = new_ulid()
        alert = N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.EX1,  # onboarding alerts route via the orchestration layer
            tier=AlertTier.MUST_RESPOND,
            category=N0AlertCategory.EXCEPTION,  # generic admin category for onboarding asks
            client_id=payload.client_id,
            firm_id=payload.firm_id,
            created_at=now,
            title=f"API onboarding pending confirmation: {payload.client_id}",
            body=(
                f"API request {payload.api_request_id} produced a canonical "
                f"InvestorContextProfile (bucket={profile.assigned_bucket.value}) "
                f"and MandateObject. "
                f"{len(conflicts)} mandate-vs-model conflict(s) surfaced. "
                f"Confirm or reject within {self._confirmation_window_days} days."
            ),
            expected_action="Review and confirm/reject the onboarded investor.",
            related_constraint_id=f"onboarding:{onboarding_id}",
        )

        self._pending[onboarding_id] = (profile, mandate, payload, conflicts)

        return PendingApiConfirmation(
            onboarding_id=onboarding_id,
            api_request_id=payload.api_request_id,
            advisor_id=payload.advisor_id,
            confirmation_alert=alert,
            investor_profile_payload=profile.model_dump(mode="json"),
            mandate_payload=mandate.model_dump(mode="json"),
            conflicts=conflicts,
        )

    async def confirm(
        self,
        onboarding_id: str,
        *,
        confirming_advisor_id: str,
        conflict_resolution_path: str | None = None,
    ) -> OnboardingResult:
        """Advisor confirms the pending onboarding → emit activation event."""
        if onboarding_id not in self._pending:
            raise KeyError(f"unknown pending onboarding {onboarding_id}")
        profile, mandate, payload, conflicts = self._pending[onboarding_id]

        if conflicts and conflict_resolution_path is None:
            raise OnboardingError(
                f"onboarding {onboarding_id} has unresolved conflicts; "
                "must supply conflict_resolution_path before confirming"
            )

        confirmed_at = get_clock().now()
        t1_event_id: str | None = None
        if self._t1 is not None:
            t1_event_id = await emit_activation_event(
                repo=self._t1,
                onboarding_id=onboarding_id,
                client_id=payload.client_id,
                firm_id=payload.firm_id,
                advisor_id=confirming_advisor_id,
                profile=profile,
                mandate=mandate,
                confirmation_method=ConfirmationMethod.API_ALERT_RESPONSE,
                confirmed_at=confirmed_at,
                conflict_resolution_path=conflict_resolution_path,
            )
        del self._pending[onboarding_id]

        return OnboardingResult(
            onboarding_id=onboarding_id,
            client_id=payload.client_id,
            firm_id=payload.firm_id,
            advisor_id=confirming_advisor_id,
            data_source=DataSource.API,
            data_source_metadata={
                "api_request_id": payload.api_request_id,
                "crm_identifier": payload.crm_identifier or "",
                "api_schema_version": payload.api_schema_version,
            },
            confirmation_method=ConfirmationMethod.API_ALERT_RESPONSE,
            confirmed_at=confirmed_at,
            activation_status=OnboardingActivationStatus.ACTIVATED,
            investor_profile_payload=profile.model_dump(mode="json"),
            mandate_payload=mandate.model_dump(mode="json"),
            conflicts=conflicts,
            conflict_resolution_path=conflict_resolution_path,
            t1_confirmation_event_id=t1_event_id,
        )

    def reject(
        self,
        onboarding_id: str,
        *,
        reason: str,
    ) -> OnboardingResult:
        """Advisor rejects (or window expires) — discard pending state."""
        if onboarding_id not in self._pending:
            raise KeyError(f"unknown pending onboarding {onboarding_id}")
        profile, mandate, payload, conflicts = self._pending[onboarding_id]
        del self._pending[onboarding_id]

        status = (
            OnboardingActivationStatus.EXPIRED
            if reason == "timeout_expired"
            else OnboardingActivationStatus.ABANDONED
        )

        return OnboardingResult(
            onboarding_id=onboarding_id,
            client_id=payload.client_id,
            firm_id=payload.firm_id,
            advisor_id=payload.advisor_id,
            data_source=DataSource.API,
            data_source_metadata={
                "api_request_id": payload.api_request_id,
                "crm_identifier": payload.crm_identifier or "",
                "api_schema_version": payload.api_schema_version,
                "rejection_reason": reason,
            },
            confirmation_method=ConfirmationMethod.API_ALERT_RESPONSE,
            confirmed_at=None,
            activation_status=status,
            investor_profile_payload=profile.model_dump(mode="json"),
            mandate_payload=mandate.model_dump(mode="json"),
            conflicts=conflicts,
            t1_confirmation_event_id=None,
        )

    def is_pending(self, onboarding_id: str) -> bool:
        return onboarding_id in self._pending

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "ApiOnboardingHandler",
    "ApiSchemaValidationError",
    "DEFAULT_API_CONFIRMATION_WINDOW_DAYS",
    "PendingApiConfirmation",
    "SUPPORTED_API_SCHEMA_VERSIONS",
]
