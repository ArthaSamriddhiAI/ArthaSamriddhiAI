"""Cluster 3 chunk 3.1 — D0 framework pure-function test suite.

Covers the framework pieces in isolation:

- :class:`D0Adapter` ABC contract + :class:`AdapterRunResult` shape.
- :mod:`registry` register / lookup / list / reset semantics.
- :mod:`freshness` threshold lookup + freshness_status computation +
  human-friendly threshold rendering.
- :mod:`staging` content-hash determinism + size computation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from artha.api_v2.d0 import freshness, registry, staging
from artha.api_v2.d0.adapter_base import (
    AdapterError,
    AdapterHealth,
    AdapterRunResult,
    D0Adapter,
)

# ---------------------------------------------------------------------------
# Adapter base + registry
# ---------------------------------------------------------------------------


class _StubAdapter(D0Adapter):
    """Trivial adapter for registry tests."""

    def __init__(self, source_id: str, entity_types: list[str]):
        self._source_id = source_id
        self._entity_types = entity_types

    @property
    def source_identifier(self) -> str:
        return self._source_id

    @property
    def supported_entity_types(self) -> list[str]:
        return self._entity_types

    async def run(self, db, *, mode: str = "full") -> AdapterRunResult:  # noqa: ARG002
        now = datetime.now(timezone.utc)
        return AdapterRunResult(
            run_id="01STUB",
            started_at=now,
            completed_at=now,
            status="success",
        )

    async def health_check(self) -> AdapterHealth:
        return AdapterHealth(healthy=True)


@pytest.fixture(autouse=True)
def reset_registry_between_tests():
    registry.reset_registry()
    yield
    registry.reset_registry()


class TestAdapterRegistry:
    def test_register_and_lookup_by_source_identifier(self):
        adapter = _StubAdapter("test_source", ["Instrument"])
        registry.register_adapter(adapter)
        retrieved = registry.get_adapter("test_source")
        assert retrieved is adapter

    def test_lookup_unknown_source_raises(self):
        with pytest.raises(registry.AdapterNotRegisteredError):
            registry.get_adapter("nonexistent_source")

    def test_list_adapters_sorted_by_source_identifier(self):
        registry.register_adapter(_StubAdapter("zeta", ["Instrument"]))
        registry.register_adapter(_StubAdapter("alpha", ["MacroSnapshot"]))
        registry.register_adapter(_StubAdapter("mu", ["IndustryReport"]))
        adapters = registry.list_adapters()
        assert [a.source_identifier for a in adapters] == ["alpha", "mu", "zeta"]

    def test_reregister_replaces_previous_entry(self):
        first = _StubAdapter("source", ["A"])
        second = _StubAdapter("source", ["B"])
        registry.register_adapter(first)
        registry.register_adapter(second)
        assert registry.get_adapter("source") is second

    def test_adapter_error_dataclass_carries_metadata(self):
        err = AdapterError(
            error_type="schema_mismatch",
            message="missing field",
            record_identifier="rec-123",
            metadata={"field": "ticker"},
        )
        assert err.error_type == "schema_mismatch"
        assert err.metadata == {"field": "ticker"}


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_thresholds_between_tests():
    freshness.reset_thresholds()
    yield
    freshness.reset_thresholds()


class TestFreshnessComputation:
    def test_fresh_when_age_below_threshold(self):
        # Threshold for instruments is 24 hours; 1-hour age is fresh.
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        last = now - timedelta(hours=1)
        result = freshness.compute_freshness(
            entity_table="instruments", last_modified_at=last, now=now
        )
        assert result.status == "fresh"
        assert result.threshold_seconds == 86_400

    def test_stale_when_age_exceeds_threshold_below_2x(self):
        # 30-hour age (between 24h and 48h) → stale.
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        last = now - timedelta(hours=30)
        result = freshness.compute_freshness(
            entity_table="instruments", last_modified_at=last, now=now
        )
        assert result.status == "stale"

    def test_very_stale_when_age_exceeds_2x_threshold(self):
        # 50-hour age (>48h) → very_stale.
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        last = now - timedelta(hours=50)
        result = freshness.compute_freshness(
            entity_table="instruments", last_modified_at=last, now=now
        )
        assert result.status == "very_stale"

    def test_none_last_modified_is_very_stale(self):
        result = freshness.compute_freshness(
            entity_table="instruments", last_modified_at=None
        )
        assert result.status == "very_stale"

    def test_naive_datetime_treated_as_utc(self):
        # Naïve datetime (no tzinfo) is silently coerced to UTC.
        now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
        last = datetime(2026, 5, 5, 11, 0, 0)  # naïve
        result = freshness.compute_freshness(
            entity_table="instruments", last_modified_at=last, now=now
        )
        assert result.status == "fresh"

    def test_unknown_entity_table_falls_back_to_one_year_threshold(self):
        threshold = freshness.get_threshold_seconds("nonexistent_table")
        assert threshold == 31_536_000

    @pytest.mark.parametrize(
        "table,expected_seconds",
        [
            ("instruments", 86_400),
            ("macro_snapshots", 604_800),
            ("industry_reports", 7_776_000),
            ("investors", 2_592_000),
            ("mandates", 31_536_000),
        ],
    )
    def test_default_thresholds_match_fr_10_5_section_2_1(self, table, expected_seconds):
        assert freshness.get_threshold_seconds(table) == expected_seconds

    def test_threshold_override_persists(self):
        freshness.set_freshness_threshold("instruments", 3_600)
        assert freshness.get_threshold_seconds("instruments") == 3_600

    def test_threshold_human_renders_friendly(self):
        # 86400s = 1 day; 604800s = 7 days; 31536000s = 1 year.
        assert freshness.threshold_as_human(86_400) == "1 day"
        assert freshness.threshold_as_human(604_800) == "7 days"
        assert freshness.threshold_as_human(31_536_000) == "1 year"
        assert freshness.threshold_as_human(7_776_000) == "3 months"


# ---------------------------------------------------------------------------
# Staging content hashing
# ---------------------------------------------------------------------------


class TestStagingContentHash:
    def test_hash_is_deterministic(self):
        h1 = staging.compute_content_hash({"a": 1, "b": 2})
        h2 = staging.compute_content_hash({"b": 2, "a": 1})  # different dict order
        assert h1 == h2  # canonical_json sorts keys

    def test_different_content_produces_different_hash(self):
        h1 = staging.compute_content_hash({"a": 1})
        h2 = staging.compute_content_hash({"a": 2})
        assert h1 != h2

    def test_canonical_json_bytes_uses_sorted_keys(self):
        # Canonical form is deterministic regardless of insertion order.
        a = staging.canonical_json_bytes({"z": 1, "a": 2, "m": 3})
        b = staging.canonical_json_bytes({"a": 2, "m": 3, "z": 1})
        assert a == b

    def test_canonical_json_no_whitespace(self):
        result = staging.canonical_json_bytes({"k": [1, 2, 3]})
        # No spaces in the canonical form.
        assert b" " not in result
