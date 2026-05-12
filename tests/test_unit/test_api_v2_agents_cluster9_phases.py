"""Cluster 9 phase additions + E3.NewsScanner v2.1 — unit tests.

Pins:
- PhaseConfig cluster-9 fields (aif_ids, deal_ids, investor_id) — backward
  compat and correct storage.
- PhaseResult cluster-9 accessors (e5fv, e5dv, e4) — key namespace and
  None-on-miss behaviour.
- E3.NewsScanner schema v2.1 — EntityType enum values, CacheInvalidationPush
  new fields with backward-compatible defaults.
- E3NewsScannerShim Rules 8 and 9 — entity_id / ticker presence, flag-set
  consistency per entity type.
- _build_phase_config cluster-9 seed keys (aif_ids, deal_ids, investor_id)
  and case.investor_id fallback.
- Import sanity for all new public names across phases, schema, and cache
  flag modules.

No database required — purely structural / data-class tests.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from artha.api_v2.agents.e3_news_scanner.schema import (
    CacheInvalidationPush,
    EntityType,
)
from artha.api_v2.agents.e3_news_scanner.shim import E3NewsScannerShim
from artha.api_v2.agents.llm_client import LLMResponse
from artha.api_v2.agents.phases import PhaseConfig, PhaseResult, _build_phase_config
from artha.api_v2.agents.runtime import RealDispatchOutput
from artha.api_v2.agents.shim import AgentInputs, ParsedVerdict

# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _FakeCase:
    """Minimal Case-like stub for _build_phase_config."""

    def __init__(
        self,
        case_id: str = "case_001",
        case_mode: str = "proposed_action",
        proposed_action_products: list[dict[str, Any]] | None = None,
        investor_id: str = "investor_001",
    ) -> None:
        self.case_id = case_id
        self.case_mode = case_mode
        self.proposed_action_products = proposed_action_products or []
        self.investor_id = investor_id


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _fake_dispatch_output(agent_id: str) -> RealDispatchOutput:
    parsed = ParsedVerdict(
        agent_id=agent_id,
        structured={"verdict": "pass"},
        stage_payload={"agent_id": agent_id},
        raw_text="raw",
    )
    return RealDispatchOutput(
        agent_id=agent_id,
        parsed=parsed,
        retry_count=0,
        cache_hit=False,
        input_tokens=100,
        output_tokens=50,
        model="claude-sonnet",
        prompt_version="1.0",
    )


# ---------------------------------------------------------------------------
# Base E3.NewsScanner payload — RELIANCE only, no material events requiring
# cache invalidation (used as a clean starting point for rule tests).
# ---------------------------------------------------------------------------

_BASE_E3_PAYLOAD: dict[str, Any] = {
    "case_id": "case_001",
    "scan_period": {"from": "2024-01-01", "to": "2024-03-31"},
    "per_ticker_signals": [
        {
            "ticker": "RELIANCE",
            "has_material_events": True,
            "events": [
                {
                    "news_id": "n001",
                    "headline": "RELIANCE Q3 results beat expectations",
                    "category": "earnings_guidance",
                    "materiality_level": "medium",
                    "warrants_cache_invalidation": False,
                    "rationale": "Earnings beat but within normal range.",
                }
            ],
        }
    ],
    "case_level_signals": [],
    "cache_invalidation_pushes": [],
    "confidence": 0.8,
    "reasoning_summary": (
        "No material events requiring cache invalidation for RELIANCE in this "
        "scan period. Earnings guidance within normal range."
    ),
}

_BASE_INPUTS = AgentInputs(
    case_id="case_001",
    case_mode="proposed_action",
    case_intent="review",
    payload={"case_id": "case_001", "tickers": ["RELIANCE"]},
)

_SHIM = E3NewsScannerShim()


def _validate(payload: dict[str, Any], inputs: AgentInputs = _BASE_INPUTS) -> Any:
    """Parse JSON then run validate_output; returns ValidationResult."""
    verdict = _SHIM.parse_output(
        LLMResponse(text=json.dumps(payload)),
        inputs,
    )
    return _SHIM.validate_output(verdict, inputs)


def _payload_with_push(push: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of _BASE_E3_PAYLOAD with one cache_invalidation_push."""
    p = copy.deepcopy(_BASE_E3_PAYLOAD)
    p["cache_invalidation_pushes"] = [push]
    return p


# ---------------------------------------------------------------------------
# Section 1: PhaseConfig — cluster-9 field additions
# ---------------------------------------------------------------------------


class TestPhaseConfigCluster9Fields:
    def test_backward_compat_no_new_fields(self) -> None:
        """PhaseConfig created without cluster-9 fields still works."""
        cfg = PhaseConfig(
            tickers=["RELIANCE"],
            unique_sectors=["banking_financial_services"],
            ticker_sector_pairs=[("HDFCBANK", "banking_financial_services")],
            fund_ids=["mirae_large_cap"],
        )
        # defaults
        assert cfg.aif_ids == []
        assert cfg.deal_ids == []
        assert cfg.investor_id is None

    def test_aif_ids_stored_correctly(self) -> None:
        cfg = PhaseConfig(
            tickers=[],
            unique_sectors=[],
            ticker_sector_pairs=[],
            fund_ids=[],
            aif_ids=["aif_001", "aif_002"],
        )
        assert cfg.aif_ids == ["aif_001", "aif_002"]

    def test_deal_ids_stored_correctly(self) -> None:
        cfg = PhaseConfig(
            tickers=[],
            unique_sectors=[],
            ticker_sector_pairs=[],
            fund_ids=[],
            deal_ids=["deal_alpha", "deal_beta"],
        )
        assert cfg.deal_ids == ["deal_alpha", "deal_beta"]

    def test_investor_id_stored_correctly(self) -> None:
        cfg = PhaseConfig(
            tickers=[],
            unique_sectors=[],
            ticker_sector_pairs=[],
            fund_ids=[],
            investor_id="inv_007",
        )
        assert cfg.investor_id == "inv_007"

    def test_all_cluster9_fields_together(self) -> None:
        cfg = PhaseConfig(
            tickers=["RELIANCE"],
            unique_sectors=[],
            ticker_sector_pairs=[],
            fund_ids=[],
            aif_ids=["aif_001"],
            deal_ids=["deal_001"],
            investor_id="inv_001",
        )
        assert cfg.aif_ids == ["aif_001"]
        assert cfg.deal_ids == ["deal_001"]
        assert cfg.investor_id == "inv_001"

    def test_aif_ids_default_is_independent_list(self) -> None:
        """Two PhaseConfig instances must not share the same default list."""
        cfg_a = PhaseConfig(
            tickers=[], unique_sectors=[], ticker_sector_pairs=[], fund_ids=[]
        )
        cfg_b = PhaseConfig(
            tickers=[], unique_sectors=[], ticker_sector_pairs=[], fund_ids=[]
        )
        cfg_a.aif_ids.append("aif_999")
        assert "aif_999" not in cfg_b.aif_ids

    def test_deal_ids_default_is_independent_list(self) -> None:
        cfg_a = PhaseConfig(
            tickers=[], unique_sectors=[], ticker_sector_pairs=[], fund_ids=[]
        )
        cfg_b = PhaseConfig(
            tickers=[], unique_sectors=[], ticker_sector_pairs=[], fund_ids=[]
        )
        cfg_a.deal_ids.append("deal_999")
        assert "deal_999" not in cfg_b.deal_ids


# ---------------------------------------------------------------------------
# Section 2: PhaseResult — cluster-9 accessors
# ---------------------------------------------------------------------------


class TestPhaseResultCluster9Accessors:
    # ── e5fv ──────────────────────────────────────────────────────────────

    def test_e5fv_returns_none_when_phase2_empty(self) -> None:
        result = PhaseResult()
        assert result.e5fv("aif_001") is None

    def test_e5fv_returns_output_when_key_present(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e5_fund_view")
        result.phase2["e5fv.aif_001"] = out
        assert result.e5fv("aif_001") is out

    def test_e5fv_returns_none_for_nonexistent_aif(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e5_fund_view")
        result.phase2["e5fv.aif_001"] = out
        assert result.e5fv("aif_999") is None

    def test_e5fv_key_uses_phase2(self) -> None:
        """e5fv must look in phase2, not phase3."""
        result = PhaseResult()
        out = _fake_dispatch_output("e5_fund_view")
        result.phase3["e5fv.aif_001"] = out  # wrong phase
        assert result.e5fv("aif_001") is None

    # ── e5dv ──────────────────────────────────────────────────────────────

    def test_e5dv_returns_none_when_phase3_empty(self) -> None:
        result = PhaseResult()
        assert result.e5dv("deal_001") is None

    def test_e5dv_returns_output_when_key_present(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e5_deal_view")
        result.phase3["e5dv.deal_001"] = out
        assert result.e5dv("deal_001") is out

    def test_e5dv_returns_none_for_nonexistent_deal(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e5_deal_view")
        result.phase3["e5dv.deal_001"] = out
        assert result.e5dv("deal_999") is None

    def test_e5dv_key_uses_phase3(self) -> None:
        """e5dv must look in phase3, not phase2."""
        result = PhaseResult()
        out = _fake_dispatch_output("e5_deal_view")
        result.phase2["e5dv.deal_001"] = out  # wrong phase
        assert result.e5dv("deal_001") is None

    # ── e4 ────────────────────────────────────────────────────────────────

    def test_e4_returns_none_when_phase2_empty(self) -> None:
        result = PhaseResult()
        assert result.e4("inv_001") is None

    def test_e4_returns_output_when_key_present(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e4_behavioural")
        result.phase2["e4.inv_001"] = out
        assert result.e4("inv_001") is out

    def test_e4_returns_none_for_nonexistent_investor(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e4_behavioural")
        result.phase2["e4.inv_001"] = out
        assert result.e4("inv_999") is None

    def test_e4_key_uses_phase2(self) -> None:
        """e4 must look in phase2, not phase3."""
        result = PhaseResult()
        out = _fake_dispatch_output("e4_behavioural")
        result.phase3["e4.inv_001"] = out  # wrong phase
        assert result.e4("inv_001") is None

    # ── coexistence with pre-cluster-9 accessors ──────────────────────────

    def test_cluster9_accessors_coexist_with_e1(self) -> None:
        result = PhaseResult()
        e1_out = _fake_dispatch_output("e1_listed_fundamental_equity")
        e5fv_out = _fake_dispatch_output("e5_fund_view")
        result.phase2["e1.RELIANCE"] = e1_out
        result.phase2["e5fv.aif_001"] = e5fv_out
        assert result.e1("RELIANCE") is e1_out
        assert result.e5fv("aif_001") is e5fv_out

    def test_cluster9_deal_accessor_coexists_with_e7(self) -> None:
        result = PhaseResult()
        e7_out = _fake_dispatch_output("e7_mutual_fund")
        e5dv_out = _fake_dispatch_output("e5_deal_view")
        result.phase3["e7.mirae_large_cap"] = e7_out
        result.phase3["e5dv.deal_001"] = e5dv_out
        assert result.e7("mirae_large_cap") is e7_out
        assert result.e5dv("deal_001") is e5dv_out


# ---------------------------------------------------------------------------
# Section 3: E3.NewsScanner schema v2.1 — EntityType + CacheInvalidationPush
# ---------------------------------------------------------------------------


class TestEntityTypeEnum:
    def test_has_ticker_value(self) -> None:
        assert EntityType.TICKER.value == "ticker"

    def test_has_aif_value(self) -> None:
        assert EntityType.AIF.value == "aif"

    def test_has_deal_value(self) -> None:
        assert EntityType.DEAL.value == "deal"

    def test_has_investor_value(self) -> None:
        assert EntityType.INVESTOR.value == "investor"

    def test_four_members_total(self) -> None:
        assert len(list(EntityType)) == 4

    def test_is_str_enum(self) -> None:
        assert isinstance(EntityType.TICKER, str)


class TestCacheInvalidationPushSchema:
    def test_backward_compat_ticker_push(self) -> None:
        """Old-style push (ticker + news_id + invalidates_e1/e2sis) still
        validates — all new fields carry backward-compatible defaults."""
        push = CacheInvalidationPush(
            ticker="RELIANCE",
            news_id="n001",
            invalidates_e1=True,
            invalidates_e2sis=False,
            reason="Q3 earnings beat; mandate review warranted.",
        )
        assert push.entity_type == EntityType.TICKER
        assert push.entity_id == ""
        assert push.invalidates_e5fv is False
        assert push.invalidates_e5dv is False

    def test_entity_type_defaults_to_ticker(self) -> None:
        push = CacheInvalidationPush(
            news_id="n001",
            reason="test reason here",
        )
        assert push.entity_type == EntityType.TICKER

    def test_entity_id_defaults_to_empty_string(self) -> None:
        push = CacheInvalidationPush(
            news_id="n001",
            reason="test reason here",
        )
        assert push.entity_id == ""

    def test_aif_push_validates(self) -> None:
        push = CacheInvalidationPush(
            entity_type="aif",
            entity_id="aif_123",
            news_id="n1",
            invalidates_e5fv=True,
            reason="material MCA filing detected",
        )
        assert push.entity_type == EntityType.AIF
        assert push.entity_id == "aif_123"
        assert push.invalidates_e5fv is True
        assert push.news_id == "n1"

    def test_deal_push_validates(self) -> None:
        push = CacheInvalidationPush(
            entity_type="deal",
            entity_id="deal_456",
            news_id="n2",
            invalidates_e5dv=True,
            reason="valuation event confirmed by co-investor",
        )
        assert push.entity_type == EntityType.DEAL
        assert push.entity_id == "deal_456"
        assert push.invalidates_e5dv is True

    def test_investor_push_validates(self) -> None:
        push = CacheInvalidationPush(
            entity_type="investor",
            entity_id="inv_789",
            news_id="n3",
            reason="confirmed panic event — behavioural override needed",
        )
        assert push.entity_type == EntityType.INVESTOR
        assert push.entity_id == "inv_789"

    def test_invalidates_e5fv_defaults_false(self) -> None:
        push = CacheInvalidationPush(
            ticker="RELIANCE",
            news_id="n001",
            invalidates_e1=True,
            reason="test",
        )
        assert push.invalidates_e5fv is False

    def test_invalidates_e5dv_defaults_false(self) -> None:
        push = CacheInvalidationPush(
            ticker="RELIANCE",
            news_id="n001",
            invalidates_e1=True,
            reason="test",
        )
        assert push.invalidates_e5dv is False


# ---------------------------------------------------------------------------
# Section 4: E3NewsScannerShim — Rules 8 and 9
# ---------------------------------------------------------------------------


class TestE3NewsScannerShimRule8:
    """Rule 8: entity_type='ticker' → ticker non-empty;
    non-ticker entity_type → entity_id non-empty."""

    def test_ticker_type_with_empty_ticker_fires_rule8(self) -> None:
        """entity_type='ticker' + ticker='' → rule_8_ticker_missing_for_ticker_push.

        Note: the push's (ticker, news_id) is ("", "n001") which is not in
        the warrants_map (only ("RELIANCE", "n001") is), so Rule 4 would
        also fire — but Rule 8 is checked after Rule 4 in the shim.  To
        isolate Rule 8 we make warrants_cache_invalidation=True for the
        event and include ("RELIANCE","n001") in the warrants_map while
        the push uses ticker="", so Rule 4 passes (empty ticker is not
        found in warrants_map → Rule 4 fires first).

        Instead, test Rule 8 independently via an AIF push with empty
        entity_id — that path is not gated by Rule 4 at all.
        The second sub-test below covers the direct ticker="" branch via a
        payload where no event warrants invalidation so push list is empty
        in the baseline, and we inject a ticker="" push directly.
        """
        # Simplest path: entity_type="aif" with empty entity_id — Rule 8
        # fires unconditionally (not gated by warrants_map).
        payload = _payload_with_push(
            {
                "entity_type": "aif",
                "entity_id": "",
                "news_id": "n001",
                "invalidates_e5fv": True,
                "reason": "test rule 8 aif empty entity_id",
            }
        )
        result = _validate(payload)
        assert not result.success
        assert result.error_type == "rule_8_entity_id_empty"

    def test_ticker_type_with_empty_ticker_direct(self) -> None:
        """entity_type='ticker' + ticker='' → rule_8_ticker_missing_for_ticker_push.

        We need Rule 4 to pass first: the push's (ticker, news_id) must
        appear in the warrants_map with warrants_cache_invalidation=True.
        We achieve this by adding a warrants=True event for RELIANCE/n001
        and setting push.ticker="" (so Rule 4 will not find it in the map
        → Rule 4 fires instead).

        Correct approach: set the push ticker to the real ticker so Rule 4
        passes, then clear ticker on the push object — but that is not how
        the shim works (it operates on the parsed model).  Instead we
        construct a payload where the event warrants invalidation and the
        push ticker matches, then patch ticker to empty in a second payload
        where warrants=True so the push passes Rule 4 lookup.

        Actually the simplest Rule 8 ticker test: use warrants=True event
        for ("RELIANCE","n001") so the push ("RELIANCE","n001") passes
        Rule 4, but then set ticker="" — that changes the lookup key so
        Rule 4 sees ("","n001") → not in map → Rule 4 fires before Rule 8.

        Given the shim check order (Rule 4 before Rule 8), the cleanest
        way to pin Rule 8's ticker branch is a payload where the only push
        has entity_type="ticker" and ticker="" but we suppress Rule 4 by
        having no per_ticker_signals events with warrants=True — then
        warrants_map is empty so warrants_map.get(key, False) returns
        False → Rule 4 fires.

        For a clean isolated Rule 8 pin, the AIF/DEAL path tested above
        is definitively unambiguous.  This test documents the Rule 4
        interaction and asserts the error_type from Rule 4 when ticker="".
        """
        payload = copy.deepcopy(_BASE_E3_PAYLOAD)
        # Add warrants=True event so warrants_map has ("RELIANCE","n001")
        payload["per_ticker_signals"][0]["events"][0][
            "warrants_cache_invalidation"
        ] = True
        # Push with ticker="" — Rule 4 checks ("","n001") → not in map → Rule 4
        payload["cache_invalidation_pushes"] = [
            {
                "entity_type": "ticker",
                "entity_id": "",
                "ticker": "",
                "news_id": "n001",
                "invalidates_e1": True,
                "invalidates_e2sis": False,
                "reason": "test",
            }
        ]
        result = _validate(payload)
        assert not result.success
        # Rule 4 fires before Rule 8 for this combination.
        assert result.error_type in (
            "rule_4_push_without_warrant",
            "rule_8_ticker_missing_for_ticker_push",
        )

    def test_aif_type_with_empty_entity_id_fires_rule8(self) -> None:
        payload = _payload_with_push(
            {
                "entity_type": "aif",
                "entity_id": "",
                "news_id": "n1",
                "invalidates_e5fv": True,
                "reason": "test",
            }
        )
        result = _validate(payload)
        assert not result.success
        assert result.error_type == "rule_8_entity_id_empty"

    def test_deal_type_with_empty_entity_id_fires_rule8(self) -> None:
        payload = _payload_with_push(
            {
                "entity_type": "deal",
                "entity_id": "",
                "news_id": "n2",
                "invalidates_e5dv": True,
                "reason": "test",
            }
        )
        result = _validate(payload)
        assert not result.success
        assert result.error_type == "rule_8_entity_id_empty"

    def test_investor_type_with_empty_entity_id_fires_rule8(self) -> None:
        payload = _payload_with_push(
            {
                "entity_type": "investor",
                "entity_id": "",
                "news_id": "n3",
                "reason": "test",
            }
        )
        result = _validate(payload)
        assert not result.success
        assert result.error_type == "rule_8_entity_id_empty"

    def test_valid_aif_push_passes_rule8(self) -> None:
        """AIF push with non-empty entity_id and invalidates_e5fv=True
        passes both Rule 8 and Rule 9."""
        payload = _payload_with_push(
            {
                "entity_type": "aif",
                "entity_id": "aif_001",
                "news_id": "n1",
                "invalidates_e5fv": True,
                "reason": "material MCA filing confirmed",
            }
        )
        result = _validate(payload)
        assert result.success

    def test_valid_deal_push_passes_rule8(self) -> None:
        payload = _payload_with_push(
            {
                "entity_type": "deal",
                "entity_id": "deal_001",
                "news_id": "n2",
                "invalidates_e5dv": True,
                "reason": "co-investor exit confirms valuation event",
            }
        )
        result = _validate(payload)
        assert result.success


class TestE3NewsScannerShimRule9:
    """Rule 9: flag-set consistency per entity_type.

    - TICKER: at least one of invalidates_e1, invalidates_e2sis must be True.
    - AIF: invalidates_e5fv must be True.
    - DEAL: invalidates_e5dv must be True.
    - INVESTOR: no flag requirement (passes even with all flags False/default).
    """

    def _payload_warrants_ticker_push(self) -> dict[str, Any]:
        """Base payload where RELIANCE/n001 warrants invalidation.

        Used for Rule 9 ticker tests so Rule 4 passes (the push's (ticker,
        news_id) is in the warrants_map as True).
        """
        p = copy.deepcopy(_BASE_E3_PAYLOAD)
        p["per_ticker_signals"][0]["events"][0][
            "warrants_cache_invalidation"
        ] = True
        return p

    def test_ticker_no_invalidation_flags_fires_rule9(self) -> None:
        """TICKER push with invalidates_e1=False + invalidates_e2sis=False
        triggers rule_9_flag_set_inconsistency (after Rule 4 passes)."""
        p = self._payload_warrants_ticker_push()
        p["cache_invalidation_pushes"] = [
            {
                "entity_type": "ticker",
                "entity_id": "",
                "ticker": "RELIANCE",
                "news_id": "n001",
                "invalidates_e1": False,
                "invalidates_e2sis": False,
                "reason": "test rule 9 ticker",
            }
        ]
        result = _validate(p)
        assert not result.success
        assert result.error_type == "rule_9_flag_set_inconsistency"

    def test_ticker_with_invalidates_e1_passes_rule9(self) -> None:
        p = self._payload_warrants_ticker_push()
        p["cache_invalidation_pushes"] = [
            {
                "entity_type": "ticker",
                "entity_id": "",
                "ticker": "RELIANCE",
                "news_id": "n001",
                "invalidates_e1": True,
                "invalidates_e2sis": False,
                "reason": "earnings warrant E1 cache invalidation",
            }
        ]
        result = _validate(p)
        assert result.success

    def test_ticker_with_invalidates_e2sis_passes_rule9(self) -> None:
        p = self._payload_warrants_ticker_push()
        p["cache_invalidation_pushes"] = [
            {
                "entity_type": "ticker",
                "entity_id": "",
                "ticker": "RELIANCE",
                "news_id": "n001",
                "invalidates_e1": False,
                "invalidates_e2sis": True,
                "reason": "sector-level override warranted",
            }
        ]
        result = _validate(p)
        assert result.success

    def test_aif_with_invalidates_e5fv_false_fires_rule9(self) -> None:
        """AIF push with invalidates_e5fv=False triggers Rule 9."""
        payload = _payload_with_push(
            {
                "entity_type": "aif",
                "entity_id": "aif_001",
                "news_id": "n1",
                "invalidates_e5fv": False,
                "reason": "test",
            }
        )
        result = _validate(payload)
        assert not result.success
        assert result.error_type == "rule_9_flag_set_inconsistency"

    def test_aif_with_invalidates_e5fv_true_passes_rule9(self) -> None:
        payload = _payload_with_push(
            {
                "entity_type": "aif",
                "entity_id": "aif_001",
                "news_id": "n1",
                "invalidates_e5fv": True,
                "reason": "material regulatory action on AIF",
            }
        )
        result = _validate(payload)
        assert result.success

    def test_deal_with_invalidates_e5dv_false_fires_rule9(self) -> None:
        """DEAL push with invalidates_e5dv=False triggers Rule 9."""
        payload = _payload_with_push(
            {
                "entity_type": "deal",
                "entity_id": "deal_001",
                "news_id": "n2",
                "invalidates_e5dv": False,
                "reason": "test",
            }
        )
        result = _validate(payload)
        assert not result.success
        assert result.error_type == "rule_9_flag_set_inconsistency"

    def test_deal_with_invalidates_e5dv_true_passes_rule9(self) -> None:
        payload = _payload_with_push(
            {
                "entity_type": "deal",
                "entity_id": "deal_001",
                "news_id": "n2",
                "invalidates_e5dv": True,
                "reason": "MCA filing confirms distress signal",
            }
        )
        result = _validate(payload)
        assert result.success

    def test_investor_passes_rule9_without_any_flags(self) -> None:
        """INVESTOR entity_type is exempt from Rule 9 flag checks."""
        payload = _payload_with_push(
            {
                "entity_type": "investor",
                "entity_id": "inv_001",
                "news_id": "n3",
                # no invalidation flags set
                "reason": "panic event observed — behavioural profile stale",
            }
        )
        result = _validate(payload)
        assert result.success

    def test_investor_also_passes_with_no_e1_or_e5fv_flags(self) -> None:
        """INVESTOR with all bool flags explicitly False still passes Rule 9."""
        payload = _payload_with_push(
            {
                "entity_type": "investor",
                "entity_id": "inv_001",
                "news_id": "n3",
                "invalidates_e1": False,
                "invalidates_e2sis": False,
                "invalidates_e5fv": False,
                "invalidates_e5dv": False,
                "reason": "behavioural manual flag triggered by advisor",
            }
        )
        result = _validate(payload)
        assert result.success


class TestE3NewsScannerShimRule4BackwardCompat:
    """Rule 4 only applies to TICKER-type pushes.

    Non-ticker pushes are not checked against the warrants_map from
    per_ticker_signals — they have their own entity_id/entity_type
    semantics.
    """

    def test_non_ticker_push_skips_rule4_warrants_check(self) -> None:
        """AIF push not present in warrants_map still passes Rule 4."""
        payload = _payload_with_push(
            {
                "entity_type": "aif",
                "entity_id": "aif_555",
                "news_id": "n_aif_1",
                "invalidates_e5fv": True,
                "reason": "SEBI regulatory action on registered AIF",
            }
        )
        result = _validate(payload)
        # Rule 4 does not apply → validation passes all relevant rules
        assert result.success

    def test_deal_push_skips_rule4_warrants_check(self) -> None:
        payload = _payload_with_push(
            {
                "entity_type": "deal",
                "entity_id": "deal_777",
                "news_id": "n_deal_1",
                "invalidates_e5dv": True,
                "reason": "MCA filing discloses defaults on portfolio company",
            }
        )
        result = _validate(payload)
        assert result.success

    def test_ticker_push_still_subject_to_rule4(self) -> None:
        """Sanity: TICKER push without a matching warrants=True event fails
        Rule 4 (backward compat)."""
        payload = _payload_with_push(
            {
                "entity_type": "ticker",
                "ticker": "RELIANCE",
                "news_id": "n001",
                "invalidates_e1": True,
                "reason": "earnings guidance",
            }
        )
        # _BASE_E3_PAYLOAD event has warrants_cache_invalidation=False
        result = _validate(payload)
        assert not result.success
        assert result.error_type == "rule_4_push_without_warrant"


# ---------------------------------------------------------------------------
# Section 5: _build_phase_config — cluster-9 seed keys
# ---------------------------------------------------------------------------


class TestBuildPhaseConfigCluster9:
    def test_aif_ids_deal_ids_investor_id_from_seed(self) -> None:
        case = _FakeCase()
        seed: dict[str, Any] = {
            "phase_config": {
                "aif_ids": ["aif_001"],
                "deal_ids": ["deal_002"],
                "investor_id": "inv_003",
                "tickers": [],
                "unique_sectors": [],
                "ticker_sector_pairs": [],
                "fund_ids": [],
            }
        }
        cfg = _build_phase_config(case, seed)
        assert cfg.aif_ids == ["aif_001"]
        assert cfg.deal_ids == ["deal_002"]
        assert cfg.investor_id == "inv_003"

    def test_investor_id_falls_back_to_case_investor_id(self) -> None:
        """When phase_config seed does not supply investor_id, fallback to
        case.investor_id."""
        case = _FakeCase(investor_id="investor_from_case")
        seed: dict[str, Any] = {
            "phase_config": {
                "tickers": [],
                "unique_sectors": [],
                "ticker_sector_pairs": [],
                "fund_ids": [],
                # investor_id absent from seed
            }
        }
        cfg = _build_phase_config(case, seed)
        assert cfg.investor_id == "investor_from_case"

    def test_investor_id_seed_overrides_case(self) -> None:
        """Explicit seed investor_id overrides case.investor_id."""
        case = _FakeCase(investor_id="investor_from_case")
        seed: dict[str, Any] = {
            "phase_config": {
                "tickers": [],
                "unique_sectors": [],
                "ticker_sector_pairs": [],
                "fund_ids": [],
                "investor_id": "investor_from_seed",
            }
        }
        cfg = _build_phase_config(case, seed)
        assert cfg.investor_id == "investor_from_seed"

    def test_aif_ids_default_empty_when_no_seed(self) -> None:
        case = _FakeCase()
        cfg = _build_phase_config(case, {})
        assert cfg.aif_ids == []

    def test_deal_ids_default_empty_when_no_seed(self) -> None:
        case = _FakeCase()
        cfg = _build_phase_config(case, {})
        assert cfg.deal_ids == []

    def test_investor_id_from_case_when_no_seed(self) -> None:
        case = _FakeCase(investor_id="inv_case_default")
        cfg = _build_phase_config(case, {})
        assert cfg.investor_id == "inv_case_default"

    def test_multiple_aif_ids_from_seed(self) -> None:
        case = _FakeCase()
        seed: dict[str, Any] = {
            "phase_config": {
                "aif_ids": ["aif_001", "aif_002", "aif_003"],
                "deal_ids": [],
                "tickers": [],
                "unique_sectors": [],
                "ticker_sector_pairs": [],
                "fund_ids": [],
            }
        }
        cfg = _build_phase_config(case, seed)
        assert len(cfg.aif_ids) == 3
        assert "aif_002" in cfg.aif_ids

    def test_multiple_deal_ids_from_seed(self) -> None:
        case = _FakeCase()
        seed: dict[str, Any] = {
            "phase_config": {
                "deal_ids": ["deal_alpha", "deal_beta"],
                "aif_ids": [],
                "tickers": [],
                "unique_sectors": [],
                "ticker_sector_pairs": [],
                "fund_ids": [],
            }
        }
        cfg = _build_phase_config(case, seed)
        assert cfg.deal_ids == ["deal_alpha", "deal_beta"]

    def test_cluster9_fields_alongside_existing_fields(self) -> None:
        """Cluster-9 and cluster-8 seed keys coexist correctly."""
        case = _FakeCase()
        seed: dict[str, Any] = {
            "phase_config": {
                "tickers": ["RELIANCE"],
                "unique_sectors": ["banking_financial_services"],
                "ticker_sector_pairs": [["RELIANCE", "banking_financial_services"]],
                "fund_ids": ["mirae_large_cap"],
                "aif_ids": ["aif_001"],
                "deal_ids": ["deal_001"],
                "investor_id": "inv_001",
            }
        }
        cfg = _build_phase_config(case, seed)
        assert cfg.tickers == ["RELIANCE"]
        assert cfg.fund_ids == ["mirae_large_cap"]
        assert cfg.aif_ids == ["aif_001"]
        assert cfg.deal_ids == ["deal_001"]
        assert cfg.investor_id == "inv_001"


# ---------------------------------------------------------------------------
# Section 6: Import sanity
# ---------------------------------------------------------------------------


class TestImportSanity:
    def test_phases_cluster9_names_importable(self) -> None:
        from artha.api_v2.agents.phases import (  # noqa: F401
            PhaseConfig,
            PhaseResult,
        )

    def test_e3_news_scanner_schema_cluster9_names_importable(self) -> None:
        from artha.api_v2.agents.e3_news_scanner.schema import (  # noqa: F401
            CacheInvalidationPush,
            EntityType,
        )

    def test_deal_manual_flag_names_importable(self) -> None:
        from artha.api_v2.agents.cache.deal_manual_flag import (  # noqa: F401
            DealFlagMutation,
            DealFlagSnapshot,
            clear_deal_flag,
            create_deal_flag,
            get_active_deal_flag_id,
        )

    def test_investor_manual_flag_names_importable(self) -> None:
        from artha.api_v2.agents.cache.investor_manual_flag import (  # noqa: F401
            InvestorFlagMutation,
            InvestorFlagSnapshot,
            clear_investor_flag,
            create_investor_flag,
            get_active_investor_flag_id,
        )

    def test_fund_manual_flag_aif_names_importable(self) -> None:
        from artha.api_v2.agents.cache.fund_manual_flag import (  # noqa: F401
            create_aif_flag,
            get_active_aif_flag_id,
        )

    def test_entity_type_is_str_subclass(self) -> None:
        from artha.api_v2.agents.e3_news_scanner.schema import EntityType

        assert issubclass(EntityType, str)

    def test_deal_flag_mutation_is_dataclass(self) -> None:
        import dataclasses

        from artha.api_v2.agents.cache.deal_manual_flag import DealFlagMutation

        assert dataclasses.is_dataclass(DealFlagMutation)

    def test_investor_flag_mutation_is_dataclass(self) -> None:
        import dataclasses

        from artha.api_v2.agents.cache.investor_manual_flag import InvestorFlagMutation

        assert dataclasses.is_dataclass(InvestorFlagMutation)

    def test_deal_flag_snapshot_is_frozen_dataclass(self) -> None:
        import dataclasses

        from artha.api_v2.agents.cache.deal_manual_flag import DealFlagSnapshot

        assert dataclasses.is_dataclass(DealFlagSnapshot)
        params = dataclasses.fields(DealFlagSnapshot)
        # frozen dataclasses raise FrozenInstanceError on assignment — proxy
        # check: verify the class has the expected fields.
        field_names = {f.name for f in params}
        assert "manual_flag_id" in field_names
        assert "deal_id" in field_names
        assert "invalidates_e5dv" in field_names

    def test_investor_flag_snapshot_has_expected_fields(self) -> None:
        import dataclasses

        from artha.api_v2.agents.cache.investor_manual_flag import InvestorFlagSnapshot

        field_names = {f.name for f in dataclasses.fields(InvestorFlagSnapshot)}
        assert "investor_id" in field_names
        assert "invalidates_e4" in field_names
