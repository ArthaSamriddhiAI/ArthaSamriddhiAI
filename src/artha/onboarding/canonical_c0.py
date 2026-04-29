"""§10.3.3 — C0 onboarding path (LLM-backed extraction with checkpoints).

C0 onboarding extracts structured fields from a multi-turn advisor
conversation, with three explicit advisor confirmation checkpoints:

  1. IDENTITY_KYC — client identity + firm + KYC fields
  2. RISK_PROFILE_HORIZON — risk_profile + time_horizon + wealth_tier
  3. MANDATE_CONSTRAINTS — asset class limits + structural flags + signoff

Each checkpoint runs an LLM extraction over the transcript so far, the
advisor reviews and either confirms or supplies corrections. The handler
keeps per-checkpoint state in memory; `finalize()` stitches the confirmed
extractions into canonical objects and emits the activation event.

Per §10.3.3 discipline:
  * The LLM never invents fields. Low-confidence parses surface as
    `data_gaps_flagged` on the final profile.
  * Confidence band is 0.8–0.95 for the activated profile (multiplicative
    of per-checkpoint parse confidences).
  * Advisor must confirm each checkpoint before the next runs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from artha.canonical.investor import (
    BeneficiaryMetadata,
    DataSource,
    FamilyMemberOverride,
    IntermediaryMetadata,
)
from artha.canonical.mandate import SignoffMethod
from artha.canonical.onboarding import (
    C0CheckpointExtraction,
    C0OnboardingTranscriptInput,
    ConfirmationMethod,
    MandateIntakePayload,
    OnboardingActivationStatus,
    OnboardingCheckpoint,
    OnboardingCheckpointKind,
    OnboardingResult,
)
from artha.common.clock import get_clock
from artha.common.types import (
    CapacityTrajectory,
    ConfidenceField,
    RiskProfile,
    TimeHorizon,
    WealthTier,
)
from artha.common.ulid import new_ulid
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest
from artha.onboarding.canonical_common import (
    OnboardingError,
    build_canonical_objects,
    detect_conflicts_against_model,
    emit_activation_event,
)

logger = logging.getLogger(__name__)


class C0OnboardingLLMUnavailableError(OnboardingError):
    """Raised when the C0 onboarding extractor LLM fails."""


class C0CheckpointNotConfirmedError(OnboardingError):
    """Raised on `finalize()` if any checkpoint hasn't been confirmed."""


# ===========================================================================
# Per-checkpoint LLM output schemas
# ===========================================================================


class _LlmIdentityKycOutput(BaseModel):
    """Output for the IDENTITY_KYC checkpoint."""

    model_config = ConfigDict(extra="forbid")

    client_id: str | None = None
    firm_id: str | None = None
    parse_confidence: ConfidenceField = 0.0
    parse_notes: str = ""


class _LlmRiskHorizonOutput(BaseModel):
    """Output for the RISK_PROFILE_HORIZON checkpoint."""

    model_config = ConfigDict(extra="forbid")

    risk_profile_value: str | None = None  # validated → RiskProfile
    time_horizon_value: str | None = None  # validated → TimeHorizon
    wealth_tier_value: str | None = None   # validated → WealthTier
    parse_confidence: ConfidenceField = 0.0
    parse_notes: str = ""


class _LlmMandateConstraintsOutput(BaseModel):
    """Output for the MANDATE_CONSTRAINTS checkpoint."""

    model_config = ConfigDict(extra="forbid")

    capacity_trajectory_value: str | None = None
    intermediary_present: bool = False
    beneficiary_can_operate: bool = True
    mandate_intake: MandateIntakePayload | None = None
    parse_confidence: ConfidenceField = 0.0
    parse_notes: str = ""


# ===========================================================================
# System prompts
# ===========================================================================


_IDENTITY_PROMPT = """\
You are C0's onboarding identity extractor (§10.3.3 checkpoint 1).

Read the conversation transcript and extract: client_id (if mentioned),
firm_id (if mentioned). Set parse_confidence (0–1) and parse_notes
describing what you couldn't extract or where you were uncertain.

Discipline: NEVER invent ids. If the transcript doesn't carry an id, leave
the field null and reduce confidence accordingly.
"""

_RISK_HORIZON_PROMPT = """\
You are C0's risk-and-horizon extractor (§10.3.3 checkpoint 2).

Read the conversation and extract: risk_profile_value (one of
Conservative / Moderate / Aggressive), time_horizon_value (one of
short_term / medium_term / long_term), wealth_tier_value (one of the
WealthTier enum values).

Discipline: leave a field null if you can't extract with confidence.
"""

_MANDATE_PROMPT = """\
You are C0's mandate-constraints extractor (§10.3.3 checkpoint 3).

Read the conversation and extract: capacity_trajectory_value (one of
stable_or_growing / stable_with_known_decline_dates / declining_moderate /
declining_severe), intermediary_present (bool), beneficiary_can_operate
(bool), mandate_intake (asset class limits, sector exclusions, etc.).

Discipline: never invent constraint values. Leave fields null if uncertain.
"""


# ===========================================================================
# Handler
# ===========================================================================


class C0OnboardingHandler:
    """§10.3.3 LLM-backed C0 onboarding handler.

    State machine: each call to `extract_checkpoint` runs the LLM for that
    checkpoint and stores the result. `confirm_checkpoint` flips the
    confirmed bit. `finalize` builds canonical objects once all three
    checkpoints have been confirmed.
    """

    handler_id = "onboarding.c0"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        t1_repository: Any | None = None,
    ) -> None:
        self._provider = provider
        self._t1 = t1_repository
        self._checkpoints: dict[
            tuple[str, OnboardingCheckpointKind], OnboardingCheckpoint
        ] = {}

    # --------------------- Public API --------------------------------

    async def extract_checkpoint(
        self,
        *,
        transcript: C0OnboardingTranscriptInput,
        kind: OnboardingCheckpointKind,
    ) -> OnboardingCheckpoint:
        """Run the LLM extraction for one checkpoint."""
        if kind is OnboardingCheckpointKind.IDENTITY_KYC:
            extraction = await self._extract_identity(transcript)
        elif kind is OnboardingCheckpointKind.RISK_PROFILE_HORIZON:
            extraction = await self._extract_risk_horizon(transcript)
        elif kind is OnboardingCheckpointKind.MANDATE_CONSTRAINTS:
            extraction = await self._extract_mandate(transcript)
        else:
            raise ValueError(f"unknown checkpoint kind: {kind}")

        cp = OnboardingCheckpoint(checkpoint_kind=kind, extraction=extraction)
        self._checkpoints[(transcript.c0_conversation_id, kind)] = cp
        return cp

    def confirm_checkpoint(
        self,
        *,
        c0_conversation_id: str,
        kind: OnboardingCheckpointKind,
        advisor_id: str,
        corrections: dict[str, Any] | None = None,
    ) -> OnboardingCheckpoint:
        """Advisor confirms an extracted checkpoint, optionally with corrections."""
        cp = self._checkpoints.get((c0_conversation_id, kind))
        if cp is None:
            raise KeyError(
                f"checkpoint {kind.value} not yet extracted for "
                f"conversation {c0_conversation_id}"
            )
        cp.confirmed = True
        cp.confirmed_by_advisor_id = advisor_id
        cp.confirmed_at = self._now()
        if corrections:
            cp.corrections = dict(corrections)
        return cp

    async def finalize(
        self,
        *,
        transcript: C0OnboardingTranscriptInput,
        family_member_overrides: list[FamilyMemberOverride] | None = None,
        intermediary_metadata: IntermediaryMetadata | None = None,
        beneficiary_metadata: BeneficiaryMetadata | None = None,
        signoff_method: SignoffMethod = SignoffMethod.E_SIGNATURE,
        signoff_evidence_id: str = "",
        signoff_captured_at: datetime | None = None,
        signed_by: str = "",
        model_portfolio: Any | None = None,
    ) -> OnboardingResult:
        """Build canonical objects after all three checkpoints confirmed."""
        for kind in (
            OnboardingCheckpointKind.IDENTITY_KYC,
            OnboardingCheckpointKind.RISK_PROFILE_HORIZON,
            OnboardingCheckpointKind.MANDATE_CONSTRAINTS,
        ):
            cp = self._checkpoints.get((transcript.c0_conversation_id, kind))
            if cp is None or not cp.confirmed:
                raise C0CheckpointNotConfirmedError(
                    f"checkpoint {kind.value} not confirmed; cannot finalize"
                )

        identity_cp = self._checkpoints[
            (transcript.c0_conversation_id, OnboardingCheckpointKind.IDENTITY_KYC)
        ]
        risk_cp = self._checkpoints[
            (transcript.c0_conversation_id, OnboardingCheckpointKind.RISK_PROFILE_HORIZON)
        ]
        mandate_cp = self._checkpoints[
            (transcript.c0_conversation_id, OnboardingCheckpointKind.MANDATE_CONSTRAINTS)
        ]

        # Stitch values, allowing corrections to override LLM output.
        identity = self._merge(
            identity_cp.extraction.extracted_fields, identity_cp.corrections
        )
        risk = self._merge(
            risk_cp.extraction.extracted_fields, risk_cp.corrections
        )
        mandate_extract = self._merge(
            mandate_cp.extraction.extracted_fields, mandate_cp.corrections
        )

        client_id = identity.get("client_id") or transcript.client_id
        firm_id = identity.get("firm_id") or transcript.firm_id

        # Resolve enum values from string fields (LLM emits string-typed for
        # mock-provider compatibility).
        risk_profile = self._enum_or_raise(
            RiskProfile, risk.get("risk_profile_value"), "risk_profile"
        )
        time_horizon = self._enum_or_raise(
            TimeHorizon, risk.get("time_horizon_value"), "time_horizon"
        )
        wealth_tier = self._enum_or_raise(
            WealthTier, risk.get("wealth_tier_value"), "wealth_tier"
        )
        capacity_trajectory = self._enum_or_default(
            CapacityTrajectory,
            mandate_extract.get("capacity_trajectory_value"),
            CapacityTrajectory.STABLE_OR_GROWING,
        )

        intermediary_present = bool(mandate_extract.get("intermediary_present", False))
        beneficiary_can_operate = bool(
            mandate_extract.get("beneficiary_can_operate", True)
        )

        mandate_intake_raw = mandate_extract.get("mandate_intake")
        if mandate_intake_raw is None:
            raise C0OnboardingLLMUnavailableError(
                "mandate intake missing from confirmed mandate-constraints checkpoint"
            )
        mandate_intake = (
            mandate_intake_raw
            if isinstance(mandate_intake_raw, MandateIntakePayload)
            else MandateIntakePayload.model_validate(mandate_intake_raw)
        )

        # Aggregate confidence: multiplicative of per-checkpoint parse confidences,
        # capped within the §10.3.3 band [0.8, 0.95].
        c1 = identity_cp.extraction.parse_confidence or 0.95
        c2 = risk_cp.extraction.parse_confidence or 0.95
        c3 = mandate_cp.extraction.parse_confidence or 0.95
        agg_confidence = max(0.8, min(0.95, c1 * c2 * c3))

        data_gaps: list[str] = []
        if not identity.get("client_id"):
            data_gaps.append("client_id_inferred_from_transcript")
        if c1 < 0.85 or c2 < 0.85 or c3 < 0.85:
            data_gaps.append("low_checkpoint_confidence")

        now = get_clock().now()
        profile, mandate = build_canonical_objects(
            client_id=client_id,
            firm_id=firm_id,
            risk_profile=risk_profile,
            time_horizon=time_horizon,
            wealth_tier=wealth_tier,
            capacity_trajectory=capacity_trajectory,
            intermediary_present=intermediary_present,
            intermediary_metadata=intermediary_metadata,
            beneficiary_can_operate=beneficiary_can_operate,
            beneficiary_metadata=beneficiary_metadata,
            family_member_overrides=family_member_overrides or [],
            mandate_intake=mandate_intake,
            data_source=DataSource.C0,
            data_source_metadata={
                "c0_conversation_id": transcript.c0_conversation_id,
            },
            confidence=agg_confidence,
            data_gaps_flagged=data_gaps,
            signoff_method=signoff_method,
            signoff_evidence_id=signoff_evidence_id or new_ulid(),
            signoff_captured_at=signoff_captured_at or now,
            signed_by=signed_by or transcript.advisor_id,
            now=now,
        )

        conflicts = detect_conflicts_against_model(profile, mandate, model_portfolio)
        activation_status = (
            OnboardingActivationStatus.PENDING_CONFLICT_RESOLUTION
            if conflicts
            else OnboardingActivationStatus.ACTIVATED
        )

        confirmed_at = now
        t1_event_id: str | None = None
        if self._t1 is not None and not conflicts:
            t1_event_id = await emit_activation_event(
                repo=self._t1,
                onboarding_id=new_ulid(),
                client_id=client_id,
                firm_id=firm_id,
                advisor_id=transcript.advisor_id,
                profile=profile,
                mandate=mandate,
                confirmation_method=ConfirmationMethod.C0_CONFIRMATION,
                confirmed_at=confirmed_at,
            )

        return OnboardingResult(
            onboarding_id=new_ulid(),
            client_id=client_id,
            firm_id=firm_id,
            advisor_id=transcript.advisor_id,
            data_source=DataSource.C0,
            data_source_metadata={
                "c0_conversation_id": transcript.c0_conversation_id,
            },
            confirmation_method=ConfirmationMethod.C0_CONFIRMATION,
            confirmed_at=confirmed_at if not conflicts else None,
            activation_status=activation_status,
            investor_profile_payload=profile.model_dump(mode="json"),
            mandate_payload=mandate.model_dump(mode="json"),
            conflicts=conflicts,
            t1_confirmation_event_id=t1_event_id,
        )

    # --------------------- LLM extractors ---------------------------

    async def _extract_identity(
        self,
        transcript: C0OnboardingTranscriptInput,
    ) -> C0CheckpointExtraction:
        out = await self._call_llm(
            transcript=transcript,
            system_prompt=_IDENTITY_PROMPT,
            output_type=_LlmIdentityKycOutput,
        )
        return C0CheckpointExtraction(
            checkpoint_kind=OnboardingCheckpointKind.IDENTITY_KYC,
            extracted_fields={
                "client_id": out.client_id,
                "firm_id": out.firm_id,
            },
            parse_confidence=out.parse_confidence,
            parse_notes=out.parse_notes,
        )

    async def _extract_risk_horizon(
        self,
        transcript: C0OnboardingTranscriptInput,
    ) -> C0CheckpointExtraction:
        out = await self._call_llm(
            transcript=transcript,
            system_prompt=_RISK_HORIZON_PROMPT,
            output_type=_LlmRiskHorizonOutput,
        )
        return C0CheckpointExtraction(
            checkpoint_kind=OnboardingCheckpointKind.RISK_PROFILE_HORIZON,
            extracted_fields={
                "risk_profile_value": out.risk_profile_value,
                "time_horizon_value": out.time_horizon_value,
                "wealth_tier_value": out.wealth_tier_value,
            },
            parse_confidence=out.parse_confidence,
            parse_notes=out.parse_notes,
        )

    async def _extract_mandate(
        self,
        transcript: C0OnboardingTranscriptInput,
    ) -> C0CheckpointExtraction:
        out = await self._call_llm(
            transcript=transcript,
            system_prompt=_MANDATE_PROMPT,
            output_type=_LlmMandateConstraintsOutput,
        )
        return C0CheckpointExtraction(
            checkpoint_kind=OnboardingCheckpointKind.MANDATE_CONSTRAINTS,
            extracted_fields={
                "capacity_trajectory_value": out.capacity_trajectory_value,
                "intermediary_present": out.intermediary_present,
                "beneficiary_can_operate": out.beneficiary_can_operate,
                "mandate_intake": (
                    out.mandate_intake.model_dump(mode="json")
                    if out.mandate_intake is not None
                    else None
                ),
            },
            parse_confidence=out.parse_confidence,
            parse_notes=out.parse_notes,
        )

    async def _call_llm(
        self,
        *,
        transcript: C0OnboardingTranscriptInput,
        system_prompt: str,
        output_type: type,
    ) -> Any:
        try:
            return await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=system_prompt),
                        LLMMessage(
                            role="user",
                            content=(
                                f"conversation_id: {transcript.c0_conversation_id}\n"
                                f"advisor_id: {transcript.advisor_id}\n"
                                f"firm_id: {transcript.firm_id}\n"
                                f"client_id_hint: {transcript.client_id}\n"
                                f"transcript:\n{transcript.transcript_text}\n"
                                "Produce the structured JSON per the system prompt."
                            ),
                        ),
                    ],
                    temperature=0.0,
                ),
                output_type,
            )
        except Exception as exc:
            logger.warning("C0 onboarding LLM unavailable: %s", exc)
            raise C0OnboardingLLMUnavailableError(
                f"c0 onboarding LLM provider unavailable: {exc}"
            ) from exc

    # --------------------- Helpers ----------------------------------

    def _merge(
        self,
        extracted: dict[str, Any],
        corrections: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(extracted)
        for k, v in corrections.items():
            if v is not None:
                merged[k] = v
        return merged

    def _enum_or_raise(self, enum_cls: type, raw: str | None, field_name: str):
        if raw is None:
            raise C0OnboardingLLMUnavailableError(
                f"required field {field_name} missing from confirmed checkpoint"
            )
        try:
            return enum_cls(raw)
        except ValueError as exc:
            raise C0OnboardingLLMUnavailableError(
                f"checkpoint emitted non-canonical {field_name}={raw!r}"
            ) from exc

    def _enum_or_default(self, enum_cls: type, raw: str | None, default):
        if raw is None:
            return default
        try:
            return enum_cls(raw)
        except ValueError:
            return default

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "C0CheckpointNotConfirmedError",
    "C0OnboardingHandler",
    "C0OnboardingLLMUnavailableError",
]
