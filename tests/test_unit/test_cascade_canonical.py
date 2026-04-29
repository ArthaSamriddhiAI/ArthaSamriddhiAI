"""Pass 17 — L4 cascade + mandate amendment acceptance tests.

§5.13 (L4 cascade):
  Test 7 — Fund A removed, Fund B added; affected clients each get a
           Mode-1-dominant case + SHOULD_RESPOND N0 alert + T1 capture.

§7.10 (mandate amendment):
  Test 7 — Amendment activates new version with diff + signoff captured in T1.
  Test 8 — Re-mapping cascades when amendment changes bucket.
  Test 10 — Out-of-bucket flag triggers single-client construction.

Plus path-specific tests:
  * Diff generation (added / removed / modified field changes).
  * Activation gates (signoff required; cannot activate twice; rejected blocks).
  * L4 cascade with no affected clients yields empty run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from artha.canonical.cascade import (
    L4CascadeCase,
    L4CascadeCaseStatus,
    L4CascadeRun,
    MandateAmendmentDiff,
    MandateAmendmentResult,
)
from artha.canonical.construction import ClientPortfolioSlice
from artha.canonical.investor import (
    DataSource,
    InvestorContextProfile,
)
from artha.canonical.mandate import (
    AssetClassLimits,
    ConcentrationLimits,
    MandateAmendmentStatus,
    MandateAmendmentType,
    MandateObject,
    SignoffEvidence,
    SignoffMethod,
    VehicleLimits,
)
from artha.canonical.model_portfolio import (
    ConstructionContext,
    ModelPortfolioObject,
    TargetWithTolerance,
)
from artha.canonical.monitoring import AlertTier
from artha.cascade import (
    AlreadyActivatedError,
    L4CascadeService,
    MandateAmendmentService,
    SignoffMissingError,
)
from artha.common.standards import T1EventType
from artha.common.types import (
    AssetClass,
    Bucket,
    MandateType,
    RiskProfile,
    TimeHorizon,
    VehicleType,
    WealthTier,
)

# ===========================================================================
# Test recorder
# ===========================================================================


class _RecordingT1Repo:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append(self, event: Any) -> Any:
        self.events.append(event)
        return event


# ===========================================================================
# Fixtures
# ===========================================================================


def _client_slice(
    *,
    client_id: str,
    holdings: dict[str, float],
    bucket: Bucket = Bucket.MOD_LT,
    aum_inr: float = 5_000_000.0,
) -> ClientPortfolioSlice:
    return ClientPortfolioSlice(
        client_id=client_id,
        firm_id="firm_test",
        bucket=bucket,
        aum_inr=aum_inr,
        current_l1_weights={"equity": 0.50, "debt": 0.50},
        holdings_by_instrument_id=holdings,
    )


def _mandate(
    *,
    version: int = 1,
    equity_max: float = 0.60,
    debt_max: float = 0.60,
    aif_cat2_max: float = 0.20,
    liquidity_floor: float = 0.10,
    sector_exclusions: list[str] | None = None,
) -> MandateObject:
    # Build internally consistent min/target/max triples (validator requires
    # min <= target <= max). Default min/target derived from max.
    equity_min = min(0.30, equity_max * 0.5)
    equity_target = min(0.50, equity_max)
    equity_target = max(equity_target, equity_min)
    debt_min = min(0.20, debt_max * 0.5)
    debt_target = min(0.40, debt_max)
    debt_target = max(debt_target, debt_min)
    return MandateObject(
        mandate_id="mandate_c1",
        client_id="c1",
        firm_id="firm_test",
        version=version,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        mandate_type=MandateType.INDIVIDUAL,
        asset_class_limits={
            AssetClass.EQUITY: AssetClassLimits(
                min_pct=equity_min, target_pct=equity_target, max_pct=equity_max
            ),
            AssetClass.DEBT: AssetClassLimits(
                min_pct=debt_min, target_pct=debt_target, max_pct=debt_max
            ),
        },
        vehicle_limits={
            VehicleType.AIF_CAT_2: VehicleLimits(
                allowed=True, min_pct=0.0, max_pct=aif_cat2_max
            ),
        },
        concentration_limits=ConcentrationLimits(
            per_holding_max=0.10, per_manager_max=0.20, per_sector_max=0.30
        ),
        liquidity_floor=liquidity_floor,
        sector_exclusions=list(sector_exclusions or []),
        signoff_method=SignoffMethod.E_SIGNATURE,
        signoff_evidence=SignoffEvidence(
            evidence_id="sign_v1",
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        signed_by="advisor_jane",
    )


def _profile(
    *,
    risk_profile: RiskProfile = RiskProfile.MODERATE,
    time_horizon: TimeHorizon = TimeHorizon.LONG_TERM,
    bucket: Bucket = Bucket.MOD_LT,
) -> InvestorContextProfile:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return InvestorContextProfile(
        client_id="c1",
        firm_id="firm_test",
        created_at=now,
        updated_at=now,
        risk_profile=risk_profile,
        time_horizon=time_horizon,
        wealth_tier=WealthTier.AUM_5CR_TO_10CR,
        assigned_bucket=bucket,
        data_source=DataSource.FORM,
    )


def _model_portfolio(
    *,
    bucket: Bucket = Bucket.MOD_LT,
    equity_target: float = 0.50,
    model_id: str | None = None,
) -> ModelPortfolioObject:
    return ModelPortfolioObject(
        model_id=model_id or f"mp_{bucket.value}",
        bucket=bucket,
        version="1.0.0",
        firm_id="firm_test",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        approved_by="cio_jane",
        approval_rationale="bucket model",
        l1_targets={
            AssetClass.EQUITY: TargetWithTolerance(
                target=equity_target, tolerance_band=0.05
            ),
            AssetClass.DEBT: TargetWithTolerance(
                target=1.0 - equity_target, tolerance_band=0.05
            ),
        },
        construction=ConstructionContext(
            construction_pipeline_run_id=f"cp_{bucket.value}"
        ),
    )


# ===========================================================================
# §5.13 Test 7 — L4 cascade
# ===========================================================================


class TestL4Cascade:
    @pytest.mark.asyncio
    async def test_test_7_per_client_case_spawned(self):
        """Each affected client gets exactly one Mode-1-dominant case."""
        repo = _RecordingT1Repo()
        service = L4CascadeService(t1_repository=repo)
        slices = [
            _client_slice(client_id="c1", holdings={"FUND_A": 1_000_000.0}),
            _client_slice(client_id="c2", holdings={"FUND_A": 500_000.0}),
            _client_slice(client_id="c3", holdings={"FUND_X": 1_000_000.0}),  # unaffected
        ]
        run, alerts = await service.cascade(
            firm_id="firm_test",
            l4_manifest_version="2.0.0",
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={"FUND_A": "FUND_B"},
            advisor_assignments={"c1": "advisor_jane", "c2": "advisor_alex"},
        )
        affected_cases = [c for c in run.spawned_cases]
        assert len(affected_cases) == 2
        assert sorted(c.client_id for c in affected_cases) == ["c1", "c2"]
        assert all(
            c.case_mode == "mode_1_dominant" for c in affected_cases
        )
        assert all(c.action_type == "substitution" for c in affected_cases)
        # Each case carries the substitution recommendation
        for case in affected_cases:
            assert case.removed_instrument_id == "FUND_A"
            assert case.replacement_instrument_id == "FUND_B"
            assert "FUND_A" in case.title
            assert "FUND_B" in case.title

    @pytest.mark.asyncio
    async def test_test_7_n0_alerts_should_respond(self):
        service = L4CascadeService()
        slices = [
            _client_slice(client_id="c1", holdings={"FUND_A": 1_000_000.0}),
        ]
        run, alerts = await service.cascade(
            firm_id="firm_test",
            l4_manifest_version="2.0.0",
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={"FUND_A": "FUND_B"},
        )
        assert len(alerts) == 1
        assert alerts[0].tier is AlertTier.SHOULD_RESPOND
        assert alerts[0].related_constraint_id == "l4_substitution:FUND_A"
        assert run.n0_alert_ids == [alerts[0].alert_id]

    @pytest.mark.asyncio
    async def test_test_7_t1_event_emitted(self):
        repo = _RecordingT1Repo()
        service = L4CascadeService(t1_repository=repo)
        slices = [_client_slice(client_id="c1", holdings={"FUND_A": 2_000_000.0})]
        run, _ = await service.cascade(
            firm_id="firm_test",
            l4_manifest_version="2.0.0",
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={"FUND_A": "FUND_B"},
        )
        assert len(repo.events) == 1
        evt = repo.events[0]
        assert evt.event_type is T1EventType.L4_MANIFEST_VERSION_PIN
        assert evt.payload["l4_manifest_version"] == "2.0.0"
        assert evt.payload["spawned_case_ids"]
        assert run.t1_event_id == evt.event_id

    @pytest.mark.asyncio
    async def test_no_affected_clients_yields_empty_run(self):
        service = L4CascadeService()
        slices = [_client_slice(client_id="c1", holdings={"FUND_X": 1_000_000.0})]
        run, alerts = await service.cascade(
            firm_id="firm_test",
            l4_manifest_version="2.0.0",
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={"FUND_A": "FUND_B"},
        )
        assert run.spawned_cases == []
        assert alerts == []

    @pytest.mark.asyncio
    async def test_advisor_unassigned_leaves_advisor_id_none(self):
        service = L4CascadeService()
        slices = [_client_slice(client_id="c1", holdings={"FUND_A": 1_000_000.0})]
        run, _ = await service.cascade(
            firm_id="firm_test",
            l4_manifest_version="2.0.0",
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={"FUND_A": "FUND_B"},
            # advisor_assignments not supplied
        )
        assert run.spawned_cases[0].advisor_id is None

    @pytest.mark.asyncio
    async def test_run_round_trips(self):
        service = L4CascadeService()
        slices = [_client_slice(client_id="c1", holdings={"FUND_A": 1_000_000.0})]
        run, _ = await service.cascade(
            firm_id="firm_test",
            l4_manifest_version="2.0.0",
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={"FUND_A": "FUND_B"},
        )
        round_tripped = L4CascadeRun.model_validate_json(run.model_dump_json())
        assert round_tripped == run

    @pytest.mark.asyncio
    async def test_unmapped_replacement_marks_sentinel(self):
        service = L4CascadeService()
        slices = [_client_slice(client_id="c1", holdings={"FUND_A": 1_000_000.0})]
        run, _ = await service.cascade(
            firm_id="firm_test",
            l4_manifest_version="2.0.0",
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={},  # no mapping
        )
        assert run.spawned_cases[0].replacement_instrument_id == "unmapped"


# ===========================================================================
# §7.6 — Mandate amendment workflow
# ===========================================================================


class TestMandateAmendmentDiff:
    def test_diff_modified_field(self):
        service = MandateAmendmentService()
        prior = _mandate(version=1, equity_max=0.60)
        proposed = _mandate(version=1, equity_max=0.70)  # raise ceiling
        request, diff = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="Client wants higher equity ceiling.",
        )
        assert request.activation_status is MandateAmendmentStatus.PENDING_SIGNOFF
        assert diff.proposed_version == 2
        # Modified field surfaced
        modified = [
            f for f in diff.field_changes
            if f.path == "asset_class_limits" and f.change_kind == "modified"
        ]
        assert modified

    def test_diff_added_sector_exclusion(self):
        service = MandateAmendmentService()
        prior = _mandate(sector_exclusions=[])
        proposed = _mandate(sector_exclusions=["tobacco"])
        _, diff = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.SECTOR_BLOCK_CHANGE,
            justification="ESG add",
        )
        sector_changes = [
            f for f in diff.field_changes if f.path == "sector_exclusions"
        ]
        assert sector_changes
        assert sector_changes[0].change_kind == "modified"

    def test_bucket_change_flag_set_when_profile_changes(self):
        service = MandateAmendmentService()
        prior_profile = _profile(
            risk_profile=RiskProfile.MODERATE,
            bucket=Bucket.MOD_LT,
        )
        proposed_profile = _profile(
            risk_profile=RiskProfile.AGGRESSIVE,
            bucket=Bucket.AGG_LT,
        )
        _, diff = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=_mandate(),
            proposed_mandate=_mandate(equity_max=0.80),
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="Risk tolerance increased.",
            prior_profile=prior_profile,
            proposed_profile=proposed_profile,
        )
        assert diff.risk_profile_changed is True
        assert diff.bucket_will_change is True


class TestMandateAmendmentActivation:
    @pytest.mark.asyncio
    async def test_test_7_amendment_activates_with_diff_and_signoff(self):
        repo = _RecordingT1Repo()
        service = MandateAmendmentService(t1_repository=repo)
        prior = _mandate(version=1, equity_max=0.60)
        proposed = _mandate(version=1, equity_max=0.70)
        signoff_at = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)

        request, _ = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="Client raises ceiling.",
        )
        signed = service.capture_signoff(
            request,
            signoff=SignoffEvidence(
                evidence_id="sign_v2",
                captured_at=signoff_at,
            ),
        )
        result = await service.activate(
            signed,
            firm_id="firm_test",
            prior_mandate=prior,
            proposed_mandate=proposed,
        )
        assert result.activated_at == signoff_at
        assert result.new_mandate.version == 2
        assert result.new_mandate.effective_at == signoff_at
        assert result.prior_mandate.superseded_at == signoff_at
        # T1 captured
        assert result.t1_amendment_event_id is not None
        amendment_events = [
            e for e in repo.events
            if e.event_type is T1EventType.MANDATE_AMENDMENT
        ]
        assert len(amendment_events) == 1
        assert amendment_events[0].payload["new_version"] == 2

    @pytest.mark.asyncio
    async def test_activation_without_signoff_raises(self):
        service = MandateAmendmentService()
        prior = _mandate(version=1)
        proposed = _mandate(version=1, equity_max=0.70)
        request, _ = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="x",
        )
        with pytest.raises(SignoffMissingError):
            await service.activate(
                request,
                firm_id="firm_test",
                prior_mandate=prior,
                proposed_mandate=proposed,
            )

    @pytest.mark.asyncio
    async def test_activation_twice_raises(self):
        service = MandateAmendmentService()
        prior = _mandate(version=1)
        proposed = _mandate(version=1, equity_max=0.70)
        signed = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="x",
        )[0].model_copy(
            update={
                "client_signoff": SignoffEvidence(
                    evidence_id="sign_v2",
                    captured_at=datetime(2026, 5, 1, tzinfo=UTC),
                ),
                "activation_status": MandateAmendmentStatus.ACTIVATED,
            }
        )
        with pytest.raises(AlreadyActivatedError):
            await service.activate(
                signed,
                firm_id="firm_test",
                prior_mandate=prior,
                proposed_mandate=proposed,
            )


class TestRemappingCascade:
    @pytest.mark.asyncio
    async def test_test_8_remapping_event_emitted_on_bucket_change(self):
        """Amendment that changes risk_profile → bucket changes → remapping event emitted."""
        repo = _RecordingT1Repo()
        service = MandateAmendmentService(t1_repository=repo)
        prior = _mandate(version=1, equity_max=0.60)
        proposed = _mandate(version=1, equity_max=0.80)  # aggressive
        prior_profile = _profile(
            risk_profile=RiskProfile.MODERATE,
            bucket=Bucket.MOD_LT,
        )
        proposed_profile = _profile(
            risk_profile=RiskProfile.AGGRESSIVE,
            bucket=Bucket.AGG_LT,
        )
        prior_model = _model_portfolio(bucket=Bucket.MOD_LT, equity_target=0.50)
        new_model = _model_portfolio(bucket=Bucket.AGG_LT, equity_target=0.70)

        request, _ = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="Risk tolerance increased to aggressive.",
            prior_profile=prior_profile,
            proposed_profile=proposed_profile,
        )
        signed = service.capture_signoff(
            request,
            signoff=SignoffEvidence(
                evidence_id="sign_v2",
                captured_at=datetime(2026, 5, 1, tzinfo=UTC),
            ),
        )
        result = await service.activate(
            signed,
            firm_id="firm_test",
            prior_mandate=prior,
            proposed_mandate=proposed,
            prior_profile=prior_profile,
            proposed_profile=proposed_profile,
            prior_model_portfolio=prior_model,
            new_model_portfolio=new_model,
        )

        assert result.remapping_event is not None
        rm = result.remapping_event
        assert rm.prior_bucket is Bucket.MOD_LT
        assert rm.new_bucket is Bucket.AGG_LT
        assert rm.prior_risk_profile is RiskProfile.MODERATE
        assert rm.new_risk_profile is RiskProfile.AGGRESSIVE
        # L1 deltas: equity moves +0.20, debt moves -0.20
        assert rm.l1_allocation_deltas["equity"] == pytest.approx(0.20)
        assert rm.l1_allocation_deltas["debt"] == pytest.approx(-0.20)
        # T1 captured both events
        assert result.t1_amendment_event_id is not None
        assert result.t1_remapping_event_id is not None
        remapping_events = [
            e for e in repo.events
            if e.event_type is T1EventType.BUCKET_REMAPPING
        ]
        assert len(remapping_events) == 1

    @pytest.mark.asyncio
    async def test_no_remapping_when_bucket_unchanged(self):
        """Amendment that doesn't change risk_profile or time_horizon → no remapping."""
        service = MandateAmendmentService()
        prior = _mandate(version=1, equity_max=0.60)
        proposed = _mandate(version=1, equity_max=0.65)  # small relax, same bucket
        profile = _profile(
            risk_profile=RiskProfile.MODERATE, bucket=Bucket.MOD_LT
        )
        request, _ = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="Slight ceiling raise.",
            prior_profile=profile,
            proposed_profile=profile,
        )
        signed = service.capture_signoff(
            request,
            signoff=SignoffEvidence(
                evidence_id="sign_v2",
                captured_at=datetime(2026, 5, 1, tzinfo=UTC),
            ),
        )
        result = await service.activate(
            signed,
            firm_id="firm_test",
            prior_mandate=prior,
            proposed_mandate=proposed,
            prior_profile=profile,
            proposed_profile=profile,
        )
        assert result.remapping_event is None


class TestOutOfBucket:
    @pytest.mark.asyncio
    async def test_test_10_out_of_bucket_when_no_bucket_fits(self):
        """New mandate with equity max 25% — no bucket model fits."""
        service = MandateAmendmentService()
        prior = _mandate(version=1, equity_max=0.60)
        # Tight ceiling on equity AND debt → mandate caps too tight to fit any bucket.
        # All standard bucket models have equity ≥ 30% which exceeds 25% cap.
        proposed = _mandate(
            version=1, equity_max=0.25, debt_max=0.40,
        )
        signoff = SignoffEvidence(
            evidence_id="sign_v2",
            captured_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        request, _ = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_ADDED,
            justification="Client wants very low equity exposure.",
        )
        signed = service.capture_signoff(request, signoff=signoff)
        bucket_models = {
            Bucket.CON_LT: _model_portfolio(
                bucket=Bucket.CON_LT, equity_target=0.30, model_id="mp_con_lt"
            ),
            Bucket.MOD_LT: _model_portfolio(
                bucket=Bucket.MOD_LT, equity_target=0.50, model_id="mp_mod_lt"
            ),
            Bucket.AGG_LT: _model_portfolio(
                bucket=Bucket.AGG_LT, equity_target=0.70, model_id="mp_agg_lt"
            ),
        }
        result = await service.activate(
            signed,
            firm_id="firm_test",
            prior_mandate=prior,
            proposed_mandate=proposed,
            bucket_models=bucket_models,
        )
        assert result.out_of_bucket_flag is True
        assert result.out_of_bucket_reasons
        # Confirmation alert should be MUST_RESPOND on out-of-bucket
        assert len(result.n0_alert_ids) == 1

    @pytest.mark.asyncio
    async def test_no_out_of_bucket_when_bucket_fits(self):
        """Mandate with equity in [40%, 60%] fits MOD_LT bucket (50% target)."""
        service = MandateAmendmentService()
        prior = _mandate(version=1, equity_max=0.55)
        proposed = _mandate(version=1, equity_max=0.60)
        request, _ = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="Slightly raise ceiling.",
        )
        signed = service.capture_signoff(
            request,
            signoff=SignoffEvidence(
                evidence_id="sign_v2",
                captured_at=datetime(2026, 5, 1, tzinfo=UTC),
            ),
        )
        bucket_models = {
            Bucket.MOD_LT: _model_portfolio(
                bucket=Bucket.MOD_LT, equity_target=0.50, model_id="mp_mod_lt"
            ),
        }
        result = await service.activate(
            signed,
            firm_id="firm_test",
            prior_mandate=prior,
            proposed_mandate=proposed,
            bucket_models=bucket_models,
        )
        assert result.out_of_bucket_flag is False
        assert result.out_of_bucket_reasons == []


class TestRoundTrips:
    @pytest.mark.asyncio
    async def test_round_trip_amendment_result(self):
        service = MandateAmendmentService()
        prior = _mandate(version=1)
        proposed = _mandate(version=1, equity_max=0.65)
        request, _ = service.propose(
            client_id="c1",
            firm_id="firm_test",
            proposed_by="advisor_jane",
            prior_mandate=prior,
            proposed_mandate=proposed,
            amendment_type=MandateAmendmentType.CONSTRAINT_RELAXED,
            justification="x",
        )
        signed = service.capture_signoff(
            request,
            signoff=SignoffEvidence(
                evidence_id="sign_v2",
                captured_at=datetime(2026, 5, 1, tzinfo=UTC),
            ),
        )
        result = await service.activate(
            signed,
            firm_id="firm_test",
            prior_mandate=prior,
            proposed_mandate=proposed,
        )
        round_tripped = MandateAmendmentResult.model_validate_json(
            result.model_dump_json()
        )
        assert round_tripped == result

    def test_round_trip_l4_cascade_case(self):
        case = L4CascadeCase(
            case_id="case_001",
            client_id="c1",
            firm_id="firm_test",
            removed_instrument_id="FUND_A",
            replacement_instrument_id="FUND_B",
            affected_aum_inr=1_000_000.0,
            title="Fund A → Fund B",
            body="Substitute.",
            status=L4CascadeCaseStatus.OPEN,
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        round_tripped = L4CascadeCase.model_validate_json(case.model_dump_json())
        assert round_tripped == case

    def test_round_trip_amendment_diff(self):
        diff = MandateAmendmentDiff(
            amendment_id="amd_001",
            client_id="c1",
            prior_version=1,
            proposed_version=2,
            risk_profile_changed=True,
            bucket_will_change=True,
        )
        round_tripped = MandateAmendmentDiff.model_validate_json(diff.model_dump_json())
        assert round_tripped == diff
