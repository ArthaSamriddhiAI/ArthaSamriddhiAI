"""Pass 1 foundation tests — ULID, hashing, types, Section 3 standards.

Covers:
  * artha.common.ulid          — new_ulid, is_ulid, time-sortable property
  * artha.common.hashing       — canonical_json, payload_hash
  * artha.common.types         — enum values, validate_confidence, shared models
  * artha.common.standards     — Section 3 formatters, rubrics, vocab, lint
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from artha.common.hashing import canonical_json, payload_hash
from artha.common.standards import (
    ACTIVE_INVESTOR_CONTEXT_FIELDS,
    BRIEFING_TOKEN_MAX,
    BRIEFING_TOKEN_MIN,
    CLARIFICATION_MAX_ROUNDS,
    T1_BASE_REQUIRED_FIELDS,
    TIME_HORIZON_YEARS,
    ConfidenceBand,
    ExceptionCategory,
    ExceptionRoutingDecision,
    OverrideReasonCategory,
    OverrideRecord,
    OverrideTargetKind,
    T1EventType,
    amplify_risk_level,
    assert_field_is_active,
    briefing_violates_discipline,
    briefing_within_budget,
    clarification_response_within_budget,
    confidence_band,
    format_basis_points,
    format_inr,
    format_percentage,
    format_return,
    is_vague_time_phrase,
)
from artha.common.types import (
    AlertTier,
    AssetClass,
    Bucket,
    CapacityTrajectory,
    CaseIntent,
    Driver,
    DriverDirection,
    DriverSeverity,
    GateResult,
    MaterialityGateResult,
    Permission,
    Recommendation,
    RiskLevel,
    RiskProfile,
    SourceCitation,
    SourceType,
    TimeHorizon,
    VehicleType,
    VersionPins,
    WatchState,
    WealthTier,
    validate_confidence,
)
from artha.common.ulid import is_ulid, new_ulid

# ===========================================================================
# ULID
# ===========================================================================


class TestUlid:
    def test_shape(self):
        u = new_ulid()
        assert len(u) == 26
        assert is_ulid(u)

    def test_uniqueness(self):
        # Even at the same instant, the random suffix differs.
        ids = {new_ulid() for _ in range(1000)}
        assert len(ids) == 1000

    def test_time_sortable(self):
        # ULIDs minted with increasing timestamps must sort lexicographically.
        a = new_ulid(now_ms=1_700_000_000_000)
        b = new_ulid(now_ms=1_700_000_001_000)
        c = new_ulid(now_ms=1_700_000_002_000)
        assert a < b < c

    def test_deterministic_with_now_ms_prefix(self):
        # Same `now_ms` produces same first 10 chars (the timestamp part).
        a = new_ulid(now_ms=1_700_000_000_000)
        b = new_ulid(now_ms=1_700_000_000_000)
        assert a[:10] == b[:10]

    def test_rejects_negative_timestamp(self):
        with pytest.raises(ValueError):
            new_ulid(now_ms=-1)

    def test_rejects_oversize_timestamp(self):
        with pytest.raises(ValueError):
            new_ulid(now_ms=1 << 48)

    def test_is_ulid_rejects_wrong_length(self):
        assert not is_ulid("ABCDE")
        assert not is_ulid("A" * 27)

    def test_is_ulid_rejects_invalid_chars(self):
        # Crockford alphabet excludes I, L, O, U
        assert not is_ulid("0123456789ABCDEFGHJKMNPQRI")


# ===========================================================================
# Canonical JSON hashing
# ===========================================================================


class TestHashing:
    def test_hex_64_chars(self):
        h = payload_hash({"a": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_key_order_invariance(self):
        # The same payload with keys inserted in different order must hash identically.
        h1 = payload_hash({"a": 1, "b": 2, "c": 3})
        h2 = payload_hash({"c": 3, "a": 1, "b": 2})
        assert h1 == h2

    def test_nested_key_order_invariance(self):
        h1 = payload_hash({"outer": {"a": 1, "b": 2}})
        h2 = payload_hash({"outer": {"b": 2, "a": 1}})
        assert h1 == h2

    def test_different_values_different_hash(self):
        assert payload_hash({"x": 1}) != payload_hash({"x": 2})

    def test_handles_enum_values(self):
        # Enums must serialise to their value, not their name.
        h = payload_hash({"level": RiskLevel.HIGH})
        assert payload_hash({"level": "HIGH"}) == h

    def test_handles_pydantic_model(self):
        # Pydantic BaseModels must serialise via model_dump.
        d = Driver(
            factor="leverage",
            direction=DriverDirection.NEGATIVE,
            severity=DriverSeverity.HIGH,
            detail="exceeds bucket norm",
        )
        h1 = payload_hash({"d": d})
        h2 = payload_hash({"d": d.model_dump(mode="json")})
        assert h1 == h2

    def test_canonical_json_compact(self):
        # Canonical JSON has no insignificant whitespace.
        s = canonical_json({"a": 1, "b": 2})
        assert s == '{"a":1,"b":2}'


# ===========================================================================
# Confidence
# ===========================================================================


class TestConfidence:
    def test_validate_accepts_zero_and_one(self):
        validate_confidence(0.0)
        validate_confidence(1.0)

    @pytest.mark.parametrize("c", [-0.01, 1.01, "high", None])
    def test_validate_rejects_invalid(self, c):
        with pytest.raises(ValueError):
            validate_confidence(c)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (0.99, ConfidenceBand.VIRTUALLY_CERTAIN),
            (0.95, ConfidenceBand.VIRTUALLY_CERTAIN),
            (0.94, ConfidenceBand.HIGH),
            (0.85, ConfidenceBand.HIGH),
            (0.84, ConfidenceBand.MODERATE),
            (0.70, ConfidenceBand.MODERATE),
            (0.69, ConfidenceBand.LOW),
            (0.50, ConfidenceBand.LOW),
            (0.49, ConfidenceBand.UNCERTAIN),
            (0.0, ConfidenceBand.UNCERTAIN),
        ],
    )
    def test_confidence_band(self, value, expected):
        assert confidence_band(value) is expected


# ===========================================================================
# Risk amplification (Section 3.1)
# ===========================================================================


class TestRiskAmplification:
    def test_empty_or_all_na_returns_na(self):
        assert amplify_risk_level([]) is RiskLevel.NOT_APPLICABLE
        assert amplify_risk_level([RiskLevel.NOT_APPLICABLE] * 3) is RiskLevel.NOT_APPLICABLE

    def test_any_high_dominates(self):
        assert amplify_risk_level([RiskLevel.LOW, RiskLevel.HIGH, RiskLevel.LOW]) is RiskLevel.HIGH

    def test_three_mediums_amplify_to_high(self):
        # "Three independent MEDIUM risks across non-overlapping dimensions can aggregate to HIGH"
        assert amplify_risk_level([RiskLevel.MEDIUM] * 3) is RiskLevel.HIGH

    def test_two_mediums_stay_medium(self):
        assert amplify_risk_level([RiskLevel.MEDIUM, RiskLevel.MEDIUM]) is RiskLevel.MEDIUM

    def test_one_medium_with_lows_is_medium(self):
        result = amplify_risk_level([RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.LOW])
        assert result is RiskLevel.MEDIUM

    def test_all_lows_stay_low(self):
        assert amplify_risk_level([RiskLevel.LOW, RiskLevel.LOW, RiskLevel.LOW]) is RiskLevel.LOW

    def test_na_does_not_count(self):
        # NA inputs are filtered out — three MEDIUMs plus NAs still amplify.
        result = amplify_risk_level([
            RiskLevel.MEDIUM,
            RiskLevel.NOT_APPLICABLE,
            RiskLevel.MEDIUM,
            RiskLevel.NOT_APPLICABLE,
            RiskLevel.MEDIUM,
        ])
        assert result is RiskLevel.HIGH


# ===========================================================================
# INR / percentage / basis points / return formatters (Section 3.3)
# ===========================================================================


class TestInrFormatting:
    @pytest.mark.parametrize(
        "amount,expected",
        [
            (12_345_000, "₹1.23 Cr"),     # >= 1 Cr
            (250_000, "₹2.50 L"),         # >= 1 L
            (12_345, "₹12,345"),           # < 1 L: lakh-crore grouping
            (999, "₹999"),
            (0, "₹0"),
        ],
    )
    def test_compact_thresholds(self, amount, expected):
        assert format_inr(amount) == expected

    def test_negative_amount(self):
        assert format_inr(-12_345_000) == "-₹1.23 Cr"
        assert format_inr(-12_345) == "-₹12,345"

    def test_non_compact_lakh_crore_grouping(self):
        # Section 3.3 example: ₹1,23,45,000 not ₹12,345,000
        assert format_inr(12_345_000, compact=False) == "₹1,23,45,000"

    def test_non_compact_below_lakh(self):
        assert format_inr(99_999, compact=False) == "₹99,999"

    def test_non_compact_exactly_one_lakh(self):
        assert format_inr(100_000, compact=False) == "₹1,00,000"

    def test_non_compact_exactly_one_crore(self):
        assert format_inr(10_000_000, compact=False) == "₹1,00,00,000"


class TestPercentageFormatting:
    def test_default_one_decimal(self):
        assert format_percentage(0.124) == "12.4%"

    def test_two_decimals(self):
        assert format_percentage(0.12433, decimals=2) == "12.43%"

    def test_rounds_half_to_even(self):
        # standard Python format rounds half-to-even — just sanity-check non-vagueness
        assert format_percentage(0.5) == "50.0%"


class TestBasisPointsAndReturns:
    def test_basis_points(self):
        assert format_basis_points(25) == "25 bps"
        assert format_basis_points(0) == "0 bps"

    def test_return_requires_period_and_qualifier(self):
        s = format_return(0.124, period="annual", qualifier="net of all costs and taxes")
        assert s == "12.4% net of all costs and taxes annual"

    def test_return_rejects_blank_period(self):
        with pytest.raises(ValueError):
            format_return(0.1, period="", qualifier="gross")

    def test_return_rejects_blank_qualifier(self):
        with pytest.raises(ValueError):
            format_return(0.1, period="annual", qualifier="   ")


# ===========================================================================
# Time horizon vocabulary (Section 3.4)
# ===========================================================================


class TestTimeHorizonVocab:
    def test_canonical_year_ranges(self):
        assert TIME_HORIZON_YEARS[TimeHorizon.SHORT_TERM] == (0.0, 3.0)
        assert TIME_HORIZON_YEARS[TimeHorizon.MEDIUM_TERM] == (3.0, 5.0)
        assert TIME_HORIZON_YEARS[TimeHorizon.LONG_TERM] == (5.0, None)

    @pytest.mark.parametrize("phrase", ["soon", "Down The Line", "EVENTUALLY", "  later  "])
    def test_vague_phrases_detected(self, phrase):
        assert is_vague_time_phrase(phrase) is True

    @pytest.mark.parametrize("phrase", ["in 18 months", "by 2030-06-01", "next quarter"])
    def test_explicit_phrases_pass(self, phrase):
        assert is_vague_time_phrase(phrase) is False


# ===========================================================================
# Investor context dormant guard (Section 3.9)
# ===========================================================================


class TestInvestorContextActiveGuard:
    @pytest.mark.parametrize(
        "field",
        [
            "risk_profile",
            "time_horizon",
            "wealth_tier",
            "capacity_trajectory",
            "intermediary_present",
            "beneficiary_can_operate_current_structure",
            "client_id",
        ],
    )
    def test_active_field_passes(self, field):
        assert_field_is_active(field)

    @pytest.mark.parametrize(
        "field",
        [
            "wealth_origin_l1_pattern",
            "worldview_indicators",
            "resistance_flags",
            "blind_spots",
            "advisory_framing",
            "pattern_interaction_flags",
        ],
    )
    def test_dormant_field_raises(self, field):
        with pytest.raises(ValueError, match="dormant"):
            assert_field_is_active(field)

    def test_active_set_immutable_shape(self):
        # Tests that the canonical set is the documented MVP scope and frozen
        assert isinstance(ACTIVE_INVESTOR_CONTEXT_FIELDS, frozenset)
        assert "risk_profile" in ACTIVE_INVESTOR_CONTEXT_FIELDS


# ===========================================================================
# Briefing budget + lint (Section 3.14)
# ===========================================================================


class TestBriefingDiscipline:
    def test_budget_constants(self):
        # Section 3.14 / 8.8.2 specify 100–300 tokens.
        assert BRIEFING_TOKEN_MIN == 100
        assert BRIEFING_TOKEN_MAX == 300

    def test_clarification_round_trip_capped_at_one(self):
        assert CLARIFICATION_MAX_ROUNDS == 1

    @pytest.mark.parametrize("n,ok", [(99, False), (100, True), (300, True), (301, False)])
    def test_briefing_within_budget(self, n, ok):
        assert briefing_within_budget(n) is ok

    @pytest.mark.parametrize("n,ok", [(49, False), (50, True), (200, True), (201, False)])
    def test_clarification_response_within_budget(self, n, ok):
        assert clarification_response_within_budget(n) is ok

    def test_clean_briefing_passes_lint(self):
        text = (
            "The client recently restructured their family trust and the proposed "
            "AIF would be the first illiquid commitment under the new structure. "
            "The cascade timing relative to existing capital calls warrants careful "
            "evaluation."
        )
        violates, reasons = briefing_violates_discipline(text)
        assert violates is False, reasons

    @pytest.mark.parametrize(
        "text",
        [
            "This is a high risk case.",
            "The client should proceed with caution.",
            "My recommendation is to approve.",
            "This will be risky given the client's profile.",
            "This case must be escalated.",
        ],
    )
    def test_verdict_anticipating_briefings_caught(self, text):
        violates, reasons = briefing_violates_discipline(text)
        assert violates is True
        assert len(reasons) > 0


# ===========================================================================
# Override mechanics (Section 3.10)
# ===========================================================================


class TestOverrideTypes:
    def test_override_record_round_trips(self):
        rec = OverrideRecord(
            target_kind=OverrideTargetKind.GATE,
            target_id="e6_gate",
            reason_category=OverrideReasonCategory.CLIENT_SPECIFIC_CIRCUMSTANCE,
            rationale_text="Client has external private liquidity covering the lock-in period.",
        )
        assert rec.target_kind is OverrideTargetKind.GATE
        round_tripped = OverrideRecord.model_validate_json(rec.model_dump_json())
        assert round_tripped == rec

    def test_other_category_uses_free_text(self):
        rec = OverrideRecord(
            target_kind=OverrideTargetKind.HARD_RULE,
            target_id="g2_rule_42",
            reason_category=OverrideReasonCategory.OTHER,
            rationale_text="See free text",
            free_text_other="Pilot programme exemption documented in policy memo 2026-04",
        )
        assert rec.free_text_other is not None


# ===========================================================================
# Telemetry and exception standards (Section 3.11, 3.13)
# ===========================================================================


class TestTelemetryStandards:
    def test_t1_event_type_enum_covers_canonical_set(self):
        # Spot-check that key event types from Section 15.11.1 are present.
        for v in [
            "router_classification",
            "e1_verdict",
            "e6_gate",
            "s1_synthesis",
            "ic1_devils_advocate",
            "g3_evaluation",
            "a1_challenge",
            "pm1_event",
            "n0_alert",
            "briefing",
            "clarification_request",
            "decision",
            "override",
            "ex1_event",
            "t2_reflection_run",
        ]:
            assert v in {e.value for e in T1EventType}

    def test_t1_base_required_fields_match_spec(self):
        # T1_BASE_REQUIRED_FIELDS is the set always populated per Section 15.11.1.
        required = [
            "event_id", "event_type", "timestamp", "firm_id",
            "payload_hash", "payload", "version_pins",
        ]
        for f in required:
            assert f in T1_BASE_REQUIRED_FIELDS


class TestExceptionStandards:
    def test_categories_present(self):
        expected = [
            "input_data_missing", "schema_violation", "service_unavailable",
            "timeout", "cascading_exception",
        ]
        for v in expected:
            assert v in {e.value for e in ExceptionCategory}

    def test_routing_decisions_present(self):
        expected = [
            "escalate_to_advisor", "escalate_to_compliance",
            "fallback_to_prior_version", "retry_once",
        ]
        for v in expected:
            assert v in {e.value for e in ExceptionRoutingDecision}


# ===========================================================================
# Section 15.2 enums sanity
# ===========================================================================


class TestCanonicalEnums:
    def test_nine_buckets(self):
        assert len(Bucket) == 9
        assert {b.value for b in Bucket} == {
            "CON_ST", "CON_MT", "CON_LT",
            "MOD_ST", "MOD_MT", "MOD_LT",
            "AGG_ST", "AGG_MT", "AGG_LT",
        }

    def test_eight_intent_types(self):
        assert len(CaseIntent) == 8

    def test_four_alert_tiers(self):
        # Section 10.2.2: four tiers including the new WATCH tier
        assert {t.value for t in AlertTier} == {
            "must_respond", "should_respond", "watch", "informational",
        }

    def test_four_gate_results(self):
        assert {g.value for g in GateResult} == {
            "PROCEED", "EVALUATE_WITH_COUNTERFACTUAL", "SOFT_BLOCK", "HARD_BLOCK",
        }

    def test_three_permissions(self):
        assert {p.value for p in Permission} == {"APPROVED", "BLOCKED", "ESCALATION_REQUIRED"}

    def test_four_recommendations(self):
        assert {r.value for r in Recommendation} == {"proceed", "modify", "do_not_proceed", "defer"}

    def test_three_watch_states(self):
        assert {s.value for s in WatchState} == {
            "active_watch", "resolved_occurred", "resolved_did_not_occur",
        }

    def test_capacity_trajectory_has_four(self):
        assert len(CapacityTrajectory) == 4

    def test_seven_wealth_tiers(self):
        assert len(WealthTier) == 7

    def test_materiality_gate_two_states(self):
        assert {m.value for m in MaterialityGateResult} == {"CONVENE", "SKIP"}

    def test_vehicle_and_asset_class_enum_values(self):
        assert VehicleType.AIF_CAT_2.value == "aif_cat_2"
        assert AssetClass.EQUITY.value == "equity"
        assert RiskProfile.MODERATE.value == "Moderate"


# ===========================================================================
# Driver / SourceCitation / VersionPins
# ===========================================================================


class TestSharedStructuredTypes:
    def test_driver_validates(self):
        d = Driver(
            factor="concentration",
            direction=DriverDirection.NEGATIVE,
            severity=DriverSeverity.HIGH,
            detail="Top-1 holding at 28% (bucket norm 15%)",
            evidence_citation=["portfolio_analytics:hhi_holding_level"],
        )
        assert d.severity is DriverSeverity.HIGH
        assert d.evidence_citation == ["portfolio_analytics:hhi_holding_level"]

    def test_driver_rejects_bad_severity(self):
        with pytest.raises(ValidationError):
            Driver(
                factor="x",
                direction=DriverDirection.POSITIVE,
                severity="extreme",  # type: ignore[arg-type]
                detail="...",
            )

    def test_source_citation_validates(self):
        c = SourceCitation(
            source_type=SourceType.RULE,
            source_id="g2_rule_42",
            source_version="2026Q2",
        )
        assert c.source_type is SourceType.RULE

    def test_version_pins_default_all_none(self):
        p = VersionPins()
        assert p.model_portfolio_version is None
        assert p.mandate_version is None

    def test_version_pins_round_trip(self):
        p = VersionPins(model_portfolio_version="3.4.0", mandate_version="2026.04.1")
        round_tripped = VersionPins.model_validate_json(p.model_dump_json())
        assert round_tripped == p
