"""Cluster 5 chunk 5.4 — dispatch registry tests.

Pins:

- The 16-agent canonical inventory matches FR 20.1 §2 + §1.4.
- ``dispatch_stub`` returns the right ``produced_via`` per is_seed_data.
- Seed-fixture lookup honours ``ARTHA_SEED_FIXTURE`` override + caches.
- Unknown agent_ids raise KeyError.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from artha.api_v2.cases import dispatch
from artha.api_v2.cases.dispatch import (
    STUB_DISPATCH,
    StageKind,
    StubResult,
    dispatch_stub,
    list_dispatchable_agent_ids,
)
from artha.api_v2.cases.state_machine import ProducedVia


class _FakeCase:
    def __init__(
        self,
        *,
        case_id: str = "01HQZTEST00000000000000001",
        is_seed_data: bool = False,
        seed_archetype_id: str | None = None,
        applicable_evidence_agents: tuple[str, ...] = (),
    ) -> None:
        self.case_id = case_id
        self.is_seed_data = is_seed_data
        self.seed_archetype_id = seed_archetype_id
        self.applicable_evidence_agents = list(applicable_evidence_agents)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


class TestInventory:
    def test_sixteen_agents_dispatched(self) -> None:
        assert len(STUB_DISPATCH) == 16

    @pytest.mark.parametrize(
        "agent_id,stage_kind",
        [
            ("m0_portfolio_risk_analytics", StageKind.PORTFOLIO_RISK),
            ("e1_listed_fundamental_equity", StageKind.EVIDENCE),
            ("e2_industry_business", StageKind.EVIDENCE),
            ("e3_macro_policy_news", StageKind.EVIDENCE),
            ("e4_behavioural_historical", StageKind.EVIDENCE),
            ("e5_unlisted_equity", StageKind.EVIDENCE),
            ("e6_pms_aif_sif", StageKind.EVIDENCE),
            ("e7_mutual_fund", StageKind.EVIDENCE),
            ("s1_case_mode", StageKind.SYNTHESIS),
            ("s1_diagnostic_mode", StageKind.SYNTHESIS),
            ("s1_briefing_mode", StageKind.SYNTHESIS),
            ("ic1_chair", StageKind.IC1),
            ("g1_mandate_gate", StageKind.GOVERNANCE),
            ("g2_sebi_regulatory_gate", StageKind.GOVERNANCE),
            ("g3_action_filter_gate", StageKind.GOVERNANCE),
            ("a1_challenge", StageKind.A1),
        ],
    )
    def test_each_agent_mapped_to_stage_kind(
        self, agent_id: str, stage_kind: str
    ) -> None:
        entry = STUB_DISPATCH[agent_id]
        assert entry.agent_id == agent_id
        assert entry.stage_kind == stage_kind
        assert callable(entry.stub_fn)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_dispatch_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            dispatch_stub(case=_FakeCase(), agent_id="not_a_real_agent")

    def test_dispatch_returns_stub_result(self) -> None:
        result = dispatch_stub(
            case=_FakeCase(), agent_id="e1_listed_fundamental_equity",
        )
        assert isinstance(result, StubResult)
        assert result.agent_id == "e1_listed_fundamental_equity"
        assert result.stage_kind == StageKind.EVIDENCE
        assert result.produced_via == ProducedVia.LOOKUP_STUB_PLACEHOLDER

    def test_seed_case_marks_produced_via_seed(self) -> None:
        case = _FakeCase(is_seed_data=True, seed_archetype_id="aarav_sharma")
        result = dispatch_stub(case=case, agent_id="e1_listed_fundamental_equity")
        assert result.produced_via == ProducedVia.LOOKUP_STUB_SEED

    def test_list_dispatchable_returns_sixteen(self) -> None:
        ids = list_dispatchable_agent_ids()
        assert len(ids) == 16


# ---------------------------------------------------------------------------
# Seed fixture lookup
# ---------------------------------------------------------------------------


class TestSeedFixture:
    def test_missing_fixture_returns_empty(self, tmp_path: Path) -> None:
        dispatch.set_seed_fixture_path(tmp_path / "absent.json")
        try:
            assert dispatch.load_seed_fixture() == {}
        finally:
            dispatch.set_seed_fixture_path(None)

    def test_loaded_fixture_cached(self, tmp_path: Path) -> None:
        path = tmp_path / "seed.json"
        path.write_text(
            json.dumps({"aarav_sharma": {"foo": "bar"}}),
            encoding="utf-8",
        )
        dispatch.set_seed_fixture_path(path)
        try:
            a = dispatch.load_seed_fixture()
            assert a == {"aarav_sharma": {"foo": "bar"}}
            # Mutate the file — cache returns the original.
            path.write_text(
                json.dumps({"aarav_sharma": {"foo": "changed"}}),
                encoding="utf-8",
            )
            b = dispatch.load_seed_fixture()
            assert b == {"aarav_sharma": {"foo": "bar"}}
            # Reset cache → picks up the change.
            dispatch.reset_seed_cache()
            c = dispatch.load_seed_fixture()
            assert c == {"aarav_sharma": {"foo": "changed"}}
        finally:
            dispatch.set_seed_fixture_path(None)

    def test_seed_payload_for_seeded_case(self, tmp_path: Path) -> None:
        path = tmp_path / "seed.json"
        payload = {
            "aarav_sharma": {
                "evidence.e1_listed_fundamental_equity": {
                    "agent_id": "e1_listed_fundamental_equity",
                    "risk_level": "low",
                    "confidence": 0.9,
                    "drivers": {},
                    "flags": {},
                    "structured_output": {"verdict_summary": "Seeded"},
                    "reasoning_summary": "Seeded.",
                },
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        dispatch.set_seed_fixture_path(path)
        try:
            case = _FakeCase(is_seed_data=True, seed_archetype_id="aarav_sharma")
            seed = dispatch.get_seed_payload_for(case)
            assert "evidence.e1_listed_fundamental_equity" in seed
            # Dispatch picks up the seed payload (not the placeholder).
            result = dispatch.dispatch_stub(
                case=case, agent_id="e1_listed_fundamental_equity",
            )
            assert (
                result.payload["structured_output"]["verdict_summary"]
                == "Seeded"
            )
        finally:
            dispatch.set_seed_fixture_path(None)

    def test_non_seeded_case_returns_empty_payload(self) -> None:
        case = _FakeCase(is_seed_data=False)
        assert dispatch.get_seed_payload_for(case) == {}
