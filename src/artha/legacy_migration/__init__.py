"""§16 — legacy → canonical migration shims.

Pass 20 wraps the pre-consolidation `artha.investor`, `artha.portfolio`,
and `artha.decision` modules with explicit conversion helpers so
downstream callers can migrate to canonical schemas incrementally.

Public surface:
  * `legacy_holding_row_to_canonical` — `PortfolioHoldingRow` → `Holding`
  * `legacy_decision_record_to_t1_payload` — `DecisionRecord` → T1 payload
  * `legacy_investor_to_canonical_profile` — wraps existing investor migration
"""

from artha.legacy_migration.canonical_shim import (
    legacy_decision_record_to_t1_payload,
    legacy_holding_row_to_canonical,
    legacy_investor_to_canonical_profile,
)

__all__ = [
    "legacy_decision_record_to_t1_payload",
    "legacy_holding_row_to_canonical",
    "legacy_investor_to_canonical_profile",
]
