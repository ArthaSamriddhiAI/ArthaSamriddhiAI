"""Section 8.5.2 — curated knowledge schemas backing M0.IndianContext.

Per Section 8.5.1 IndianContext is "an LLM with curated reference data; it does
not freelance on tax rates." This module defines the typed shapes of that
curated reference data so that:

  * Compliance and tax teams can populate them via versioned firm-managed snapshots
    (Pass 19 wires persistence; Pass 7 uses an in-memory default snapshot).
  * The IndianContext service can do deterministic lookups for standard scenarios
    and surface gaps explicitly when scenarios are out of coverage.
  * Replay reads the snapshot version captured at decision time (§3.7-style
    version pinning extends to curated knowledge per §8.5.7 staleness rules).

The schemas are intentionally narrow — what an Indian wealth platform routinely
references. Edge cases the firm encounters surface as `gap` flags from the service,
not as bespoke schema extensions.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import AssetClass, MandateType


class HoldingPeriodCategory(str, Enum):
    """Section 8.9.2 + Indian tax rules — short vs long-term classification."""

    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class ResidencyStatus(str, Enum):
    """Section 8.5.2 — relevant residency categories for tax + FEMA routing."""

    RESIDENT = "resident"
    NRI = "nri"
    OCI = "oci"
    PIO = "pio"


class GiftCityRoutingRequirement(str, Enum):
    """Section 8.5.2 GIFT city routing rules."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    UNAVAILABLE = "unavailable"


class StructureCompatibilityVerdict(str, Enum):
    """Section 8.5.2 structure compatibility matrix."""

    COMPATIBLE = "compatible"
    RESTRICTED = "restricted"
    REQUIRES_ADDITIONAL_KYC = "requires_additional_kyc"
    PROHIBITED = "prohibited"


# ===========================================================================
# Tax tables (Section 8.5.2 tax tables)
# ===========================================================================


class TaxRateRow(BaseModel):
    """A single (asset_class, holding_period, residency) tax-rate row.

    Rates are stored as fractions (0.10 = 10%). The presentation layer
    multiplies by 100 for percent display per Section 3.3.

    `applicable_from` / `applicable_until` define the row's validity window;
    historical case replay reads the row valid at decision time.
    """

    model_config = ConfigDict(extra="forbid")

    asset_class: AssetClass
    holding_period: HoldingPeriodCategory
    residency: ResidencyStatus
    base_rate: float
    surcharge: float = 0.0
    cess: float = 0.04  # standard 4% health & education cess
    applicable_from: date
    applicable_until: date | None = None
    citation: str  # e.g. "Income Tax Act 1961 Section 112A"
    notes: str = ""


class TaxTable(BaseModel):
    """Versioned snapshot of tax rates (Section 8.5.2).

    `fy_label` is the financial year identifier (e.g. "FY26-27").
    The IndianContext service uses `last_updated` to drive the staleness
    flag (default 30-day window per Section 8.5.4).
    """

    model_config = ConfigDict(extra="forbid")

    fy_label: str
    rates: list[TaxRateRow] = Field(default_factory=list)
    last_updated: date


# ===========================================================================
# Structure compatibility matrix (Section 8.5.2)
# ===========================================================================


class StructureCompatibilityRow(BaseModel):
    """Per (legal structure × product/vehicle) compatibility row."""

    model_config = ConfigDict(extra="forbid")

    structure_type: MandateType
    product_or_vehicle: str  # free-form: e.g. "pms", "aif_cat_2", "reit", "unlisted_equity"
    verdict: StructureCompatibilityVerdict
    citation: str
    notes: str = ""


class StructureCompatibilityMatrix(BaseModel):
    """Section 8.5.2 — structural compatibility matrix snapshot."""

    model_config = ConfigDict(extra="forbid")

    rows: list[StructureCompatibilityRow] = Field(default_factory=list)
    last_updated: date


# ===========================================================================
# SEBI product boundaries (Section 8.5.2)
# ===========================================================================


class SebiProductRule(BaseModel):
    """A single SEBI rule constraining a product category."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str  # e.g. "SEBI_AIF_2012_REGULATION_2"
    product_category: str  # e.g. "aif_cat_2", "pms", "sif", "mf"
    rule_text: str
    minimum_ticket_size_inr: float | None = None
    maximum_concentration_pct: float | None = None
    documentation_required: list[str] = Field(default_factory=list)
    effective_from: date
    effective_until: date | None = None


class SebiProductRulesSet(BaseModel):
    """Section 8.5.2 — versioned snapshot of SEBI product rules."""

    model_config = ConfigDict(extra="forbid")

    rules: list[SebiProductRule] = Field(default_factory=list)
    last_updated: date


# ===========================================================================
# GIFT city / IFSCA routing (Section 8.5.2)
# ===========================================================================


class GiftCityRoutingRule(BaseModel):
    """Per (residency × product domicile × route) routing rule."""

    model_config = ConfigDict(extra="forbid")

    residency: ResidencyStatus
    product_domicile: str  # e.g. "indian", "us", "uae"
    route: str  # e.g. "direct", "gift_city", "lrs"
    requirement: GiftCityRoutingRequirement
    citation: str = ""
    notes: str = ""


class GiftCityRoutingRulesSet(BaseModel):
    """Section 8.5.2 — versioned snapshot of GIFT city / IFSCA routing rules."""

    model_config = ConfigDict(extra="forbid")

    rules: list[GiftCityRoutingRule] = Field(default_factory=list)
    last_updated: date


# ===========================================================================
# Demat / non-demat mechanics (Section 8.5.2)
# ===========================================================================


class DematMechanicsRule(BaseModel):
    """Per-vehicle settlement / NAV / redemption mechanics."""

    model_config = ConfigDict(extra="forbid")

    vehicle_type: str  # "mutual_fund_demat", "mutual_fund_non_demat", "pms", etc.
    redemption_settlement_days: int
    nav_booking_convention: str  # "cut_off_2pm" / "cut_off_3pm" / etc.
    notes: str = ""


class DematMechanicsRulesSet(BaseModel):
    """Section 8.5.2 — versioned snapshot of demat/non-demat mechanics rules."""

    model_config = ConfigDict(extra="forbid")

    rules: list[DematMechanicsRule] = Field(default_factory=list)
    last_updated: date


# ===========================================================================
# Recent regulatory changes (Section 8.5.2)
# ===========================================================================


class RegulatoryChangelogEntry(BaseModel):
    """A single regulatory update with effective date.

    Section 8.5.4 — IndianContext flags scenarios with `staleness_warning` when
    the changelog is older than 7 days from the decision date.
    """

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    title: str
    description: str
    affected_categories: list[str] = Field(default_factory=list)
    effective_from: date
    effective_until: date | None = None
    citation: str = ""


class RegulatoryChangelog(BaseModel):
    """Section 8.5.2 — versioned regulatory changelog."""

    model_config = ConfigDict(extra="forbid")

    entries: list[RegulatoryChangelogEntry] = Field(default_factory=list)
    last_updated: date


# ===========================================================================
# Aggregated curated knowledge snapshot
# ===========================================================================


class CuratedKnowledgeSnapshot(BaseModel):
    """A versioned bundle of all curated knowledge IndianContext reads (Section 8.5.2).

    Pass 19 (persistence) wires snapshots to a Git-versioned registry. For Pass 7
    the in-memory default snapshot in `m0.curated_knowledge` is the substrate.
    Replay pins `snapshot_version` so the historical state is reconstructable.
    """

    model_config = ConfigDict(extra="forbid")

    snapshot_version: str  # e.g. "2026.04.1"
    tax_table: TaxTable
    structure_compatibility: StructureCompatibilityMatrix
    sebi_rules: SebiProductRulesSet
    gift_city_rules: GiftCityRoutingRulesSet
    demat_mechanics: DematMechanicsRulesSet
    regulatory_changelog: RegulatoryChangelog
    last_updated: date
