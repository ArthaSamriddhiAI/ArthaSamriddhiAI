"""Cluster 5 chunk 5.1 — materiality gate tests.

Pins FR Entry 20.1 §6.2 thresholds + reason-string format.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from artha.api_v2.cases.materiality import (
    DEFAULT_MATERIALITY_CONFIG,
    MaterialityConfig,
    MaterialityInput,
    MaterialityRuleId,
    evaluate_materiality,
)
from artha.api_v2.cases.state_machine import CaseMode


def _input(**overrides) -> MaterialityInput:
    base = dict(
        case_mode=CaseMode.PROPOSED_ACTION,
        manual_flag=False,
        proposed_action_amount_inr=None,
        proposed_action_products=frozenset(),
        pushes_concentration_above_threshold=False,
        s1_amplification_flag=False,
        pushes_within_mandate_band_proximity=False,
        largest_single_instrument_exit_inr=None,
    )
    base.update(overrides)
    return MaterialityInput(**base)


class TestModeExclusion:
    @pytest.mark.parametrize("mode", [CaseMode.DIAGNOSTIC, CaseMode.BRIEFING])
    def test_diagnostic_and_briefing_never_material(self, mode):
        # Even if every rule would fire, mode-excluded comes first.
        result = evaluate_materiality(
            _input(
                case_mode=mode,
                manual_flag=True,
                proposed_action_amount_inr=Decimal("99000000"),
                proposed_action_products=frozenset({"pms"}),
                pushes_concentration_above_threshold=True,
                s1_amplification_flag=True,
                pushes_within_mandate_band_proximity=True,
                largest_single_instrument_exit_inr=Decimal("99000000"),
            )
        )
        assert result.is_material is False
        assert result.reason == "mode_excluded"
        assert result.rules_triggered == ()


class TestManualFlag:
    def test_manual_flag_overrides_everything(self):
        result = evaluate_materiality(
            _input(
                case_mode=CaseMode.PROPOSED_ACTION,
                manual_flag=True,
            )
        )
        assert result.is_material is True
        assert result.reason == "manual_flag"
        assert result.rules_triggered == ()


class TestRuleTriggers:
    def test_ticket_size_above_threshold(self):
        # Default threshold is Rs 1 Cr = 10,000,000.
        result = evaluate_materiality(
            _input(proposed_action_amount_inr=Decimal("15000000")),
        )
        assert result.is_material is True
        assert result.reason == "MAT_TICKET_SIZE"
        assert result.rules_triggered == (MaterialityRuleId.MAT_TICKET_SIZE,)

    def test_ticket_size_at_threshold_not_material(self):
        # Spec says "> Rs 1 Cr"; equality is NOT material.
        result = evaluate_materiality(
            _input(proposed_action_amount_inr=Decimal("10000000")),
        )
        assert result.is_material is False
        assert result.reason == "no_rule_triggered"

    @pytest.mark.parametrize("product", ["pms", "aif", "sif"])
    def test_pms_aif_sif_product(self, product):
        result = evaluate_materiality(
            _input(proposed_action_products=frozenset({product})),
        )
        assert result.is_material is True
        assert result.reason == "MAT_PRODUCT_PMS_AIF_SIF"

    def test_concentration_threshold(self):
        result = evaluate_materiality(
            _input(pushes_concentration_above_threshold=True),
        )
        assert result.is_material is True
        assert result.reason == "MAT_CONCENTRATION"

    def test_s1_amplification(self):
        result = evaluate_materiality(_input(s1_amplification_flag=True))
        assert result.is_material is True
        assert result.reason == "MAT_S1_AMPLIFICATION"

    def test_mandate_proximity(self):
        result = evaluate_materiality(
            _input(pushes_within_mandate_band_proximity=True),
        )
        assert result.is_material is True
        assert result.reason == "MAT_MANDATE_PROXIMITY"

    def test_large_exit_above_threshold(self):
        # Default threshold is Rs 50 L = 5,000,000.
        result = evaluate_materiality(
            _input(largest_single_instrument_exit_inr=Decimal("5500000")),
        )
        assert result.is_material is True
        assert result.reason == "MAT_LARGE_EXIT"


class TestMultipleRulesTrigger:
    def test_two_rules_join_with_plus(self):
        result = evaluate_materiality(
            _input(
                proposed_action_amount_inr=Decimal("15000000"),
                proposed_action_products=frozenset({"pms"}),
            )
        )
        assert result.is_material is True
        assert result.reason == "MAT_TICKET_SIZE+MAT_PRODUCT_PMS_AIF_SIF"
        assert MaterialityRuleId.MAT_TICKET_SIZE in result.rules_triggered
        assert MaterialityRuleId.MAT_PRODUCT_PMS_AIF_SIF in result.rules_triggered

    def test_reason_order_is_deterministic(self):
        # Both reasons trigger; reason string MUST be in the rule-evaluation
        # order (FR 20.1 §6.4 — replayable / deterministic).
        result = evaluate_materiality(
            _input(
                proposed_action_amount_inr=Decimal("15000000"),
                pushes_concentration_above_threshold=True,
                s1_amplification_flag=True,
            )
        )
        assert result.reason == (
            "MAT_TICKET_SIZE+MAT_CONCENTRATION+MAT_S1_AMPLIFICATION"
        )


class TestNoRuleTriggered:
    def test_returns_no_rule_triggered_label(self):
        result = evaluate_materiality(_input())
        assert result.is_material is False
        assert result.reason == "no_rule_triggered"
        assert result.rules_triggered == ()


class TestConfigOverride:
    def test_custom_threshold_changes_outcome(self):
        # Custom firm config: Rs 50 L ticket = material.
        cfg = MaterialityConfig(
            ticket_size_threshold_inr=Decimal("5000000"),
        )
        result = evaluate_materiality(
            _input(proposed_action_amount_inr=Decimal("8000000")),
            config=cfg,
        )
        assert result.is_material is True

    def test_default_config_preserved(self):
        # Sanity: the module-level default isn't accidentally mutated by
        # earlier tests creating custom configs.
        assert DEFAULT_MATERIALITY_CONFIG.ticket_size_threshold_inr == Decimal(
            "10000000"
        )
