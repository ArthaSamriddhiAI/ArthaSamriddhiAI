# Samriddhi AI: Foundation Reference and Chunk Plan Structure

## Documentation Infrastructure Specification

**Document:** Samriddhi AI, Foundation Reference and Chunk Plan Structure
**Version:** v1.0
**Status:** Locked; structural specification for all Doc 1 v2 cluster work
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This document specifies the structure of the two parallel documentation artefacts that together comprise Doc 1 v2: the foundation reference and the chunk plan. It is the structural complement to the Principles of Operation document (foundation reference entry 0), which locks the architectural and methodological decisions. This document locks how those decisions and their implementing components are documented.

The reason this document exists separately from the principles document is that the two concerns are genuinely separate. The principles document answers "what are the rules of the system." This document answers "how do we write down what gets built." Future readers can consume the principles without reading this; future authors of cluster documentation must read this.

This document covers four things: how the foundation reference is organised internally (the topic taxonomy, the entry format, the cross-referencing convention), how the chunk plan is organised (the chunk template, acceptance criteria format, dependency notation, lifecycle states), how the two artefacts relate to each other (when each is updated, how they reference each other), and how documentation versioning works across cluster cycles.

The format and conventions specified here are deliberately conservative. They are the minimum structure required to make cluster work tractable. They are not maximally elaborate; later refinement is expected after clusters 0 and 1 produce real content and surface things this structure didn't anticipate.

---

## 1. Foundation Reference Structure

### 1.1 Purpose

The foundation reference is the topic-organised wiki of architectural primitives. It is what implementation reads to understand a component. Its readers are: implementation engineers (human and AI), reviewers, future maintainers, compliance auditors, the product team's future hires.

The foundation reference is not a sequential document. It is not read top to bottom. It is consulted by topic. A reader trying to understand E3's input contract reads the E3 foundation reference entry. A reader trying to understand how the case state machine works reads the case-orchestration foundation reference entry. The structure must support consultation by topic, not narrative consumption.

### 1.2 Topic Taxonomy

The foundation reference is organised into the following topic clusters. Each topic cluster contains one or more entries. Within a topic cluster, entries are numbered for stable cross-reference.

**Topic 0: Principles and Structure.** Entry 0.0: Principles of Operation (already authored). Entry 0.1: Foundation Reference and Chunk Plan Structure (this document). Future entries in this cluster are reserved for cross-cutting principles that emerge during cluster work.

**Topic 1: Agent Layer.** Entry 1.0: Evidence Layer Overview (the seven-agent layer summary, isolation invariant, output schema standard, telemetry contract, skill.md mechanism). Entries 1.1 through 1.7: per-agent specifications (E1 through E7 in numerical order). Entry 1.8: E8 Placeholder. Entry 1.9: Agents Considered and Not Included (E9, E10 with explicit folding logic).

**Topic 2: Master Agent (M0).** Entry 2.0: M0 Overview and Boss Agent. Entry 2.1: M0.Router. Entry 2.2: M0.PortfolioState. Entry 2.3: M0.IndianContext. Entry 2.4: M0.Stitcher. Entry 2.5: M0.Briefer. Entry 2.6: M0.Librarian. Entry 2.7: M0.PortfolioRiskAnalytics (formerly part of E1; relocated per principle 3.8). Entry 2.8: M0.ExecutionPlanner (new sub-agent; per principle 3.9).

**Topic 3: Synthesis Layer.** Entry 3.0: S1 Overview and Three Modes. Entry 3.1: S1 Case Mode. Entry 3.2: S1 Diagnostic Mode. Entry 3.3: S1 Briefing Mode.

**Topic 4: Investment Committee (IC1).** Entry 4.0: IC1 Overview and Five Sub-Roles. Entry 4.1: IC1.Chair. Entry 4.2: IC1.DevilsAdvocate. Entry 4.3: IC1.RiskAssessor. Entry 4.4: IC1.MinutesRecorder. Entry 4.5: IC1.MaterialityGate. Entry 4.6: IC1.CounterfactualSubAgent (extracted from E6; per principle 3.7).

**Topic 5: Governance Gate.** Entry 5.0: Governance Gate Overview. Entry 5.1: G1 Mandate Compliance. Entry 5.2: G2 SEBI/Regulatory Rules Engine. Entry 5.3: G3 Action Permission Aggregation. Entry 5.4: Override Mechanism. Entry 5.5: Escalation Mechanism.

**Topic 6: Challenge Layer (A1).** Entry 6.0: A1 Overview. Entry 6.1: A1 Counter-Arguments and Stress Tests. Entry 6.2: A1 Accountability Surface (briefing close-paraphrase, clarification verdict-anticipation).

**Topic 7: Monitoring (PM1).** Entry 7.0: PM1 Overview. Entry 7.1: PM1 Drift Detection. Entry 7.2: PM1 Thesis Validity Tracking. Entry 7.3: PM1 Benchmark Divergence. Entry 7.4: PM1 Threshold Breaches.

**Topic 8: Watch Tier.** Entry 8.0: Watch Lifecycle. Entry 8.1: Watch Origination. Entry 8.2: Watch Resolution and T2 Calibration Feed.

**Topic 9: Telemetry and Reflection (T1, T2, EX1).** Entry 9.0: T1 Telemetry Bus. Entry 9.1: T2 Reflection Engine. Entry 9.2: EX1 Exception Handler.

**Topic 10: Data Layer (D0).** Entry 10.0: D0 Overview (with reference to the D0 product thesis). Entry 10.1: D0.Adapters. Entry 10.2: D0.Staging. Entry 10.3: D0.Normalization (including signal extractors). Entry 10.4: D0.SnapshotAssembler. Entry 10.5: D0.FreshnessSLA. Entry 10.6: D0.NewsAssembler. Entry 10.7: Canonical Entity Schemas.

**Topic 11: Investor Context Engine (I0).** Entry 11.0: I0 Overview. Entry 11.1: I0 Active Layer. Entry 11.2: I0 Dormant Layer. Entry 11.3: I0 Pattern Library.

**Topic 12: Mandate Management (M1).** Entry 12.0: M1 Overview. Entry 12.1: Mandate Schema and Constraints. Entry 12.2: Amendment Workflow.

**Topic 13: Model Portfolio.** Entry 13.0: Model Portfolio Overview. Entry 13.1: L1 Asset Class Allocation. Entry 13.2: L2 Vehicle Mix. Entry 13.3: L3 Sub-Asset-Class. Entry 13.4: L4 Manifest. Entry 13.5: Construction Pipeline. Entry 13.6: Substitution Cascade. Entry 13.7: Model Portfolio Dashboard (per principle 3.10).

**Topic 14: Conversational and Notification (C0, N0).** Entry 14.0: C0 Conversational Orchestrator. Entry 14.1: N0 Alert Tiers and Inbox.

**Topic 15: Case Pipeline.** Entry 15.0: Case Object Schema. Entry 15.1: Case State Machine. Entry 15.2: Case Bundle and Snapshot.

**Topic 16: LLM Provider Strategy.** Entry 16.0: SmartLLMRouter Overview. Entry 16.1: Platform Toggle (economy, quality). Entry 16.2: Provider Failover. Entry 16.3: Kill Switch.

**Topic 17: Authentication and Identity.** Entry 17.0: OIDC Authentication. Entry 17.1: JWT and Session Management. Entry 17.2: Role-Permission Vocabulary.

**Topic 18: Real-Time Layer (SSE).** Entry 18.0: SSE Channel Overview. Entry 18.1: Event Multiplex Schema. Entry 18.2: Reconnect Semantics.

The topic numbering (0 through 18) is stable. Topics will not be renumbered as the foundation reference grows; new topics get the next available number. Entries within a topic can be added in any order (the entry number does not imply ordering).

### 1.3 Entry Format

Each foundation reference entry follows a uniform structure:

**Header.** Entry number and title (e.g., "Entry 1.3: E3 Macro, Policy, and News"). Status (draft, locked, deprecated). Date last revised. Author and reviewer attribution.

**Cross-references in.** Which other foundation reference entries refer to this one. Maintained as a list at the top of each entry; updated when entries that reference this one are added or revised.

**Cross-references out.** Which other foundation reference entries this entry refers to.

**Body.** The substantive content. The body's internal structure depends on the entry type:

For agent entries (1.1 through 1.7): the structure follows the eight-part agent specification template established in Doc 1 v1 (purpose, functional specification, schema, integration points, telemetry and observability, failure modes and EX1 contract, acceptance criteria, plus the skill.md content as an inline section or a separate file reference).

For component entries (M0 sub-agents, S1 modes, IC1 sub-roles, governance components, etc.): the same eight-part template, scaled appropriately. Some sub-components have shorter entries because they are smaller in scope.

For schema entries (canonical entity schemas in topic 10.7, the case object in 15.0, etc.): the structure is field-by-field specification with type, purpose, validation, provenance fields, version history.

For overview entries (the topic-cluster summaries: 1.0, 2.0, etc.): the structure is a brief introduction plus a table of contents pointing to the detailed entries within the topic.

**Open questions.** A section listing decisions that have not yet been locked in this entry. Each open question is tagged with its blocking cluster (which cluster needs to lock this question to proceed) and its dependent clusters (which clusters need this question's answer).

**Revision history.** A log of meaningful revisions to this entry, with date, author, and a brief description of what changed.

### 1.4 Cross-Referencing Convention

When one entry refers to another, the format is "FR Entry X.Y" where X is the topic number and Y is the entry number within the topic. For example, "FR Entry 1.3" refers to the E3 specification entry; "FR Entry 10.4" refers to the D0.SnapshotAssembler entry.

When an entry refers to a section within another entry, the format is "FR Entry X.Y §Z" where Z is the section number within that entry. For example, "FR Entry 1.3 §4" refers to section 4 (integration points) of the E3 entry.

When an entry refers to a chunk plan entry (a specific chunk by ID), the format is "CP Chunk N.M" where N is the cluster number and M is the chunk number within the cluster. For example, "CP Chunk 5.1" refers to the first chunk of cluster 5.

The principles of operation document is referenced as "Principles §X.Y" where X is the principles document section number and Y is the sub-section. For example, "Principles §3.1" refers to the seven-agent evidence layer principle.

### 1.5 Entry Lifecycle

Entries progress through three states: draft, locked, deprecated.

A draft entry is in active editing. It may have open questions, incomplete sections, placeholder content. Drafts are not authoritative; readers should expect changes. Implementation work should not begin against draft entries.

A locked entry is the authoritative specification of its component. Implementation can rely on it. Changes to locked entries require a revision pass that updates the revision history, names the change explicitly, and considers downstream impact (which other entries or chunks need updating in response).

A deprecated entry is preserved for historical reference but no longer authoritative. New work must not refer to deprecated entries except to acknowledge supersession. Deprecated entries link to their successor.

The lifecycle state is in the entry header. Cluster work locks entries as the cluster ships; the foundation reference grows with locked entries plus any drafts in progress.

### 1.6 Authoring Discipline

A new entry is authored as part of a cluster's drafting passes. The cluster that introduces a component is the cluster that authors the component's foundation reference entry. For example, cluster 5 (first agent and case pipeline) authors entries 1.0 (evidence layer overview), 1.3 (E3, the first agent shipped), 2.0 (M0 overview and boss agent), 2.1 (M0.Router), 2.4 (M0.Stitcher), 15.0 (case object schema), 15.1 (case state machine), 15.2 (case bundle and snapshot).

Subsequent clusters that introduce additional components within the same topic cluster (e.g., cluster 6 adds entries 1.1, 1.2, 1.4, 1.5, 1.6, 1.7 for the additional evidence agents) revise the topic overview entry (1.0) as appropriate to reflect the now-complete picture, but do not re-author it from scratch.

Foundation reference entries are not aspirational. They describe what the cluster has shipped or is shipping, with the architectural detail required for implementation to proceed. They are not roadmaps or future state visions; those live in the chunk plan or in dedicated planning documents.

---

## 2. Chunk Plan Structure

### 2.1 Purpose

The chunk plan is the time-ordered project artefact listing chunks in build order. Its readers are: the project lead, the team, implementation engineers (human and AI), reviewers tracking project velocity. Where the foundation reference is what implementation reads to understand a component, the chunk plan is what implementation reads to understand what is being built right now and what acceptance looks like.

The chunk plan is not a static project schedule. It evolves as clusters ship and the next cluster's plan is refined. It is the live agile artefact.

### 2.2 Chunk Plan Organisation

The chunk plan is organised by cluster. Within each cluster, chunks are listed in build order (typically dependency order, sometimes value order if dependencies permit flexibility). Each cluster has a header section describing the cluster's purpose, foundation references it depends on, foundation references it produces, and the cluster's overall acceptance criterion (what an advisor can do at the end of the cluster that they could not at the start).

The cluster sequence follows the indicative plan from the consolidation conversation: cluster 0 (walking skeleton), cluster 1 (investor onboarding), cluster 2 (mandate management), cluster 3 (D0 data foundation), cluster 4 (model portfolio infrastructure), cluster 5 (first agent and case pipeline), cluster 6 (additional evidence agents), cluster 7 (synthesis and committee), cluster 8 (governance gate), cluster 9 (override and challenge), cluster 10 (portfolio analytics in M0), cluster 11 (watch tier), cluster 12 (M0.ExecutionPlanner), cluster 13 (model portfolio dashboard), cluster 14 (briefings), cluster 15 (audit replay), cluster 16 (T2 reflection), cluster 17 (webhook ingress and live feeds).

The cluster numbering is stable. Cluster boundaries can shift (chunks can move between clusters during planning) but the numbering does not get reordered.

### 2.3 Chunk Template

Each chunk in the plan follows this template:

**Chunk header.** Chunk ID (cluster number dot chunk number, e.g., 5.1). Title (a short noun phrase describing what the chunk produces). Status (planned, in-progress, shipped, deprecated). Lifecycle dates (planning started, ideation locked, drafting completed, implementation started, shipped).

**Purpose.** One paragraph describing what the chunk produces and why it ships in this position in the sequence. Specifically: what advisor experience does this chunk make possible that wasn't possible before, and what does it depend on from prior chunks.

**Dependencies.** Two lists. Foundation reference entries this chunk depends on (must be locked before this chunk's implementation begins). Other chunks this chunk depends on (must be shipped before this chunk ships).

**Scope: in.** A bulleted list of what this chunk includes. Each item is a discrete capability, not a vague intention. "User can submit an investor onboarding form" is acceptable; "improve onboarding" is not.

**Scope: out.** A bulleted list of what this chunk explicitly does not include. This is as important as the in-scope list. It prevents scope creep during implementation and makes the next chunk's dependencies clearer.

**Acceptance criteria.** A numbered list of testable conditions that must hold for the chunk to be considered shipped. Each criterion is verifiable: "an advisor can log in via the firm's IdP and see their name on the dashboard" is verifiable; "auth works correctly" is not. Acceptance criteria are advisor-experience-stated where possible; backend-only criteria are acceptable for chunks that produce admin or observability surfaces.

**Out-of-scope notes.** Specific clarifications about things that are intentionally not addressed in this chunk but that someone might mistakenly assume are addressed. This is a defensive section that reduces ambiguity.

**Implementation notes.** Brief notes on anything specific implementation will need: known constraints, expected challenges, references to relevant external documentation (SEBI circulars, regulatory references, library docs).

**Open questions.** Any decisions that haven't been locked at the time of plan authoring. Each tagged with what the question is and how it should be resolved (typically: through team discussion, by reading the relevant FR entry once it exists, or by deferring to a future chunk).

**Revision history.** A log of meaningful revisions to this chunk's plan, with date and brief description.

### 2.4 Acceptance Criteria Format

Acceptance criteria deserve their own subsection because they are the most failure-prone part of the chunk template.

A good acceptance criterion is verifiable in a finite, bounded test. Examples:

"An advisor logged in with the advisor role sees the route /app/advisor as their home tree."

"On opening a case for an investor with at least one PMS holding, E6 produces a verdict within 30 seconds and the verdict appears in the case workspace."

"The L4 manifest substitution endpoint correctly creates a cascade case for every investor holding the substituted instrument."

A bad acceptance criterion is vague, untestable, or aspirational. Examples that should be rewritten:

"Onboarding works smoothly." (Vague; what does smoothly mean.)

"The user experience is good." (Untestable.)

"Performance is acceptable." (Define acceptable; if measurable, state the threshold.)

When in doubt, the test is: can a reviewer go through the criterion and definitively say yes-it-passed or no-it-did-not. If the answer is "depends on judgement," the criterion needs sharpening.

Acceptance criteria are the contract between cluster planning and implementation. They are not modified during implementation without explicit revision (which goes in the revision history). If implementation reveals that a criterion was wrong, the criterion is revised, the chunk's plan is updated, and the revision is logged. Silent criterion drift is the failure mode that produces "I thought it was done but it actually wasn't" arguments.

### 2.5 Dependency Notation

Dependencies are stated explicitly in the chunk template's Dependencies section. The notation:

Foundation reference dependencies are listed by FR entry number. For example, "FR Entry 10.4 (D0.SnapshotAssembler) must be locked." If the dependency is on a specific section within the entry, the section number is included: "FR Entry 1.3 §4 (E3 integration points)."

Chunk dependencies are listed by chunk ID. For example, "CP Chunk 4.2 (L4 manifest) must be shipped." If the dependency is partial (this chunk depends on a specific capability from another chunk, not the full chunk), the dependency is described: "CP Chunk 5.1's case object schema must be locked, but the full case pipeline implementation is not required."

Cross-cluster dependencies (this chunk in cluster N depends on a chunk in cluster M where M is later in the plan) are flagged as risks. They typically indicate the cluster sequence needs revisiting; chunks should not depend forward unless there's a strong reason.

### 2.6 Lifecycle States

Chunks progress through these states:

**Planned.** The chunk is in the plan. The chunk template is filled out. Acceptance criteria are stated. Dependencies are listed. Implementation has not begun.

**Ideation locked.** Architectural questions about the chunk have been resolved. The cluster's ideation passes are complete for this chunk.

**Drafting completed.** The chunk's foundation reference entries are locked. Implementation can begin.

**In-progress.** Implementation has started. The chunk is being built in code. The plan should not be modified during this phase except via explicit revision.

**Shipped.** The chunk's acceptance criteria all pass. The chunk is in production. Subsequent chunks can depend on it.

**Deprecated.** A previously-shipped chunk has been superseded. Preserved for historical reference.

The lifecycle state is in the chunk header. Cluster work transitions chunks through these states; the chunk plan reflects the current state of every chunk at every moment.

### 2.7 Chunk Plan Update Cadence

The chunk plan is updated as work proceeds:

When a cluster opens, the cluster's chunks are filled out from "planned" templates to fully-specified chunks (acceptance criteria, dependencies, scope in/out). This happens during the cluster's ideation passes.

When a chunk's foundation reference entries lock, the chunk transitions from ideation-locked to drafting-completed.

When implementation begins, the chunk transitions to in-progress.

When acceptance criteria pass, the chunk transitions to shipped.

The chunk plan is read often (every implementation session typically begins with reviewing the chunk plan for the current chunk) and revised regularly. Stale chunk plans are worse than no chunk plans because they actively mislead.

---

## 3. Relationship Between Foundation Reference and Chunk Plan

### 3.1 The Two Are Complementary

The foundation reference is what implementation reads to understand what to build (the architectural primitives). The chunk plan is what implementation reads to understand what is being built right now (the time-ordered work). Both are needed; neither replaces the other.

The two refer to each other constantly. A chunk's Dependencies section names the foundation reference entries it depends on. A foundation reference entry's Cross-references In section can name the chunks that introduce or modify it. The two artefacts are mutually consistent at all times; inconsistencies are surfaced and resolved during cluster work, not deferred.

### 3.2 Update Triggers

Updates to the foundation reference happen during cluster drafting passes. Updates to the chunk plan happen at the cluster's start (when chunks are fleshed out from templates) and continuously as chunks transition through lifecycle states.

A change to a foundation reference entry that affects chunks (other than the chunk that authored the entry) requires a chunk plan revision pass: every dependent chunk has its plan reviewed for impact, and the chunk plan is updated accordingly. This is the foundation reference rot prevention mechanism (per Principles §1.4).

### 3.3 What Lives Where

When in doubt about which artefact something belongs in:

If it describes a component (its purpose, its inputs, its outputs, its integration with other components), it's foundation reference.

If it describes a piece of work (what's being built when, with what acceptance), it's chunk plan.

If it's a principle or invariant that constrains everything, it's the principles document (which is technically foundation reference entry 0.0, but is preserved as a separate document for visibility).

If it's neither (a one-off operational note, a meeting summary, a retrospective), it lives elsewhere and is referenced from the appropriate artefact only if needed.

---

## 4. File Organisation

### 4.1 Working Tree

The Doc 1 v2 documentation lives in a working tree organised as follows:

```
docs/
  doc1_v2/
    principles_of_operation.md          (foundation reference entry 0.0)
    foundation_reference_structure.md   (this document; entry 0.1)
    foundation_reference/
      topic_01_agent_layer/
        entry_1_0_evidence_layer_overview.md
        entry_1_1_e1_listed_fundamental_equity.md
        entry_1_2_e2_industry_business_model.md
        ... (one file per entry)
      topic_02_master_agent/
        entry_2_0_m0_overview_boss_agent.md
        ...
      ... (one folder per topic cluster, one file per entry)
    chunk_plan/
      cluster_00_walking_skeleton.md
      cluster_01_investor_onboarding.md
      ... (one file per cluster)
      chunk_plan_index.md   (master index of all chunks across all clusters)
```

This structure is illustrative; the team is free to adjust file locations during cluster 0 setup as long as the naming convention stays consistent.

### 4.2 File Naming

Foundation reference entry files: `entry_X_Y_short_descriptive_slug.md` where X is the topic number, Y is the entry number, and the slug is a brief description.

Chunk plan cluster files: `cluster_NN_short_descriptive_slug.md` where NN is the zero-padded cluster number.

The naming convention exists so files sort correctly in directory listings and so cross-references are unambiguous.

### 4.3 Versioning Across Iterations

When a foundation reference entry undergoes a meaningful revision (not just typo fixes), the revision history at the bottom of the entry records the change. Major revisions (those that affect multiple dependent chunks) are flagged in commit messages.

When a chunk's plan changes after the chunk is in-progress or shipped, the revision is logged in the chunk's revision history. This produces an audit trail of "what did this chunk's plan say at the time the work started," which matters for retrospectives.

The Doc 1 v2 working tree itself is in Git (presumably the same repository as the implementation code, possibly a sibling repository, deferred to ops decision). Git history is the version control mechanism.

---

## 5. PDF Rendering

### 5.1 PDF Conventions

Markdown is the canonical format. PDF is the human-readable presentation layer. Both are produced from the same source and must be identical in content.

PDFs follow the Samriddhi style established in earlier documents (Doc 1 v1, Doc 2 v1, D0 product thesis): A4 page size, navy and teal palette, 22mm margins, two-pass TOC build, header showing document title and version on every body page.

The build_pdf_v3.py engine and PDF Generation Skill are the authoritative conventions for rendering. Each foundation reference entry can render as its own PDF if needed, or aggregated PDFs can be produced for review (e.g., a "topic 1 agent layer" PDF aggregating entries 1.0 through 1.7).

### 5.2 When to Render PDF

Foundation reference entries are typically read in markdown form (in IDE, in GitHub web view) during implementation. PDFs are produced for review checkpoints: end of cluster, periodic stakeholder reviews, regulatory submissions.

Chunk plans are typically read in markdown form. PDFs are produced for milestone reviews and quarterly project reviews.

The PDF rendering is automatable (the build_pdf_v3.py engine handles it); rendering is not a manual activity that needs to happen during every revision.

---

## 6. Closing Notes

This document and the principles document together form the documentation infrastructure. With both in place, cluster 0 can open with a clean shape: the cluster authors its foundation reference entries (using the format specified in Section 1), it authors its chunk plan entries (using the format specified in Section 2), and the cross-references between the two are explicit and consistent.

The structure specified here is deliberately conservative. It does not anticipate every scenario. Cluster 0 and cluster 1 will reveal where the structure is right, where it is wrong, and where it is missing. The structure is expected to evolve based on that learning. Revisions to this document are made through explicit revision passes, not through silent drift.

The first cluster work, when it opens, is cluster 0: the walking skeleton. It will produce foundation reference entries in topics 0 (additional principles if any), 14 (C0 if applicable to walking skeleton; probably not), 17 (authentication), and 18 (real-time SSE). It will produce chunk plan cluster_00 with chunks 0.1 and 0.2.

When that cluster ships, this document gets its first revision pass to absorb whatever was learned about the structure itself.

---

**End of Foundation Reference and Chunk Plan Structure document.**
