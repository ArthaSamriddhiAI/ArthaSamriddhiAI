"""Default curated-knowledge snapshot for M0.IndianContext.

Per Section 8.5.1 the curated tables are "maintained by the firm's compliance
and tax teams" — meaning the canonical source of truth is firm-managed data.
This module provides a sensible Indian-market default snapshot that:

  * Backs unit tests and demos
  * Serves as a reference shape for firms populating their own snapshot
  * Is intentionally conservative and incomplete; production firms override it

Pass 19 (persistence) wires firm-specific snapshots to a versioned registry.
For Pass 7, callers either use this default or pass their own
`CuratedKnowledgeSnapshot` directly to the service.
"""

from __future__ import annotations

from datetime import date

from artha.canonical.curated_knowledge import (
    CuratedKnowledgeSnapshot,
    DematMechanicsRule,
    DematMechanicsRulesSet,
    GiftCityRoutingRequirement,
    GiftCityRoutingRule,
    GiftCityRoutingRulesSet,
    HoldingPeriodCategory,
    RegulatoryChangelog,
    RegulatoryChangelogEntry,
    ResidencyStatus,
    SebiProductRule,
    SebiProductRulesSet,
    StructureCompatibilityMatrix,
    StructureCompatibilityRow,
    StructureCompatibilityVerdict,
    TaxRateRow,
    TaxTable,
)
from artha.common.types import AssetClass, MandateType


def _default_tax_table(today: date) -> TaxTable:
    """Indian equity / debt tax rates as of FY26-27, conservative defaults."""
    return TaxTable(
        fy_label="FY26-27",
        last_updated=today,
        rates=[
            # Equity LTCG (≥1 year) — 12.5% above ₹1.25L exemption (FY26-27 reform)
            TaxRateRow(
                asset_class=AssetClass.EQUITY,
                holding_period=HoldingPeriodCategory.LONG_TERM,
                residency=ResidencyStatus.RESIDENT,
                base_rate=0.125,
                surcharge=0.0,
                cess=0.04,
                applicable_from=date(2024, 7, 23),
                citation="Income Tax Act 1961 Section 112A (post-Budget-2024)",
            ),
            # Equity STCG (<1 year) — 20%
            TaxRateRow(
                asset_class=AssetClass.EQUITY,
                holding_period=HoldingPeriodCategory.SHORT_TERM,
                residency=ResidencyStatus.RESIDENT,
                base_rate=0.20,
                surcharge=0.0,
                cess=0.04,
                applicable_from=date(2024, 7, 23),
                citation="Income Tax Act 1961 Section 111A (post-Budget-2024)",
            ),
            # Debt LTCG (≥3 years) — slab rate without indexation; placeholder 30%
            TaxRateRow(
                asset_class=AssetClass.DEBT,
                holding_period=HoldingPeriodCategory.LONG_TERM,
                residency=ResidencyStatus.RESIDENT,
                base_rate=0.30,
                surcharge=0.0,
                cess=0.04,
                applicable_from=date(2023, 4, 1),
                citation="Income Tax Act 1961 Section 50AA",
                notes="Debt MFs (post-Apr-2023) taxed at slab rate; placeholder 30%",
            ),
            # Debt STCG — slab rate, placeholder 30%
            TaxRateRow(
                asset_class=AssetClass.DEBT,
                holding_period=HoldingPeriodCategory.SHORT_TERM,
                residency=ResidencyStatus.RESIDENT,
                base_rate=0.30,
                surcharge=0.0,
                cess=0.04,
                applicable_from=date(2023, 4, 1),
                citation="Income Tax Act 1961 Slab Rate",
            ),
            # NRI variants for equity LTCG — same base + treaty considerations
            TaxRateRow(
                asset_class=AssetClass.EQUITY,
                holding_period=HoldingPeriodCategory.LONG_TERM,
                residency=ResidencyStatus.NRI,
                base_rate=0.125,
                surcharge=0.10,  # placeholder: 10% surcharge for higher income brackets
                cess=0.04,
                applicable_from=date(2024, 7, 23),
                citation="Income Tax Act 1961 Section 112A",
                notes="Subject to DTAA between India and country of residence.",
            ),
        ],
    )


def _default_structure_compatibility(today: date) -> StructureCompatibilityMatrix:
    return StructureCompatibilityMatrix(
        last_updated=today,
        rows=[
            StructureCompatibilityRow(
                structure_type=MandateType.HUF,
                product_or_vehicle="pms",
                verdict=StructureCompatibilityVerdict.COMPATIBLE,
                citation="SEBI PMS Regulations 2020",
            ),
            StructureCompatibilityRow(
                structure_type=MandateType.HUF,
                product_or_vehicle="aif_cat_2",
                verdict=StructureCompatibilityVerdict.REQUIRES_ADDITIONAL_KYC,
                citation="SEBI AIF Regulations 2012; HUF subscription documents",
            ),
            StructureCompatibilityRow(
                structure_type=MandateType.TRUST,
                product_or_vehicle="aif_cat_2",
                verdict=StructureCompatibilityVerdict.COMPATIBLE,
                citation="SEBI AIF Regulations 2012",
            ),
            StructureCompatibilityRow(
                structure_type=MandateType.LLP,
                product_or_vehicle="aif_cat_2",
                verdict=StructureCompatibilityVerdict.COMPATIBLE,
                citation="SEBI AIF Regulations 2012",
            ),
            StructureCompatibilityRow(
                structure_type=MandateType.INDIVIDUAL,
                product_or_vehicle="reit",
                verdict=StructureCompatibilityVerdict.COMPATIBLE,
                citation="SEBI REIT Regulations 2014",
            ),
            StructureCompatibilityRow(
                structure_type=MandateType.INDIVIDUAL,
                product_or_vehicle="unlisted_equity",
                verdict=StructureCompatibilityVerdict.RESTRICTED,
                citation="SEBI Insider Trading + FEMA",
                notes="Direct unlisted equity requires accredited investor confirmation.",
            ),
        ],
    )


def _default_sebi_rules(today: date) -> SebiProductRulesSet:
    return SebiProductRulesSet(
        last_updated=today,
        rules=[
            SebiProductRule(
                rule_id="SEBI_PMS_MIN_TICKET",
                product_category="pms",
                rule_text="PMS minimum ticket size is ₹50 lakh per investor.",
                minimum_ticket_size_inr=50_00_000.0,
                effective_from=date(2020, 1, 21),
            ),
            SebiProductRule(
                rule_id="SEBI_AIF_CAT_2_MIN_TICKET",
                product_category="aif_cat_2",
                rule_text="AIF Cat II minimum ticket is ₹1 crore.",
                minimum_ticket_size_inr=1_00_00_000.0,
                effective_from=date(2012, 5, 21),
            ),
            SebiProductRule(
                rule_id="SEBI_AIF_CAT_3_MIN_TICKET",
                product_category="aif_cat_3",
                rule_text="AIF Cat III minimum ticket is ₹1 crore.",
                minimum_ticket_size_inr=1_00_00_000.0,
                effective_from=date(2012, 5, 21),
            ),
        ],
    )


def _default_gift_city_rules(today: date) -> GiftCityRoutingRulesSet:
    return GiftCityRoutingRulesSet(
        last_updated=today,
        rules=[
            GiftCityRoutingRule(
                residency=ResidencyStatus.RESIDENT,
                product_domicile="indian",
                route="direct",
                requirement=GiftCityRoutingRequirement.OPTIONAL,
                notes="Direct route is the default for resident Indians.",
            ),
            GiftCityRoutingRule(
                residency=ResidencyStatus.RESIDENT,
                product_domicile="us",
                route="lrs",
                requirement=GiftCityRoutingRequirement.REQUIRED,
                citation="RBI LRS scheme",
                notes="Liberalised Remittance Scheme up to USD 250k per FY.",
            ),
            GiftCityRoutingRule(
                residency=ResidencyStatus.NRI,
                product_domicile="indian",
                route="gift_city",
                requirement=GiftCityRoutingRequirement.OPTIONAL,
                notes="GIFT city offers tax-efficient access for NRI investors.",
            ),
            GiftCityRoutingRule(
                residency=ResidencyStatus.NRI,
                product_domicile="us",
                route="direct",
                requirement=GiftCityRoutingRequirement.UNAVAILABLE,
                notes=(
                    "NRI investors cannot directly access US-domiciled funds "
                    "without GIFT city or NRE/NRO routing."
                ),
            ),
        ],
    )


def _default_demat_mechanics(today: date) -> DematMechanicsRulesSet:
    return DematMechanicsRulesSet(
        last_updated=today,
        rules=[
            DematMechanicsRule(
                vehicle_type="mutual_fund_demat",
                redemption_settlement_days=2,
                nav_booking_convention="cut_off_3pm",
            ),
            DematMechanicsRule(
                vehicle_type="mutual_fund_non_demat",
                redemption_settlement_days=3,
                nav_booking_convention="cut_off_3pm",
            ),
            DematMechanicsRule(
                vehicle_type="pms",
                redemption_settlement_days=7,
                nav_booking_convention="end_of_day",
            ),
            DematMechanicsRule(
                vehicle_type="aif_cat_2",
                redemption_settlement_days=90,
                nav_booking_convention="quarterly",
                notes="AIF Cat II typically has gates and quarterly NAV strikes.",
            ),
        ],
    )


def _default_changelog(today: date) -> RegulatoryChangelog:
    return RegulatoryChangelog(
        last_updated=today,
        entries=[
            RegulatoryChangelogEntry(
                entry_id="CL_2024_07_LTCG_REFORM",
                title="LTCG / STCG harmonisation post-Budget-2024",
                description=(
                    "LTCG on equity raised to 12.5% with ₹1.25L exemption; STCG raised to 20%."
                ),
                affected_categories=["equity", "mutual_fund"],
                effective_from=date(2024, 7, 23),
                citation="Finance Act 2024",
            ),
        ],
    )


def make_default_snapshot(*, as_of: date | None = None) -> CuratedKnowledgeSnapshot:
    """Build the default curated knowledge snapshot.

    `as_of` controls the `last_updated` field on each sub-table; useful for
    tests that need a non-stale snapshot relative to the case's `as_of_date`.
    """
    today = as_of or date(2026, 4, 25)
    return CuratedKnowledgeSnapshot(
        snapshot_version="default-2026.04.1",
        last_updated=today,
        tax_table=_default_tax_table(today),
        structure_compatibility=_default_structure_compatibility(today),
        sebi_rules=_default_sebi_rules(today),
        gift_city_rules=_default_gift_city_rules(today),
        demat_mechanics=_default_demat_mechanics(today),
        regulatory_changelog=_default_changelog(today),
    )
