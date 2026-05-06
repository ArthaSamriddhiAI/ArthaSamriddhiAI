"""Case framework — cluster 5 chunk 5.1.

The Case is the central reasoning unit of Samriddhi AI. Every advisor
question that warrants institutional reasoning becomes a Case. The Case
flows through a pipeline of evidence agents, synthesis, optional
deliberation, governance, and challenge before reaching the CIO for an
authoritative decision.

Submodules (chunk 5.1 surface):

- :mod:`artha.api_v2.cases.models` — :class:`Case` ORM + 10 child stage
  tables (evidence_verdicts, portfolio_risk_analytics_outputs, synthesis,
  ic1_deliberations, governance_results, a1_challenges,
  decision_artifacts, briefing_notes, health_reports, llm_call_logs).
- :mod:`artha.api_v2.cases.state_machine` — pure validator for case
  status transitions (FR Entry 20.1 §1.5).
- :mod:`artha.api_v2.cases.materiality` — deterministic materiality
  gate (FR Entry 20.1 §6).
- :mod:`artha.api_v2.cases.hashing` — canonical-JSON SHA-256 over the
  evidence / synthesis / governance / portfolio-risk / IC1 / A1 packets
  for the decision artifact (FR Entry 20.4 §3).
- :mod:`artha.api_v2.cases.event_names` — T1 event constants.
- :mod:`artha.api_v2.cases.repository` — CRUD + transition helpers.
- :mod:`artha.api_v2.cases.snapshot_pinner` — wraps cluster 3's
  Snapshot machinery to pin a snapshot at case creation (immutable).

Chunks 5.2 onwards build on this surface: M0 framework, intake flows,
stub layer, decision recording UI, demo seed framework.
"""

from __future__ import annotations
