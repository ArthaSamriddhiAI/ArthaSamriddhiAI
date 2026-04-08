#!/usr/bin/env python3
"""
Samriddhi AI Demo Data Seeder
==================================
Seeds realistic HNI (High Net-worth Individual) portfolio scenarios
covering explainability, auditability, and decision telemetry.

Scenarios:
  1. Conservative HNI Rebalance — well-diversified, should be APPROVED
  2. Aggressive Tech Overweight — concentrated, triggers HARD rule violations → REJECTED
  3. Retirement Portfolio Risk Review — moderate risk, may trigger SOFT rules → ESCALATION
  4. New Client Onboarding — fresh portfolio construction proposal
  5. Market Stress Response — volatile regime, defensive rebalance
  6. ESG-Conscious Rebalance — sector rotation with governance constraints
  7. MSME Credit Committee — trade proposal under tight risk constraints

Usage:
  python scripts/seed_demo.py [--base-url http://13.204.187.25]
"""

import argparse
import json
import sys
import time
import urllib.request

DEFAULT_BASE = "http://13.204.187.25"


def post(base_url, path, data):
    url = f"{base_url}/api/v1{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  ERROR {e.code}: {err[:200]}")
        return {"error": err}
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"error": str(e)}


def get(base_url, path):
    url = f"{base_url}/api/v1{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


SCENARIOS = [
    {
        "name": "1. Conservative HNI Rebalance (Rs 5Cr Portfolio)",
        "description": "Well-diversified portfolio of a conservative HNI investor. Blue-chip heavy, moderate risk appetite. Should pass all governance rules and be APPROVED.",
        "intent": {
            "intent_type": "rebalance",
            "source": "human",
            "initiator": "Rajesh Sharma (Relationship Manager)",
            "symbols": ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC", "BHARTIARTL", "SBIN", "HINDUNILVR", "KOTAKBANK", "MARUTI"],
            "holdings": {
                "RELIANCE": 120, "TCS": 85, "HDFCBANK": 200, "INFY": 150, "ITC": 500,
                "BHARTIARTL": 180, "SBIN": 300, "HINDUNILVR": 60, "KOTAKBANK": 90, "MARUTI": 15
            },
            "parameters": {
                "client_name": "Mr. Vikram Mehta",
                "portfolio_value_inr": "5,00,00,000",
                "risk_appetite": "conservative",
                "investment_horizon": "5-7 years",
                "objective": "Capital preservation with steady income",
                "trigger": "Quarterly review — Q1 FY2026"
            }
        }
    },
    {
        "name": "2. Aggressive Tech Overweight (Rs 8Cr Portfolio)",
        "description": "HNI with extreme tech concentration — 65% in IT sector. Violates max sector exposure (40%) and max single position (25%) rules. Should be REJECTED by hard governance rules.",
        "intent": {
            "intent_type": "rebalance",
            "source": "human",
            "initiator": "Priya Nair (Portfolio Advisor)",
            "symbols": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "HDFCBANK", "ICICIBANK"],
            "holdings": {
                "TCS": 300, "INFY": 400, "WIPRO": 500, "HCLTECH": 200,
                "TECHM": 350, "HDFCBANK": 80, "ICICIBANK": 60
            },
            "parameters": {
                "client_name": "Mr. Arjun Kapoor",
                "portfolio_value_inr": "8,00,00,000",
                "risk_appetite": "aggressive",
                "investment_horizon": "3-5 years",
                "objective": "Growth maximization — willing to accept concentration risk",
                "trigger": "Client requested increased tech exposure after strong Q3 earnings",
                "rm_note": "Client insists on tech overweight despite our diversification advice"
            }
        }
    },
    {
        "name": "3. Retirement Portfolio Risk Review (Rs 3Cr Portfolio)",
        "description": "Senior HNI approaching retirement — needs risk assessment. Mixed large-cap with some mid-cap exposure. Soft rules may trigger for position sizing.",
        "intent": {
            "intent_type": "risk_review",
            "source": "human",
            "initiator": "Amit Desai (Wealth Manager)",
            "symbols": ["HDFCBANK", "RELIANCE", "BAJFINANCE", "ASIANPAINT", "NESTLEIND", "TITAN", "DMART", "PIDILITIND"],
            "holdings": {
                "HDFCBANK": 250, "RELIANCE": 100, "BAJFINANCE": 60, "ASIANPAINT": 80,
                "NESTLEIND": 12, "TITAN": 40, "DMART": 25, "PIDILITIND": 45
            },
            "parameters": {
                "client_name": "Dr. Sunita Reddy",
                "portfolio_value_inr": "3,00,00,000",
                "risk_appetite": "low",
                "investment_horizon": "10+ years (retirement corpus)",
                "objective": "Capital safety, inflation protection, regular income",
                "trigger": "Annual risk review — client turns 58 next month",
                "special_instructions": "Evaluate downside protection and income generation capability"
            }
        }
    },
    {
        "name": "4. New HNI Client Onboarding (Rs 12Cr Portfolio)",
        "description": "Fresh portfolio construction for a new ultra-HNI client. Trade proposal with specific sector allocation targets. Tests the full governance pipeline.",
        "intent": {
            "intent_type": "trade_proposal",
            "source": "human",
            "initiator": "Kavitha Iyer (Senior Portfolio Manager)",
            "symbols": ["RELIANCE", "TCS", "HDFCBANK", "INFY", "BHARTIARTL", "SBIN", "LT", "SUNPHARMA", "TITAN", "ADANIENT", "POWERGRID", "NTPC"],
            "holdings": {
                "RELIANCE": 0, "TCS": 0, "HDFCBANK": 0, "INFY": 0,
                "BHARTIARTL": 0, "SBIN": 0, "LT": 0, "SUNPHARMA": 0,
                "TITAN": 0, "ADANIENT": 0, "POWERGRID": 0, "NTPC": 0
            },
            "parameters": {
                "client_name": "Mr. & Mrs. Rajan Pillai",
                "portfolio_value_inr": "12,00,00,000",
                "risk_appetite": "moderate-aggressive",
                "investment_horizon": "7-10 years",
                "objective": "Wealth creation with controlled drawdown",
                "trigger": "New client onboarding — transferred from competitor",
                "proposed_trades": [
                    {"symbol": "RELIANCE", "action": "buy", "target_weight": 0.12},
                    {"symbol": "TCS", "action": "buy", "target_weight": 0.10},
                    {"symbol": "HDFCBANK", "action": "buy", "target_weight": 0.12},
                    {"symbol": "INFY", "action": "buy", "target_weight": 0.08},
                    {"symbol": "BHARTIARTL", "action": "buy", "target_weight": 0.08},
                    {"symbol": "SBIN", "action": "buy", "target_weight": 0.08},
                    {"symbol": "LT", "action": "buy", "target_weight": 0.10},
                    {"symbol": "SUNPHARMA", "action": "buy", "target_weight": 0.08},
                    {"symbol": "TITAN", "action": "buy", "target_weight": 0.06},
                    {"symbol": "ADANIENT", "action": "buy", "target_weight": 0.06},
                    {"symbol": "POWERGRID", "action": "buy", "target_weight": 0.06},
                    {"symbol": "NTPC", "action": "buy", "target_weight": 0.06}
                ],
                "special_instructions": "Equal-weight core with tactical overweights in financials and infra"
            }
        }
    },
    {
        "name": "5. Market Stress — Defensive Rebalance (Rs 6Cr Portfolio)",
        "description": "Triggered by rising VIX and sector rotation signals. Portfolio needs defensive repositioning. Tests regime-awareness and risk constraints.",
        "intent": {
            "intent_type": "rebalance",
            "source": "trigger",
            "initiator": "Risk Management Desk (Auto-triggered)",
            "symbols": ["HDFCBANK", "ICICIBANK", "RELIANCE", "TCS", "HINDUNILVR", "NESTLEIND", "POWERGRID", "NTPC", "COALINDIA", "ITC"],
            "holdings": {
                "HDFCBANK": 180, "ICICIBANK": 150, "RELIANCE": 140, "TCS": 100,
                "HINDUNILVR": 45, "NESTLEIND": 10, "POWERGRID": 200, "NTPC": 250,
                "COALINDIA": 300, "ITC": 400
            },
            "parameters": {
                "client_name": "Sharma Family Office",
                "portfolio_value_inr": "6,00,00,000",
                "risk_appetite": "moderate",
                "investment_horizon": "5-7 years",
                "objective": "Shift to defensive posture — reduce cyclical exposure",
                "trigger": "India VIX crossed 20-day moving average, FII selling for 5 consecutive days",
                "market_context": {
                    "india_vix": 18.5,
                    "nifty_50_change_1w": -3.2,
                    "fii_net_flow_5d_cr": -8500,
                    "usd_inr": 84.75
                }
            }
        }
    },
    {
        "name": "6. ESG-Conscious Sector Rotation (Rs 4Cr Portfolio)",
        "description": "HNI requesting ESG-aligned rebalance — exit fossil fuels, increase green energy. Tests governance around sector transition constraints.",
        "intent": {
            "intent_type": "rebalance",
            "source": "scheduled",
            "initiator": "Meera Krishnan (ESG Advisory)",
            "symbols": ["RELIANCE", "TCS", "INFY", "TATAMOTORS", "TATAPOWER", "ADANIGREEN", "HDFCBANK", "BAJFINANCE", "COALINDIA", "ONGC"],
            "holdings": {
                "RELIANCE": 80, "TCS": 100, "INFY": 120, "TATAMOTORS": 60,
                "TATAPOWER": 150, "ADANIGREEN": 200, "HDFCBANK": 100,
                "BAJFINANCE": 40, "COALINDIA": 250, "ONGC": 180
            },
            "parameters": {
                "client_name": "Ms. Ananya Bhat",
                "portfolio_value_inr": "4,00,00,000",
                "risk_appetite": "moderate",
                "investment_horizon": "10+ years",
                "objective": "Transition to ESG-compliant portfolio — exit coal, reduce oil & gas",
                "trigger": "Semi-annual ESG review — client mandate to achieve ESG score > 70",
                "esg_constraints": {
                    "exit_sectors": ["Coal", "Oil & Gas Exploration"],
                    "target_green_allocation": 0.20,
                    "max_transition_per_quarter": 0.15
                }
            }
        }
    },
    {
        "name": "7. MSME Credit Committee Review (Rs 2Cr Exposure)",
        "description": "Credit risk evaluation for an MSME loan proposal. Simulates the credit committee architecture with multiple risk agents providing structured opinions.",
        "intent": {
            "intent_type": "risk_review",
            "source": "human",
            "initiator": "Deepak Joshi (Credit Analyst)",
            "symbols": ["MSME_BORROWER_101", "SECTOR_TEXTILE", "REGION_SURAT", "GUARANTOR_A"],
            "holdings": {
                "MSME_BORROWER_101": 1, "SECTOR_TEXTILE": 1, "REGION_SURAT": 1, "GUARANTOR_A": 1
            },
            "parameters": {
                "assessment_type": "msme_credit_underwriting",
                "borrower_name": "Shree Ganesh Textiles Pvt Ltd",
                "proposed_exposure_inr": "2,00,00,000",
                "facility_type": "Working Capital + Term Loan",
                "sector": "Textiles — Cotton Yarn Manufacturing",
                "geography": "Surat, Gujarat",
                "vintage_years": 8,
                "gst_filing_regularity": "95% on-time (last 24 months)",
                "bank_statement_summary": {
                    "avg_monthly_credits": 4500000,
                    "avg_monthly_debits": 4200000,
                    "avg_balance": 850000,
                    "bounce_ratio": 0.02
                },
                "financial_highlights": {
                    "revenue_fy25": 48000000,
                    "revenue_fy24": 42000000,
                    "revenue_growth": 0.143,
                    "ebitda_margin": 0.12,
                    "debt_to_equity": 1.8,
                    "current_ratio": 1.3,
                    "interest_coverage": 2.1
                },
                "risk_factors": [
                    "Cyclical sector — cotton price volatility",
                    "Single geography concentration",
                    "Key-man dependency on promoter",
                    "Export exposure (30%) — currency risk"
                ],
                "mitigants": [
                    "8-year track record with no defaults",
                    "Diversified buyer base (15+ buyers)",
                    "Collateral: Factory land + machinery (valued Rs 3.5Cr)",
                    "Personal guarantee of promoter + spouse"
                ]
            }
        }
    },
]


def main():
    parser = argparse.ArgumentParser(description="Seed Samriddhi AI with demo data")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help=f"API base URL (default: {DEFAULT_BASE})")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    print(f"\n{'='*70}")
    print(f"  Samriddhi AI Demo Data Seeder")
    print(f"  Target: {base}")
    print(f"{'='*70}\n")

    # Check health
    health = get(base, "/health")
    if health.get("error"):
        print(f"ERROR: Cannot reach {base}/api/v1/health — {health['error']}")
        sys.exit(1)
    print(f"  System: {health.get('status', 'unknown')}\n")

    results = []
    for i, scenario in enumerate(SCENARIOS):
        print(f"\n{'-'*70}")
        print(f"  Scenario: {scenario['name']}")
        print(f"  {scenario['description']}")
        print(f"{'-'*70}")

        print(f"  Submitting governance intent...")
        t0 = time.time()
        result = post(base, "/governance/intents", scenario["intent"])
        elapsed = time.time() - t0

        if result.get("error"):
            print(f"  FAILED: {result['error'][:200]}")
            results.append({"scenario": scenario["name"], "status": "ERROR", "decision_id": None})
            continue

        decision_id = result.get("decision_id", "?")
        status = result.get("status", "?")
        agents = len(result.get("agent_outputs", []))
        rules = len(result.get("rule_evaluations", []))

        print(f"  Decision ID : {decision_id}")
        print(f"  Status      : {status.upper()}")
        print(f"  Agents      : {agents} consulted")
        print(f"  Rules       : {rules} evaluated")
        print(f"  Time        : {elapsed:.1f}s")

        # Print agent summaries
        for agent in result.get("agent_outputs", []):
            name = agent.get("agent_name", "?")
            risk = agent.get("risk_level", "?")
            conf = agent.get("confidence", 0)
            n_actions = len(agent.get("proposed_actions", []))
            n_flags = len(agent.get("flags", []))
            print(f"    Agent [{name}]: risk={risk}, confidence={conf:.0%}, actions={n_actions}, flags={n_flags}")

        # Print permission outcome
        perm = result.get("permission_outcome", {})
        if perm:
            overall = perm.get("overall_status", "?")
            n_perms = len(perm.get("permissions", []))
            needs_approval = perm.get("requires_human_approval", False)
            print(f"  Permission  : {overall} ({n_perms} actions evaluated)")
            if needs_approval:
                print(f"  *** REQUIRES HUMAN APPROVAL ***")

        results.append({
            "scenario": scenario["name"],
            "status": status,
            "decision_id": decision_id,
            "agents": agents,
            "rules": rules,
            "elapsed": f"{elapsed:.1f}s"
        })

        # Brief pause between scenarios
        if i < len(SCENARIOS) - 1:
            time.sleep(1)

    # Summary
    print(f"\n\n{'='*70}")
    print(f"  DEMO SEEDING COMPLETE — SUMMARY")
    print(f"{'='*70}\n")
    print(f"  {'Scenario':<55} {'Status':<20} {'Decision ID'}")
    print(f"  {'-'*55} {'-'*20} {'-'*36}")
    for r in results:
        did = r["decision_id"][:12] + "..." if r["decision_id"] and len(r["decision_id"]) > 12 else (r["decision_id"] or "N/A")
        print(f"  {r['scenario']:<55} {r['status'].upper():<20} {did}")

    approved = sum(1 for r in results if r["status"] == "approved")
    rejected = sum(1 for r in results if r["status"] == "rejected")
    escalated = sum(1 for r in results if r["status"] == "escalation_required")
    errors = sum(1 for r in results if r["status"] == "ERROR")

    print(f"\n  Approved: {approved}  |  Rejected: {rejected}  |  Escalated: {escalated}  |  Errors: {errors}")
    print(f"\n  View at: {base}/app#/history")
    print(f"  Landing: {base}/\n")


if __name__ == "__main__":
    main()
