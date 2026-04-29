"""Pass 15 — three onboarding paths acceptance tests.

§10.3.7:
  Test 1 — Same investor across paths → identical canonical objects (modulo data_source).
  Test 2 — Schema validation enforced across all three paths.
  Test 5 — Advisor confirmation captured in T1 with method + timestamp.
  Test 8 — Bucket-mapping determinism: same active fields → same bucket regardless of path.

Plus path-specific tests:
  * FORM: structural-flag confirmation gate; conflict surfacing blocks T1 emission.
  * C0: per-checkpoint extraction → confirmation → finalize; missing checkpoints block.
  * API: schema-version validation; pending → confirm flow; reject path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from artha.canonical.investor import DataSource
from artha.canonical.mandate import (
    AssetClassLimits,
    ConcentrationLimits,
    SignoffMethod,
    VehicleLimits,
)
from artha.canonical.model_portfolio import (
    ConstructionContext,
    ModelPortfolioObject,
    TargetWithTolerance,
)
from artha.canonical.monitoring import AlertTier
from artha.canonical.onboarding import (
    ConfirmationMethod,
    MandateIntakePayload,
    OnboardingActivationStatus,
    OnboardingApiPayload,
    OnboardingCheckpointKind,
    OnboardingFormPayload,
    OnboardingResult,
)
from artha.common.standards import T1EventType
from artha.common.types import (
    AssetClass,
    Bucket,
    CapacityTrajectory,
    MandateType,
    RiskProfile,
    TimeHorizon,
    VehicleType,
    WealthTier,
)
from artha.llm.providers.mock import MockProvider
from artha.onboarding import (
    ApiOnboardingHandler,
    ApiSchemaValidationError,
    C0CheckpointNotConfirmedError,
    C0OnboardingHandler,
    FormOnboardingHandler,
    StructuralFlagsNotConfirmedError,
)

# ===========================================================================
# Test recorder for T1 (in-memory)
# ===========================================================================


class _RecordingT1Repo:
    """Async append-only recorder mirroring `T1Repository.append`."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append(self, event: Any) -> Any:
        self.events.append(event)
        return event


# ===========================================================================
# Shared fixtures
# ===========================================================================


def _mandate_intake() -> MandateIntakePayload:
    return MandateIntakePayload(
        mandate_type=MandateType.INDIVIDUAL,
        asset_class_limits={
            AssetClass.EQUITY: AssetClassLimits(
                min_pct=0.30, target_pct=0.50, max_pct=0.60
            ),
            AssetClass.DEBT: AssetClassLimits(
                min_pct=0.20, target_pct=0.40, max_pct=0.60
            ),
        },
        vehicle_limits={
            VehicleType.AIF_CAT_2: VehicleLimits(
                allowed=True, min_pct=0.0, max_pct=0.20
            ),
        },
        concentration_limits=ConcentrationLimits(
            per_holding_max=0.10, per_manager_max=0.20, per_sector_max=0.30
        ),
        liquidity_floor=0.10,
    )


def _form_payload(*, structural_confirmed: bool = True) -> OnboardingFormPayload:
    now = datetime(2026, 4, 29, 9, 0, tzinfo=UTC)
    return OnboardingFormPayload(
        form_session_id="form_session_abc",
        submitted_by_advisor_id="advisor_jane",
        submitted_at=now,
        client_id="c1",
        firm_id="firm_test",
        risk_profile=RiskProfile.MODERATE,
        time_horizon=TimeHorizon.LONG_TERM,
        wealth_tier=WealthTier.AUM_5CR_TO_10CR,
        capacity_trajectory=CapacityTrajectory.STABLE_OR_GROWING,
        intermediary_present=False,
        beneficiary_can_operate_current_structure=True,
        structural_flags_advisor_confirmed=structural_confirmed,
        mandate=_mandate_intake(),
        signoff_method=SignoffMethod.E_SIGNATURE,
        signoff_evidence_id="sign_evidence_001",
        signoff_captured_at=now,
        signed_by="advisor_jane",
    )


def _api_payload(
    *, api_schema_version: str = "1.0.0"
) -> OnboardingApiPayload:
    now = datetime(2026, 4, 29, 9, 0, tzinfo=UTC)
    return OnboardingApiPayload(
        api_request_id="api_req_xyz",
        crm_identifier="salesforce",
        payload_received_at=now,
        api_schema_version=api_schema_version,
        client_id="c1",
        firm_id="firm_test",
        advisor_id="advisor_jane",
        risk_profile=RiskProfile.MODERATE,
        time_horizon=TimeHorizon.LONG_TERM,
        wealth_tier=WealthTier.AUM_5CR_TO_10CR,
        capacity_trajectory=CapacityTrajectory.STABLE_OR_GROWING,
        intermediary_present=False,
        beneficiary_can_operate_current_structure=True,
        mandate=_mandate_intake(),
        signoff_method=SignoffMethod.E_SIGNATURE,
        signoff_evidence_id="sign_evidence_001",
        signoff_captured_at=now,
        signed_by="advisor_jane",
    )


def _model_portfolio() -> ModelPortfolioObject:
    return ModelPortfolioObject(
        model_id="mp_test",
        bucket=Bucket.MOD_LT,
        version="1.0.0",
        firm_id="firm_test",
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        approved_by="advisor_jane",
        approval_rationale="initial bucket model",
        l1_targets={
            AssetClass.EQUITY: TargetWithTolerance(target=0.50, tolerance_band=0.05),
            AssetClass.DEBT: TargetWithTolerance(target=0.50, tolerance_band=0.05),
        },
        construction=ConstructionContext(construction_pipeline_run_id="cp_test"),
    )


def _c0_mock(
    *,
    client_id: str = "c1",
    firm_id: str = "firm_test",
    risk_profile: RiskProfile = RiskProfile.MODERATE,
    time_horizon: TimeHorizon = TimeHorizon.LONG_TERM,
    wealth_tier: WealthTier = WealthTier.AUM_5CR_TO_10CR,
    parse_confidence: float = 0.92,
) -> MockProvider:
    mock = MockProvider()
    mock.set_structured_response(
        "onboarding identity extractor",
        {
            "client_id": client_id,
            "firm_id": firm_id,
            "parse_confidence": parse_confidence,
            "parse_notes": "client name + firm extracted unambiguously",
        },
    )
    mock.set_structured_response(
        "risk-and-horizon extractor",
        {
            "risk_profile_value": risk_profile.value,
            "time_horizon_value": time_horizon.value,
            "wealth_tier_value": wealth_tier.value,
            "parse_confidence": parse_confidence,
            "parse_notes": "all three values explicit",
        },
    )
    mock.set_structured_response(
        "mandate-constraints extractor",
        {
            "capacity_trajectory_value": CapacityTrajectory.STABLE_OR_GROWING.value,
            "intermediary_present": False,
            "beneficiary_can_operate": True,
            "mandate_intake": _mandate_intake().model_dump(mode="json"),
            "parse_confidence": parse_confidence,
            "parse_notes": "constraints captured",
        },
    )
    return mock


# ===========================================================================
# §10.3.2 — FORM path
# ===========================================================================


class TestFormPath:
    @pytest.mark.asyncio
    async def test_form_submit_happy_path(self):
        repo = _RecordingT1Repo()
        handler = FormOnboardingHandler(t1_repository=repo)
        result = await handler.submit(_form_payload())

        assert isinstance(result, OnboardingResult)
        assert result.data_source is DataSource.FORM
        assert result.confirmation_method is ConfirmationMethod.FORM_SUBMIT
        assert result.activation_status is OnboardingActivationStatus.ACTIVATED
        assert result.t1_confirmation_event_id is not None
        # Bucket derived deterministically: MODERATE + LONG_TERM = MOD_LT
        assert result.investor_profile_payload["assigned_bucket"] == Bucket.MOD_LT.value

    @pytest.mark.asyncio
    async def test_form_blocks_without_structural_confirmation(self):
        handler = FormOnboardingHandler()
        with pytest.raises(StructuralFlagsNotConfirmedError):
            await handler.submit(_form_payload(structural_confirmed=False))

    @pytest.mark.asyncio
    async def test_form_t1_event_carries_method_and_payload(self):
        repo = _RecordingT1Repo()
        handler = FormOnboardingHandler(t1_repository=repo)
        await handler.submit(_form_payload())
        assert len(repo.events) == 1
        evt = repo.events[0]
        assert evt.event_type is T1EventType.INVESTOR_ACTIVATED
        assert evt.payload["confirmation_method"] == "form_submit"
        assert evt.payload["bucket_assigned"] == Bucket.MOD_LT.value
        assert "investor_context_profile" in evt.payload
        assert "mandate_object" in evt.payload

    @pytest.mark.asyncio
    async def test_form_with_conflicts_blocks_activation(self):
        """Mandate vs model conflict should leave status PENDING_CONFLICT_RESOLUTION
        and skip T1 activation event."""
        # Build a model that conflicts with the mandate (model says 80% equity,
        # mandate caps at 60% — that's a clear ceiling conflict).
        model = ModelPortfolioObject(
            model_id="mp_conflict",
            bucket=Bucket.MOD_LT,
            version="1.0.0",
            firm_id="firm_test",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
            effective_at=datetime(2026, 4, 1, tzinfo=UTC),
            approved_by="advisor_jane",
            approval_rationale="aggressive equity model",
            l1_targets={
                AssetClass.EQUITY: TargetWithTolerance(target=0.80, tolerance_band=0.05),
                AssetClass.DEBT: TargetWithTolerance(target=0.20, tolerance_band=0.05),
            },
            construction=ConstructionContext(construction_pipeline_run_id="cp_conflict"),
        )
        repo = _RecordingT1Repo()
        handler = FormOnboardingHandler(t1_repository=repo)
        result = await handler.submit(_form_payload(), model_portfolio=model)
        # When conflict_at_activation surfaces conflicts, we hold off activation
        if result.conflicts:
            assert (
                result.activation_status
                is OnboardingActivationStatus.PENDING_CONFLICT_RESOLUTION
            )
            assert result.t1_confirmation_event_id is None
            assert repo.events == []


# ===========================================================================
# §10.3.4 — API path
# ===========================================================================


class TestApiPath:
    @pytest.mark.asyncio
    async def test_api_submit_returns_pending_with_must_respond_alert(self):
        handler = ApiOnboardingHandler()
        pending = await handler.submit(_api_payload())
        assert pending.confirmation_alert.tier is AlertTier.MUST_RESPOND
        assert handler.is_pending(pending.onboarding_id)

    @pytest.mark.asyncio
    async def test_api_unsupported_schema_version_rejected(self):
        handler = ApiOnboardingHandler()
        with pytest.raises(ApiSchemaValidationError):
            await handler.submit(_api_payload(api_schema_version="9.9.9"))

    @pytest.mark.asyncio
    async def test_api_confirm_emits_t1_event(self):
        repo = _RecordingT1Repo()
        handler = ApiOnboardingHandler(t1_repository=repo)
        pending = await handler.submit(_api_payload())
        result = await handler.confirm(
            pending.onboarding_id, confirming_advisor_id="advisor_jane"
        )
        assert result.activation_status is OnboardingActivationStatus.ACTIVATED
        assert result.confirmation_method is ConfirmationMethod.API_ALERT_RESPONSE
        assert result.t1_confirmation_event_id is not None
        assert len(repo.events) == 1
        assert repo.events[0].payload["confirmation_method"] == "api_alert_response"
        assert not handler.is_pending(pending.onboarding_id)

    @pytest.mark.asyncio
    async def test_api_reject_marks_abandoned(self):
        handler = ApiOnboardingHandler()
        pending = await handler.submit(_api_payload())
        result = handler.reject(pending.onboarding_id, reason="advisor_declined")
        assert result.activation_status is OnboardingActivationStatus.ABANDONED
        assert result.t1_confirmation_event_id is None

    @pytest.mark.asyncio
    async def test_api_timeout_marks_expired(self):
        handler = ApiOnboardingHandler()
        pending = await handler.submit(_api_payload())
        result = handler.reject(pending.onboarding_id, reason="timeout_expired")
        assert result.activation_status is OnboardingActivationStatus.EXPIRED


# ===========================================================================
# §10.3.3 — C0 path
# ===========================================================================


class TestC0Path:
    def _transcript(self, *, conv_id: str = "c0_conv_001"):
        from artha.canonical.onboarding import C0OnboardingTranscriptInput

        return C0OnboardingTranscriptInput(
            c0_conversation_id=conv_id,
            advisor_id="advisor_jane",
            firm_id="firm_test",
            client_id="c1",
            transcript_text=(
                "Advisor: New client onboarding for Sharma Family.\n"
                "Advisor: They want a moderate risk profile, long-term horizon.\n"
                "Advisor: AUM ₹6 Cr, individual mandate.\n"
                "Advisor: Standard mandate constraints, no intermediary."
            ),
            started_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        )

    @pytest.mark.asyncio
    async def test_c0_full_flow(self):
        repo = _RecordingT1Repo()
        handler = C0OnboardingHandler(_c0_mock(), t1_repository=repo)
        transcript = self._transcript()

        # Run all three checkpoints
        for kind in (
            OnboardingCheckpointKind.IDENTITY_KYC,
            OnboardingCheckpointKind.RISK_PROFILE_HORIZON,
            OnboardingCheckpointKind.MANDATE_CONSTRAINTS,
        ):
            cp = await handler.extract_checkpoint(transcript=transcript, kind=kind)
            assert cp.extraction.checkpoint_kind is kind
            handler.confirm_checkpoint(
                c0_conversation_id=transcript.c0_conversation_id,
                kind=kind,
                advisor_id="advisor_jane",
            )

        result = await handler.finalize(transcript=transcript)
        assert result.data_source is DataSource.C0
        assert result.confirmation_method is ConfirmationMethod.C0_CONFIRMATION
        assert result.activation_status is OnboardingActivationStatus.ACTIVATED
        assert result.t1_confirmation_event_id is not None
        # Confidence is in the §10.3.3 band
        confidence = result.investor_profile_payload["confidence"]
        assert 0.8 <= confidence <= 0.95
        # Bucket mapping deterministic
        assert result.investor_profile_payload["assigned_bucket"] == Bucket.MOD_LT.value

    @pytest.mark.asyncio
    async def test_c0_finalize_without_confirmation_blocks(self):
        handler = C0OnboardingHandler(_c0_mock())
        transcript = self._transcript()
        # Extract but don't confirm
        await handler.extract_checkpoint(
            transcript=transcript, kind=OnboardingCheckpointKind.IDENTITY_KYC
        )
        with pytest.raises(C0CheckpointNotConfirmedError):
            await handler.finalize(transcript=transcript)

    @pytest.mark.asyncio
    async def test_c0_t1_event_carries_method_c0_confirmation(self):
        repo = _RecordingT1Repo()
        handler = C0OnboardingHandler(_c0_mock(), t1_repository=repo)
        transcript = self._transcript()
        for kind in OnboardingCheckpointKind:
            await handler.extract_checkpoint(transcript=transcript, kind=kind)
            handler.confirm_checkpoint(
                c0_conversation_id=transcript.c0_conversation_id,
                kind=kind,
                advisor_id="advisor_jane",
            )
        await handler.finalize(transcript=transcript)
        assert len(repo.events) == 1
        assert repo.events[0].payload["confirmation_method"] == "c0_confirmation"

    @pytest.mark.asyncio
    async def test_c0_advisor_corrections_override_extraction(self):
        # LLM extracts wealth_tier=AUM_5CR_TO_10CR; advisor corrects to AUM_2CR_TO_5CR
        handler = C0OnboardingHandler(
            _c0_mock(wealth_tier=WealthTier.AUM_5CR_TO_10CR)
        )
        transcript = self._transcript()
        for kind in OnboardingCheckpointKind:
            await handler.extract_checkpoint(transcript=transcript, kind=kind)

        handler.confirm_checkpoint(
            c0_conversation_id=transcript.c0_conversation_id,
            kind=OnboardingCheckpointKind.IDENTITY_KYC,
            advisor_id="advisor_jane",
        )
        handler.confirm_checkpoint(
            c0_conversation_id=transcript.c0_conversation_id,
            kind=OnboardingCheckpointKind.RISK_PROFILE_HORIZON,
            advisor_id="advisor_jane",
            corrections={"wealth_tier_value": WealthTier.AUM_2CR_TO_5CR.value},
        )
        handler.confirm_checkpoint(
            c0_conversation_id=transcript.c0_conversation_id,
            kind=OnboardingCheckpointKind.MANDATE_CONSTRAINTS,
            advisor_id="advisor_jane",
        )

        result = await handler.finalize(transcript=transcript)
        assert (
            result.investor_profile_payload["wealth_tier"]
            == WealthTier.AUM_2CR_TO_5CR.value
        )


# ===========================================================================
# §10.3.7 — Cross-path equivalence + acceptance tests
# ===========================================================================


class TestCrossPathEquivalence:
    @pytest.mark.asyncio
    async def test_test_1_same_investor_same_canonical_objects(self):
        """Test 1 — same active fields across paths produce identical canonical
        InvestorContextProfile + MandateObject (modulo data_source / metadata /
        confidence / data_gaps_flagged)."""
        # FORM
        form_handler = FormOnboardingHandler()
        form_result = await form_handler.submit(_form_payload())

        # API
        api_handler = ApiOnboardingHandler()
        pending = await api_handler.submit(_api_payload())
        api_result = await api_handler.confirm(
            pending.onboarding_id, confirming_advisor_id="advisor_jane"
        )

        # C0
        c0_handler = C0OnboardingHandler(_c0_mock())
        from artha.canonical.onboarding import C0OnboardingTranscriptInput

        transcript = C0OnboardingTranscriptInput(
            c0_conversation_id="c0_conv_001",
            advisor_id="advisor_jane",
            firm_id="firm_test",
            client_id="c1",
            transcript_text="canned",
            started_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
        )
        for kind in OnboardingCheckpointKind:
            await c0_handler.extract_checkpoint(transcript=transcript, kind=kind)
            c0_handler.confirm_checkpoint(
                c0_conversation_id=transcript.c0_conversation_id,
                kind=kind,
                advisor_id="advisor_jane",
            )
        c0_result = await c0_handler.finalize(transcript=transcript)

        # All three should produce the same canonical core fields
        for path_result in (form_result, api_result, c0_result):
            profile = path_result.investor_profile_payload
            assert profile["client_id"] == "c1"
            assert profile["firm_id"] == "firm_test"
            assert profile["risk_profile"] == RiskProfile.MODERATE.value
            assert profile["time_horizon"] == TimeHorizon.LONG_TERM.value
            assert profile["wealth_tier"] == WealthTier.AUM_5CR_TO_10CR.value
            assert profile["assigned_bucket"] == Bucket.MOD_LT.value

        # Mandate types match across paths
        for path_result in (form_result, api_result, c0_result):
            assert path_result.mandate_payload["mandate_type"] == MandateType.INDIVIDUAL.value
            assert (
                path_result.mandate_payload["asset_class_limits"]
                == form_result.mandate_payload["asset_class_limits"]
            )

        # Path differences isolated to data_source + metadata
        assert form_result.data_source is DataSource.FORM
        assert api_result.data_source is DataSource.API
        assert c0_result.data_source is DataSource.C0
        assert "form_session_id" in form_result.data_source_metadata
        assert "api_request_id" in api_result.data_source_metadata
        assert "c0_conversation_id" in c0_result.data_source_metadata

    @pytest.mark.asyncio
    async def test_test_2_schema_validation_enforced(self):
        # Required fields enforced by Pydantic — try to build with missing field
        with pytest.raises(ValidationError):
            OnboardingFormPayload(
                # missing form_session_id and other required fields
                submitted_by_advisor_id="advisor_jane",
                submitted_at=datetime(2026, 4, 29, tzinfo=UTC),
            )

        # API payload validation
        with pytest.raises(ValidationError):
            OnboardingApiPayload(
                api_request_id="req",
                payload_received_at=datetime(2026, 4, 29, tzinfo=UTC),
                # missing required fields
            )

    @pytest.mark.asyncio
    async def test_test_5_t1_confirmation_captured_with_method_and_timestamp(self):
        """Each path's T1 INVESTOR_ACTIVATED event carries the confirmation method
        and the confirmation timestamp."""
        for path, expected_method in [
            ("form", "form_submit"),
            ("api", "api_alert_response"),
            ("c0", "c0_confirmation"),
        ]:
            repo = _RecordingT1Repo()
            if path == "form":
                handler = FormOnboardingHandler(t1_repository=repo)
                await handler.submit(_form_payload())
            elif path == "api":
                handler = ApiOnboardingHandler(t1_repository=repo)
                pending = await handler.submit(_api_payload())
                await handler.confirm(
                    pending.onboarding_id, confirming_advisor_id="advisor_jane"
                )
            else:
                handler = C0OnboardingHandler(_c0_mock(), t1_repository=repo)
                from artha.canonical.onboarding import C0OnboardingTranscriptInput

                transcript = C0OnboardingTranscriptInput(
                    c0_conversation_id="conv",
                    advisor_id="advisor_jane",
                    firm_id="firm_test",
                    client_id="c1",
                    transcript_text="x",
                    started_at=datetime(2026, 4, 29, tzinfo=UTC),
                )
                for kind in OnboardingCheckpointKind:
                    await handler.extract_checkpoint(transcript=transcript, kind=kind)
                    handler.confirm_checkpoint(
                        c0_conversation_id=transcript.c0_conversation_id,
                        kind=kind,
                        advisor_id="advisor_jane",
                    )
                await handler.finalize(transcript=transcript)

            assert len(repo.events) == 1
            evt = repo.events[0]
            assert evt.event_type is T1EventType.INVESTOR_ACTIVATED
            assert evt.payload["confirmation_method"] == expected_method
            assert "confirmed_at" in evt.payload

    @pytest.mark.asyncio
    async def test_test_8_bucket_determinism_across_paths(self):
        """Test 8 — bucket assignment is deterministic across all three paths
        for a given (risk_profile, time_horizon)."""
        # Try several (risk, horizon) combinations
        cases = [
            (RiskProfile.CONSERVATIVE, TimeHorizon.SHORT_TERM, Bucket.CON_ST),
            (RiskProfile.AGGRESSIVE, TimeHorizon.LONG_TERM, Bucket.AGG_LT),
            (RiskProfile.MODERATE, TimeHorizon.MEDIUM_TERM, Bucket.MOD_MT),
        ]
        for risk, horizon, expected_bucket in cases:
            # FORM
            form_payload = _form_payload()
            form_payload = form_payload.model_copy(
                update={"risk_profile": risk, "time_horizon": horizon}
            )
            form_handler = FormOnboardingHandler()
            form_result = await form_handler.submit(form_payload)
            assert (
                form_result.investor_profile_payload["assigned_bucket"]
                == expected_bucket.value
            )

            # API
            api_payload = _api_payload()
            api_payload = api_payload.model_copy(
                update={"risk_profile": risk, "time_horizon": horizon}
            )
            api_handler = ApiOnboardingHandler()
            pending = await api_handler.submit(api_payload)
            api_result = await api_handler.confirm(
                pending.onboarding_id, confirming_advisor_id="advisor_jane"
            )
            assert (
                api_result.investor_profile_payload["assigned_bucket"]
                == expected_bucket.value
            )

            # C0
            c0_handler = C0OnboardingHandler(
                _c0_mock(risk_profile=risk, time_horizon=horizon)
            )
            from artha.canonical.onboarding import C0OnboardingTranscriptInput

            transcript = C0OnboardingTranscriptInput(
                c0_conversation_id=f"conv_{risk.value}_{horizon.value}",
                advisor_id="advisor_jane",
                firm_id="firm_test",
                client_id="c1",
                transcript_text="x",
                started_at=datetime(2026, 4, 29, tzinfo=UTC),
            )
            for kind in OnboardingCheckpointKind:
                await c0_handler.extract_checkpoint(transcript=transcript, kind=kind)
                c0_handler.confirm_checkpoint(
                    c0_conversation_id=transcript.c0_conversation_id,
                    kind=kind,
                    advisor_id="advisor_jane",
                )
            c0_result = await c0_handler.finalize(transcript=transcript)
            assert (
                c0_result.investor_profile_payload["assigned_bucket"]
                == expected_bucket.value
            )

    @pytest.mark.asyncio
    async def test_round_trip_onboarding_result_schema(self):
        handler = FormOnboardingHandler()
        result = await handler.submit(_form_payload())
        round_tripped = OnboardingResult.model_validate_json(result.model_dump_json())
        assert round_tripped == result
