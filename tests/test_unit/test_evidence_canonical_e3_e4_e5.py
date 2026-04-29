"""Pass 9 — E3 + E4 + E5 acceptance tests.

§11.4.8 (E3):
  Test 1 — determinism within version
  Test 3 — watch generation correctly opens an alert when probability is in
           the watch range and resolution_horizon is set
  Test 4 — watch metadata schema validates 100%

§11.5.8 (E4):
  Test 1 — new-client case produces verdict with limited_history flag and
           confidence at or below 0.5
  Test 2 — established-client case (5+ years, 50+ events) produces verdict
           with full confidence calibration and no limited_history flag
  Test 4 — determinism within version

§11.6.8 (E5):
  Test 1 — determinism
  Test 2 — holding with last-round mark from 18 months ago produces
           valuation_stale flag
  Test 4 — cases without unlisted holdings produce NOT_APPLICABLE
  Test 6 — exit pathway probabilities sum to 1.0 across pathways
"""

from __future__ import annotations

from datetime import UTC, date, datetime

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
    BehaviouralHistorySummary,
    ConfidenceBandLabel,
    E3Verdict,
    E5HoldingEvaluation,
    E5Verdict,
    MacroDimension,
    RegimeAssessment,
    WatchCandidate,
)
from artha.canonical.holding import Holding
from artha.common.types import (
    AssetClass,
    CaseIntent,
    Driver,
    DriverDirection,
    DriverSeverity,
    RiskLevel,
    RunMode,
    VehicleType,
)
from artha.evidence.canonical_base import EvidenceLLMUnavailableError
from artha.evidence.canonical_e3 import E3MacroPolicy, MacroSignals
from artha.evidence.canonical_e4 import (
    LIMITED_HISTORY_CONFIDENCE_CAP,
    E4BehaviouralHistorical,
)
from artha.evidence.canonical_e5 import E5UnlistedSpecialist, UnlistedDataSnapshot
from artha.llm.providers.mock import MockProvider

# ===========================================================================
# Helpers
# ===========================================================================


def _envelope(
    target_agent: str = "e3",
    run_mode: RunMode = RunMode.CASE,
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
    )
    return AgentActivationEnvelope(case=case, target_agent=target_agent, run_mode=run_mode)


def _holding(
    iid: str,
    market_value: float = 1_000_000.0,
    *,
    vehicle: VehicleType = VehicleType.MUTUAL_FUND,
    asset_class: AssetClass = AssetClass.EQUITY,
) -> Holding:
    return Holding(
        instrument_id=iid,
        instrument_name=f"{iid}_name",
        units=100.0,
        cost_basis=market_value * 0.9,
        market_value=market_value,
        unrealised_gain_loss=market_value * 0.1,
        amc_or_issuer="Test",
        vehicle_type=vehicle,
        asset_class=asset_class,
        sub_asset_class="multi_cap",
        acquisition_date=date(2024, 1, 15),
        as_of_date=date(2026, 4, 25),
    )


# ===========================================================================
# E3 — Macro & Policy
# ===========================================================================


def _e3_mock(
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    confidence: float = 0.78,
    watch_candidates: list[dict] | None = None,
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
                    factor="rate_cycle",
                    direction=DriverDirection.NEGATIVE,
                    severity=DriverSeverity.MEDIUM,
                    detail="Repo rate steady; cuts expected next quarter.",
                ).model_dump(mode="json"),
            ],
            "flags": flags or [],
            "reasoning_trace": (
                "RBI MPC cut expectations rising. CPI within tolerance band. "
                "Currency stable per RBI DBIE snapshot."
            ),
            "regime_assessments": [
                RegimeAssessment(
                    dimension=MacroDimension.RATE_ENVIRONMENT,
                    risk_level=risk_level,
                    confidence=confidence,
                    summary="Rate cuts expected in next MPC.",
                ).model_dump(mode="json"),
            ],
            "watch_candidates": watch_candidates or [],
        },
    )
    return mock


class TestE3Acceptance:
    @pytest.mark.asyncio
    async def test_test_1_determinism(self):
        e3 = E3MacroPolicy(_e3_mock())
        signals = MacroSignals(policy_rate=0.06, headline_cpi=0.048)
        v1 = await e3.evaluate(_envelope(), signals=signals)
        v2 = await e3.evaluate(_envelope(), signals=signals)
        assert v1.input_hash == v2.input_hash
        assert v1.flags == v2.flags
        assert v1.regime_assessments == v2.regime_assessments

    @pytest.mark.asyncio
    async def test_test_3_watch_generated_in_range(self):
        # Probability 0.55 sits in [0.40, 0.70] watch range
        watch_dict = WatchCandidate(
            dimension=MacroDimension.RATE_ENVIRONMENT,
            probability=0.55,
            confidence_band=ConfidenceBandLabel.MODERATE,
            resolution_horizon_days=90,
            impact_if_resolved="Rebalance debt allocation toward longer duration.",
        ).model_dump(mode="json")

        e3 = E3MacroPolicy(_e3_mock(watch_candidates=[watch_dict]))
        verdict = await e3.evaluate(_envelope(), signals=MacroSignals())
        assert len(verdict.watch_candidates) == 1
        assert verdict.watch_candidates[0].dimension is MacroDimension.RATE_ENVIRONMENT

    @pytest.mark.asyncio
    async def test_test_4_watch_metadata_schema_round_trips(self):
        watch_dict = WatchCandidate(
            dimension=MacroDimension.INFLATION,
            probability=0.50,
            confidence_band=ConfidenceBandLabel.LOW,
            resolution_horizon_days=60,
            impact_if_resolved="Cash buffer expansion of 200bps.",
        ).model_dump(mode="json")
        e3 = E3MacroPolicy(_e3_mock(watch_candidates=[watch_dict]))
        verdict = await e3.evaluate(_envelope(), signals=MacroSignals())
        round_tripped = E3Verdict.model_validate_json(verdict.model_dump_json())
        assert round_tripped == verdict

    @pytest.mark.asyncio
    async def test_out_of_range_watch_filtered_with_flag(self):
        # Probability 0.85 above the watch range — must-respond candidate
        watch_dict = WatchCandidate(
            dimension=MacroDimension.CURRENCY,
            probability=0.85,
            confidence_band=ConfidenceBandLabel.HIGH,
            resolution_horizon_days=30,
            impact_if_resolved="Reduce foreign currency exposure.",
        ).model_dump(mode="json")
        e3 = E3MacroPolicy(_e3_mock(watch_candidates=[watch_dict]))
        verdict = await e3.evaluate(_envelope(), signals=MacroSignals())
        # Watch is NOT included; flag surfaces calibration drift
        assert len(verdict.watch_candidates) == 0
        assert any(f.startswith("watch_probability_out_of_range_") for f in verdict.flags)

    @pytest.mark.asyncio
    async def test_no_signals_produces_partial_evaluation(self):
        e3 = E3MacroPolicy(_e3_mock())
        verdict = await e3.evaluate(_envelope(), signals=None)
        # The agent still emits a verdict via the LLM (mock returns the canned response)
        assert verdict.risk_level is RiskLevel.MEDIUM

    @pytest.mark.asyncio
    async def test_run_mode_propagates(self):
        e3 = E3MacroPolicy(_e3_mock())
        verdict = await e3.evaluate(
            _envelope(run_mode=RunMode.CONSTRUCTION),
            signals=MacroSignals(),
        )
        assert verdict.run_mode is RunMode.CONSTRUCTION

    @pytest.mark.asyncio
    async def test_llm_unavailable_raises(self):
        class _Failing:
            name = "failing"

            async def complete(self, request):
                raise RuntimeError("LLM unavailable")

            async def complete_structured(self, request, output_type):
                raise RuntimeError("LLM unavailable")

        e3 = E3MacroPolicy(_Failing())
        with pytest.raises(EvidenceLLMUnavailableError):
            await e3.evaluate(_envelope(), signals=MacroSignals())

    @pytest.mark.asyncio
    async def test_data_as_of_propagated(self):
        e3 = E3MacroPolicy(_e3_mock())
        signals = MacroSignals(data_as_of=date(2026, 4, 20))
        verdict = await e3.evaluate(_envelope(), signals=signals)
        assert verdict.data_as_of == date(2026, 4, 20)


# ===========================================================================
# E4 — Behavioural & Historical
# ===========================================================================


def _e4_mock(
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    confidence: float = 0.75,
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
                    factor="redemption_history",
                    direction=DriverDirection.NEGATIVE,
                    severity=DriverSeverity.MEDIUM,
                    detail="Two redemptions during 2022 drawdown.",
                ).model_dump(mode="json"),
            ],
            "flags": flags or [],
            "reasoning_trace": (
                "Reviewed 5 years of T1 history. Override pattern stable. "
                "Redemption frequency moderate. Horizon adherence within stated mandate."
            ),
        },
    )
    return mock


class TestE4Acceptance:
    @pytest.mark.asyncio
    async def test_test_1_new_client_no_history(self):
        # Event count below the no-history threshold (5)
        history = BehaviouralHistorySummary(
            historical_window_days=180, event_count=2
        )

        # LLM should NOT be called for no-history case
        class _Strict:
            name = "strict_no_call"

            async def complete(self, request):
                raise AssertionError("LLM must not be called for new clients")

            async def complete_structured(self, request, output_type):
                raise AssertionError("LLM must not be called for new clients")

        e4 = E4BehaviouralHistorical(_Strict())
        verdict = await e4.evaluate(_envelope(target_agent="e4"), history=history)
        assert "no_history" in verdict.flags
        assert verdict.confidence == 0.0
        assert verdict.historical_event_count == 2

    @pytest.mark.asyncio
    async def test_limited_history_caps_confidence(self):
        # 20 events — between no-history (5) and full-history (50)
        history = BehaviouralHistorySummary(
            historical_window_days=730, event_count=20
        )
        # LLM emits 0.85 confidence; the agent caps it to 0.5
        e4 = E4BehaviouralHistorical(_e4_mock(confidence=0.85))
        verdict = await e4.evaluate(_envelope(target_agent="e4"), history=history)
        assert "limited_history" in verdict.flags
        assert verdict.confidence <= LIMITED_HISTORY_CONFIDENCE_CAP

    @pytest.mark.asyncio
    async def test_test_2_established_client_full_confidence(self):
        history = BehaviouralHistorySummary(
            historical_window_days=1825,  # 5 years
            event_count=120,  # well above 50
        )
        e4 = E4BehaviouralHistorical(_e4_mock(confidence=0.85))
        verdict = await e4.evaluate(_envelope(target_agent="e4"), history=history)
        assert "limited_history" not in verdict.flags
        assert verdict.confidence == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_test_4_determinism(self):
        history = BehaviouralHistorySummary(
            historical_window_days=1825, event_count=120
        )
        e4 = E4BehaviouralHistorical(_e4_mock())
        v1 = await e4.evaluate(_envelope(target_agent="e4"), history=history)
        v2 = await e4.evaluate(_envelope(target_agent="e4"), history=history)
        assert v1.input_hash == v2.input_hash
        assert v1.flags == v2.flags

    @pytest.mark.asyncio
    async def test_redemption_volatility_flag(self):
        # 3 redemptions out of 4 occurred in drawdowns → volatile
        history = BehaviouralHistorySummary(
            historical_window_days=1825,
            event_count=100,
            redemption_count_total=4,
            redemption_count_in_drawdowns=3,
        )
        e4 = E4BehaviouralHistorical(_e4_mock())
        verdict = await e4.evaluate(_envelope(target_agent="e4"), history=history)
        assert "redemption_history_volatile" in verdict.flags

    @pytest.mark.asyncio
    async def test_verdict_carries_history_metadata(self):
        history = BehaviouralHistorySummary(
            historical_window_days=730, event_count=80
        )
        e4 = E4BehaviouralHistorical(_e4_mock())
        verdict = await e4.evaluate(_envelope(target_agent="e4"), history=history)
        assert verdict.historical_window_evaluated_days == 730
        assert verdict.historical_event_count == 80


# ===========================================================================
# E5 — Unlisted Specialist
# ===========================================================================


def _e5_mock(
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    confidence: float = 0.7,
    per_holding: list[dict] | None = None,
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
                    factor="exit_uncertainty",
                    direction=DriverDirection.NEGATIVE,
                    severity=DriverSeverity.HIGH,
                    detail="Pre-IPO; exit pathway uncertain.",
                ).model_dump(mode="json"),
            ],
            "flags": flags or [],
            "reasoning_trace": "Pre-IPO holding; last round 18mo old per Tracxn.",
            "per_holding_evaluations": per_holding or [],
        },
    )
    return mock


class TestE5Acceptance:
    @pytest.mark.asyncio
    async def test_test_4_no_unlisted_returns_not_applicable(self):
        # Mock that would crash if invoked — proves no LLM call
        class _Strict:
            name = "strict_no_call"

            async def complete(self, request):
                raise AssertionError("LLM must not be called when no unlisted holdings")

            async def complete_structured(self, request, output_type):
                raise AssertionError("LLM must not be called when no unlisted holdings")

        e5 = E5UnlistedSpecialist(_Strict())
        verdict = await e5.evaluate(
            _envelope(target_agent="e5"),
            holdings=[_holding("MF1")],  # equity MF, not unlisted
        )
        assert verdict.risk_level is RiskLevel.NOT_APPLICABLE

    @pytest.mark.asyncio
    async def test_test_2_18_month_valuation_flags_stale(self):
        # 18-month-old valuation → valuation_stale (>365 days)
        holdings = [_holding("UE1", vehicle=VehicleType.UNLISTED_EQUITY)]
        unlisted_data = UnlistedDataSnapshot(
            valuation_dates={"UE1": date(2024, 10, 25)},  # ~18 months before 2026-04-25
            valuation_basis={"UE1": "last_funding_round"},
            comparable_data_available={"UE1": True},
            valuation_data_as_of=date(2026, 4, 25),
        )
        per_holding = [
            E5HoldingEvaluation(
                holding_id="UE1",
                valuation_age_days=548,
                valuation_basis="last_funding_round",
                exit_pathway_probabilities={
                    "ipo": 0.4, "secondary": 0.3, "strategic": 0.2, "writeoff": 0.1,
                },
            ).model_dump(mode="json"),
        ]
        e5 = E5UnlistedSpecialist(_e5_mock(per_holding=per_holding))
        verdict = await e5.evaluate(
            _envelope(target_agent="e5"),
            holdings=holdings,
            unlisted_data=unlisted_data,
        )
        assert "valuation_stale" in verdict.flags

    @pytest.mark.asyncio
    async def test_severely_stale_flag(self):
        # 30-month-old valuation → valuation_severely_stale
        holdings = [_holding("UE2", vehicle=VehicleType.UNLISTED_EQUITY)]
        unlisted_data = UnlistedDataSnapshot(
            valuation_dates={"UE2": date(2023, 10, 25)},  # ~30 months before 2026-04-25
        )
        per_holding = [
            E5HoldingEvaluation(
                holding_id="UE2",
                valuation_age_days=900,
                exit_pathway_probabilities={"ipo": 0.5, "secondary": 0.3, "writeoff": 0.2},
            ).model_dump(mode="json"),
        ]
        e5 = E5UnlistedSpecialist(_e5_mock(per_holding=per_holding))
        verdict = await e5.evaluate(
            _envelope(target_agent="e5"),
            holdings=holdings,
            unlisted_data=unlisted_data,
        )
        assert "valuation_severely_stale" in verdict.flags

    @pytest.mark.asyncio
    async def test_test_6_exit_pathway_probabilities_validate(self):
        # Probabilities sum to 1.0 → no validation flag
        holdings = [_holding("UE1", vehicle=VehicleType.UNLISTED_EQUITY)]
        unlisted_data = UnlistedDataSnapshot(
            valuation_dates={"UE1": date(2026, 4, 1)},  # fresh
        )
        per_holding = [
            E5HoldingEvaluation(
                holding_id="UE1",
                valuation_age_days=24,
                exit_pathway_probabilities={
                    "ipo": 0.4, "secondary": 0.3, "strategic": 0.2, "writeoff": 0.1,
                },
            ).model_dump(mode="json"),
        ]
        e5 = E5UnlistedSpecialist(_e5_mock(per_holding=per_holding))
        verdict = await e5.evaluate(
            _envelope(target_agent="e5"),
            holdings=holdings,
            unlisted_data=unlisted_data,
        )
        assert not any(f.startswith("exit_pathway_probabilities_invalid_") for f in verdict.flags)

    @pytest.mark.asyncio
    async def test_invalid_probabilities_surface_flag(self):
        # Sum to 0.8, not 1.0 → flag fires
        holdings = [_holding("UE1", vehicle=VehicleType.UNLISTED_EQUITY)]
        per_holding = [
            E5HoldingEvaluation(
                holding_id="UE1",
                valuation_age_days=24,
                exit_pathway_probabilities={"ipo": 0.5, "secondary": 0.3},  # sums to 0.8
            ).model_dump(mode="json"),
        ]
        e5 = E5UnlistedSpecialist(_e5_mock(per_holding=per_holding))
        verdict = await e5.evaluate(
            _envelope(target_agent="e5"),
            holdings=holdings,
            unlisted_data=UnlistedDataSnapshot(),
        )
        assert any(f.startswith("exit_pathway_probabilities_invalid_") for f in verdict.flags)

    @pytest.mark.asyncio
    async def test_comparables_unavailable_flag(self):
        holdings = [_holding("UE1", vehicle=VehicleType.UNLISTED_EQUITY)]
        unlisted_data = UnlistedDataSnapshot(
            valuation_dates={"UE1": date(2026, 4, 1)},
            comparable_data_available={"UE1": False},
        )
        e5 = E5UnlistedSpecialist(_e5_mock())
        verdict = await e5.evaluate(
            _envelope(target_agent="e5"),
            holdings=holdings,
            unlisted_data=unlisted_data,
        )
        assert "comparables_unavailable" in verdict.flags

    @pytest.mark.asyncio
    async def test_test_1_determinism(self):
        holdings = [_holding("UE1", vehicle=VehicleType.UNLISTED_EQUITY)]
        unlisted_data = UnlistedDataSnapshot(
            valuation_dates={"UE1": date(2026, 4, 1)},
        )
        e5 = E5UnlistedSpecialist(_e5_mock())
        v1 = await e5.evaluate(
            _envelope(target_agent="e5"), holdings=holdings, unlisted_data=unlisted_data
        )
        v2 = await e5.evaluate(
            _envelope(target_agent="e5"), holdings=holdings, unlisted_data=unlisted_data
        )
        assert v1.input_hash == v2.input_hash
        assert v1.flags == v2.flags

    @pytest.mark.asyncio
    async def test_verdict_round_trips(self):
        holdings = [_holding("UE1", vehicle=VehicleType.UNLISTED_EQUITY)]
        e5 = E5UnlistedSpecialist(_e5_mock())
        verdict = await e5.evaluate(
            _envelope(target_agent="e5"),
            holdings=holdings,
            unlisted_data=UnlistedDataSnapshot(),
        )
        round_tripped = E5Verdict.model_validate_json(verdict.model_dump_json())
        assert round_tripped == verdict

    @pytest.mark.asyncio
    async def test_pms_holding_does_not_trigger_e5(self):
        # Per §11.6.6, E5 doesn't fire on PMS even when wrapper holds unlisted positions
        class _Strict:
            name = "strict_no_call"

            async def complete(self, request):
                raise AssertionError("LLM must not be called for PMS-only portfolio")

            async def complete_structured(self, request, output_type):
                raise AssertionError("LLM must not be called for PMS-only portfolio")

        e5 = E5UnlistedSpecialist(_Strict())
        holdings = [_holding("PMS1", vehicle=VehicleType.PMS)]
        verdict = await e5.evaluate(_envelope(target_agent="e5"), holdings=holdings)
        assert verdict.risk_level is RiskLevel.NOT_APPLICABLE
