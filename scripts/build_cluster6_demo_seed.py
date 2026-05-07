#!/usr/bin/env python3
"""Build cluster-6 demo_seed.json from cases.json + archetype profiles.

One-shot synthesizer that turns the cluster-6 ``_cluster6_cases.json``
(23 cases) into the full demo_seed.json (households + investors +
mandates + cases). Profile data per archetype is hand-curated from the
character bibles + bibles_index + case proposed_action narratives.

Run:  python -m scripts.build_cluster6_demo_seed > data/fixtures/demo_seed.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "data" / "fixtures" / "_cluster6_cases.json"

# 15 archetypes — name, advisor (the assigned_to from cases), age,
# risk_appetite, time_horizon. Compiled from character bibles + cases.
ARCHETYPES: dict[str, dict[str, Any]] = {
    "01": {
        "name": "Lalitha Iyengar",
        "advisor": "adv_priya_nair",
        "age": 67,
        "risk_appetite": "conservative",
        "time_horizon": "3_to_5_years",
        "email": "lalitha.iyengar@demo.test",
        "phone": "+919810000001",
        "pan": "AAAPI1234A",
        "household_name": "Iyengar Family",
    },
    "02": {
        "name": "Rohan Shetty",
        "advisor": "adv_priya_nair",
        "age": 41,
        "risk_appetite": "moderate",
        "time_horizon": "3_to_5_years",
        "email": "rohan.shetty@demo.test",
        "phone": "+919810000002",
        "pan": "AAARS1234B",
        "household_name": "Shetty Household",
    },
    "03": {
        "name": "Vikram Malhotra",
        "advisor": "adv_amit_sharma",
        "age": 49,
        "risk_appetite": "aggressive",
        "time_horizon": "over_5_years",
        "email": "vikram.malhotra@demo.test",
        "phone": "+919810000003",
        "pan": "AAAVM1234C",
        "household_name": "Malhotra Family",
    },
    "04": {
        "name": "Vijay Ranawat",
        "advisor": "adv_amit_sharma",
        "age": 58,
        "risk_appetite": "moderate",
        "time_horizon": "over_5_years",
        "email": "vijay.ranawat@demo.test",
        "phone": "+919810000004",
        "pan": "AAAVR1234D",
        "household_name": "Ranawat Family Office",
    },
    "05": {
        "name": "Arjun Menon",
        "advisor": "adv_rohan_kapoor",
        "age": 46,
        "risk_appetite": "aggressive",
        "time_horizon": "over_5_years",
        "email": "arjun.menon@demo.test",
        "phone": "+919810000005",
        "pan": "AAAAM1234E",
        "household_name": "Menon Household",
    },
    "06": {
        "name": "Aggarwal HUF",
        "advisor": "adv_amit_sharma",
        "age": 55,
        "risk_appetite": "moderate",
        "time_horizon": "over_5_years",
        "email": "aggarwal.huf@demo.test",
        "phone": "+919810000006",
        "pan": "AAAHUF234F",
        "household_name": "Aggarwal HUF",
    },
    "07": {
        "name": "Priya Raghavan",
        "advisor": "adv_amit_sharma",
        "age": 44,
        "risk_appetite": "aggressive",
        "time_horizon": "over_5_years",
        "email": "priya.raghavan@demo.test",
        "phone": "+919810000007",
        "pan": "AAAPR1234G",
        "household_name": "Raghavan Family",
    },
    "08": {
        "name": "Shailesh Bhatt",
        "advisor": "adv_priya_nair",
        "age": 61,
        "risk_appetite": "moderate",
        "time_horizon": "3_to_5_years",
        "email": "shailesh.bhatt@demo.test",
        "phone": "+919810000008",
        "pan": "AAASB1234H",
        "household_name": "Bhatt Household",
    },
    "09": {
        "name": "Rajiv Surana",
        "advisor": "adv_rohan_kapoor",
        "age": 52,
        "risk_appetite": "aggressive",
        "time_horizon": "over_5_years",
        "email": "rajiv.surana@demo.test",
        "phone": "+919810000009",
        "pan": "AAARS1234I",
        "household_name": "Surana Family",
    },
    "10": {
        "name": "Col. Harvinder Singh (Retd.)",
        "advisor": "adv_priya_nair",
        "age": 71,
        "risk_appetite": "conservative",
        "time_horizon": "3_to_5_years",
        "email": "h.singh@demo.test",
        "phone": "+919810000010",
        "pan": "AAAHS1234J",
        "household_name": "Singh Household",
    },
    "11": {
        "name": "Sushila Goenka",
        "advisor": "adv_priya_nair",
        "age": 64,
        "risk_appetite": "moderate",
        "time_horizon": "3_to_5_years",
        "email": "sushila.goenka@demo.test",
        "phone": "+919810000011",
        "pan": "AAASG1234K",
        "household_name": "Goenka Family",
    },
    "12": {
        "name": "Aanya Kapoor",
        "advisor": "adv_rohan_kapoor",
        "age": 33,
        "risk_appetite": "aggressive",
        "time_horizon": "over_5_years",
        "email": "aanya.kapoor@demo.test",
        "phone": "+919810000012",
        "pan": "AAAAK1234L",
        "household_name": "Kapoor Household",
    },
    "13": {
        "name": "Dharmani Family Office",
        "advisor": "adv_amit_sharma",
        "age": 65,
        "risk_appetite": "moderate",
        "time_horizon": "over_5_years",
        "email": "dharmani.fo@demo.test",
        "phone": "+919810000013",
        "pan": "AAADF1234M",
        "household_name": "Dharmani Family Office",
    },
    "14": {
        "name": "Karan Mehra",
        "advisor": "adv_rohan_kapoor",
        "age": 36,
        "risk_appetite": "aggressive",
        "time_horizon": "over_5_years",
        "email": "karan.mehra@demo.test",
        "phone": "+919810000014",
        "pan": "AAAKM1234N",
        "household_name": "Mehra Household",
    },
    "15": {
        "name": "Inder Thapar",
        "advisor": "adv_priya_nair",
        "age": 73,
        "risk_appetite": "conservative",
        "time_horizon": "3_to_5_years",
        "email": "inder.thapar@demo.test",
        "phone": "+919810000015",
        "pan": "AAAIT1234O",
        "household_name": "Thapar Household",
    },
}

# Mandate band defaults per risk_appetite.
MANDATE_DEFAULTS: dict[str, dict[str, int]] = {
    "conservative": {
        "equity_min_pct": 15,
        "equity_max_pct": 30,
        "debt_min_pct": 50,
        "debt_max_pct": 70,
        "cash_min_pct": 5,
        "cash_max_pct": 15,
        "alternatives_min_pct": 0,
        "alternatives_max_pct": 5,
        "single_position_max_pct": 8,
        "liquidity_floor_pct": 30,
        "sector_max_pct": 25,
    },
    "moderate": {
        "equity_min_pct": 35,
        "equity_max_pct": 55,
        "debt_min_pct": 30,
        "debt_max_pct": 50,
        "cash_min_pct": 0,
        "cash_max_pct": 10,
        "alternatives_min_pct": 0,
        "alternatives_max_pct": 12,
        "single_position_max_pct": 10,
        "liquidity_floor_pct": 20,
        "sector_max_pct": 30,
    },
    "aggressive": {
        "equity_min_pct": 55,
        "equity_max_pct": 75,
        "debt_min_pct": 10,
        "debt_max_pct": 25,
        "cash_min_pct": 0,
        "cash_max_pct": 8,
        "alternatives_min_pct": 5,
        "alternatives_max_pct": 20,
        "single_position_max_pct": 15,
        "liquidity_floor_pct": 10,
        "sector_max_pct": 35,
    },
}

CREATED_AT = "2026-01-10T09:00:00+00:00"


def build() -> dict[str, Any]:
    cases_payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    case_rows = cases_payload["rows"]

    households: list[dict[str, Any]] = []
    investors: list[dict[str, Any]] = []
    mandates: list[dict[str, Any]] = []

    for archetype_num, profile in ARCHETYPES.items():
        archetype_id = f"investor_archetype_{archetype_num}"
        household_id = f"hh_archetype_{archetype_num}"
        # IDs shortened to fit the String(26) ORM column type.
        mandate_id = f"mandate_arch_{archetype_num}"
        version_id = f"mv_arch_{archetype_num}"

        households.append({
            "household_id": household_id,
            "name": profile["household_name"],
            "created_by": profile["advisor"],
            "created_at": CREATED_AT,
        })

        investors.append({
            "investor_id": archetype_id,
            "household_id": household_id,
            "name": profile["name"],
            "email": profile["email"],
            "phone": profile["phone"],
            "pan": profile["pan"],
            "age": profile["age"],
            "advisor_id": profile["advisor"],
            "risk_appetite": profile["risk_appetite"],
            "time_horizon": profile["time_horizon"],
            "created_at": CREATED_AT,
            "archetype_id": archetype_id,
        })

        bands = MANDATE_DEFAULTS[profile["risk_appetite"]]
        mandates.append({
            "mandate_id": mandate_id,
            "investor_id": archetype_id,
            "version_id": version_id,
            **bands,
            "prohibited_instruments": [],
            "created_at": CREATED_AT,
            "created_by": profile["advisor"],
        })

    # Cases — pass-through from cases.json. The seed loader inserts
    # cases through ``case_opener.open_case`` which runs the chunk-5.4
    # pipeline; cluster-6-only fields like ``_decision_artifact_preview``,
    # ``health_report_id``, ``briefing_note_id``, ``failure_cause`` are
    # intentionally dropped here (Stage 3 absorbs them via the
    # per-archetype curation in case_seed_data.json).
    cases: list[dict[str, Any]] = []
    for c in case_rows:
        cases.append({
            # Stable case_id (e.g. case_arch01_a) so the dispatcher's
            # case_id-keyed seed-payload lookup matches; cluster 6 stage 3.
            "case_id": c["case_id"],
            "investor_id": c["investor_id"],
            "case_mode": c["case_mode"],
            "case_intent": c.get("case_intent"),
            "dominant_lens": c.get("dominant_lens"),
            "proposed_action": c.get("proposed_action"),
            "proposed_action_amount_inr": c.get("proposed_action_amount_inr"),
            "proposed_action_products": c.get("proposed_action_products", []),
            "materiality_manual_flag": c.get("materiality_manual_flag", False),
            "opened_by": c["opened_by"],
            "seed_archetype_id": c["seed_archetype_id"],
        })

    return {
        "version": "0.2-cluster6",
        "fixture_authored_in_cluster": 6,
        "description": (
            "Cluster 6 enriched cohort per FR Entry 19.0 cluster 6 "
            "revision: 15 archetype investors + 15 households + 15 mandates "
            "+ 23 cases across 3 advisors + 1 CIO. Replaces the cluster-5 "
            "minimal 12-case cohort. Cases ship through chunk 5.4 pipeline; "
            "in_flight + failed lifecycle nuances are deferred to Stage 3 "
            "(per-archetype curated stage outputs)."
        ),
        "advisors_referenced": [
            "adv_priya_nair",
            "adv_amit_sharma",
            "adv_rohan_kapoor",
            "cio_anjali_mehta",
        ],
        "households": households,
        "investors": investors,
        "mandates": mandates,
        "cases": cases,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
