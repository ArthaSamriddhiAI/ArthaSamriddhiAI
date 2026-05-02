# Samriddhi AI: Principles of Operation

## Foundation Reference Document, Entry 0

**Document:** Samriddhi AI, Principles of Operation
**Version:** v1.0
**Status:** Locked; baseline for all cluster work in Doc 1 v2
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This is the principles-of-operation entry of the Samriddhi AI foundation reference document. It is the first thing any reader of the Doc 1 v2 stack should consume, because it locks the architectural and methodological decisions that constrain every cluster of work that follows.

The principles below are not derived; they are the result of explicit deliberation across multiple discussions with the team, and they have been ratified as the canonical decisions for the Doc 1 v2 build cycle. Subsequent cluster documents (cluster 0 through cluster 17) refer to this document by entry number rather than re-deriving each principle. If a later cluster's work reveals a tension with a principle here, the resolution is to revise this document explicitly, not to silently override it.

Every principle in this document was a real decision against a real alternative. The alternatives are noted briefly so future readers understand what was considered and what was deliberately set aside. The principles are organised into seven sections: build methodology, deployment model, agent architecture, data layer, governance and accountability, LLM provider strategy, and document structure.

---

## 1. Build Methodology

### 1.1 Chunky Implementation, Not Waterfall

The system is built in vertical slices, not horizontal layers. A chunk is a piece of work that goes from data layer through to UI surface, end-to-end testable, advisor-perceived-visible. A cluster is a group of chunks that share a foundation slice and ship as coherent product capability.

The alternative considered: layer-by-layer waterfall (build all data, then all backend, then all UI). This was attempted in the Doc 1 v1 implementation cycle and produced an unmaintainable mega-commit of 20 passes that could not be tested incrementally. The lesson: layer-by-layer implementation produces nothing visible until everything is built, which means nothing is testable, which means errors compound silently across passes.

The chunky principle implies several discipline requirements. Each chunk must produce something an advisor can do that they could not do before. No chunk is purely infrastructure; if a piece of infrastructure must ship, it pairs with a thin admin or observability surface that exercises it visibly. Acceptance criteria for each chunk are stated in advisor-experience terms, not in component-completion terms.

### 1.2 Cluster-by-Cluster Documentation

The Doc 1 v2 work proceeds cluster by cluster, not as a single mega-document. For each cluster, ideation passes lock the cluster's architectural decisions, drafting passes produce the foundation reference entries and chunk plan entries, and only then does implementation in Claude Code begin.

The alternative considered: produce the entire Doc 1 v2 first, then implement everything. This was rejected because it reproduces the failure mode of v1: speculative spec ahead of working code, with no opportunity for learning from real implementation to flow back into the specification. Cluster-by-cluster keeps spec and code in tight coupling.

This implies the Doc 1 v2 is not a fixed document but a growing artefact. After each cluster ships, the next cluster's plan is revisited with the benefit of what was learned, and adjustments are made.

### 1.3 The Foundation Reference Plus Chunk Plan Pattern

Documentation is organised into two parallel artefacts. The foundation reference is the topic-organised wiki of architectural primitives that grows as clusters specify their components. The chunk plan is the time-ordered project artefact listing chunks in build order with acceptance criteria. They reference each other but serve different purposes: the foundation reference is what implementation reads to understand a component; the chunk plan is what the project reads to know what's being built when.

The alternative considered: a single sequential Doc 1 v2 in the shape of Doc 1 v1. Rejected because Doc 1 v1's structure is implicitly waterfall (read top to bottom to understand the system); the chunky methodology needs a topic-organised reference plus a time-ordered plan as separate concerns.

### 1.4 Foundation Reference Rot Is Not Acceptable

When a cluster reveals that a foundation reference entry from a prior cluster is wrong or incomplete, the entry is revised, not patched-around. The cost of foundation revision is paid in the cluster that surfaces the issue, not deferred. The consequence of letting foundation entries drift out of date is that after several clusters the foundation reference becomes unreliable, which compounds.

The alternative considered: patch corrections in cluster-specific notes rather than revising foundation entries directly. Rejected because it produces technical-debt-equivalent in the documentation that is far more expensive to clean up later than to address immediately.

### 1.5 Implementation Code Is Frozen Until Cluster Documentation Is Ready

The existing implementation code from the Doc 1 v1 cycle is rolled back to the last clean GitHub commit before Doc 1 v2 work begins. No code is touched until at least cluster 0's documentation ships. Subsequent clusters' code work begins only after that cluster's documentation ships.

The alternative considered: continue implementation against partial Doc 1 v2 documentation. Rejected because the v1 implementation was waterfall-shaped and cannot be incrementally chunkified retrospectively; preserving it as a reference while building chunky from a clean baseline is the right tradeoff.

---

## 2. Deployment Model

### 2.1 Per-Firm Deployment, No Multi-Tenancy

Each adopting wealth advisory firm receives an independent deployment. One firm per deployment, one backend per deployment, one Postgres per deployment. Year-one target is three to five firms operating their own instances.

The alternative considered: hosted multi-tenant SaaS with row-level firm scoping. Rejected because the regulatory burden of mixing firm data even with row-scoping is high, the operational simplicity benefits of per-firm deployment outweigh the duplication cost at this scale, and per-firm deployment matches the trust model of regulated wealth advisory firms (each firm wants its compute, its database, its audit trail).

### 2.2 The /api/v2/system/firm-info Hook

The frontend bundle is identical across all firm deployments. Firm-specific configuration (branding, feature flags, IdP issuer URL, regulatory jurisdiction) is fetched at runtime from /api/v2/system/firm-info on auth completion. This is the indirection hook that supports per-firm flexibility without per-firm rebuilds.

The alternative considered: build-time configuration baked into per-firm bundles. Rejected because runtime configuration is operationally cleaner (deploy once, configure per firm) and matches the per-firm-deployment-but-shared-codebase model.

---

## 3. Agent Architecture

### 3.1 Seven-Agent Evidence Layer

The evidence layer consists of exactly seven agents:

E1: Listed/Fundamental Equity Analysis. Evaluates one listed equity company at a time through threshold-based metric families (leverage, liquidity, cashflow stability, capital efficiency, valuation, ownership distress, market relative).

E2: Industry and Business Model. Conditional sector-structural analysis. Five Forces, lifecycle, moats, business model quality.

E3: Macro, Policy, and News. Mandatory unconditional activation. Four-quadrant regime classification (Goldilocks, Reflation, Stagflation, Deflation), five analytical dimensions including news intelligence.

E4: Behavioural and Historical. Client patterns, biases, advisor patterns, historical analogues.

E5: Unlisted Equity Specialist. Conditional activation for unlisted holdings. Pre-IPO valuation, illiquidity premium, exit risk.

E6: PMS, AIF, SIF Fund Analysis. The most architecturally complex single agent, with internal sub-agent architecture (Gate, PMS, Cat I/II, Cat III, SIF, Fee Normalisation, Liquidity Manager, Recommendation Synthesis). Counterfactual Engine extracted to IC1 per principle 5.2.

E7: Mutual Fund Analysis. Five analysis pipelines (Active Equity, Passive/Index, Debt, Hybrid, Solution/FoF), SEBI category logic, look-through analysis.

### 3.2 Agents Considered and Not Included

E8 Technical Analysis: placeholder reserved in the numbering scheme; deferred to v2 consideration. The HNI advisory population does not lead with technical analysis; the seven-agent layer covers the analytical surfaces wealth advisors actually use.

E9 Sectoral Analysis: dropped. Folded into E2 industry and business model. The sectoral lens (rotation, FII/DII flows, cyclical analysis) is structurally indistinguishable from the industry lens; treating them as separate agents was redundant.

E10 Sentiment: dropped. Split across E3 (market sentiment as part of news intelligence dimension) and E4 (investor sentiment as part of behavioural analysis). News-as-perception and investor-perception are separate concepts that already have natural homes; a third agent was unnecessary.

These agents appear in cross-references within E2, E3, and the original E11 specification documents. Those cross-references are stripped during the cluster-6 cleanup pass (per the agent restructuring sequence).

### 3.3 Agent Isolation Invariant

Each evidence agent runs independently. No agent can see another agent's output, chain-of-thought, or verdict. This prevents reasoning contamination. Verdicts are produced based solely on the data snapshot input.

The alternative considered: agents that read each other's verdicts mid-pipeline. Rejected because it creates ordering dependencies, introduces error propagation across agents, and makes confidence scoring non-mechanical.

### 3.4 The skill.md Per Agent Mechanism

Each agent's intelligence (its system prompt, its analytical framework, its output schema) lives in a skill.md file. The skill.md is the canonical authoring surface for the agent's capability. Updating the agent's analytical depth means editing the skill.md; the rest of the agent's code (input parsing, LLM call, output validation) is stable.

The alternative considered: prompts embedded in Python source code. Rejected because non-engineers (the team's analysts, the CIO, compliance) cannot easily update embedded prompts, version control of prompt changes is awkward, and the boundary between agent code and agent intelligence becomes blurred.

The skill.md mechanism applies to all agents (E1 through E7), all M0 sub-agents, all S1 modes, all IC1 sub-roles, A1, governance components, and any future LLM-reasoning components. Each gets its own skill.md file with consistent structure.

### 3.5 Master Agent Has a Boss Agent Skill.md

M0 itself has a top-level skill.md that defines its orchestration role, exception handling vocabulary, and sub-agent coordination logic. This is the boss agent skill.md pattern. M0 is not just an orchestrator-by-implementation; it is an orchestrator with explicit reasoning capability for cases that don't fit standard workflows.

The alternative considered: M0 as pure code orchestration without an LLM-reasoning layer. Rejected because edge cases inevitably emerge where structured orchestration is insufficient, and having M0 fall back to LLM reasoning under explicit governance is cleaner than building exception logic in code per case type.

### 3.6 Agents Can Engage M0 Outside Generic Workflows

Agent prompts include the explicit capability to flag unique edge cases that warrant M0 attention. The mechanism: an agent's output schema includes an optional `escalate_to_master` field; when populated, M0's boss agent picks up the case, applies its exception-handling reasoning, and decides what to do (re-run with adjusted context, escalate to human, request additional data, abort).

The alternative considered: agents always run to completion regardless of edge case detection. Rejected because some edge cases are visible only to the specialist agent (an unusual fund structure visible only to E6, an anomalous behavioural pattern visible only to E4) and the cleanest signal is for that agent to flag it explicitly.

### 3.7 The Counterfactual Concept Lives in IC1 as a Sub-Agent

The counterfactual reasoning capability (would the client be better served by a different vehicle for the same exposure) is generalised across the system as a service. It lives as a sub-agent within IC1 and is callable by every layer that needs counterfactual comparison: S1 synthesis, IC1 deliberation, E6 product evaluations.

The alternative considered: counterfactual reasoning embedded inside E6 (the original location) and not generalised. Rejected because the team agreed the counterfactual lens applies across asset classes, not just E6's PMS-vs-MF context. Keeping it inside E6 would have required duplicating the logic when other agents or layers needed similar reasoning.

E6's existing Counterfactual Engine is extracted to IC1 during cluster 7. E6 calls the IC1 sub-agent as a consumer rather than owning the engine.

### 3.8 Portfolio-Level Financial Risk Function Is in M0

The portfolio-level rollup analysis (concentration, HHI, weighted leverage, weighted current ratio, breach counting across the portfolio) is an M0 sub-agent, not part of any evidence agent. The sub-agent name is M0.PortfolioRiskAnalytics.

The alternative considered: keeping this function inside E1 (where it appeared in earlier drafts). Rejected because portfolio-level rollup requires visibility across all holdings (which violates the agent isolation invariant if it lives inside E1) and is naturally per-case-orchestration work (which is M0's role).

### 3.9 Rebalance Execution Gap: M0.ExecutionPlanner

The system has, prior to v2, no explicit logic for converting "the portfolio needs to move from X to Y" into "sell these specific holdings, in this sequence, in these amounts, and buy these specific instruments from the L4 manifest." This gap is closed by a new M0 sub-agent: M0.ExecutionPlanner.

M0.ExecutionPlanner has four components: sell-side selection (which holdings to reduce, criteria-adjudicated), lock-in awareness (routing around locked positions), tax sequencing (LTCG vs STCG, surcharge band, FY-end timing), buy-side instrument selection (from the L4 approved universe).

The alternative considered: leave the gap to advisor manual execution. Rejected because at scale (50 to 200 clients per advisor) manual execution is a real product liability, and the system already does the harder work of producing the rebalance recommendation; the execution planning is the natural extension.

### 3.10 Model Portfolio Dashboard Visualizer

A new UI surface allows the CIO to edit percentage bands of the model portfolio at three levels (L1 asset class, L2 vehicle mix, L3 sub-asset-class) globally and at per-investor level (per-investor band overrides). This is a UI-heavy capability; cluster 13 ships it.

The alternative considered: API-only model portfolio editing without a dashboard surface. Rejected because the model portfolio is consulted on every case and its values affect every advisor; making it editable through a usable interface (rather than only through API or YAML) is a v1.0 requirement.

---

## 4. Data Layer

### 4.1 D0 Is the System-Wide Data Layer

D0 is the architectural element responsible for transforming source feeds into canonical state and producing frozen snapshot bundles for case execution. It has four sub-components plus a cross-cutting concern: D0.Adapters (hexagonal pattern at the system edge), D0.Staging (raw records with provenance), D0.Normalization (per-entity normalizers including signal extractors), D0.SnapshotAssembler (case-time freezing with bit-identical replay), D0.FreshnessSLA (cross-cutting staleness detection and propagation).

The alternative considered: implicit per-component data fetching. Rejected because the snapshot freezing invariant requires a single coordinated layer that produces frozen snapshots, and per-component data fetching duplicates work and breaks replay.

D0's product thesis is documented separately as D0_data_layer_product_thesis.md. The implementation specification is built across cluster 3 of the cluster sequence.

### 4.2 Snapshot-and-Pass Invariant

The snapshot is frozen at case creation. Once frozen, agents reason over the snapshot for the duration of the case. Mid-case live data updates are not permitted. T1 captures the snapshot's content hash; replay six months later uses the frozen snapshot, reconstructing the case bit-identically.

The alternative considered: live data fetching during case execution (the original E3 spec described this for news intelligence). Rejected because mid-case live updates break the replay invariant and the audit story collapses without bit-identical reconstruction.

### 4.3 D0.NewsAssembler

To preserve the snapshot freezing invariant while supporting E3's news intelligence dimension, news fetching is moved from E3 internal logic to a D0 sub-component (D0.NewsAssembler). The news fetcher runs at case creation, deduplicates and classifies materiality, produces a structured news bundle, and includes it in the case snapshot. E3 receives the bundle as input rather than fetching live.

The alternative considered: leave news fetching inside E3, accept replay drift on news. Rejected because of the principle 4.2 invariant.

### 4.4 No Vector DB in MVP

Most of what initially looks like RAG in the system is actually upstream signal extraction in disguise. E3 reasons over structured policy stance signals, not raw MPC text. E2 reasons over structured sector signals. E1 reasons over structured fundamentals. E4 through E7 reason over structured data. Signal extraction services in D0.Normalization produce structured signals from text sources where needed.

The alternative considered: pgvector inside the existing Postgres for retrieval over document corpora. Deferred to v2; the MVP does not require it. Genuine candidates for retrieval (E6 fund offer documents if structured fields are insufficient, A1 prior-case retrieval) are evaluated per-agent in their respective cluster passes; if any returns "yes, this needs retrieval," pgvector enters MVP for that agent.

### 4.5 Static-to-Live Adapter Swap

The MVP runs against static JSON fixtures. Production runs against live HTTP, RSS, webhook, SFTP feeds. The adapter abstraction is identical across both; the implementation differs. Agent code is unchanged; the snapshot assembler interface is unchanged; the ingestion machinery underneath swaps.

The alternative considered: separate code paths for MVP versus production. Rejected because it produces a fork in the codebase that has to be maintained twice and migrated through later.

### 4.6 Per-Entity Freshness SLA

Each canonical entity has a freshness SLA configurable per environment. At snapshot assembly, the assembler checks each entity against its SLA. Entities past SLA produce a stale_data flag in the bundle; consuming agents reduce confidence accordingly; the staleness becomes part of the case's audit context.

The alternative considered: all-or-nothing freshness checking. Rejected because different entity types have different update cadences (mandate any-age once locked, market data 24-hour EOD, regulatory rules 72-hour, fund analytics 30-day) and uniform SLAs either tolerate too much staleness for sensitive entities or block on freshness for entities that are inherently slow-updating.

---

## 5. Governance and Accountability

### 5.1 The Governance Gate Is Deterministic

G1 (mandate compliance), G2 (SEBI/regulatory rules), G3 (action permission filter aggregation) are deterministic rule engines, not LLM-reasoning components. The rules are versioned YAML maintained by compliance in Git. Rule evaluations against proposed actions produce structured verdicts (APPROVED, BLOCKED, ESCALATION_REQUIRED) without LLM judgement.

The alternative considered: LLM-reasoning governance. Rejected because regulatory compliance demands reproducibility and auditability that LLM reasoning cannot deliver, and rules-as-code provides the version pinning and replay capability that audit defence requires.

### 5.2 T1 Telemetry Is Append-Only

Every event of consequence (case lifecycle, agent verdicts, governance evaluations, IC1 deliberations, A1 challenges, PM1 events, override applications, T2 proposals) is captured in T1 as an immutable append-only ledger. T1 is the audit foundation; bit-identical replay depends on it.

The alternative considered: mutable event logs with redaction capability. Rejected because regulatory expectations require immutable audit trails and any system that can be redacted retroactively cannot be defended against post-hoc tampering claims.

### 5.3 Governed-Not-Online Learning Through T2

The system does not modify itself online. T2 reads T1 history at scheduled cadence, produces calibration analyses and proposal outputs (prompt updates, rule updates, threshold adjustments, agent skill version updates), and routes them to the firm's governance review queue. Nothing deploys without explicit human approval and version bumping.

The alternative considered: online adaptation where agents update their behaviour from observed outcomes. Rejected because financial advisory is a regulated context where every behavioural change must be documented, reviewed, and version-pinned for audit defence.

---

## 6. LLM Provider Strategy

### 6.1 Platform-Level Provider Toggle

The SmartLLMRouter is configured at the firm-deployment level with two modes: economy (Mistral via SmartLLMRouter, free or low-cost) and quality (Claude via SmartLLMRouter, paid). The toggle is in firm settings and applies platform-wide.

The alternative considered: per-agent model tier configuration (Opus for high-stakes reasoning, Sonnet for evidence agents, Haiku for orchestration). Deferred to v2. The platform toggle ships in v1.0; per-agent tiering is an optimisation that can be added without breaking the architecture.

### 6.2 SmartLLMRouter Is a Real Architectural Component

The SmartLLMRouter is not just a provider switch; it is the LLM access governance layer. It handles provider failover, kill-switch behaviour, rate limiting, eventual per-agent tiering, and (in v2) multi-provider quality monitoring. It is specified explicitly in Doc 1 v2 as a foundation component, not assumed implicitly.

The alternative considered: direct provider calls from each agent. Rejected because per-agent direct calls duplicate auth, retry, and rate-limit logic, and centralising provider concerns in one component is cleaner.

---

## 7. Document Structure

### 7.1 Foundation Reference Plus Chunk Plan

The Doc 1 v2 documentation lives in two parallel artefacts. The foundation reference is a topic-organised wiki of architectural primitives (this document is foundation reference entry 0). The chunk plan is a time-ordered project artefact listing chunks in build order with acceptance criteria.

The shape and conventions of both documents are specified in the Foundation Reference and Chunk Plan Structure document, which is the structural complement to this principles document.

### 7.2 Doc 2 and Doc 3 Cascade After Doc 1 v2

Doc 2 (API and Real-Time Contract) and Doc 3 (UI/UX Implementation) revise as cascade work after Doc 1 v2 is structurally complete. Doc 2 v2 walks through its 127 endpoints and identifies which need schema changes from Doc 1 v2's agent restructuring, which need new endpoints (model portfolio dashboard mutations, M0.ExecutionPlanner output retrieval, IC1 counterfactual sub-agent results, D0 admin surfaces). Doc 3 Pass 2 onwards builds on Doc 2 v2.

The alternative considered: revise Doc 2 and Doc 3 in lockstep with Doc 1 v2 cluster work. Rejected because Doc 1 v2 changes will cascade through Doc 2 and Doc 3, and revising downstream docs against a moving upstream is wasteful.

### 7.3 Documents Are Versioned Explicitly

Doc 1 v2, Doc 2 v2, Doc 3 v2 are explicitly distinct from Doc 1 v1, Doc 2 v1, Doc 3 v1. The v1 versions are preserved as historical reference. The v2 versions are the working implementation specification.

---

## 8. Closing Notes

This document is the foundation reference's entry 0. It is the first document any reader of the Doc 1 v2 stack should consume.

The principles in this document are not exhaustive of all decisions made for Samriddhi AI. They are the architectural and methodological principles that constrain the cluster work. Per-component specifications, per-agent skill.md content, per-cluster chunk plans, per-API endpoint specifications: these live in their own documents and are referenced from the foundation reference's other entries.

When a future cluster's work surfaces a tension with a principle here, the resolution path is:

1. The cluster pauses ideation work.
2. The tension is named explicitly: which principle, what new evidence, what alternatives.
3. A revision pass on this document is opened.
4. The principle is either revised (with a new version number for this document) or the cluster's framing is adjusted to fit the existing principle.
5. The cluster work resumes.

This is the disciplined path. Silent override of principles is not acceptable; the audit trail of architectural decisions matters as much as the audit trail of operational decisions.

Subsequent foundation reference entries cover specific topics (agent specifications, M0 architecture, D0 implementation, governance gate mechanics, telemetry contracts, and so on). Each subsequent entry references this document by entry number and section number rather than re-deriving the principles.

---

**End of Foundation Reference Entry 0: Principles of Operation.**
