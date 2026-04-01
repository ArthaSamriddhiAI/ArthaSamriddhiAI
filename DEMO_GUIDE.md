# ArthaSamriddhiAI — Demo Guide

## Live URLs

| URL | What It Shows |
|-----|---------------|
| http://13.204.187.25/ | Landing page — EGA architecture, design principles |
| http://13.204.187.25/app | Main application dashboard |
| http://13.204.187.25/app#/history | All past decisions |
| http://13.204.187.25/docs | FastAPI auto-generated API docs |

---

## Pre-Loaded Demo Scenarios (7 HNI Cases)

The system already has 7 realistic scenarios seeded. Go to **Decisions** in the sidebar to see them all.

| # | Scenario | Status | Demo Focus |
|---|----------|--------|------------|
| 1 | **Conservative HNI Rebalance** (Rs 5Cr) — Mr. Vikram Mehta | Rejected | Agent collaboration, rule enforcement |
| 2 | **Aggressive Tech Overweight** (Rs 8Cr) — Mr. Arjun Kapoor | Rejected | Hard rule violations, concentration risk |
| 3 | **Retirement Risk Review** (Rs 3Cr) — Dr. Sunita Reddy | Approved | Risk assessment with no trade actions |
| 4 | **New Ultra-HNI Onboarding** (Rs 12Cr) — Rajan Pillai Family | Rejected | Full pipeline, 12-stock portfolio construction |
| 5 | **Market Stress Defensive** (Rs 6Cr) — Sharma Family Office | Rejected | Regime-aware rebalance, VIX trigger |
| 6 | **ESG Sector Rotation** (Rs 4Cr) — Ms. Ananya Bhat | Rejected | ESG mandate, fossil fuel exit |
| 7 | **MSME Credit Committee** (Rs 2Cr) — Shree Ganesh Textiles | Rejected | Credit underwriting, non-equity domain |

---

## Demo Walkthrough

### Act 1: The Landing Page (2 min)

1. Open **http://13.204.187.25/**
2. Walk through the hero: "Governed Intelligence for Capital Markets"
3. Scroll down to show:
   - **Trust bar**: 3 layers, 100% traceability, 0 drift tolerance
   - **Core Thesis**: AI as Risk Committee, Portfolio as Operating System
   - **EGA Architecture**: Evidence → Governance → Accountability
   - **Decision Boundary**: The instant a decision is made, it becomes history
   - **Design Principles**: 8 non-negotiable invariants
4. Click **"Enter the Platform"**

### Act 2: The Dashboard (1 min)

1. Show the 4 status cards: Health, Kill Switch, LLM Provider, Decisions
2. Point out the recent decisions list — 7 pre-loaded scenarios
3. Click on any decision to drill in

### Act 3: Explainability — Agent Collaboration (3 min)

1. Click into **Scenario 2: Aggressive Tech Overweight** (the most interesting one)
2. On the **Agents** tab, show:
   - **Allocation Agent**: risk=high, confidence=85%, identified tech concentration at 65%
   - **Risk Agent**: risk=high, confidence=92%, flagged all individual positions
   - **Review Agent**: synthesized both views into consensus
3. Emphasize: "Three independent agents, each with their own skill.md. They don't see each other's reasoning. They surface risk — they do NOT decide."
4. Show the **flow diagram** at top: Intent → Evidence → Agents → Rules → Decision
5. Expand a proposed action to show the rationale (e.g., "Reduce TCS from 28% to 15%")

### Act 4: Governance — Rule Enforcement (2 min)

1. Switch to the **Rules** tab
2. Show the table: red rows = HARD violations, amber = SOFT
3. Point out specific rules:
   - `max_single_position <= 0.25` — FAILED for concentrated positions
   - `portfolio_risk_score <= max_risk_score` — FAILED
4. Show the **condition** column — real executable expressions, not black boxes
5. Key message: "Rules are deterministic, versioned, YAML-defined. No AI involved. No exceptions."

### Act 5: Decision Telemetry — The Trace (2 min)

1. Switch to the **Trace DAG** tab
2. Walk through the timeline:
   - Intent Received → Evidence Frozen → Agent Invoked (x3) → Agent Output (x3) → Rule Evaluated (many) → Permission Denied
3. Click any node to expand its data payload
4. Key message: "Every step is a node in a causal graph. Not logs — a DAG. You can traverse backwards from any outcome to understand why."

### Act 6: Auditability — Evidence at Decision Time (2 min)

1. Switch to the **Evidence** tab on the decision view
2. Show the frozen artifacts: market snapshot, risk estimates, regime classification
3. Key message: "This is what the system believed at the moment of decision. Immutable. If you audit this decision 3 years later, you see exactly the same evidence."
4. Navigate to **Evidence Explorer** in the sidebar to show latest artifacts

### Act 7: Live Demo — Submit a New Intent (3 min)

1. Go to **New Intent** in the sidebar
2. Fill in:
   - Type: **Rebalance**
   - Symbols: RELIANCE, TCS, HDFCBANK, INFY, ITC (type each and press Enter)
   - Holdings: RELIANCE=100, TCS=80, HDFCBANK=200, INFY=150, ITC=500
3. Click **Submit Intent**
4. Watch the spinner (Mistral LLM processing in real-time, ~15-25 seconds)
5. Show the inline result: status, agent count, rule count
6. Click **"View Full Analysis"** to see the complete decision

### Act 8: Safety — Kill Switch (1 min)

1. Go to **System** in the sidebar
2. Show the kill switch status (Inactive)
3. Demonstrate: "In an emergency, one click halts all execution. Requires typing CONFIRM."
4. (Optional) Activate and deactivate to demonstrate

### Act 9: Help & Documentation (1 min)

1. Go to **Help & Docs** in the sidebar
2. Show the **EGA Architecture** tab with the three-layer diagram
3. Show the **Glossary** — every term defined
4. Key message: "Built-in documentation. No tribal knowledge needed."

---

## Re-Seeding Demo Data

If you need to reset and re-seed:

```bash
# From your local machine (Windows)
cd D:\Projects\ArthaSamriddhiAI
.venv\Scripts\python scripts\seed_demo.py --base-url http://13.204.187.25

# Or target localhost if running locally
.venv\Scripts\python scripts\seed_demo.py --base-url http://localhost:8000
```

---

## Key Talking Points

### For Financial Decision Makers
- "AI agents surface risk. They never decide. Your portfolio managers retain full authority."
- "Every decision is traceable — what was known, who flagged risk, why the decision was taken."
- "Rules are deterministic and versioned. No black boxes. No silent drift."

### For Risk & Compliance
- "Complete audit reconstruction: evidence-at-the-time, rules-in-force-at-the-time."
- "Decision trace is a causal graph, not flat logs. Real lineage."
- "Governance is real-time permissioning — constraints are checked before action, not after."

### For Technology Leaders
- "Three-layer EGA architecture: Evidence / Governance / Accountability. Invariant across deployments."
- "Agents are modular, replaceable, governed by skill.md. Learning happens through versioned updates."
- "Models are replaceable. Governance is not."

---

## Architecture Summary (Quick Reference)

```
Evidence Layer        → "What does the system believe?"
  Market data, features, risk estimates, regime classification
  Append-only, immutable, timestamped artifacts

Governance Layer      → "What actions are permitted?"
  Orchestrator (bounded authority) → Agents → Rule Engine → Permission Filter
  Agents: Allocation | Risk Interpretation | Review
  Rules: YAML-defined, AST-sandboxed, deterministic

Accountability Layer  → "Who acted, under what authority?"
  Decision Trace (causal DAG, not logs)
  Approval Records (human sign-off)
  Audit Reconstruction (evidence + rules at decision time)
```

---

## SSH Access (if needed)

```bash
ssh -i D:\Downloads\ArthaSamriddhiAI.pem ubuntu@13.204.187.25

# Service management
sudo systemctl status artha
sudo systemctl restart artha
sudo journalctl -u artha -f       # tail logs

# App location
cd /home/ubuntu/ArthaSamriddhiAI
```
