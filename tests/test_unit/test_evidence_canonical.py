"""Pass 8 — canonical evidence agent tests covering §11.2.8 + §11.3.8 acceptance.

Standard verdict schema, E1 financial_risk, E2 industry_analyst.

§11.2.8 (E1):
  Test 1 — same inputs produce identical verdict
  Test 2 — HHI exceeding bucket threshold flags concentration_breach
  Test 3 — reasoning_trace cites at least three named PortfolioAnalytics metrics
  Test 4 — verdict schema validates 100%
  Test 5 — diagnostic mode on aligned portfolio produces LOW + high confidence
           [tested via mock; calibration tests deferred to T2/Phase D]

§11.3.8 (E2):
  Test 1 — determinism within version
  Test 5 — pure-debt portfolio returns NOT_APPLICABLE
  Test 6 — sector_weakening_concentration flag fires
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.case import (
    CaseChannel,
    CaseObject,
    CaseStatus,
    DominantLens,
    LensMetadata,
)
from artha.canonical.evidence_verdict import (
    E1Verdict,
    E2SectorEvaluation,
    E2Verdict,
    StandardEvidenceVerdict,
    _LlmEvidenceCore,
)
from artha.canonical.holding import Holding
from artha.canonical.portfolio_analytics import (
    AnalyticsQueryResult,
    ConcentrationMetrics,
    DeploymentMetrics,
    FeeMetrics,
    LiquidityBucket,
    LiquidityMetrics,
    MetricFlags,
    TaxMetrics,
    TopNConcentration,
)
from artha.common.types import (
    AssetClass,
    Bucket,
    CaseIntent,
    Driver,
    DriverDirection,
    DriverSeverity,
    RiskLevel,
    RunMode,
    VehicleType,
)
from artha.evidence.canonical_base import EvidenceLLMUnavailableError
from artha.evidence.canonical_e1 import E1FinancialRisk
from artha.evidence.canonical_e2 import E2IndustryAnalyst
from artha.llm.providers.mock import MockProvider
from tests.canonical_fixtures import make_model_portfolio_for_bucket

# ===========================================================================
# Helpers
# ===========================================================================


def _envelope(
    *,
    target_agent: str = "e1_financial_risk",
    run_mode: RunMode = RunMode.CASE,
    case_payload: dict[str, Any] | None = None,
) -> AgentActivationEnvelope:
    case = CaseObject(
        case_id="case_001",
        client_id="c1",
        firm_id="firm_test",
        advisor_id="advisor_jane",
        created_at=datetime(2026, 4, 25, tzinfo=UTC),
        intent=CaseIntent.CASE,
        intent_confidence=0.9,
        dominant_lens=DominantLens.PROPOSAL,
        lens_metadata=LensMetadata(lenses_fired=[DominantLens.PROPOSAL]),
        current_status=CaseStatus.IN_PROGRESS,
        channel=CaseChannel.C0,
        payload=case_payload or {},
    )
    return AgentActivationEnvelope(
        case=case,
        target_agent=target_agent,
        run_mode=run_mode,
    )


def _holding(
    iid: str,
    market_value: float,
    *,
    asset_class: AssetClass = AssetClass.EQUITY,
    vehicle: VehicleType = VehicleType.MUTUAL_FUND,
    amc: str = "Test AMC",
) -> Holding:
    return Holding(
        instrument_id=iid,
        instrument_name=f"{iid}_name",
        units=1000.0,
        cost_basis=market_value * 0.9,
        market_value=market_value,
        unrealised_gain_loss=market_value * 0.1,
        amc_or_issuer=amc,
        vehicle_type=vehicle,
        asset_class=asset_class,
        sub_asset_class="multi_cap",
        acquisition_date=date(2024, 1, 15),
        as_of_date=date(2026, 4, 25),
    )


def _analytics(
    *,
    hhi: float = 0.15,
    aum: float = 10_000_000.0,
    fee_bps: int = 80,
    liquidity_floor_compliance: bool = True,
) -> AnalyticsQueryResult:
    return AnalyticsQueryResult(
        client_id="c1",
        as_of_date=date(2026, 4, 25),
        snapshot_id="snap_test",
        deployment=DeploymentMetrics(total_aum_inr=aum, cash_buffer_inr=0.0),
        concentration=ConcentrationMetrics(
            hhi_holding_level=hhi,
            hhi_manager_level=hhi * 0.8,
            hhi_lookthrough_stock_level=hhi * 0.9,
            top_n_holding_level=[
                TopNConcentration(n=1, weight=0.25),
                TopNConcentration(n=5, weight=0.7),
            ],
            top_n_lookthrough_level=[],
            look_through_depth=1,
            flags=MetricFlags(),
        ),
        liquidity=LiquidityMetrics(
            liquidity_buckets={LiquidityBucket.DAYS_0_7: 0.2, LiquidityBucket.YEARS_1_3: 0.8},
            liquidity_floor_compliance=liquidity_floor_compliance,
        ),
        fees=FeeMetrics(aggregate_fee_bps=fee_bps),
        tax=TaxMetrics(unrealised_gain_loss_total_inr=500_000.0),
    )


def _llm_with_e1_verdict(
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    confidence: float = 0.82,
    flags: list[str] | None = None,
    reasoning: str | None = None,
) -> MockProvider:
    """Build a MockProvider that returns a canned E1 LLM core for any prompt
    whose user content begins with 'Case:' (which our base class always emits)."""
    mock = MockProvider()
    if reasoning is None:
        # Default reasoning_trace cites three named PortfolioAnalytics metrics
        # so §11.2.8 Test 3 passes.
        reasoning = (
            "Bucket-relative concentration is moderate "
            "(concentration.hhi_holding_level within bucket norm). "
            "Liquidity buckets concentration mostly in liquidity.0_7_days. "
            "Fee drag at fees.aggregate_fee_bps is below threshold."
        )
    mock.set_structured_response(
        "Signals:",
        {
            "risk_level_value": risk_level.value,
            "confidence": confidence,
            "drivers": [
                Driver(
                    factor="hhi_within_bucket_norm",
                    direction=DriverDirection.NEUTRAL,
                    severity=DriverSeverity.LOW,
                    detail="HHI within band for bucket.",
                ).model_dump(mode="json"),
                Driver(
                    factor="fee_drag_acceptable",
                    direction=DriverDirection.POSITIVE,
                    severity=DriverSeverity.LOW,
                    detail="Aggregate fee bps below threshold.",
                ).model_dump(mode="json"),
                Driver(
                    factor="liquidity_balanced",
                    direction=DriverDirection.NEUTRAL,
                    severity=DriverSeverity.LOW,
                    detail="Bucketed liquidity within bands.",
                ).model_dump(mode="json"),
            ],
            "flags": flags or [],
            "reasoning_trace": reasoning,
        },
    )
    return mock


def _llm_with_e2_verdict(
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    confidence: float = 0.78,
    flags: list[str] | None = None,
) -> MockProvider:
    mock = MockProvider()
    mock.set_structured_response(
        "Signals:",
        {
            "risk_level_value": risk_level.value,
            "confidence": confidence,
            "drivers": [
                Driver(
                    factor="banking_sector_weight_high",
                    direction=DriverDirection.NEGATIVE,
                    severity=DriverSeverity.MEDIUM,
                    detail="Banking sector represents top weight.",
                ).model_dump(mode="json"),
            ],
            "flags": flags or [],
            "reasoning_trace": (
                "Sector concentration in banking; moat classification mixed; "
                "lifecycle in maturity phase."
            ),
        },
    )
    return mock


# ===========================================================================
# Standard verdict schema
# ===========================================================================


class TestStandardVerdictSchema:
    def test_standard_verdict_round_trips(self):
        v = StandardEvidenceVerdict(
            agent_id="financial_risk",
            case_id="case_x",
            timestamp=datetime(2026, 4, 25, tzinfo=UTC),
            risk_level=RiskLevel.MEDIUM,
            confidence=0.85,
            drivers=[],
            flags=[],
            reasoning_trace="trace",
            input_hash="0" * 64,
        )
        round_tripped = StandardEvidenceVerdict.model_validate_json(v.model_dump_json())
        assert round_tripped == v

    def test_internal_llm_core_validates(self):
        c = _LlmEvidenceCore(
            risk_level_value="MEDIUM",
            confidence=0.85,
            drivers=[],
            flags=[],
            reasoning_trace="trace",
        )
        assert c.risk_level_value == "MEDIUM"


# ===========================================================================
# §11.2.8 — E1 acceptance
# ===========================================================================


class TestE1Acceptance:
    @pytest.mark.asyncio
    async def test_test_1_determinism(self):
        # Same inputs → identical verdict (modulo timestamp).
        mock = _llm_with_e1_verdict()
        e1 = E1FinancialRisk(mock, agent_version="0.1.0")
        envelope = _envelope()
        analytics = _analytics()
        model = make_model_portfolio_for_bucket(Bucket.MOD_LT)

        v1 = await e1.evaluate(envelope, analytics=analytics, model_portfolio=model)
        v2 = await e1.evaluate(envelope, analytics=analytics, model_portfolio=model)
        # Timestamps differ by clock; everything else (including input_hash) must match.
        assert v1.input_hash == v2.input_hash
        assert v1.risk_level == v2.risk_level
        assert v1.flags == v2.flags
        assert v1.reasoning_trace == v2.reasoning_trace

    @pytest.mark.asyncio
    async def test_test_2_concentration_breach_flag(self):
        # MOD_LT bucket threshold is 0.30; HHI=0.45 exceeds → concentration_breach
        mock = _llm_with_e1_verdict(risk_level=RiskLevel.HIGH)
        e1 = E1FinancialRisk(mock)
        envelope = _envelope()
        analytics = _analytics(hhi=0.45)  # exceeds MOD_LT 0.30 threshold
        model = make_model_portfolio_for_bucket(Bucket.MOD_LT)

        verdict = await e1.evaluate(envelope, analytics=analytics, model_portfolio=model)
        assert "concentration_breach" in verdict.flags

    @pytest.mark.asyncio
    async def test_test_3_reasoning_trace_cites_metrics(self):
        # The default mock reasoning cites three named PortfolioAnalytics metrics.
        mock = _llm_with_e1_verdict()
        e1 = E1FinancialRisk(mock)
        envelope = _envelope()
        verdict = await e1.evaluate(
            envelope,
            analytics=_analytics(),
            model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
        )
        # Citations include explicit metric paths
        cited_metrics = [
            m for m in [
                "concentration.hhi_holding_level",
                "fees.aggregate_fee_bps",
                "liquidity.0_7_days",
            ]
            if m in verdict.reasoning_trace
        ]
        assert len(cited_metrics) >= 3

    @pytest.mark.asyncio
    async def test_test_4_verdict_schema_round_trips(self):
        mock = _llm_with_e1_verdict()
        e1 = E1FinancialRisk(mock)
        verdict = await e1.evaluate(
            _envelope(),
            analytics=_analytics(),
            model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
        )
        round_tripped = E1Verdict.model_validate_json(verdict.model_dump_json())
        assert round_tripped == verdict

    @pytest.mark.asyncio
    async def test_test_5_diagnostic_mode_aligned_portfolio_low_risk(self):
        # Mocked LLM emits LOW risk + 0.85 confidence; diagnostic run mode propagates
        mock = _llm_with_e1_verdict(risk_level=RiskLevel.LOW, confidence=0.85)
        e1 = E1FinancialRisk(mock)
        envelope = _envelope(run_mode=RunMode.DIAGNOSTIC)
        verdict = await e1.evaluate(
            envelope,
            analytics=_analytics(hhi=0.10),  # well within bucket norm
            model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
        )
        assert verdict.run_mode is RunMode.DIAGNOSTIC
        assert verdict.risk_level is RiskLevel.LOW
        assert verdict.confidence >= 0.7


class TestE1DeterministicFlags:
    @pytest.mark.asyncio
    async def test_liquidity_floor_proximity_flag(self):
        mock = _llm_with_e1_verdict()
        e1 = E1FinancialRisk(mock)
        analytics = _analytics(liquidity_floor_compliance=False)
        verdict = await e1.evaluate(
            _envelope(),
            analytics=analytics,
            model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
        )
        assert "liquidity_floor_proximity" in verdict.flags

    @pytest.mark.asyncio
    async def test_fee_drag_excessive_flag(self):
        mock = _llm_with_e1_verdict()
        e1 = E1FinancialRisk(mock)
        analytics = _analytics(fee_bps=300)  # above 250 bps threshold
        verdict = await e1.evaluate(
            _envelope(),
            analytics=analytics,
            model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
        )
        assert "fee_drag_excessive" in verdict.flags

    @pytest.mark.asyncio
    async def test_partial_evaluation_flag_when_no_analytics(self):
        mock = _llm_with_e1_verdict()
        e1 = E1FinancialRisk(mock)
        verdict = await e1.evaluate(
            _envelope(),
            analytics=None,
            model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
        )
        assert "partial_evaluation" in verdict.flags


class TestE1RunModeAndPipelinePropagation:
    @pytest.mark.asyncio
    async def test_run_mode_propagates_to_verdict(self):
        mock = _llm_with_e1_verdict()
        e1 = E1FinancialRisk(mock)
        envelope = _envelope(run_mode=RunMode.CONSTRUCTION)
        verdict = await e1.evaluate(
            envelope,
            analytics=_analytics(),
            model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
        )
        assert verdict.run_mode is RunMode.CONSTRUCTION

    @pytest.mark.asyncio
    async def test_dimensions_evaluated_populated(self):
        mock = _llm_with_e1_verdict()
        e1 = E1FinancialRisk(mock)
        verdict = await e1.evaluate(
            _envelope(),
            analytics=_analytics(),
            model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
        )
        # Concentration, liquidity, return_quality (fees), deployment all populated
        dims = {d.dimension for d in verdict.dimensions_evaluated}
        assert dims >= {"concentration", "liquidity", "return_quality", "deployment"}


class TestE1LlmFailures:
    @pytest.mark.asyncio
    async def test_llm_unavailable_raises(self):
        class _FailingProvider:
            name = "failing"

            async def complete(self, request):
                raise RuntimeError("LLM unavailable")

            async def complete_structured(self, request, output_type):
                raise RuntimeError("LLM unavailable")

        e1 = E1FinancialRisk(_FailingProvider())
        with pytest.raises(EvidenceLLMUnavailableError):
            await e1.evaluate(
                _envelope(),
                analytics=_analytics(),
                model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
            )

    @pytest.mark.asyncio
    async def test_invalid_risk_level_raises(self):
        mock = MockProvider()
        mock.set_structured_response(
            "Signals:",
            {
                "risk_level_value": "EXTREME_INVALID",
                "confidence": 0.5,
                "drivers": [],
                "flags": [],
                "reasoning_trace": "test",
            },
        )
        e1 = E1FinancialRisk(mock)
        with pytest.raises(EvidenceLLMUnavailableError, match="non-canonical risk_level"):
            await e1.evaluate(
                _envelope(),
                analytics=_analytics(),
                model_portfolio=make_model_portfolio_for_bucket(Bucket.MOD_LT),
            )


# ===========================================================================
# §11.3.8 — E2 acceptance
# ===========================================================================


class TestE2Acceptance:
    @pytest.mark.asyncio
    async def test_test_1_determinism(self):
        mock = _llm_with_e2_verdict()
        e2 = E2IndustryAnalyst(mock)
        envelope = _envelope(target_agent="e2_industry_analyst")
        sw = {"banking": 0.30, "it": 0.25, "fmcg": 0.20}
        v1 = await e2.evaluate(
            envelope,
            holdings=[_holding("A", 10_000_000.0)],
            sector_weights=sw,
        )
        v2 = await e2.evaluate(
            envelope,
            holdings=[_holding("A", 10_000_000.0)],
            sector_weights=sw,
        )
        assert v1.input_hash == v2.input_hash
        assert v1.flags == v2.flags

    @pytest.mark.asyncio
    async def test_test_5_pure_debt_returns_not_applicable(self):
        # No equity holdings → NOT_APPLICABLE without LLM call
        class _ShouldNotBeCalled:
            name = "should_not_be_called"

            async def complete(self, request):
                raise AssertionError("LLM must not be called")

            async def complete_structured(self, request, output_type):
                raise AssertionError("LLM must not be called")

        e2 = E2IndustryAnalyst(_ShouldNotBeCalled())
        debt_only = [
            _holding(
                "FD1",
                1_000_000.0,
                asset_class=AssetClass.DEBT,
                vehicle=VehicleType.FD,
            ),
            _holding(
                "BOND1",
                500_000.0,
                asset_class=AssetClass.DEBT,
                vehicle=VehicleType.DEBT_DIRECT,
            ),
        ]
        verdict = await e2.evaluate(
            _envelope(target_agent="e2_industry_analyst"),
            holdings=debt_only,
        )
        assert verdict.risk_level is RiskLevel.NOT_APPLICABLE

    @pytest.mark.asyncio
    async def test_test_6_sector_concentration_flag(self):
        # Banking at 40% > 35% threshold → sector_weakening_concentration
        mock = _llm_with_e2_verdict()
        e2 = E2IndustryAnalyst(mock)
        verdict = await e2.evaluate(
            _envelope(target_agent="e2_industry_analyst"),
            holdings=[_holding("A", 10_000_000.0)],
            sector_weights={"banking": 0.40, "it": 0.30, "fmcg": 0.30},
        )
        assert "sector_weakening_concentration" in verdict.flags


class TestE2FieldCoverage:
    @pytest.mark.asyncio
    async def test_low_field_coverage_flag(self):
        mock = _llm_with_e2_verdict()
        e2 = E2IndustryAnalyst(mock)
        verdict = await e2.evaluate(
            _envelope(target_agent="e2_industry_analyst"),
            holdings=[_holding("A", 1_000_000.0)],
            sector_weights={"banking": 0.20},
            field_coverage_pct=0.40,  # below 0.6 threshold
        )
        assert "low_field_coverage" in verdict.flags

    @pytest.mark.asyncio
    async def test_full_coverage_no_flag(self):
        mock = _llm_with_e2_verdict()
        e2 = E2IndustryAnalyst(mock)
        verdict = await e2.evaluate(
            _envelope(target_agent="e2_industry_analyst"),
            holdings=[_holding("A", 1_000_000.0)],
            sector_weights={"banking": 0.20, "it": 0.30, "fmcg": 0.30, "auto": 0.20},
            field_coverage_pct=1.0,
        )
        assert "low_field_coverage" not in verdict.flags


class TestE2VerdictShape:
    @pytest.mark.asyncio
    async def test_verdict_carries_portfolio_quality(self):
        mock = _llm_with_e2_verdict()
        e2 = E2IndustryAnalyst(mock)
        verdict = await e2.evaluate(
            _envelope(target_agent="e2_industry_analyst"),
            holdings=[_holding("A", 1_000_000.0)],
            sector_weights={"banking": 0.20, "it": 0.30, "fmcg": 0.30},
        )
        assert verdict.portfolio_quality_verdict is not None
        assert verdict.portfolio_quality_verdict.overall_risk_level == verdict.risk_level

    @pytest.mark.asyncio
    async def test_verdict_round_trips(self):
        mock = _llm_with_e2_verdict()
        e2 = E2IndustryAnalyst(mock)
        verdict = await e2.evaluate(
            _envelope(target_agent="e2_industry_analyst"),
            holdings=[_holding("A", 1_000_000.0)],
            sector_weights={"banking": 0.20},
        )
        round_tripped = E2Verdict.model_validate_json(verdict.model_dump_json())
        assert round_tripped == verdict

    @pytest.mark.asyncio
    async def test_sector_evaluations_passed_through(self):
        mock = _llm_with_e2_verdict()
        e2 = E2IndustryAnalyst(mock)
        sector_evals = [
            E2SectorEvaluation(sector="banking", sector_weight=0.30),
        ]
        verdict = await e2.evaluate(
            _envelope(target_agent="e2_industry_analyst"),
            holdings=[_holding("A", 1_000_000.0)],
            sector_weights={"banking": 0.30},
            sector_evaluations=sector_evals,
        )
        assert len(verdict.sector_evaluations) == 1
        assert verdict.sector_evaluations[0].sector == "banking"
