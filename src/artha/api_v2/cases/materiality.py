"""Deterministic materiality gate (FR Entry 20.1 §6).

Evaluates whether a proposed_action / scenario case is "material"
(= IC1 deliberation required) by applying six rules. Diagnostic and
briefing modes are mode-excluded.

The materiality reason string format: rule IDs joined by ``+`` (e.g.
``"MAT_TICKET_SIZE+MAT_PRODUCT_PMS_AIF_SIF"``). Special values:

- ``"manual_flag"`` — advisor / CIO flagged at intake.
- ``"no_rule_triggered"`` — checked, nothing fires → not material.
- ``"mode_excluded"`` — diagnostic / briefing case.

Thresholds are configurable per firm (FR 20.1 §6.4); defaults from §6.2
ship as constants here. Cluster 5 stub layer reuses these via
:class:`MaterialityConfig`; admin override surface arrives later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from artha.api_v2.cases.state_machine import CaseMode

# ---------------------------------------------------------------------------
# Rule IDs
# ---------------------------------------------------------------------------


class MaterialityRuleId(str, Enum):
    """Identifiers used in the materiality_reason string (FR 20.1 §6.2)."""

    MAT_TICKET_SIZE = "MAT_TICKET_SIZE"
    MAT_PRODUCT_PMS_AIF_SIF = "MAT_PRODUCT_PMS_AIF_SIF"
    MAT_CONCENTRATION = "MAT_CONCENTRATION"
    MAT_S1_AMPLIFICATION = "MAT_S1_AMPLIFICATION"
    MAT_MANDATE_PROXIMITY = "MAT_MANDATE_PROXIMITY"
    MAT_LARGE_EXIT = "MAT_LARGE_EXIT"


# ---------------------------------------------------------------------------
# Thresholds (FR 20.1 §6.2 defaults)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MaterialityConfig:
    """Per-firm thresholds for the six materiality rules.

    All thresholds in INR / % unless noted. Constructed once at startup
    (or per-firm at request time when an admin override exists).
    """

    #: ``proposed_action.amount > Rs 1 Cr`` → material.
    ticket_size_threshold_inr: Decimal = Decimal("10000000")  # 1 Cr
    #: SEBI categories that always trigger materiality regardless of size.
    pms_aif_sif_product_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"pms", "aif", "sif"})
    )
    #: Action would push single-position concentration above this fraction.
    concentration_threshold_pct: Decimal = Decimal("8")  # 8 %
    #: Action would push portfolio within this many percentage points of
    #: any mandate band edge → material.
    mandate_proximity_threshold_pct: Decimal = Decimal("5")
    #: Action exits more than this much from a single instrument → material.
    large_exit_threshold_inr: Decimal = Decimal("5000000")  # 50 L


DEFAULT_MATERIALITY_CONFIG = MaterialityConfig()


# ---------------------------------------------------------------------------
# Inputs + result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MaterialityInput:
    """All the case-level facts the gate needs.

    The cluster 5 stub layer + future real M0 both populate this; the
    pure-Python gate below has no DB dependency.
    """

    case_mode: CaseMode
    #: Set true if advisor / CIO marked the case material at intake.
    manual_flag: bool = False
    #: Proposed-action ticket size in INR. None = not applicable.
    proposed_action_amount_inr: Decimal | None = None
    #: List of normalised product categories for the proposed action
    #: (e.g., ``{"pms"}``). Lower-case strings.
    proposed_action_products: frozenset[str] = field(default_factory=frozenset)
    #: True if the proposed action would push a single instrument's
    #: concentration above the threshold. Caller pre-computes.
    pushes_concentration_above_threshold: bool = False
    #: True if the S1 synthesis flagged amplification (3+ medium risks
    #: combining to high). Read from synthesis_outputs.amplification.
    s1_amplification_flag: bool = False
    #: True if the action would push the portfolio within
    #: ``mandate_proximity_threshold_pct`` of any mandate band edge.
    pushes_within_mandate_band_proximity: bool = False
    #: Largest single-instrument exit size in INR. None when not exiting.
    largest_single_instrument_exit_inr: Decimal | None = None


@dataclass(frozen=True)
class MaterialityResult:
    """Output of :func:`evaluate_materiality`."""

    is_material: bool
    reason: str
    rules_triggered: tuple[MaterialityRuleId, ...]


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def evaluate_materiality(
    inp: MaterialityInput,
    config: MaterialityConfig | None = None,
) -> MaterialityResult:
    """Apply the six rules to :class:`MaterialityInput` and return a
    :class:`MaterialityResult`.

    Order of evaluation is fixed for deterministic + replayable output.
    """
    cfg = config or DEFAULT_MATERIALITY_CONFIG

    # Mode exclusion comes first: diagnostic + briefing never trigger
    # IC1 (FR 20.1 §6.2 last paragraph).
    if inp.case_mode in {CaseMode.DIAGNOSTIC, CaseMode.BRIEFING}:
        return MaterialityResult(
            is_material=False,
            reason="mode_excluded",
            rules_triggered=(),
        )

    # Manual flag short-circuits — advisor / CIO override.
    if inp.manual_flag:
        return MaterialityResult(
            is_material=True,
            reason="manual_flag",
            rules_triggered=(),
        )

    triggered: list[MaterialityRuleId] = []

    # MAT_TICKET_SIZE
    if (
        inp.proposed_action_amount_inr is not None
        and inp.proposed_action_amount_inr > cfg.ticket_size_threshold_inr
    ):
        triggered.append(MaterialityRuleId.MAT_TICKET_SIZE)

    # MAT_PRODUCT_PMS_AIF_SIF
    if inp.proposed_action_products & cfg.pms_aif_sif_product_categories:
        triggered.append(MaterialityRuleId.MAT_PRODUCT_PMS_AIF_SIF)

    # MAT_CONCENTRATION
    if inp.pushes_concentration_above_threshold:
        triggered.append(MaterialityRuleId.MAT_CONCENTRATION)

    # MAT_S1_AMPLIFICATION
    if inp.s1_amplification_flag:
        triggered.append(MaterialityRuleId.MAT_S1_AMPLIFICATION)

    # MAT_MANDATE_PROXIMITY
    if inp.pushes_within_mandate_band_proximity:
        triggered.append(MaterialityRuleId.MAT_MANDATE_PROXIMITY)

    # MAT_LARGE_EXIT
    if (
        inp.largest_single_instrument_exit_inr is not None
        and inp.largest_single_instrument_exit_inr > cfg.large_exit_threshold_inr
    ):
        triggered.append(MaterialityRuleId.MAT_LARGE_EXIT)

    if not triggered:
        return MaterialityResult(
            is_material=False,
            reason="no_rule_triggered",
            rules_triggered=(),
        )

    return MaterialityResult(
        is_material=True,
        reason="+".join(rule.value for rule in triggered),
        rules_triggered=tuple(triggered),
    )


__all__ = [
    "DEFAULT_MATERIALITY_CONFIG",
    "MaterialityConfig",
    "MaterialityInput",
    "MaterialityResult",
    "MaterialityRuleId",
    "evaluate_materiality",
]
