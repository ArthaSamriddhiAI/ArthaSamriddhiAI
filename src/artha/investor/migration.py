"""Migrate pre-consolidation investor data into the canonical InvestorContextProfile.

The legacy investor stack stores three concerns separately: identity (`InvestorRow`),
risk profile (`InvestorRiskProfileRow` + `RiskConstraints`), and per-investor mandate
keys (`InvestorMandateRow`). The canonical profile (Section 6.4) folds the active
fields into a single object with explicit risk_profile, time_horizon, wealth_tier,
and three structural flags.

The legacy RiskCategory has five values (CONSERVATIVE, MODERATELY_CONSERVATIVE,
MODERATE, MODERATELY_AGGRESSIVE, AGGRESSIVE); the canonical RiskProfile has three.
We map the moderately-* values onto the closer pole. This is a deliberate
simplification per Section 6.1 — the active layer is reduced and the dormant
layer captures the deeper categorisation when activated.

Other canonical fields (capacity_trajectory, intermediary_present,
beneficiary_can_operate_current_structure) have no legacy equivalent. We default
them to the safest values (STABLE_OR_GROWING, False, True) and leave a
`data_gaps_flagged` entry naming each field so the advisor reviews and confirms
before activation.
"""

from __future__ import annotations

from datetime import datetime

from artha.canonical.investor import (
    DataSource,
    DormantLayerStub,
    InvestorContextProfile,
)
from artha.common.types import (
    Bucket,
    CapacityTrajectory,
    RiskProfile,
    TimeHorizon,
    WealthTier,
)
from artha.investor.schemas import RiskCategory
from artha.model_portfolio.buckets import derive_bucket

# ---------------------------------------------------------------------------
# Mapping tables: legacy → canonical
# ---------------------------------------------------------------------------

LEGACY_RISK_CATEGORY_MAP: dict[RiskCategory, RiskProfile] = {
    # Section 6.1 — active layer carries three risk profiles. The
    # MODERATELY_* legacy values fold onto the closer canonical pole. T2
    # outcome data over MVP can refine this at activation time.
    RiskCategory.CONSERVATIVE: RiskProfile.CONSERVATIVE,
    RiskCategory.MODERATELY_CONSERVATIVE: RiskProfile.CONSERVATIVE,
    RiskCategory.MODERATE: RiskProfile.MODERATE,
    RiskCategory.MODERATELY_AGGRESSIVE: RiskProfile.AGGRESSIVE,
    RiskCategory.AGGRESSIVE: RiskProfile.AGGRESSIVE,
}


LEGACY_HORIZON_STRING_MAP: dict[str, TimeHorizon] = {
    # The legacy `RiskConstraints.investment_horizon` is a free-form string
    # carrying "short" / "medium" / "long". The canonical TimeHorizon adds
    # the explicit "_term" suffix per Section 3.4.
    "short": TimeHorizon.SHORT_TERM,
    "medium": TimeHorizon.MEDIUM_TERM,
    "long": TimeHorizon.LONG_TERM,
}


# Fields whose values cannot be inferred from legacy data and are defaulted to
# the safest option. The advisor must review and confirm each before the
# canonical profile is considered fully populated.
DEFAULTED_FROM_LEGACY: tuple[str, ...] = (
    "wealth_tier",
    "capacity_trajectory",
    "intermediary_present",
    "beneficiary_can_operate_current_structure",
)


def map_legacy_risk_category(legacy: RiskCategory) -> RiskProfile:
    """Map a 5-tier legacy risk category to a 3-tier canonical risk profile."""
    return LEGACY_RISK_CATEGORY_MAP[legacy]


def map_legacy_horizon(legacy_horizon: str) -> TimeHorizon:
    """Parse a legacy `RiskConstraints.investment_horizon` string.

    Raises if the string is not one of "short" / "medium" / "long" (case-insensitive).
    """
    key = legacy_horizon.strip().lower()
    if key not in LEGACY_HORIZON_STRING_MAP:
        raise ValueError(
            f"unknown legacy horizon string {legacy_horizon!r}; "
            f"expected one of {sorted(LEGACY_HORIZON_STRING_MAP)}"
        )
    return LEGACY_HORIZON_STRING_MAP[key]


# ---------------------------------------------------------------------------
# Projection helper
# ---------------------------------------------------------------------------


def migrate_legacy_investor(
    *,
    client_id: str,
    firm_id: str,
    legacy_risk_category: RiskCategory,
    legacy_horizon: str,
    created_at: datetime,
    updated_at: datetime,
    wealth_tier: WealthTier = WealthTier.UP_TO_25K_SIP,
    capacity_trajectory: CapacityTrajectory = CapacityTrajectory.STABLE_OR_GROWING,
    intermediary_present: bool = False,
    beneficiary_can_operate_current_structure: bool = True,
    data_source: DataSource = DataSource.FORM,
    data_source_metadata: dict | None = None,
    version: int = 1,
) -> InvestorContextProfile:
    """Project legacy investor + risk profile data onto a canonical profile.

    The mandatory mapping (legacy_risk_category → risk_profile, legacy_horizon →
    time_horizon) is deterministic. The other active fields default to the
    safest value and are flagged in `data_gaps_flagged` so the advisor reviews
    and confirms before treating the canonical profile as fully populated.

    Returns a profile with `dormant_layer.active=False` per Section 6.5.
    Activation of dormant fields is a separate, governed event and not part of
    migration.
    """
    risk_profile = map_legacy_risk_category(legacy_risk_category)
    time_horizon = map_legacy_horizon(legacy_horizon)
    bucket: Bucket = derive_bucket(risk_profile, time_horizon)

    # Flag every active field that came from a default rather than legacy data,
    # so a human reviews. wealth_tier defaults to the smallest tier (safer for
    # eligibility filters — fewer accidental high-minimum-vehicle exposures).
    data_gaps_flagged: list[str] = list(DEFAULTED_FROM_LEGACY)

    return InvestorContextProfile(
        client_id=client_id,
        firm_id=firm_id,
        created_at=created_at,
        updated_at=updated_at,
        version=version,
        risk_profile=risk_profile,
        time_horizon=time_horizon,
        wealth_tier=wealth_tier,
        assigned_bucket=bucket,
        capacity_trajectory=capacity_trajectory,
        intermediary_present=intermediary_present,
        beneficiary_can_operate_current_structure=beneficiary_can_operate_current_structure,
        data_source=data_source,
        data_source_metadata=data_source_metadata or {"migration": "legacy_v1"},
        data_gaps_flagged=data_gaps_flagged,
        confidence=0.7,  # migrated profile has moderate confidence until advisor confirms
        dormant_layer=DormantLayerStub(active=False),
    )
