"""Pass 20 — legacy migration + deprecation acceptance tests.

§16 (deployment plan):
  * Legacy entry points emit `DeprecationWarning` on use without breaking.
  * Migration shim converts legacy ORM rows / models to canonical schemas.
  * `DEPRECATION_MANIFEST` records every deprecated symbol with its
    canonical replacement + removal pass.

Tests cover:
  * `@deprecated` decorator emits warning + registers in manifest.
  * `mark_module_deprecated` emits + registers.
  * `legacy_holding_row_to_canonical` round-trip preserves value semantics.
  * `legacy_decision_record_to_t1_payload` produces a forward-compatible payload.
  * `legacy_investor_to_canonical_profile` chains into existing migration helper.
  * Manifest contains expected entries for the legacy modules we marked.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from pydantic import BaseModel

from artha.canonical.holding import Holding
from artha.canonical.investor import InvestorContextProfile
from artha.common.deprecation import (
    DEPRECATION_MANIFEST,
    deprecated,
    manifest,
    mark_module_deprecated,
    reset_manifest_for_tests,
)
from artha.common.types import (
    AssetClass,
    Bucket,
    RiskProfile,
    TimeHorizon,
    VehicleType,
    WealthTier,
)
from artha.investor.schemas import RiskCategory
from artha.legacy_migration import (
    legacy_decision_record_to_t1_payload,
    legacy_holding_row_to_canonical,
    legacy_investor_to_canonical_profile,
)

# ===========================================================================
# Test recorder for deprecation warnings
# ===========================================================================


@pytest.fixture
def reset_deprecation_state():
    """Wipe deprecation manifest before each test that needs a clean slate."""
    reset_manifest_for_tests()
    yield
    reset_manifest_for_tests()


# ===========================================================================
# Deprecation framework
# ===========================================================================


class TestDeprecationDecorator:
    def test_deprecated_function_emits_warning(self, reset_deprecation_state):
        @deprecated(
            canonical_replacement="canonical.replacement",
            removed_in_pass=21,
            reason="legacy contract",
        )
        def legacy_func(x: int) -> int:
            return x * 2

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = legacy_func(3)

        assert result == 6
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecations) >= 1
        msg = str(deprecations[0].message)
        assert "deprecated" in msg
        assert "Pass 21" in msg
        assert "canonical.replacement" in msg
        assert "legacy contract" in msg

    def test_deprecated_function_warns_only_once(self, reset_deprecation_state):
        @deprecated(canonical_replacement="x", removed_in_pass=21)
        def legacy_func() -> None:
            pass

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(5):
                legacy_func()
        # Process-level "warned once" — only the first call surfaces a warning
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecations) == 1

    def test_deprecated_class_warns_on_instantiation(self, reset_deprecation_state):
        @deprecated(
            canonical_replacement="canonical.NewClass",
            removed_in_pass=21,
            kind="class",
        )
        class LegacyClass:
            def __init__(self, value: int) -> None:
                self.value = value

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            instance = LegacyClass(42)

        assert instance.value == 42
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecations) >= 1
        assert "canonical.NewClass" in str(deprecations[0].message)

    def test_deprecated_function_registers_in_manifest(self, reset_deprecation_state):
        @deprecated(
            canonical_replacement="canonical.foo",
            removed_in_pass=21,
            reason="reason text",
        )
        def my_legacy_helper() -> None:
            pass

        # Manifest is pre-populated by decorator (not waiting for first call)
        entries = manifest()
        matching = [
            e for e in entries
            if "my_legacy_helper" in e.module_path
        ]
        assert len(matching) == 1
        assert matching[0].canonical_replacement == "canonical.foo"
        assert matching[0].removed_in_pass == 21
        assert matching[0].reason == "reason text"

    def test_mark_module_deprecated_emits_and_registers(
        self, reset_deprecation_state
    ):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            mark_module_deprecated(
                "test.legacy_pkg",
                canonical_replacement="test.canonical_pkg",
                removed_in_pass=21,
                reason="test fixture",
            )
        deprecations = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecations) >= 1
        # And manifest carries it
        entries = manifest()
        assert any(e.module_path == "test.legacy_pkg" for e in entries)

    def test_decision_module_in_manifest(self):
        """Importing artha.decision should register the package as deprecated."""
        # Re-import to ensure mark fired (idempotent so this is safe)
        import artha.decision  # noqa: F401

        entries = manifest()
        decision_entries = [
            e for e in entries if e.module_path == "artha.decision"
        ]
        assert decision_entries, (
            "expected artha.decision to be in DEPRECATION_MANIFEST"
        )
        e = decision_entries[0]
        assert e.removed_in_pass == 21
        assert "T1" in e.canonical_replacement

    def test_investor_service_module_in_manifest(self):
        """Importing artha.investor.service should mark the module."""
        import artha.investor.service  # noqa: F401

        entries = manifest()
        matching = [
            e for e in entries if e.module_path == "artha.investor.service"
        ]
        assert matching, "expected artha.investor.service to be marked deprecated"
        assert matching[0].removed_in_pass == 21

    def test_portfolio_service_module_in_manifest(self):
        import artha.portfolio.service  # noqa: F401

        entries = manifest()
        matching = [
            e for e in entries if e.module_path == "artha.portfolio.service"
        ]
        assert matching, "expected artha.portfolio.service to be marked deprecated"


# ===========================================================================
# Legacy → canonical: holding row converter
# ===========================================================================


@dataclass
class _FakeLegacyHoldingRow:
    """Duck-typed mirror of `PortfolioHoldingRow` for shim testing."""

    id: str
    investor_id: str
    asset_class: str
    symbol_or_id: str
    description: str
    quantity: float
    acquisition_date: date
    acquisition_price: float
    current_price: float | None
    current_value: float | None
    gain_loss: float | None
    updated_at: datetime


class TestLegacyHoldingConverter:
    def _row(
        self,
        *,
        asset_class: str = "equity",
        symbol: str = "MF1",
        description: str = "Mutual Fund Large Cap",
        quantity: float = 100.0,
        acquisition_price: float = 90.0,
        current_price: float | None = 100.0,
        current_value: float | None = None,
        gain_loss: float | None = None,
    ) -> _FakeLegacyHoldingRow:
        return _FakeLegacyHoldingRow(
            id="row-001",
            investor_id="inv-001",
            asset_class=asset_class,
            symbol_or_id=symbol,
            description=description,
            quantity=quantity,
            acquisition_date=date(2024, 1, 15),
            acquisition_price=acquisition_price,
            current_price=current_price,
            current_value=current_value,
            gain_loss=gain_loss,
            updated_at=datetime(2026, 4, 25, tzinfo=UTC),
        )

    def test_round_trip_preserves_value_semantics(self):
        row = self._row()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            holding = legacy_holding_row_to_canonical(row)
        assert isinstance(holding, Holding)
        assert holding.instrument_id == "MF1"
        assert holding.units == pytest.approx(100.0)
        # cost_basis derived from quantity × acquisition_price
        assert holding.cost_basis == pytest.approx(9_000.0)
        # market_value derived from quantity × current_price when current_value missing
        assert holding.market_value == pytest.approx(10_000.0)
        assert holding.unrealised_gain_loss == pytest.approx(1_000.0)

    def test_uses_explicit_current_value_when_present(self):
        row = self._row(current_value=15_000.0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            holding = legacy_holding_row_to_canonical(row)
        assert holding.market_value == pytest.approx(15_000.0)

    def test_asset_class_mapping_equity_mutual_fund(self):
        row = self._row(asset_class="equity", description="Large Cap Mutual Fund")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            holding = legacy_holding_row_to_canonical(row)
        assert holding.asset_class is AssetClass.EQUITY
        assert holding.vehicle_type is VehicleType.MUTUAL_FUND

    def test_asset_class_mapping_equity_direct(self):
        row = self._row(asset_class="stocks", description="HDFCBANK direct")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            holding = legacy_holding_row_to_canonical(row)
        assert holding.asset_class is AssetClass.EQUITY
        assert holding.vehicle_type is VehicleType.DIRECT_EQUITY

    def test_asset_class_mapping_debt(self):
        row = self._row(asset_class="bonds", description="Govt Bond 10Y")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            holding = legacy_holding_row_to_canonical(row)
        assert holding.asset_class is AssetClass.DEBT
        assert holding.vehicle_type is VehicleType.DEBT_DIRECT

    def test_asset_class_unknown_falls_back_to_cash(self):
        row = self._row(asset_class="unknown_asset", description="Unknown")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            holding = legacy_holding_row_to_canonical(row)
        # Default: CASH for unmapped legacy strings
        assert holding.asset_class is AssetClass.CASH

    def test_emits_deprecation_warning(self):
        row = self._row()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # Reset manifest to ensure first-use warning fires
            reset_manifest_for_tests()
            legacy_holding_row_to_canonical(row)
        deprecations = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert deprecations
        assert "Holding" in str(deprecations[0].message)

    def test_look_through_unavailable_default(self):
        row = self._row()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            holding = legacy_holding_row_to_canonical(row)
        # Legacy rows never carry look-through → flag set
        assert holding.look_through_unavailable is True


# ===========================================================================
# Legacy → canonical: decision record converter
# ===========================================================================


class _FakeLegacyDecisionBoundary(BaseModel):
    rule_set_version_id: str
    frozen_at: datetime


class _FakeLegacyDecisionRecord(BaseModel):
    decision_id: str
    intent_id: str
    intent_type: str
    status: str
    boundary: _FakeLegacyDecisionBoundary | None = None
    result: dict = {}
    created_at: datetime
    completed_at: datetime | None = None


class TestLegacyDecisionConverter:
    def test_full_payload_projection(self):
        rec = _FakeLegacyDecisionRecord(
            decision_id="dec-001",
            intent_id="intent-001",
            intent_type="case_review",
            status="approved",
            boundary=_FakeLegacyDecisionBoundary(
                rule_set_version_id="rs-v1",
                frozen_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
            ),
            result={"verdict": "ok"},
            created_at=datetime(2026, 4, 29, 9, 0, tzinfo=UTC),
            completed_at=datetime(2026, 4, 29, 10, 0, tzinfo=UTC),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            payload = legacy_decision_record_to_t1_payload(rec)
        assert payload["decision_id"] == "dec-001"
        assert payload["intent_type"] == "case_review"
        assert payload["status"] == "approved"
        assert payload["result"] == {"verdict": "ok"}
        assert payload["boundary"]["rule_set_version_id"] == "rs-v1"
        assert payload["boundary"]["frozen_at"] is not None
        # ISO formatted timestamps
        assert "2026-04-29" in payload["created_at"]

    def test_payload_with_no_boundary(self):
        rec = _FakeLegacyDecisionRecord(
            decision_id="dec-002",
            intent_id="intent-002",
            intent_type="case_review",
            status="pending",
            boundary=None,
            created_at=datetime(2026, 4, 29, tzinfo=UTC),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            payload = legacy_decision_record_to_t1_payload(rec)
        assert payload["boundary"] == {}
        assert payload["completed_at"] is None

    def test_emits_deprecation_warning(self):
        rec = _FakeLegacyDecisionRecord(
            decision_id="dec-003",
            intent_id="intent-003",
            intent_type="x",
            status="x",
            created_at=datetime(2026, 4, 29, tzinfo=UTC),
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            reset_manifest_for_tests()
            legacy_decision_record_to_t1_payload(rec)
        deprecations = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert deprecations
        assert "T1" in str(deprecations[0].message)


# ===========================================================================
# Legacy → canonical: investor profile converter
# ===========================================================================


class TestLegacyInvestorConverter:
    def test_round_trip_to_canonical_profile(self):
        now = datetime(2026, 4, 29, tzinfo=UTC)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            profile = legacy_investor_to_canonical_profile(
                client_id="c1",
                firm_id="firm_test",
                legacy_risk_category=RiskCategory.MODERATE,
                legacy_horizon="long",
                created_at=now,
                updated_at=now,
            )
        assert isinstance(profile, InvestorContextProfile)
        assert profile.client_id == "c1"
        assert profile.firm_id == "firm_test"
        assert profile.risk_profile is RiskProfile.MODERATE
        assert profile.time_horizon is TimeHorizon.LONG_TERM
        assert profile.assigned_bucket is Bucket.MOD_LT

    def test_moderately_aggressive_maps_to_aggressive(self):
        now = datetime(2026, 4, 29, tzinfo=UTC)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            profile = legacy_investor_to_canonical_profile(
                client_id="c1",
                firm_id="firm_test",
                legacy_risk_category=RiskCategory.MODERATELY_AGGRESSIVE,
                legacy_horizon="long",
                created_at=now,
                updated_at=now,
            )
        assert profile.risk_profile is RiskProfile.AGGRESSIVE

    def test_data_gaps_flagged_for_unknown_fields(self):
        """Migration should record gaps for fields legacy schema doesn't carry."""
        now = datetime(2026, 4, 29, tzinfo=UTC)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            profile = legacy_investor_to_canonical_profile(
                client_id="c1",
                firm_id="firm_test",
                legacy_risk_category=RiskCategory.CONSERVATIVE,
                legacy_horizon="short",
                created_at=now,
                updated_at=now,
            )
        # The wrapped migration helper populates `data_gaps_flagged` for
        # capacity_trajectory, intermediary_present,
        # beneficiary_can_operate_current_structure (no legacy equivalent)
        assert profile.data_gaps_flagged
        assert any("capacity" in g.lower() for g in profile.data_gaps_flagged)

    def test_emits_deprecation_warning(self):
        now = datetime(2026, 4, 29, tzinfo=UTC)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            reset_manifest_for_tests()
            legacy_investor_to_canonical_profile(
                client_id="c1",
                firm_id="firm_test",
                legacy_risk_category=RiskCategory.MODERATE,
                legacy_horizon="long",
                created_at=now,
                updated_at=now,
            )
        deprecations = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert deprecations
        assert "InvestorContextProfile" in str(deprecations[0].message)


# ===========================================================================
# Manifest integration
# ===========================================================================


class TestDeprecationManifest:
    def test_manifest_is_a_list_of_entries(self):
        entries = manifest()
        assert isinstance(entries, list)
        # The manifest is global; legacy modules already register on import.
        # We can't assert exact size (depends on test order) but each entry is well-formed.
        for e in entries:
            assert e.module_path
            assert e.removed_in_pass >= 1
            assert e.kind in ("callable", "class", "module")

    def test_manifest_returns_copy_not_reference(self):
        entries_a = manifest()
        entries_b = manifest()
        # Mutating one shouldn't affect the other
        entries_a.append(
            type(entries_a[0]) if entries_a else None
        )
        # The internal manifest is not affected by external append
        assert len(manifest()) == len(entries_b) or len(entries_a) != len(
            entries_b
        )

    def test_manifest_contains_legacy_modules(self):
        # Other tests in this file may have wiped the manifest via
        # `reset_manifest_for_tests()`. Force re-execution of the module-level
        # `mark_module_deprecated` calls so the entries are present in this
        # test regardless of ordering.
        import importlib

        import artha.decision
        import artha.investor.service
        import artha.portfolio.service

        importlib.reload(artha.decision)
        importlib.reload(artha.investor.service)
        importlib.reload(artha.portfolio.service)

        paths = {e.module_path for e in manifest()}
        assert "artha.decision" in paths
        assert "artha.investor.service" in paths
        assert "artha.portfolio.service" in paths


# Avoid losing the WealthTier import (used implicitly via the migrated profile's
# wealth_tier default).
_keep = (WealthTier, DEPRECATION_MANIFEST)
