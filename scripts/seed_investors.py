#!/usr/bin/env python3
"""Seed realistic investor profiles with historical assessment data."""

import json
import sys
import time
import urllib.request

BASE = "http://13.204.187.25/api/v1"


def post(path, data):
    req = urllib.request.Request(f"{BASE}{path}", json.dumps(data).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"error": str(e)}


def get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


# ── Investor Definitions with Historical Assessment Trajectories ──

INVESTORS = [
    {
        "create": {"name": "Dr. Sunita Reddy", "phone": "+91-98765-43210", "investor_type": "individual"},
        "assessments": [
            {
                "context": "onboarding", "assessed_by": "Amit Desai (Wealth Manager)",
                "date_label": "Jan 2023 - Onboarding",
                "options": "a,a,b,a,b,a,a, a,b,a,b,a, a,a,a,a,b,a,a, a,a,b,a, a,a,a, a,b, a,a, a,a,a,a,a,a,a,a,a".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Amit Desai (Wealth Manager)",
                "date_label": "Jan 2024 - Annual Review",
                "options": "a,a,b,a,b,a,a, a,b,b,b,a, a,a,a,b,b,a,b, a,b,b,a, b,a,a, a,b, a,a, a,a,b,a,a,b,a,a,a".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Amit Desai (Wealth Manager)",
                "date_label": "Jan 2025 - Annual Review",
                "options": "a,a,b,b,b,a,a, b,b,b,b,b, a,b,a,b,b,b,b, b,b,b,b, b,b,a, b,b, b,a, b,a,b,a,b,b,a,b,a".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Priya Nair (Senior Advisor)",
                "date_label": "Mar 2026 - Latest Review",
                "options": "a,b,b,b,b,b,a, b,b,b,b,b, b,b,b,b,b,b,b, b,b,b,b, b,b,b, b,b, b,b, b,b,b,b,b,b,b,b,b".split(","),
            },
        ],
    },
    {
        "create": {"name": "Mr. Vikram Mehta", "phone": "+91-98765-43211", "investor_type": "hni"},
        "assessments": [
            {
                "context": "onboarding", "assessed_by": "Rajesh Sharma (Relationship Manager)",
                "date_label": "Apr 2022 - Onboarding",
                "options": "c,c,c,c,b,c,c, c,c,c,c,c, b,b,b,b,b,b,b, b,b,b,b, c,c,c, b,b, b,b, b,b,b,b,b,b,b,b,b".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Rajesh Sharma (Relationship Manager)",
                "date_label": "Apr 2023 - Annual Review",
                "options": "c,c,c,c,b,c,c, c,c,c,c,c, b,b,c,b,c,b,c, b,c,b,c, c,c,c, b,c, c,b, b,b,c,b,c,c,b,c,b".split(","),
            },
            {
                "context": "regulatory", "assessed_by": "Compliance Team",
                "date_label": "Sep 2024 - SEBI Regulatory Review",
                "options": "c,c,c,c,c,c,c, c,c,c,c,c, c,c,c,b,c,c,c, c,c,c,c, c,c,c, c,c, c,c, c,b,c,b,c,c,c,c,c".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Kavitha Iyer (Senior Portfolio Manager)",
                "date_label": "Apr 2025 - Annual Review",
                "options": "c,c,c,c,c,c,c, c,c,c,c,c, c,c,c,c,c,c,c, c,c,c,c, c,c,c, c,c, c,c, c,c,c,c,c,c,c,c,c".split(","),
            },
        ],
    },
    {
        "create": {"name": "Mr. Arjun Kapoor", "phone": "+91-98765-43212", "investor_type": "individual"},
        "assessments": [
            {
                "context": "onboarding", "assessed_by": "Meera Krishnan (Growth Advisor)",
                "date_label": "Jul 2023 - Onboarding",
                "options": "d,d,d,d,c,d,d, d,d,d,d,d, d,d,d,d,d,d,d, d,d,d,d, d,d,d, d,d, d,d, d,d,d,d,d,d,d,d,d".split(","),
            },
            {
                "context": "ad_hoc", "assessed_by": "Meera Krishnan (Growth Advisor)",
                "date_label": "Mar 2024 - Post Market Correction Review",
                "options": "d,d,d,d,c,d,d, d,d,d,d,d, d,d,d,c,d,c,d, c,d,c,d, d,d,d, c,d, d,c, d,c,d,c,d,d,c,d,c".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Meera Krishnan (Growth Advisor)",
                "date_label": "Jul 2025 - Annual Review",
                "options": "d,d,d,d,d,d,d, d,d,d,d,d, c,d,c,d,c,d,c, d,c,d,d, d,d,d, d,c, c,d, c,d,c,d,c,d,c,d,c".split(","),
            },
        ],
    },
    {
        "create": {"name": "Sharma Family Office (Principal)", "phone": "+91-98765-43213", "investor_type": "family_office"},
        "fo_create": {"name": "Sharma Family Office", "office_type": "single_family", "total_aum_band": "25-50Cr"},
        "assessments": [
            {
                "context": "onboarding", "assessed_by": "Deepak Joshi (Family Office Advisor)",
                "date_label": "Jun 2022 - Family Office Onboarding",
                "options": "b,c,b,b,c,b,b, b,c,b,b,c, b,b,b,b,b,b,b, b,b,b,b, c,b,b, b,b, b,b, b,b,b,b,b,b,b,b,b".split(","),
                "fo_options": "b,b,b,b,c, c,b,b,b, b,b,b".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Deepak Joshi (Family Office Advisor)",
                "date_label": "Jun 2023 - Annual Review (Family transition)",
                "options": "b,c,c,b,c,b,c, c,c,c,c,c, b,c,b,b,c,b,c, b,c,b,c, c,c,b, b,c, c,b, b,b,c,b,c,b,b,c,b".split(","),
                "fo_options": "c,c,b,c,c, c,c,c,b, b,c,c".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Kavitha Iyer (Senior Portfolio Manager)",
                "date_label": "Jun 2024 - Annual Review (Post restructuring)",
                "options": "c,c,c,c,c,c,c, c,c,c,c,c, b,c,c,b,c,b,c, b,c,b,c, c,c,c, c,c, c,c, c,b,b,c,b,c,b,c,c".split(","),
                "fo_options": "c,c,c,c,d, d,c,c,c, c,c,c".split(","),
            },
            {
                "context": "regulatory", "assessed_by": "Compliance Team",
                "date_label": "Dec 2025 - Regulatory Re-assessment",
                "options": "c,c,c,c,c,c,c, c,c,c,c,c, c,c,c,c,c,c,c, c,c,c,c, c,c,c, c,c, c,c, c,c,c,c,c,c,c,c,c".split(","),
                "fo_options": "c,c,c,c,d, d,c,c,c, c,c,c".split(","),
            },
        ],
    },
    {
        "create": {"name": "Ms. Ananya Bhat", "phone": "+91-98765-43214", "investor_type": "hni"},
        "assessments": [
            {
                "context": "onboarding", "assessed_by": "Meera Krishnan (ESG Advisory)",
                "date_label": "Feb 2024 - Onboarding (ESG mandate)",
                "options": "c,c,c,c,d,c,c, c,d,c,c,d, c,c,c,c,c,c,c, c,c,c,c, c,c,c, c,c, c,c, c,c,c,c,c,c,c,c,c".split(","),
            },
            {
                "context": "annual_review", "assessed_by": "Meera Krishnan (ESG Advisory)",
                "date_label": "Feb 2025 - Annual Review",
                "options": "c,c,c,c,d,c,d, c,d,c,d,d, c,c,c,c,c,c,c, c,c,c,c, c,c,c, c,d, c,c, c,c,c,c,c,c,c,d,c".split(","),
            },
        ],
    },
    {
        "create": {"name": "Mr. Rajan Pillai", "phone": "+91-98765-43215", "investor_type": "hni"},
        "assessments": [
            {
                "context": "onboarding", "assessed_by": "Kavitha Iyer (Senior Portfolio Manager)",
                "date_label": "Oct 2024 - Onboarding (Transfer from competitor)",
                "options": "c,d,c,c,c,d,d, c,c,d,c,c, c,d,c,c,c,c,d, c,d,c,d, c,c,c, c,d, d,c, c,d,c,d,c,d,c,d,c".split(","),
            },
        ],
    },
]


def main():
    print("=" * 70)
    print("  Samriddhi AI - Investor & Assessment Data Seeder")
    print("=" * 70)

    for inv_data in INVESTORS:
        inv_name = inv_data["create"]["name"]
        print(f"\n--- {inv_name} ---")

        # Create family office if needed
        fo_id = None
        if "fo_create" in inv_data:
            fo = post("/investor/family-offices", inv_data["fo_create"])
            if not fo.get("error"):
                fo_id = fo["id"]
                print(f"  Created FO: {fo['name']} ({fo['id'][:8]}...)")

        # Create investor
        create_data = inv_data["create"].copy()
        if fo_id:
            create_data["family_office_id"] = fo_id
        inv = post("/investor/investors", create_data)
        if inv.get("error"):
            print(f"  FAILED to create investor: {inv['error']}")
            continue
        inv_id = inv["id"]
        print(f"  Created: {inv['name']} ({inv_id[:8]}...) type={inv['investor_type']}")

        # Submit assessments (historical trajectory)
        for assess in inv_data["assessments"]:
            options = [o.strip() for o in assess["options"]]
            responses = [{"question_number": i + 1, "selected_option": o} for i, o in enumerate(options)]

            payload = {
                "responses": responses,
                "assessed_by": assess["assessed_by"],
                "assessment_context": assess["context"],
            }

            if "fo_options" in assess and fo_id:
                fo_opts = [o.strip() for o in assess["fo_options"]]
                payload["include_family_office"] = True
                payload["family_office_responses"] = [
                    {"question_number": i + 1, "selected_option": o} for i, o in enumerate(fo_opts)
                ]

            result = post(f"/investor/investors/{inv_id}/questionnaire", payload)
            if result.get("error"):
                print(f"  [{assess['date_label']}] ERROR: {str(result['error'])[:80]}")
            else:
                score = result.get("overall_score", "?")
                cat = result.get("risk_category", "?")
                fc = result.get("family_complexity_score")
                fc_str = f", FO complexity={fc}" if fc else ""
                print(f"  [{assess['date_label']}] Score: {score}, Category: {cat}{fc_str} -- by {assess['assessed_by']}")

            time.sleep(1)  # Throttle for LLM narrative generation

    # Summary
    print("\n" + "=" * 70)
    investors = get("/investor/investors?limit=20")
    if not isinstance(investors, list):
        investors = []
    print(f"  Total investors: {len(investors)}")
    for inv in investors:
        name = inv.get("name", "?")
        itype = inv.get("investor_type", "?")
        profile = inv.get("risk_profile")
        if profile:
            print(f"  {name} ({itype}) -- Score: {profile['overall_score']}, Category: {profile['risk_category']}")
        else:
            print(f"  {name} ({itype}) -- No profile")
    print(f"\n  View at: http://13.204.187.25/api/v1/investor/investors")
    print("=" * 70)


if __name__ == "__main__":
    main()
