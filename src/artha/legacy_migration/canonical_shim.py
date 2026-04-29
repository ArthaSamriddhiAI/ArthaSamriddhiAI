"""§16 — legacy → canonical migration shim.

Pass 20's translation layer over pre-consolidation modules. Three
converters here:

  * `legacy_holding_row_to_canonical` — `PortfolioHoldingRow` (legacy ORM)
    → `Holding` (canonical §15.3.3). Maps the 12-column legacy row onto
    the canonical 15-field shape, defaulting fields the legacy schema
    doesn't carry (vehicle_type, sub_asset_class, look_through_unavailable).

  * `legacy_decision_record_to_t1_payload` — `DecisionRecord` (legacy
    pre-consolidation decision/) → a structured T1 `DECISION` event
    payload. The legacy `decision/` package has 0 external imports and
    is scheduled for removal in Pass 21; this shim provides a forward
    bridge for any consumer that still needs the legacy shape projected
    onto T1.

  * `legacy_investor_to_canonical_profile` — re-exports the
    pre-existing helper from `artha.investor.migration` so callers have
    one place to look for "convert legacy → canonical".

All converters are deterministic. No LLM. They emit `DeprecationWarning`
when invoked so callers see the migration path explicitly; replace with
direct construction of canonical objects to silence the warning.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from artha.canonical.holding import Holding
from artha.canonical.investor import InvestorContextProfile
from artha.common.deprecation import deprecated
from artha.common.types import (
    AssetClass,
    VehicleType,
)

# Re-export the legacy-investor migration helper so callers have a single
# import surface. Marked deprecated to nudge migration to canonical.
from artha.investor.migration import migrate_legacy_investor

# ---------------------------------------------------------------------------
# Asset-class string normalisation
# ---------------------------------------------------------------------------


_LEGACY_ASSET_CLASS_MAP: dict[str, AssetClass] = {
    "equity": AssetClass.EQUITY,
    "stocks": AssetClass.EQUITY,
    "shares": AssetClass.EQUITY,
    "debt": AssetClass.DEBT,
    "bonds": AssetClass.DEBT,
    "fixed_income": AssetClass.DEBT,
    "gold": AssetClass.GOLD_COMMODITIES,
    "commodities": AssetClass.GOLD_COMMODITIES,
    "real_assets": AssetClass.REAL_ASSETS,
    "real_estate": AssetClass.REAL_ASSETS,
    "reit": AssetClass.REAL_ASSETS,
    "alternatives": AssetClass.ALTERNATIVES,
    "cash": AssetClass.CASH,
}


def _map_asset_class(raw: str) -> AssetClass:
    """Best-effort mapping of legacy asset_class strings → canonical enum."""
    if not raw:
        return AssetClass.CASH  # safe default for missing data
    normalised = raw.strip().lower().replace(" ", "_")
    return _LEGACY_ASSET_CLASS_MAP.get(normalised, AssetClass.CASH)


# Legacy free-form symbols often imply mutual fund vs direct equity
# without a structured field. We default to MUTUAL_FUND when asset_class
# is equity and the description contains hints; CASH for anything we
# can't infer. Production wires the firm's actual instrument-master here.
def _map_vehicle_type(asset_class: AssetClass, description: str) -> VehicleType:
    desc = description.lower() if description else ""
    if asset_class is AssetClass.EQUITY:
        if "mf" in desc or "mutual fund" in desc or "fund" in desc:
            return VehicleType.MUTUAL_FUND
        return VehicleType.DIRECT_EQUITY
    if asset_class is AssetClass.DEBT:
        return VehicleType.DEBT_DIRECT
    if asset_class is AssetClass.GOLD_COMMODITIES:
        return VehicleType.GOLD
    if asset_class is AssetClass.REAL_ASSETS:
        return VehicleType.REIT
    return VehicleType.CASH


# ---------------------------------------------------------------------------
# Holding converter
# ---------------------------------------------------------------------------


@deprecated(
    canonical_replacement="artha.canonical.holding.Holding",
    removed_in_pass=21,
    reason="legacy PortfolioHoldingRow shape; new code should construct Holding directly",
)
def legacy_holding_row_to_canonical(row: Any) -> Holding:
    """Convert a `PortfolioHoldingRow` ORM instance to a canonical `Holding`.

    `row` is duck-typed (we don't import `PortfolioHoldingRow` here to avoid
    coupling the shim to legacy lifecycle). Required attributes:

      * `id` / `symbol_or_id` / `description`
      * `asset_class` (str), `acquisition_date`, `acquisition_price`
      * `quantity`, `current_price` (nullable), `current_value` (nullable),
        `gain_loss` (nullable)
      * `updated_at` (datetime)
    """
    asset_class = _map_asset_class(getattr(row, "asset_class", "") or "")
    description = getattr(row, "description", "") or ""
    vehicle_type = _map_vehicle_type(asset_class, description)

    quantity = float(getattr(row, "quantity", 0.0) or 0.0)
    acquisition_price = float(getattr(row, "acquisition_price", 0.0) or 0.0)
    current_value = getattr(row, "current_value", None)
    if current_value is None:
        current_price = float(getattr(row, "current_price", 0.0) or 0.0)
        current_value = quantity * current_price
    current_value = float(current_value)

    cost_basis = quantity * acquisition_price
    gain_loss = getattr(row, "gain_loss", None)
    if gain_loss is None:
        gain_loss = current_value - cost_basis
    gain_loss = float(gain_loss)

    acquisition_date = getattr(row, "acquisition_date")
    updated_at = getattr(row, "updated_at", None)
    as_of_date = updated_at.date() if isinstance(updated_at, datetime) else acquisition_date

    instrument_id = str(getattr(row, "symbol_or_id", "") or getattr(row, "id", ""))
    instrument_name = description or instrument_id

    return Holding(
        instrument_id=instrument_id,
        instrument_name=instrument_name,
        units=quantity,
        cost_basis=cost_basis,
        market_value=current_value,
        unrealised_gain_loss=gain_loss,
        amc_or_issuer="",  # legacy schema doesn't carry AMC; production wires this
        vehicle_type=vehicle_type,
        asset_class=asset_class,
        sub_asset_class="legacy_unspecified",
        acquisition_date=acquisition_date,
        as_of_date=as_of_date,
        look_through_unavailable=True,  # legacy rows never carry look-through
    )


# ---------------------------------------------------------------------------
# Decision record converter (legacy decision/ → T1 payload)
# ---------------------------------------------------------------------------


@deprecated(
    canonical_replacement="T1Event(event_type=T1EventType.DECISION, payload=...)",
    removed_in_pass=21,
    reason="legacy artha.decision.DecisionRecord shape; canonical path emits T1 directly",
)
def legacy_decision_record_to_t1_payload(
    record: Any,
) -> dict[str, Any]:
    """Project a legacy `DecisionRecord` into a structured T1 DECISION payload.

    Used by callers that still hold legacy `DecisionRecord` instances and
    want to forward-emit them onto T1 without losing structure. The
    returned dict is the `payload` for a `T1Event(event_type=DECISION)`.
    """
    boundary = getattr(record, "boundary", None)
    boundary_payload: dict[str, Any] = {}
    if boundary is not None:
        boundary_payload = {
            "rule_set_version_id": getattr(boundary, "rule_set_version_id", ""),
            "frozen_at": _iso_or_none(getattr(boundary, "frozen_at", None)),
            "evidence_snapshot_present": bool(
                getattr(boundary, "evidence_snapshot", None)
            ),
        }

    return {
        "agent_id": "legacy.decision",
        "decision_id": getattr(record, "decision_id", ""),
        "intent_id": getattr(record, "intent_id", ""),
        "intent_type": getattr(record, "intent_type", ""),
        "status": getattr(record, "status", ""),
        "result": dict(getattr(record, "result", {}) or {}),
        "boundary": boundary_payload,
        "created_at": _iso_or_none(getattr(record, "created_at", None)),
        "completed_at": _iso_or_none(getattr(record, "completed_at", None)),
        "summary": (
            f"legacy decision {getattr(record, 'decision_id', '?')} "
            f"({getattr(record, 'status', '?')})"
        ),
    }


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# Investor converter — thin wrapper over the existing migration helper
# ---------------------------------------------------------------------------


@deprecated(
    canonical_replacement="artha.canonical.investor.InvestorContextProfile",
    removed_in_pass=21,
    reason="legacy 5-tier RiskCategory → canonical 3-tier RiskProfile bridge",
)
def legacy_investor_to_canonical_profile(
    *,
    client_id: str,
    firm_id: str,
    legacy_risk_category: Any,
    legacy_horizon: str,
    created_at: datetime,
    updated_at: datetime,
) -> InvestorContextProfile:
    """Single-call wrapper: legacy investor fields → `InvestorContextProfile`.

    Delegates to the existing `migrate_legacy_investor` helper. The shim
    layer's purpose is convenience + a deprecation surface — the existing
    function in `artha.investor.migration` keeps working.
    """
    return migrate_legacy_investor(
        client_id=client_id,
        firm_id=firm_id,
        legacy_risk_category=legacy_risk_category,
        legacy_horizon=legacy_horizon,
        created_at=created_at,
        updated_at=updated_at,
    )


__all__ = [
    "legacy_decision_record_to_t1_payload",
    "legacy_holding_row_to_canonical",
    "legacy_investor_to_canonical_profile",
]
