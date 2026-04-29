"""Pass 7 — M0.IndianContext tests against §8.5.8 acceptance.

Source citation completeness, no invention, staleness flagging, time-aware
correctness, determinism. Plus curated-knowledge default-snapshot validation.
"""

from __future__ import annotations

from datetime import date

import pytest

from artha.canonical.curated_knowledge import (
    GiftCityRoutingRequirement,
    HoldingPeriodCategory,
    ResidencyStatus,
    StructureCompatibilityVerdict,
)
from artha.canonical.m0_indian_context import (
    IndianContextQueryType,
    M0IndianContextClientContext,
    M0IndianContextProductContext,
    M0IndianContextQuery,
)
from artha.common.types import AssetClass, MandateType, VehicleType
from artha.m0.curated_knowledge import make_default_snapshot
from artha.m0.indian_context import (
    REGULATORY_CHANGELOG_STALE_DAYS,
    TAX_TABLE_STALE_DAYS,
    M0IndianContext,
)

_AS_OF = date(2026, 4, 25)


def _query(
    *,
    asset_class: AssetClass = AssetClass.EQUITY,
    holding_period: HoldingPeriodCategory = HoldingPeriodCategory.LONG_TERM,
    residency: ResidencyStatus = ResidencyStatus.RESIDENT,
    structure: MandateType = MandateType.INDIVIDUAL,
    product_type: str = "mutual_fund",
    domicile: str = "indian",
    as_of: date = _AS_OF,
) -> M0IndianContextQuery:
    return M0IndianContextQuery(
        client_context=M0IndianContextClientContext(
            residency=residency, structure_type=structure
        ),
        product_context=M0IndianContextProductContext(
            product_type=product_type,
            domicile=domicile,
            asset_class=asset_class,
            vehicle=VehicleType.MUTUAL_FUND,
        ),
        query_type=IndianContextQueryType.INLINE,
        as_of_date=as_of,
        holding_period=holding_period,
    )


# ===========================================================================
# §8.5.8 Test 1 — Source citation completeness
# ===========================================================================


class TestSourceCitation:
    def test_resident_equity_ltcg_cites_section_112a(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query())
        assert any("112A" in c.source_id for c in resp.cited_sources)

    def test_response_includes_snapshot_version(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query())
        assert resp.snapshot_version.startswith("default-")


# ===========================================================================
# §8.5.8 Test 2 — No invention (gap surfacing)
# ===========================================================================


class TestNoInvention:
    def test_unknown_asset_class_combination_flags_gap(self):
        # Default snapshot has no real_assets tax row; service must flag a gap
        # rather than guess a rate.
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query(asset_class=AssetClass.REAL_ASSETS))
        assert "tax_table_no_match" in resp.flags
        assert resp.tax_treatment.base_rate is None

    def test_unknown_structure_product_pair_flags_gap(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(
            _query(structure=MandateType.LVF, product_type="aif_cat_2")
        )
        assert "structure_compatibility_no_match" in resp.flags
        assert resp.structural_compatibility.verdict is None

    def test_confidence_decays_with_flag_count(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        # Combine two gap-triggering scenarios
        resp = ctx.query(
            _query(
                asset_class=AssetClass.REAL_ASSETS,
                structure=MandateType.LVF,
                product_type="aif_cat_2",
            )
        )
        # Two flags should drop confidence below 0.7
        assert resp.confidence < 0.7
        # And by the floor cap, never go negative
        assert resp.confidence >= 0.0


# ===========================================================================
# §8.5.8 Test 3 — Staleness flagging
# ===========================================================================


class TestStalenessFlag:
    def test_tax_table_stale_when_older_than_30_days(self):
        # Snapshot last updated 35 days before as_of_date → tax_table stale
        old = date(2026, 3, 21)  # 35 days before _AS_OF
        snapshot = make_default_snapshot(as_of=old)
        ctx = M0IndianContext(snapshot)
        resp = ctx.query(_query(as_of=_AS_OF))
        assert any(w.startswith("tax_table_stale_") for w in resp.staleness_warnings)

    def test_changelog_stale_when_older_than_7_days(self):
        old = date(2026, 4, 17)  # 8 days before _AS_OF
        snapshot = make_default_snapshot(as_of=old)
        ctx = M0IndianContext(snapshot)
        resp = ctx.query(_query(as_of=_AS_OF))
        assert any(
            w.startswith("regulatory_changelog_stale_")
            for w in resp.staleness_warnings
        )

    def test_no_staleness_when_fresh(self):
        snapshot = make_default_snapshot(as_of=_AS_OF)
        ctx = M0IndianContext(snapshot)
        resp = ctx.query(_query(as_of=_AS_OF))
        assert resp.staleness_warnings == []


# ===========================================================================
# §8.5.8 Test 4 — Time-aware correctness
# ===========================================================================


class TestTimeAware:
    def test_picks_rule_in_force_at_as_of_date(self):
        # The default snapshot has equity LTCG 12.5% effective from 2024-07-23.
        # Querying with as_of after that date returns the rule.
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query())
        assert resp.tax_treatment.base_rate == pytest.approx(0.125)

    def test_query_before_rule_effective_returns_no_match(self):
        # Querying with as_of=2024-01-01 (before 2024-07-23 rule) → no match
        ctx = M0IndianContext(make_default_snapshot(as_of=date(2024, 1, 1)))
        resp = ctx.query(_query(as_of=date(2024, 1, 1)))
        # No equity LTCG rule applies before 2024-07-23 in the default snapshot
        assert "tax_table_no_match" in resp.flags


# ===========================================================================
# §8.5.8 Test 5 — Determinism
# ===========================================================================


class TestDeterminism:
    def test_same_query_same_response(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        q = _query()
        a = ctx.query(q)
        b = ctx.query(q)
        assert a == b


# ===========================================================================
# Tax-treatment compute
# ===========================================================================


class TestTaxTreatmentCompute:
    def test_effective_rate_includes_cess(self):
        # base 0.125 with cess 0.04 → effective ~0.13
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query())
        assert resp.tax_treatment.effective_rate == pytest.approx(0.125 * 1.04)

    def test_nri_treaty_benefits_flagged(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query(residency=ResidencyStatus.NRI))
        assert resp.tax_treatment.treaty_benefits_applicable is True

    def test_resident_no_treaty_benefits(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query())
        assert resp.tax_treatment.treaty_benefits_applicable is False


# ===========================================================================
# Structural compatibility
# ===========================================================================


class TestStructuralCompatibility:
    def test_huf_pms_compatible(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query(structure=MandateType.HUF, product_type="pms"))
        assert (
            resp.structural_compatibility.verdict
            is StructureCompatibilityVerdict.COMPATIBLE
        )

    def test_huf_aif_cat_2_requires_kyc(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(
            _query(structure=MandateType.HUF, product_type="aif_cat_2")
        )
        assert (
            resp.structural_compatibility.verdict
            is StructureCompatibilityVerdict.REQUIRES_ADDITIONAL_KYC
        )
        assert len(resp.structural_compatibility.additional_kyc_required) > 0

    def test_individual_unlisted_equity_restricted(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(
            _query(
                structure=MandateType.INDIVIDUAL,
                product_type="unlisted_equity",
            )
        )
        assert (
            resp.structural_compatibility.verdict
            is StructureCompatibilityVerdict.RESTRICTED
        )


# ===========================================================================
# Regulatory routing (GIFT + FEMA + SEBI)
# ===========================================================================


class TestRegulatoryRouting:
    def test_resident_indian_product_optional_gift(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query())
        assert (
            resp.regulatory_routing.gift_city_required
            is GiftCityRoutingRequirement.OPTIONAL
        )

    def test_resident_us_product_requires_lrs(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query(domicile="us"))
        assert (
            resp.regulatory_routing.gift_city_required
            is GiftCityRoutingRequirement.REQUIRED
        )

    def test_nri_us_direct_unavailable(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(
            _query(residency=ResidencyStatus.NRI, domicile="us")
        )
        assert (
            resp.regulatory_routing.gift_city_required
            is GiftCityRoutingRequirement.UNAVAILABLE
        )

    def test_nri_carries_repatriation_implication(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query(residency=ResidencyStatus.NRI))
        assert "nri_repatriation_rules_apply" in resp.regulatory_routing.fema_implications

    def test_pms_query_returns_sebi_min_ticket_rule(self):
        ctx = M0IndianContext(make_default_snapshot(as_of=_AS_OF))
        resp = ctx.query(_query(product_type="pms"))
        assert "SEBI_PMS_MIN_TICKET" in resp.regulatory_routing.sebi_rules_applicable


# ===========================================================================
# Staleness window constants match spec
# ===========================================================================


def test_stale_window_constants():
    # Section 8.5.4 — tax tables 30 days; changelog 7 days
    assert TAX_TABLE_STALE_DAYS == 30
    assert REGULATORY_CHANGELOG_STALE_DAYS == 7
