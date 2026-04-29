"""Pass 2 test fixtures — 9-bucket model portfolios + sample family-office mandate.

Imported by tests; not auto-collected by pytest (no `test_` prefix).

The 9-bucket sweep gives every Section 5.4 bucket a complete L1 allocation that
sums to 1.0 and validates against the canonical `ModelPortfolioObject`. One
bucket (MOD_LT) is built up to L2 + L3 to exercise the deeper sum validators.
The family-office fixture covers the Section 15.4 mandate with member overrides.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from artha.canonical import (
    AssetClassLimits,
    ConcentrationLimits,
    ConstructionContext,
    CounterfactualSupport,
    ExpectedReturnProfile,
    FamilyMemberOverrideMandate,
    LiquidityWindow,
    MandateObject,
    ModelPortfolioObject,
    SignoffEvidence,
    SignoffMethod,
    TargetWithTolerance,
    VehicleLimits,
)
from artha.common.types import (
    AssetClass,
    Bucket,
    MandateType,
    VehicleType,
)
from artha.model_portfolio.buckets import bucket_components

# ---------------------------------------------------------------------------
# 9-bucket L1 allocation matrix
# ---------------------------------------------------------------------------
# Each row sums to 1.0. Risk profile drives the equity/debt mix; horizon shifts
# within the row (longer horizon → more equity, shorter → more debt).
# Commodities and real_assets stay roughly flat across the matrix; their
# exact split is illustrative, not a firm view.

_L1_TARGETS_BY_BUCKET: dict[Bucket, dict[AssetClass, tuple[float, float]]] = {
    # bucket : { asset_class : (target, tolerance_band) }
    Bucket.AGG_ST: {
        AssetClass.EQUITY: (0.70, 0.07),
        AssetClass.DEBT: (0.25, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.03, 0.02),
        AssetClass.REAL_ASSETS: (0.02, 0.02),
    },
    Bucket.AGG_MT: {
        AssetClass.EQUITY: (0.75, 0.07),
        AssetClass.DEBT: (0.20, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.03, 0.02),
        AssetClass.REAL_ASSETS: (0.02, 0.02),
    },
    Bucket.AGG_LT: {
        AssetClass.EQUITY: (0.80, 0.07),
        AssetClass.DEBT: (0.15, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.03, 0.02),
        AssetClass.REAL_ASSETS: (0.02, 0.02),
    },
    Bucket.MOD_ST: {
        AssetClass.EQUITY: (0.50, 0.05),
        AssetClass.DEBT: (0.40, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.07, 0.02),
        AssetClass.REAL_ASSETS: (0.03, 0.02),
    },
    Bucket.MOD_MT: {
        AssetClass.EQUITY: (0.60, 0.05),
        AssetClass.DEBT: (0.30, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.07, 0.02),
        AssetClass.REAL_ASSETS: (0.03, 0.02),
    },
    Bucket.MOD_LT: {
        AssetClass.EQUITY: (0.60, 0.05),
        AssetClass.DEBT: (0.30, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.07, 0.02),
        AssetClass.REAL_ASSETS: (0.03, 0.02),
    },
    Bucket.CON_ST: {
        AssetClass.EQUITY: (0.20, 0.03),
        AssetClass.DEBT: (0.70, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.07, 0.02),
        AssetClass.REAL_ASSETS: (0.03, 0.02),
    },
    Bucket.CON_MT: {
        AssetClass.EQUITY: (0.30, 0.03),
        AssetClass.DEBT: (0.60, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.07, 0.02),
        AssetClass.REAL_ASSETS: (0.03, 0.02),
    },
    Bucket.CON_LT: {
        AssetClass.EQUITY: (0.35, 0.03),
        AssetClass.DEBT: (0.55, 0.05),
        AssetClass.GOLD_COMMODITIES: (0.07, 0.02),
        AssetClass.REAL_ASSETS: (0.03, 0.02),
    },
}


# Section 5.3.2 example for MOD_LT — equity vehicle mix
_MOD_LT_L2_EQUITY: dict[VehicleType, tuple[float, float]] = {
    VehicleType.DIRECT_EQUITY: (0.10, 0.10),
    VehicleType.MUTUAL_FUND: (0.40, 0.10),  # mf_active in spec terms
    VehicleType.PMS: (0.25, 0.10),
    VehicleType.AIF_CAT_3: (0.05, 0.05),
    VehicleType.SIF: (0.00, 0.05),
    VehicleType.UNLISTED_EQUITY: (0.00, 0.05),
    # mf_passive_etf folded into MUTUAL_FUND for now; Section 5.3.2 distinguishes
    # active vs passive at L2 sub-level. Pass 3 may split.
    # Allocate the remaining 20% to a passive bucket via "DIRECT_EQUITY" tweaked above.
}
# Adjust to sum to 1.0: use mf_passive 0.20 by widening MUTUAL_FUND to 0.60.
_MOD_LT_L2_EQUITY[VehicleType.MUTUAL_FUND] = (0.60, 0.10)
# Sum: 0.10 + 0.60 + 0.25 + 0.05 + 0.00 + 0.00 = 1.00


# Section 5.3.3 example for MOD_LT equity → MF active sub-asset-class mix
# Cell key is "asset_class.vehicle_type" composite per ModelPortfolioObject.l3_targets.
_MOD_LT_L3_EQUITY_MF: dict[str, tuple[float, float]] = {
    "large_cap": (0.30, 0.15),
    "mid_cap": (0.20, 0.15),
    "small_cap": (0.15, 0.15),
    "multi_cap": (0.30, 0.15),
    "international": (0.05, 0.10),
}


def _twt(target: float, band: float) -> TargetWithTolerance:
    return TargetWithTolerance(target=target, tolerance_band=band)


def make_model_portfolio_for_bucket(
    bucket: Bucket,
    *,
    firm_id: str = "firm_test",
    version: str = "1.0.0",
    effective_at: datetime | None = None,
    include_l2_l3_mod_lt: bool = True,
) -> ModelPortfolioObject:
    """Construct a canonical model portfolio for `bucket` with the matrix above.

    For MOD_LT specifically, an L2 equity vehicle mix and an L3 mf-active
    sub-asset-class mix are populated when `include_l2_l3_mod_lt=True`. Other
    buckets carry L1 only.
    """
    risk_profile, time_horizon = bucket_components(bucket)
    eff = effective_at or datetime(2026, 1, 1, tzinfo=UTC)

    l1 = {
        ac: _twt(target, band)
        for ac, (target, band) in _L1_TARGETS_BY_BUCKET[bucket].items()
    }

    l2: dict[AssetClass, dict[VehicleType, TargetWithTolerance]] = {}
    l3: dict[str, dict[str, TargetWithTolerance]] = {}
    if include_l2_l3_mod_lt and bucket == Bucket.MOD_LT:
        l2[AssetClass.EQUITY] = {
            v: _twt(t, b) for v, (t, b) in _MOD_LT_L2_EQUITY.items()
        }
        l3["equity.mutual_fund"] = {
            sub: _twt(t, b) for sub, (t, b) in _MOD_LT_L3_EQUITY_MF.items()
        }

    return ModelPortfolioObject(
        model_id=f"MP_{bucket.value}_{firm_id}",
        bucket=bucket,
        version=version,
        firm_id=firm_id,
        created_at=eff,
        effective_at=eff,
        approved_by="cio_test",
        approval_rationale=(
            f"Test fixture for bucket {bucket.value} "
            f"(risk={risk_profile.value}, horizon={time_horizon.value})."
        ),
        l1_targets=l1,
        l2_targets=l2,
        l3_targets=l3,
        construction=ConstructionContext(
            construction_pipeline_run_id="test_run_001",
            ic1_approval_id="test_ic1_001",
        ),
        counterfactual=CounterfactualSupport(
            expected_return_profile=[
                ExpectedReturnProfile(
                    period="1Y",
                    gross_return_estimate=0.13,
                    net_of_costs_estimate=0.115,
                ),
                ExpectedReturnProfile(
                    period="5Y",
                    gross_return_estimate=0.12,
                    net_of_costs_estimate=0.105,
                ),
            ],
        ),
    )


def make_all_bucket_portfolios(*, firm_id: str = "firm_test") -> dict[Bucket, ModelPortfolioObject]:
    """Return all nine canonical model portfolios for the 9-bucket sweep."""
    return {bucket: make_model_portfolio_for_bucket(bucket, firm_id=firm_id) for bucket in Bucket}


# ---------------------------------------------------------------------------
# Family office mandate fixture
# ---------------------------------------------------------------------------


def make_family_office_mandate(
    *,
    client_id: str = "family_office_test",
    firm_id: str = "firm_test",
) -> MandateObject:
    """A complete family-office mandate exercising:

      * per-asset-class min/target/max bounds
      * per-vehicle limits (PMS allowed, AIF Cat II not)
      * a sector exclusion (tobacco) and a hard block (firearms)
      * concentration limits
      * a liquidity floor and one specific liquidity window
      * three family-member overrides (patriarch, son, daughter)
    """
    eff = datetime(2026, 1, 1, tzinfo=UTC)
    return MandateObject(
        mandate_id="MAND_FO_TEST_001",
        client_id=client_id,
        firm_id=firm_id,
        version=1,
        created_at=eff,
        effective_at=eff,
        mandate_type=MandateType.FAMILY_OFFICE,
        asset_class_limits={
            AssetClass.EQUITY: AssetClassLimits(min_pct=0.30, target_pct=0.55, max_pct=0.70),
            AssetClass.DEBT: AssetClassLimits(min_pct=0.20, target_pct=0.30, max_pct=0.50),
            AssetClass.GOLD_COMMODITIES: AssetClassLimits(
                min_pct=0.02, target_pct=0.07, max_pct=0.15
            ),
            AssetClass.REAL_ASSETS: AssetClassLimits(min_pct=0.0, target_pct=0.03, max_pct=0.10),
        },
        vehicle_limits={
            VehicleType.PMS: VehicleLimits(allowed=True, max_pct=0.30),
            VehicleType.AIF_CAT_2: VehicleLimits(allowed=False),
            VehicleType.AIF_CAT_3: VehicleLimits(allowed=True, max_pct=0.10),
            VehicleType.UNLISTED_EQUITY: VehicleLimits(allowed=True, max_pct=0.05),
        },
        sector_exclusions=["tobacco", "alcohol"],
        sector_hard_blocks=["firearms", "adult_entertainment"],
        concentration_limits=ConcentrationLimits(
            per_holding_max=0.10,
            per_manager_max=0.20,
            per_sector_max=0.30,
        ),
        liquidity_floor=0.10,  # 10% must be liquid
        liquidity_windows=[
            LiquidityWindow(by_date=date(2030, 6, 1), amount_inr=50_000_000.0),
        ],
        thematic_preferences={
            "esg_preference": "moderate",
            "infra_overweight": True,
        },
        family_overrides=[
            FamilyMemberOverrideMandate(
                member_id="member_patriarch",
                override_fields={
                    # patriarch is more conservative — tighten equity ceiling
                    "asset_class_limits.equity.max_pct": 0.55,
                },
            ),
            FamilyMemberOverrideMandate(
                member_id="member_son_aggressive",
                override_fields={
                    # son has higher risk tolerance — relax PMS cap
                    "vehicle_limits.pms.max_pct": 0.40,
                },
            ),
            FamilyMemberOverrideMandate(
                member_id="member_daughter_balanced",
                override_fields={
                    # daughter wants strict ESG — extend exclusions
                    "sector_exclusions_extra": ["coal", "oil_gas"],
                },
            ),
        ],
        signoff_method=SignoffMethod.IN_PERSON,
        signoff_evidence=SignoffEvidence(
            evidence_id="sig_test_001",
            captured_at=eff,
            storage_uri="s3://test-bucket/signoffs/sig_test_001.pdf",
        ),
        signed_by="patriarch_full_name",
    )
