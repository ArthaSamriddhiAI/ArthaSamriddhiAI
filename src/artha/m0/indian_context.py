"""Section 8.5 — M0.IndianContext: deterministic cross-cutting reasoner.

Per Section 8.5.1 IndianContext is "an LLM with curated reference data; it does
not freelance on tax rates." Pass 7 ships the deterministic-lookup half of that
contract: given a query and a curated knowledge snapshot, the service does
table-driven lookups, cites every source, and flags gaps explicitly. The LLM
overlay (for nuanced reasoning over the same tables) is a Phase D refinement.

Discipline per Section 8.5.4:
  * Never invent a rate — return base_rate=None with a `tax_table_no_match` flag.
  * Always cite the source rule / table / changelog entry.
  * Flag staleness when tax_table > 30 days old or changelog > 7 days old.
  * Flag conflicts when two rules would apply.

Staleness windows (Section 8.5.4):
  * Tax tables — 30 days
  * Regulatory changelog — 7 days
  * Other tables — 30 days as a sensible default
"""

from __future__ import annotations

from datetime import date

from artha.canonical.curated_knowledge import (
    CuratedKnowledgeSnapshot,
    GiftCityRoutingRequirement,
    HoldingPeriodCategory,
    StructureCompatibilityVerdict,
)
from artha.canonical.m0_indian_context import (
    M0IndianContextQuery,
    M0IndianContextResponse,
    RegulatoryRouting,
    StructuralCompatibility,
    TaxTreatment,
)
from artha.common.types import SourceCitation, SourceType

# Staleness windows per Section 8.5.4 (calendar days)
TAX_TABLE_STALE_DAYS = 30
REGULATORY_CHANGELOG_STALE_DAYS = 7
DEFAULT_STALE_DAYS = 30


class M0IndianContext:
    """Section 8.5 — deterministic curated-knowledge reasoner.

    Inject a `CuratedKnowledgeSnapshot` (defaults to the snapshot in
    `m0.curated_knowledge.make_default_snapshot()`); production firms supply
    their own. Same query + same snapshot ⇒ same response (Section 8.5.4
    determinism rule).
    """

    def __init__(self, snapshot: CuratedKnowledgeSnapshot) -> None:
        self._snapshot = snapshot

    def query(self, query: M0IndianContextQuery) -> M0IndianContextResponse:
        """Run all three reasoning categories and assemble the response."""
        cited: list[SourceCitation] = []
        flags: list[str] = []
        staleness: list[str] = []

        # ----- Tax treatment (Section 8.5.2 tax tables) -----
        tax_treatment = self._lookup_tax_treatment(query, cited, flags)
        self._flag_staleness(
            "tax_table",
            self._snapshot.tax_table.last_updated,
            query.as_of_date,
            TAX_TABLE_STALE_DAYS,
            staleness,
        )

        # ----- Structural compatibility (Section 8.5.2 structure matrix) -----
        structural = self._lookup_structural_compatibility(query, cited, flags)
        self._flag_staleness(
            "structure_compatibility",
            self._snapshot.structure_compatibility.last_updated,
            query.as_of_date,
            DEFAULT_STALE_DAYS,
            staleness,
        )

        # ----- Regulatory routing (GIFT + SEBI + FEMA) -----
        regulatory = self._lookup_regulatory_routing(query, cited, flags)
        self._flag_staleness(
            "regulatory_changelog",
            self._snapshot.regulatory_changelog.last_updated,
            query.as_of_date,
            REGULATORY_CHANGELOG_STALE_DAYS,
            staleness,
        )

        # Confidence summary: 1.0 minus 0.2 per flag, floored at 0.0.
        confidence = max(0.0, 1.0 - 0.2 * len(flags))

        return M0IndianContextResponse(
            tax_treatment=tax_treatment,
            structural_compatibility=structural,
            regulatory_routing=regulatory,
            flags=flags,
            cited_sources=cited,
            confidence=confidence,
            staleness_warnings=staleness,
            snapshot_version=self._snapshot.snapshot_version,
        )

    # -----------------------------------------------------------------------
    # Tax
    # -----------------------------------------------------------------------

    def _lookup_tax_treatment(
        self,
        query: M0IndianContextQuery,
        cited: list[SourceCitation],
        flags: list[str],
    ) -> TaxTreatment:
        if query.product_context.asset_class is None:
            flags.append("tax_table_no_match")
            return TaxTreatment(notes="asset_class missing in product_context")

        # Determine holding period — default to long_term if not provided
        period = query.holding_period or HoldingPeriodCategory.LONG_TERM
        residency = query.client_context.residency

        candidates = [
            r
            for r in self._snapshot.tax_table.rates
            if r.asset_class == query.product_context.asset_class
            and r.holding_period == period
            and r.residency == residency
            and r.applicable_from <= query.as_of_date
            and (r.applicable_until is None or r.applicable_until >= query.as_of_date)
        ]

        if not candidates:
            flags.append("tax_table_no_match")
            return TaxTreatment(
                notes=(
                    f"No tax rule for asset_class={query.product_context.asset_class.value}, "
                    f"period={period.value}, residency={residency.value} "
                    f"as of {query.as_of_date.isoformat()}"
                )
            )

        if len(candidates) > 1:
            flags.append("tax_rule_conflict")

        # Pick the most recently effective rule
        rule = max(candidates, key=lambda r: r.applicable_from)
        cited.append(
            SourceCitation(
                source_type=SourceType.TABLE,
                source_id=rule.citation,
                source_version=self._snapshot.tax_table.fy_label,
            )
        )

        effective = rule.base_rate * (1.0 + rule.surcharge) * (1.0 + rule.cess)
        return TaxTreatment(
            base_rate=rule.base_rate,
            surcharge=rule.surcharge,
            cess=rule.cess,
            effective_rate=effective,
            treaty_benefits_applicable=residency != _resident_value(),
            notes=rule.notes,
        )

    # -----------------------------------------------------------------------
    # Structural compatibility
    # -----------------------------------------------------------------------

    def _lookup_structural_compatibility(
        self,
        query: M0IndianContextQuery,
        cited: list[SourceCitation],
        flags: list[str],
    ) -> StructuralCompatibility:
        rows = self._snapshot.structure_compatibility.rows
        candidates = [
            r
            for r in rows
            if r.structure_type == query.client_context.structure_type
            and r.product_or_vehicle == query.product_context.product_type
        ]

        if not candidates:
            flags.append("structure_compatibility_no_match")
            return StructuralCompatibility(
                verdict=None,
                notes=(
                    f"No structure compatibility rule for "
                    f"{query.client_context.structure_type.value} × "
                    f"{query.product_context.product_type}"
                ),
            )

        # Pick the strictest verdict if multiple match
        strictness = {
            StructureCompatibilityVerdict.PROHIBITED: 4,
            StructureCompatibilityVerdict.RESTRICTED: 3,
            StructureCompatibilityVerdict.REQUIRES_ADDITIONAL_KYC: 2,
            StructureCompatibilityVerdict.COMPATIBLE: 1,
        }
        row = max(candidates, key=lambda r: strictness.get(r.verdict, 0))
        cited.append(
            SourceCitation(
                source_type=SourceType.TABLE,
                source_id=row.citation,
                source_version="structure_matrix",
            )
        )

        kyc_required: list[str] = []
        if row.verdict == StructureCompatibilityVerdict.REQUIRES_ADDITIONAL_KYC:
            kyc_required = [row.notes] if row.notes else ["additional KYC required"]

        return StructuralCompatibility(
            verdict=row.verdict,
            additional_kyc_required=kyc_required,
            notes=row.notes,
        )

    # -----------------------------------------------------------------------
    # Regulatory routing
    # -----------------------------------------------------------------------

    def _lookup_regulatory_routing(
        self,
        query: M0IndianContextQuery,
        cited: list[SourceCitation],
        flags: list[str],
    ) -> RegulatoryRouting:
        gift_required = self._lookup_gift_routing(query, cited)
        sebi_rules = self._lookup_sebi_rules(query, cited, flags)
        fema_implications = self._derive_fema_implications(query)

        return RegulatoryRouting(
            gift_city_required=gift_required,
            fema_implications=fema_implications,
            fatca_status=None,
            sebi_rules_applicable=[r.rule_id for r in sebi_rules],
            notes="",
        )

    def _lookup_gift_routing(
        self, query: M0IndianContextQuery, cited: list[SourceCitation]
    ) -> GiftCityRoutingRequirement | None:
        rules = self._snapshot.gift_city_rules.rules
        candidates = [
            r
            for r in rules
            if r.residency == query.client_context.residency
            and r.product_domicile == query.product_context.domicile
        ]
        if not candidates:
            return None
        # Most permissive route: prefer optional > required > unavailable for caller.
        # In practice we'll return the *first* matching rule's requirement —
        # the caller can drill down via cited_sources for nuance.
        rule = candidates[0]
        if rule.citation:
            cited.append(
                SourceCitation(
                    source_type=SourceType.RULE,
                    source_id=rule.citation,
                    source_version="gift_routing",
                )
            )
        return rule.requirement

    def _lookup_sebi_rules(
        self,
        query: M0IndianContextQuery,
        cited: list[SourceCitation],
        flags: list[str],
    ) -> list:
        rules = self._snapshot.sebi_rules.rules
        applicable = [
            r
            for r in rules
            if r.product_category == query.product_context.product_type
            and r.effective_from <= query.as_of_date
            and (r.effective_until is None or r.effective_until >= query.as_of_date)
        ]
        for r in applicable:
            cited.append(
                SourceCitation(
                    source_type=SourceType.RULE,
                    source_id=r.rule_id,
                    source_version="sebi",
                )
            )
        return applicable

    def _derive_fema_implications(
        self, query: M0IndianContextQuery
    ) -> list[str]:
        """Light heuristic: if cross-border element exists, surface FEMA flag."""
        residency = query.client_context.residency
        domicile = query.product_context.domicile
        implications: list[str] = []
        if residency != _resident_value():
            implications.append("nri_repatriation_rules_apply")
        if domicile != "indian":
            implications.append("foreign_remittance_compliance_required")
        if (
            query.client_context.nre_or_nro is not None
            and query.client_context.nre_or_nro.lower() == "nre"
        ):
            implications.append("nre_account_repatriable")
        return implications

    # -----------------------------------------------------------------------
    # Staleness
    # -----------------------------------------------------------------------

    @staticmethod
    def _flag_staleness(
        source_name: str,
        last_updated: date,
        as_of_date: date,
        window_days: int,
        out: list[str],
    ) -> None:
        delta = (as_of_date - last_updated).days
        if delta > window_days:
            out.append(f"{source_name}_stale_{delta}_days")


def _resident_value():
    """Lazy import to avoid circular reference."""
    from artha.canonical.curated_knowledge import ResidencyStatus
    return ResidencyStatus.RESIDENT
