"""M1 cross-constraint validation + soft-warning generation.

Pure-Python helpers — no DB access, no I/O, no LLM. Used by the service
layer + the Pydantic schemas to enforce FR Entry 12.1's hard rules
(§2.3, §3.3, §4.3, §5.3, §6.3) and produce soft warnings on divergence
from I0 / industry-standard ranges.

Hard rules raise :class:`MandateValidationError` and are surfaced as RFC
7807 problem details by the router. Soft warnings are returned alongside
the value as a list of :class:`SoftWarning` instances; the advisor sees
them inline but can submit anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from artha.api_v2.m1.i0_defaults import compute_defaults

# ---------------------------------------------------------------------------
# Industry-standard ranges from FR 12.1 §3.3 + §5.3
# ---------------------------------------------------------------------------

SINGLE_POSITION_TYPICAL_MIN = 3
SINGLE_POSITION_TYPICAL_MAX = 10

SECTOR_TYPICAL_MIN = 15
SECTOR_TYPICAL_MAX = 40

# Soft warning fires when liquidity_floor_pct deviates from the I0
# suggested default by more than this many points (FR 12.1 §4.3).
LIQUIDITY_FLOOR_DIVERGENCE_THRESHOLD = 10


# ---------------------------------------------------------------------------
# Exception + warning shapes
# ---------------------------------------------------------------------------


class MandateValidationError(Exception):
    """One or more hard validation rules failed.

    Carries a list of structured failure dicts so the router can surface
    them in an RFC 7807 problem-detail envelope. Each failure has
    ``field`` (or ``code`` for cross-constraint rules), ``message``, and
    ``code`` keys.
    """

    def __init__(self, failures: list[dict[str, str]]) -> None:
        super().__init__(f"{len(failures)} mandate validation failure(s)")
        self.failures = failures


@dataclass(frozen=True)
class SoftWarning:
    """One advisory warning. Does NOT block submission."""

    field: str
    code: str
    message: str


# ---------------------------------------------------------------------------
# Hard validation (FR 12.1 hard rules)
# ---------------------------------------------------------------------------


def validate_hard_rules(constraints: dict[str, Any]) -> None:
    """Raise :class:`MandateValidationError` if any hard rule fails.

    The Pydantic schema (:class:`MandateConstraintInput`) handles per-field
    range / type checks; this function adds the cross-constraint checks
    that span multiple fields and can't be expressed by a per-field
    validator.
    """
    failures: list[dict[str, str]] = []

    pairs = [
        ("equity", "equity_min_pct", "equity_max_pct"),
        ("debt", "debt_min_pct", "debt_max_pct"),
        ("alternatives", "alternatives_min_pct", "alternatives_max_pct"),
    ]
    for label, min_key, max_key in pairs:
        if constraints[max_key] < constraints[min_key]:
            failures.append({
                "field": max_key,
                "code": "max_less_than_min",
                "message": f"{label} max ({constraints[max_key]}%) must be "
                           f"greater than or equal to {label} min "
                           f"({constraints[min_key]}%)",
            })

    sum_min = (
        constraints["equity_min_pct"]
        + constraints["debt_min_pct"]
        + constraints["alternatives_min_pct"]
    )
    if sum_min > 100:
        failures.append({
            "field": "asset_allocation",
            "code": "sum_min_exceeds_100",
            "message": (
                f"Asset allocation minimums sum to {sum_min}%; total must be "
                "at most 100%."
            ),
        })

    sum_max = (
        constraints["equity_max_pct"]
        + constraints["debt_max_pct"]
        + constraints["alternatives_max_pct"]
    )
    if sum_max < 100:
        failures.append({
            "field": "asset_allocation",
            "code": "sum_max_below_100",
            "message": (
                f"Asset allocation maximums sum to {sum_max}%; total must be "
                "at least 100% so the portfolio can be fully allocated."
            ),
        })

    if failures:
        raise MandateValidationError(failures)


# ---------------------------------------------------------------------------
# Soft-warning generation (FR 12.1 §3.3, §4.3, §5.3)
# ---------------------------------------------------------------------------


def generate_soft_warnings(
    constraints: dict[str, Any],
    *,
    risk_appetite: str | None,
    liquidity_tier: str | None,
) -> list[SoftWarning]:
    """Return advisory warnings; does not raise.

    The advisor can override any of these — submission still succeeds.
    Used by the create + amend services to enrich the response with the
    same warnings shape the form / C0 surfaces render inline.
    """
    warnings: list[SoftWarning] = []
    defaults = compute_defaults(
        risk_appetite=risk_appetite, liquidity_tier=liquidity_tier
    )

    # Single-position concentration (FR 12.1 §3.3)
    spm = constraints["single_position_max_pct"]
    if spm < SINGLE_POSITION_TYPICAL_MIN or spm > SINGLE_POSITION_TYPICAL_MAX:
        warnings.append(SoftWarning(
            field="single_position_max_pct",
            code="single_position_outside_typical",
            message=(
                f"Single-position max of {spm}% is outside the typical "
                f"{SINGLE_POSITION_TYPICAL_MIN}-{SINGLE_POSITION_TYPICAL_MAX}% "
                "range for HNI mandates. Confirm this is intentional."
            ),
        ))

    # Sector cap (FR 12.1 §5.3)
    sec = constraints["sector_max_pct"]
    if sec < SECTOR_TYPICAL_MIN or sec > SECTOR_TYPICAL_MAX:
        warnings.append(SoftWarning(
            field="sector_max_pct",
            code="sector_cap_outside_typical",
            message=(
                f"Sector cap of {sec}% is outside the typical "
                f"{SECTOR_TYPICAL_MIN}-{SECTOR_TYPICAL_MAX}% range. "
                "Values below 15% may force over-diversification; values "
                "above 40% allow significant sector concentration."
            ),
        ))

    # Liquidity floor divergence (FR 12.1 §4.3)
    liq = constraints["liquidity_floor_pct"]
    if abs(liq - defaults.liquidity_floor_pct) > LIQUIDITY_FLOOR_DIVERGENCE_THRESHOLD:
        warnings.append(SoftWarning(
            field="liquidity_floor_pct",
            code="liquidity_floor_diverges_from_i0",
            message=(
                f"Liquidity floor of {liq}% diverges significantly from the "
                f"I0-suggested {defaults.liquidity_floor_pct}% "
                f"({liquidity_tier or 'secondary'} liquidity tier). "
                "Confirm this aligns with the investor's needs."
            ),
        ))

    return warnings
