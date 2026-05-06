"""Cluster 4 chunk 4.1 — 3x3 cell vocabulary tests."""

from __future__ import annotations

import pytest

from artha.api_v2.m2 import cells


class TestCellEnum:
    def test_nine_cells_total(self):
        assert len(cells.ALL_CELLS) == 9

    def test_three_risk_profiles_three_horizons(self):
        assert cells.RISK_PROFILES == ("aggressive", "moderate", "conservative")
        assert cells.HORIZONS == ("long_term", "medium_term", "short_term")

    def test_cell_id_builds_canonical_form(self):
        assert cells.cell_id("moderate", "long_term") == "moderate_long_term"
        assert cells.cell_id("aggressive", "short_term") == "aggressive_short_term"

    def test_cell_id_rejects_unknown(self):
        with pytest.raises(ValueError, match="risk_profile"):
            cells.cell_id("very_aggressive", "long_term")
        with pytest.raises(ValueError, match="horizon"):
            cells.cell_id("moderate", "forever")

    def test_split_cell_round_trip(self):
        for cid in cells.ALL_CELLS:
            rp, h = cells.split_cell(cid)
            assert cells.cell_id(rp, h) == cid

    def test_split_cell_rejects_unknown(self):
        with pytest.raises(ValueError):
            cells.split_cell("garbage")

    def test_is_valid_cell(self):
        assert cells.is_valid_cell("moderate_long_term")
        assert not cells.is_valid_cell("moderate_forever")
        assert not cells.is_valid_cell("")


class TestInvestorToCell:
    @pytest.mark.parametrize(
        "risk,horizon,expected",
        [
            ("aggressive", "over_5_years", "aggressive_long_term"),
            ("aggressive", "3_to_5_years", "aggressive_medium_term"),
            ("aggressive", "under_3_years", "aggressive_short_term"),
            ("moderate", "over_5_years", "moderate_long_term"),
            ("moderate", "3_to_5_years", "moderate_medium_term"),
            ("moderate", "under_3_years", "moderate_short_term"),
            ("conservative", "over_5_years", "conservative_long_term"),
            ("conservative", "3_to_5_years", "conservative_medium_term"),
            ("conservative", "under_3_years", "conservative_short_term"),
        ],
    )
    def test_canonical_mapping(self, risk, horizon, expected):
        assert (
            cells.investor_to_cell(risk_appetite=risk, time_horizon=horizon)
            == expected
        )

    def test_missing_risk_returns_none(self):
        assert (
            cells.investor_to_cell(risk_appetite=None, time_horizon="over_5_years")
            is None
        )

    def test_missing_horizon_returns_none(self):
        assert (
            cells.investor_to_cell(risk_appetite="moderate", time_horizon=None)
            is None
        )

    def test_unknown_values_return_none(self):
        assert (
            cells.investor_to_cell(risk_appetite="speculative", time_horizon="over_5_years")
            is None
        )
        assert (
            cells.investor_to_cell(risk_appetite="moderate", time_horizon="forever")
            is None
        )
