"""Section 15.6.4 — M0.IndianContext canonical query schemas."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.curated_knowledge import (
    GiftCityRoutingRequirement,
    HoldingPeriodCategory,
    ResidencyStatus,
    StructureCompatibilityVerdict,
)
from artha.common.types import (
    AssetClass,
    ConfidenceField,
    MandateType,
    SourceCitation,
    VehicleType,
)


class IndianContextQueryType(str, Enum):
    """Section 8.5.2 — two modes per the spec."""

    INLINE = "inline"  # per-case during evidence agent activation
    BULK = "bulk"  # for Stitcher composition's India-context summary
    SCENARIO_SPECIFIC = "scenario_specific"  # one-off lookups


class M0IndianContextClientContext(BaseModel):
    """Per-case client metadata IndianContext consumes (Section 15.6.4)."""

    model_config = ConfigDict(extra="forbid")

    residency: ResidencyStatus = ResidencyStatus.RESIDENT
    structure_type: MandateType = MandateType.INDIVIDUAL
    nre_or_nro: str | None = None  # "nre" | "nro" | None for residents
    tax_status_notes: str = ""


class M0IndianContextProductContext(BaseModel):
    """Per-case product metadata (Section 15.6.4)."""

    model_config = ConfigDict(extra="forbid")

    product_type: str  # e.g. "aif_cat_2", "pms", "mf_active_demat", "reit"
    domicile: str = "indian"  # "indian" | "us" | "uae" | etc.
    vehicle: VehicleType | None = None
    asset_class: AssetClass | None = None


class M0IndianContextQuery(BaseModel):
    """Section 15.6.4 input envelope."""

    model_config = ConfigDict(extra="forbid")

    client_context: M0IndianContextClientContext
    product_context: M0IndianContextProductContext
    query_type: IndianContextQueryType = IndianContextQueryType.INLINE
    as_of_date: date
    holding_period: HoldingPeriodCategory | None = None  # short_term / long_term


class TaxTreatment(BaseModel):
    """Tax overlay output (Section 15.6.4)."""

    model_config = ConfigDict(extra="forbid")

    base_rate: float | None = None
    surcharge: float = 0.0
    cess: float = 0.0
    effective_rate: float | None = None  # base × (1 + surcharge) × (1 + cess), if computable
    treaty_benefits_applicable: bool = False
    notes: str = ""


class StructuralCompatibility(BaseModel):
    """Structure compatibility output (Section 15.6.4)."""

    model_config = ConfigDict(extra="forbid")

    verdict: StructureCompatibilityVerdict | None = None
    additional_kyc_required: list[str] = Field(default_factory=list)
    notes: str = ""


class RegulatoryRouting(BaseModel):
    """Regulatory / FEMA / GIFT routing output (Section 15.6.4)."""

    model_config = ConfigDict(extra="forbid")

    gift_city_required: GiftCityRoutingRequirement | None = None
    fema_implications: list[str] = Field(default_factory=list)
    fatca_status: str | None = None
    sebi_rules_applicable: list[str] = Field(default_factory=list)
    notes: str = ""


class M0IndianContextResponse(BaseModel):
    """Section 15.6.4 output envelope.

    `flags` carries gap signals like `tax_table_no_match`, `irreducible_ambiguity`.
    `staleness_warnings` flags any source older than its allowed window per
    Section 8.5.4.
    """

    model_config = ConfigDict(extra="forbid")

    tax_treatment: TaxTreatment = Field(default_factory=TaxTreatment)
    structural_compatibility: StructuralCompatibility = Field(
        default_factory=StructuralCompatibility
    )
    regulatory_routing: RegulatoryRouting = Field(default_factory=RegulatoryRouting)
    flags: list[str] = Field(default_factory=list)
    cited_sources: list[SourceCitation] = Field(default_factory=list)
    confidence: ConfidenceField = 1.0
    staleness_warnings: list[str] = Field(default_factory=list)
    snapshot_version: str = ""
