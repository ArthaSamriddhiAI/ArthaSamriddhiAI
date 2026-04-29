"""§10.3 — shared onboarding helpers.

`build_canonical_objects` produces the `InvestorContextProfile` +
`MandateObject` from the shared active fields all three paths supply.
`emit_activation_event` writes the T1 `INVESTOR_ACTIVATED` event.

Per §10.3.7 Test 1: the same active-field inputs produce identical
canonical objects modulo `data_source` / `data_source_metadata` /
`confidence` / `data_gaps_flagged` / `confirmation_method`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from artha.canonical.holding import ConflictReport
from artha.canonical.investor import (
    BeneficiaryMetadata,
    DataSource,
    DormantI0Layer,
    FamilyMemberOverride,
    IntermediaryMetadata,
    InvestorContextProfile,
)
from artha.canonical.mandate import (
    MandateObject,
    SignoffEvidence,
    SignoffMethod,
)
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.canonical.onboarding import (
    ConfirmationMethod,
    MandateIntakePayload,
    OnboardingConflictItem,
)
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.standards import T1EventType
from artha.common.types import (
    CapacityTrajectory,
    ConfidenceField,
    RiskProfile,
    TimeHorizon,
    WealthTier,
)
from artha.investor.canonical_service import check_conflicts_at_activation


class OnboardingError(ArthaError):
    """Base class for onboarding-specific failures."""


def build_canonical_objects(
    *,
    client_id: str,
    firm_id: str,
    risk_profile: RiskProfile,
    time_horizon: TimeHorizon,
    wealth_tier: WealthTier,
    capacity_trajectory: CapacityTrajectory,
    intermediary_present: bool,
    intermediary_metadata: IntermediaryMetadata | None,
    beneficiary_can_operate: bool,
    beneficiary_metadata: BeneficiaryMetadata | None,
    family_member_overrides: list[FamilyMemberOverride],
    mandate_intake: MandateIntakePayload,
    data_source: DataSource,
    data_source_metadata: dict[str, str],
    confidence: ConfidenceField,
    data_gaps_flagged: list[str],
    signoff_method: SignoffMethod,
    signoff_evidence_id: str,
    signoff_captured_at: datetime,
    signed_by: str,
    now: datetime,
    mandate_id: str | None = None,
    mandate_version: int = 1,
) -> tuple[InvestorContextProfile, MandateObject]:
    """Produce the canonical investor profile + mandate from cross-path active fields.

    `derive_bucket(risk_profile, time_horizon)` runs inside the
    `InvestorContextProfile` model validator, so every path lands on the
    same bucket assignment.
    """
    # InvestorContextProfile auto-derives `assigned_bucket` consistency.
    from artha.model_portfolio.buckets import derive_bucket

    profile = InvestorContextProfile(
        client_id=client_id,
        firm_id=firm_id,
        created_at=now,
        updated_at=now,
        risk_profile=risk_profile,
        time_horizon=time_horizon,
        wealth_tier=wealth_tier,
        assigned_bucket=derive_bucket(risk_profile, time_horizon),
        capacity_trajectory=capacity_trajectory,
        intermediary_present=intermediary_present,
        intermediary_metadata=intermediary_metadata,
        beneficiary_can_operate_current_structure=beneficiary_can_operate,
        beneficiary_metadata=beneficiary_metadata,
        data_source=data_source,
        data_source_metadata=data_source_metadata,
        data_gaps_flagged=list(data_gaps_flagged),
        confidence=confidence,
        dormant_layer=DormantI0Layer(),
        family_member_overrides=list(family_member_overrides),
    )

    mandate = MandateObject(
        mandate_id=mandate_id or f"mandate_{client_id}_{mandate_version}",
        client_id=client_id,
        firm_id=firm_id,
        version=mandate_version,
        created_at=now,
        effective_at=now,
        mandate_type=mandate_intake.mandate_type,
        asset_class_limits=mandate_intake.asset_class_limits,
        vehicle_limits=mandate_intake.vehicle_limits,
        sub_asset_class_limits=mandate_intake.sub_asset_class_limits,
        sector_exclusions=list(mandate_intake.sector_exclusions),
        sector_hard_blocks=list(mandate_intake.sector_hard_blocks),
        concentration_limits=mandate_intake.concentration_limits,
        liquidity_floor=mandate_intake.liquidity_floor,
        liquidity_windows=list(mandate_intake.liquidity_windows),
        thematic_preferences=dict(mandate_intake.thematic_preferences),
        family_overrides=list(mandate_intake.family_overrides),
        signoff_method=signoff_method,
        signoff_evidence=SignoffEvidence(
            evidence_id=signoff_evidence_id,
            captured_at=signoff_captured_at,
        ),
        signed_by=signed_by,
    )
    return profile, mandate


def detect_conflicts_against_model(
    profile: InvestorContextProfile,
    mandate: MandateObject,
    model: ModelPortfolioObject | None,
) -> list[OnboardingConflictItem]:
    """Wrap `check_conflicts_at_activation` into the onboarding-shaped item list.

    Returns `[]` when no model is supplied (caller will skip the conflict
    surfacing step).
    """
    if model is None:
        return []
    raw: list[ConflictReport] = check_conflicts_at_activation(profile, mandate, model)
    out: list[OnboardingConflictItem] = []
    for c in raw:
        mandate_value = (
            float(c.mandate_value) if isinstance(c.mandate_value, (int, float)) else None
        )
        model_value = (
            float(c.model_value) if isinstance(c.model_value, (int, float)) else None
        )
        out.append(
            OnboardingConflictItem(
                dimension=c.dimension,
                mandate_value=mandate_value,
                model_value=model_value,
                description=(
                    f"{c.conflict_type.value}: mandate={c.mandate_value} "
                    f"model={c.model_value}"
                ),
            )
        )
    return out


async def emit_activation_event(
    *,
    repo: Any,
    onboarding_id: str,
    client_id: str,
    firm_id: str,
    advisor_id: str,
    profile: InvestorContextProfile,
    mandate: MandateObject,
    confirmation_method: ConfirmationMethod,
    confirmed_at: datetime,
    conflict_resolution_path: str | None = None,
    case_id: str | None = None,
) -> str:
    """Append the T1 `INVESTOR_ACTIVATED` event. Returns its event_id.

    `repo` is duck-typed to the T1Repository protocol — anything with
    `async def append(event)`. Tests can supply an in-memory recorder.
    """
    from artha.accountability.t1.models import T1Event

    payload = {
        "onboarding_id": onboarding_id,
        "confirmation_method": confirmation_method.value,
        "confirmed_at": confirmed_at.isoformat(),
        "client_id": client_id,
        "firm_id": firm_id,
        "advisor_id": advisor_id,
        "investor_context_profile": profile.model_dump(mode="json"),
        "mandate_object": mandate.model_dump(mode="json"),
        "bucket_assigned": profile.assigned_bucket.value,
        "conflict_resolution_path": conflict_resolution_path,
    }
    event = T1Event(
        event_type=T1EventType.INVESTOR_ACTIVATED,
        timestamp=confirmed_at,
        firm_id=firm_id,
        case_id=case_id,
        client_id=client_id,
        advisor_id=advisor_id,
        payload=payload,
        payload_hash=payload_hash(payload),
    )
    appended = await repo.append(event)
    return appended.event_id


__all__ = [
    "OnboardingError",
    "build_canonical_objects",
    "detect_conflicts_against_model",
    "emit_activation_event",
]
