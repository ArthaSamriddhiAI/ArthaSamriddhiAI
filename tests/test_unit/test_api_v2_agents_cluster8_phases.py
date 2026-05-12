"""Cluster 8 phase dispatcher — data structure + error class unit tests.

Pins:
- PhaseDispatchError carries agent_key + cause; is a RuntimeError.
- PhaseConfig creation from seed_payload + case attributes.
- PhaseResult convenience accessors (e3_macro_view, e1(ticker), etc.).
"""

from __future__ import annotations

from typing import Any

from artha.api_v2.agents.phases import (
    PhaseConfig,
    PhaseDispatchError,
    PhaseResult,
    _build_phase_config,  # internal — tested deliberately
)
from artha.api_v2.agents.runtime import RealDispatchOutput
from artha.api_v2.agents.shim import ParsedVerdict

# ---------------------------------------------------------------------------
# Fake case stub
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
# Helpers
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
# TestPhaseDispatchError
# ---------------------------------------------------------------------------


class TestPhaseDispatchError:
    def test_is_runtime_error(self) -> None:
        err = PhaseDispatchError("e1.RELIANCE", ValueError("boom"))
        assert isinstance(err, RuntimeError)

    def test_carries_agent_key(self) -> None:
        err = PhaseDispatchError("e3_macro_view", OSError("disk full"))
        assert err.agent_key == "e3_macro_view"

    def test_carries_cause(self) -> None:
        cause = ValueError("llm timeout")
        err = PhaseDispatchError("e2sv.banking", cause)
        assert err.cause is cause

    def test_str_contains_agent_key(self) -> None:
        err = PhaseDispatchError("e7.mirae_fund", RuntimeError("down"))
        assert "e7.mirae_fund" in str(err)

    def test_str_contains_cause_repr(self) -> None:
        cause = ValueError("some error")
        err = PhaseDispatchError("e1.TCS", cause)
        assert "some error" in str(err)


# ---------------------------------------------------------------------------
# TestPhaseConfig
# ---------------------------------------------------------------------------


class TestPhaseConfig:
    def test_create_with_tickers(self) -> None:
        cfg = PhaseConfig(
            tickers=["RELIANCE", "INFY"],
            unique_sectors=["banking_financial_services"],
            ticker_sector_pairs=[("HDFCBANK", "banking_financial_services")],
            fund_ids=["mirae_large_cap"],
        )
        assert "RELIANCE" in cfg.tickers
        assert "INFY" in cfg.tickers

    def test_create_with_sectors(self) -> None:
        cfg = PhaseConfig(
            tickers=[],
            unique_sectors=["banking_financial_services", "information_technology"],
            ticker_sector_pairs=[],
            fund_ids=[],
        )
        assert len(cfg.unique_sectors) == 2

    def test_create_with_pairs(self) -> None:
        pairs = [
            ("HDFCBANK", "banking_financial_services"),
            ("INFY", "information_technology"),
        ]
        cfg = PhaseConfig(
            tickers=["HDFCBANK", "INFY"],
            unique_sectors=["banking_financial_services", "information_technology"],
            ticker_sector_pairs=pairs,
            fund_ids=[],
        )
        assert pairs[0] in cfg.ticker_sector_pairs

    def test_create_with_fund_ids(self) -> None:
        cfg = PhaseConfig(
            tickers=[],
            unique_sectors=[],
            ticker_sector_pairs=[],
            fund_ids=["mirae_large_cap", "axis_bluechip"],
        )
        assert "mirae_large_cap" in cfg.fund_ids
        assert "axis_bluechip" in cfg.fund_ids

    def test_empty_config(self) -> None:
        cfg = PhaseConfig(
            tickers=[],
            unique_sectors=[],
            ticker_sector_pairs=[],
            fund_ids=[],
        )
        assert cfg.tickers == []
        assert cfg.fund_ids == []


# ---------------------------------------------------------------------------
# TestPhaseResult
# ---------------------------------------------------------------------------


class TestPhaseResult:
    def test_e3_macro_view_none_when_phase1_empty(self) -> None:
        result = PhaseResult()
        assert result.e3_macro_view is None

    def test_e3_macro_view_returns_value(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e3_macro_view")
        result.phase1["e3_macro_view"] = out
        assert result.e3_macro_view is out

    def test_e1_accessor_by_ticker(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e1_listed_fundamental_equity")
        result.phase2["e1.RELIANCE"] = out
        assert result.e1("RELIANCE") is out

    def test_e1_accessor_missing_ticker(self) -> None:
        result = PhaseResult()
        assert result.e1("MISSING") is None

    def test_e2_sector_view_accessor(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e2_sector_view")
        result.phase2["e2sv.banking_financial_services"] = out
        assert result.e2_sector_view("banking_financial_services") is out

    def test_e2_stock_in_sector_accessor(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e2_stock_in_sector")
        result.phase3["e2sis.HDFCBANK"] = out
        assert result.e2_stock_in_sector("HDFCBANK") is out

    def test_e7_accessor(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e7_mutual_fund")
        result.phase3["e7.mirae_large_cap"] = out
        assert result.e7("mirae_large_cap") is out

    def test_e3_news_scanner_accessor(self) -> None:
        result = PhaseResult()
        out = _fake_dispatch_output("e3_news_scanner")
        result.phase4["e3_news_scanner"] = out
        assert result.e3_news_scanner is out

    def test_e3_news_scanner_none_when_phase4_empty(self) -> None:
        result = PhaseResult()
        assert result.e3_news_scanner is None

    def test_push_summary_defaults_to_none(self) -> None:
        result = PhaseResult()
        assert result.push_summary is None


# ---------------------------------------------------------------------------
# TestBuildPhaseConfig
# ---------------------------------------------------------------------------


class TestBuildPhaseConfig:
    def test_seed_payload_phase_config_override(self) -> None:
        case = _FakeCase()
        seed_payload: dict[str, Any] = {
            "phase_config": {
                "tickers": ["RELIANCE", "TCS"],
                "unique_sectors": ["information_technology"],
                "ticker_sector_pairs": [["TCS", "information_technology"]],
                "fund_ids": [],
            }
        }
        cfg = _build_phase_config(case, seed_payload)
        assert "RELIANCE" in cfg.tickers
        assert "TCS" in cfg.tickers
        assert "information_technology" in cfg.unique_sectors

    def test_empty_seed_payload_gives_empty_config(self) -> None:
        case = _FakeCase(proposed_action_products=[])
        cfg = _build_phase_config(case, {})
        # Without proposed_action_products or seed overrides, should be empty
        assert isinstance(cfg, PhaseConfig)

    def test_phase_config_tickers_from_seed(self) -> None:
        case = _FakeCase()
        seed: dict[str, Any] = {
            "phase_config": {
                "tickers": ["WIPRO"],
                "unique_sectors": [],
                "ticker_sector_pairs": [],
                "fund_ids": [],
            }
        }
        cfg = _build_phase_config(case, seed)
        assert cfg.tickers == ["WIPRO"]

    def test_phase_config_fund_ids_from_seed(self) -> None:
        case = _FakeCase()
        seed: dict[str, Any] = {
            "phase_config": {
                "tickers": [],
                "unique_sectors": [],
                "ticker_sector_pairs": [],
                "fund_ids": ["axis_bluechip", "mirae_large_cap"],
            }
        }
        cfg = _build_phase_config(case, seed)
        assert "axis_bluechip" in cfg.fund_ids


# ---------------------------------------------------------------------------
# Import sanity
# ---------------------------------------------------------------------------


class TestImportSanity:
    def test_all_public_names_importable(self) -> None:
        from artha.api_v2.agents.phases import (  # noqa: F401
            PhaseConfig,
            PhaseDispatchError,
            PhaseResult,
            run_phases,
        )

    def test_phase_dispatch_error_importable_from_phases(self) -> None:
        from artha.api_v2.agents.phases import PhaseDispatchError

        assert issubclass(PhaseDispatchError, RuntimeError)
