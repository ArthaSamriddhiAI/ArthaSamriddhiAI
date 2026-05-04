# Samriddhi AI: Cluster 2 Ideation Log

## Mandate Management, Architectural Decisions Locked

**Document:** Samriddhi AI, Cluster 2 Ideation Log
**Cluster:** 2 (Mandate Management)
**Pass:** 1 of 2 (Ideation)
**Status:** Complete; ready for drafting pass
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This is the cluster 2 ideation log. It captures the architectural decisions locked during the cluster's ideation pass, before drafting of foundation reference entries and the chunk plan begins.

Cluster 2 ships mandate management as the second product capability of Samriddhi AI. Where cluster 1 onboarded investors into the system, cluster 2 attaches investment policy mandates to those investors. The mandate is the structured representation of the investor's IPS (Investment Policy Statement) constraints: asset allocation bands, concentration limits, liquidity floors, sector caps, prohibited instruments. Future clusters consume the mandate: the governance gate (cluster 8) checks proposed actions against active mandate constraints, portfolio analytics (cluster 10) monitors drift against mandate-defined bands.

Cluster 2 ships four chunks. Chunk 2.1 is form-based mandate creation, the demo-friendly default. Chunk 2.2 is C0 conversational mandate creation, extending C0 from cluster 1 with a new intent. Chunk 2.3 is mandate amendments with CIO approval, the governance workflow for changing existing mandates. Chunk 2.4 is the PDF stub, reserving the capability for production-readiness phase.

The decisions in this log span seven topic areas: cluster scope and chunk boundaries, the canonical mandate schema with five constraint families, the form-based path with I0 defaults integration, the C0 conversational path with structured investor disambiguation, the amendment workflow with CIO approval, the impact analysis design, and demo-stage carve-outs.

---

## 1. Cluster Scope and Chunk Boundaries

### 1.1 Decision: Four Chunks Across Three Paths

**Locked answer:** Cluster 2 ships four chunks. Chunk 2.1 is form-based mandate creation with I0 default suggestions. Chunk 2.2 is C0 conversational mandate creation, adding a `mandate_creation` intent to C0's intent vocabulary. Chunk 2.3 is mandate amendments with CIO approval workflow including impact analysis. Chunk 2.4 is the PDF stub: an endpoint that accepts a PDF and returns a clear "PDF parsing not yet implemented" message, paired with a UI button visibly disabled.

**Rationale:** Chunk 2.1 is the primary path; advisors can fully complete the cluster's purpose using only chunk 2.1. Chunk 2.2 demonstrates that C0 is a reusable pattern across the system rather than a one-off cluster 1 feature; adding the mandate_creation intent is incremental work because the C0 infrastructure (state machine, slot extraction, persistence) was built in cluster 1. Chunk 2.3 is the governance workflow that distinguishes mandate amendments from initial creation; the first mandate auto-completes without approval, but changes require CIO sign-off. Chunk 2.4 reserves the PDF capability architecturally so that production-readiness phase can implement it without altering the foundation reference.

**Alternatives considered:** Skipping chunk 2.2 entirely (rejected because conversational mandate creation is genuinely useful for demos and the C0 reuse cost is low), shipping PDF parsing in cluster 2 (rejected because production-grade PDF parsing requires LLM-based extraction with validation logic that's substantial demo-stage scope creep; better to ship later when realism matters).

### 1.2 Decision: Cluster Acceptance Criterion

**Locked answer:** Cluster 2 ships when an advisor can: (a) create an initial mandate for an investor via the form path with all five constraint families captured and I0-suggested defaults visible; (b) create an initial mandate via C0 conversational path producing the same canonical mandate record; (c) propose an amendment to an existing mandate, and the CIO can review with side-by-side diff, see structural impact analysis, and approve or reject the amendment; (d) see the active mandate version on the investor profile after creation or amendment approval.

If all four points work for at least one investor through each path, cluster 2 is shipped.

---

## 2. Canonical Mandate Schema

### 2.1 Decision: Mandate as Versioned Entity with Five Constraint Families

**Locked answer:** The mandate is a canonical entity with two parts. The Mandate entity itself represents the investor's mandate identity (one per investor). The MandateVersion entity represents a specific version of constraints, with each amendment producing a new version. The active version of a mandate is the version currently in force; older versions are retained for audit but marked inactive.

The five constraint families captured in each MandateVersion:

**Asset allocation bands.** Range constraints per asset class. For demo stage, three asset classes: equity, debt, alternatives (covers gold, real estate, alternatives). Each has a min and max percentage. Example: equity 50-70%, debt 20-40%, alternatives 5-15%. Sum of mins must be less than or equal to 100; sum of maxes must be greater than or equal to 100.

**Single-position concentration limits.** Maximum percentage of portfolio in any single instrument. Single integer percentage. Example: 5% (no single holding more than 5% of portfolio).

**Liquidity floor.** Minimum percentage of portfolio held in highly liquid instruments. Single integer percentage. Suggested default from I0's liquidity_tier on the investor (essential = 10, secondary = 20, deep = 30).

**Sector exposure cap.** Maximum percentage of portfolio in any single sector. Single integer percentage. Example: 25% (no single sector more than 25% of portfolio). Sectors are GICS 1-tier (e.g., Information Technology, Financials, Consumer Staples).

**Prohibited instruments.** List of specific instruments or instrument types the investor explicitly excludes. Free-form list of strings; can be specific tickers (e.g., "ITC Limited"), categories (e.g., "tobacco stocks"), or thematic exclusions (e.g., "fossil fuel companies"). Used by the governance gate as a hard exclusion check.

**Rationale:** These five constraint families cover the most common patterns in Indian wealth advisory IPS documents without modelling every possible constraint. Production-readiness phase can add ESG screens, derivatives policies, leverage limits, geographic restrictions, currency exposure rules, and other constraint types when they become relevant. The five locked here are sufficient to demonstrate mandate compliance meaningfully.

**Alternatives considered:** Fewer constraint families (rejected as too thin; cluster 8 governance gate needs enough constraints to demonstrate real compliance checking), more constraint families (rejected as scope creep; can be added later without breaking the schema).

### 2.2 Decision: Mandate Schema

**Locked answer:** The mandate entity schema:

```
mandates:
  mandate_id (string, ULID, primary key)
  investor_id (string, references investors, indexed, unique within mandates)
  active_version_id (string, references mandate_versions; the current active version)
  created_at (timestamp)
  created_by (string, references users)
  schema_version (integer; current = 1)
```

The mandate_versions entity schema:

```
mandate_versions:
  version_id (string, ULID, primary key)
  mandate_id (string, references mandates, indexed)
  version_number (integer; auto-increments per mandate, starting at 1)
  status (enum: draft, pending_approval, active, archived, rejected)
  
  # Constraint family 1: Asset allocation bands
  equity_min_pct (integer, 0-100)
  equity_max_pct (integer, 0-100; must be >= equity_min_pct)
  debt_min_pct (integer, 0-100)
  debt_max_pct (integer, 0-100; must be >= debt_min_pct)
  alternatives_min_pct (integer, 0-100)
  alternatives_max_pct (integer, 0-100; must be >= alternatives_min_pct)
  
  # Constraint family 2: Single-position concentration
  single_position_max_pct (integer, 0-100)
  
  # Constraint family 3: Liquidity floor
  liquidity_floor_pct (integer, 0-100)
  
  # Constraint family 4: Sector exposure cap
  sector_max_pct (integer, 0-100)
  
  # Constraint family 5: Prohibited instruments
  prohibited_instruments (JSON array of strings)
  
  # Provenance
  created_at (timestamp)
  created_by (string, references users; the advisor or system actor)
  created_via (enum: form, conversational, api, pdf)
  parent_version_id (string, references mandate_versions; nullable, for amendments)
  
  # Approval workflow
  proposed_at (timestamp; when status moved to pending_approval)
  proposed_by (string)
  approved_at (timestamp; nullable)
  approved_by (string; nullable; the CIO or other approver)
  rejected_at (timestamp; nullable)
  rejected_by (string; nullable)
  rejection_reason (string; nullable)
  approval_comments (string; nullable)
  
  # Activation
  activated_at (timestamp; when status moved to active)
  archived_at (timestamp; when status moved from active to archived as a newer version became active)
```

The version_number on each mandate_version is the human-readable version (1, 2, 3, ...). Version 1 is the initial mandate; subsequent versions are amendments.

**Rationale:** Splitting mandate identity from mandate version state matches the canonical pattern: the mandate exists once per investor; versions represent state over time. The status enum captures the full amendment lifecycle. Constraint fields are denormalised into the version table rather than nested in JSON because the governance gate (cluster 8) will need to query against constraint values, and querying denormalised fields is simpler and more performant on both SQLite and Postgres than querying JSON fields.

The prohibited_instruments field is JSON-arrayed because it's a list of strings that don't have a natural relational structure; this is the one constraint family that benefits from JSON.

### 2.3 Decision: Mandate Validation Rules

**Locked answer:** Validation rules per field:

| Field | Validation Rule |
|---|---|
| equity_min_pct, equity_max_pct, debt_min_pct, debt_max_pct, alternatives_min_pct, alternatives_max_pct | Each integer 0-100; max >= min for each pair |
| Cross-constraint: sum of mins | Must be <= 100 |
| Cross-constraint: sum of maxes | Must be >= 100 (otherwise the bands cannot be satisfied) |
| single_position_max_pct | Integer 0-100; recommended 3-10 for typical HNI mandates |
| liquidity_floor_pct | Integer 0-100; warn if significantly different from I0 suggested default |
| sector_max_pct | Integer 0-100; recommended 15-40 for typical HNI mandates |
| prohibited_instruments | List of strings; each 1-200 characters; max 50 items |

Server-side validation produces an RFC 7807 problem detail on failure. The "warn if significantly different from I0 default" rule is a soft warning, not a hard error: the advisor can override the I0 default but the warning surfaces the discrepancy.

**Rationale:** These validation rules prevent obviously invalid mandates without being so restrictive that legitimate variation is blocked. The I0 default warning is the kind of soft signal that helps advisors notice when they're departing from system suggestions, without blocking the departure.

---

## 3. Form-Based Path (Chunk 2.1)

### 3.1 Decision: Single-Page Form with Five Constraint Sections

**Locked answer:** The form is a single page with five sections, each corresponding to a constraint family. Each section has a header explaining the constraint family, the input fields, and inline help text. Sections appear in order: Asset Allocation, Single-Position Limit, Liquidity Floor, Sector Cap, Prohibited Instruments.

The form is accessed from the investor profile detail page (cluster 1) via a "Create Mandate" button visible when no mandate exists yet for the investor. The button is disabled if the investor already has a mandate (in which case the advisor's path is to amend, not create new).

### 3.2 Decision: I0 Defaults Pre-Population

**Locked answer:** When the form loads for a specific investor, fields are pre-populated with I0-suggested defaults where applicable:

- Liquidity floor: pre-populated based on I0 liquidity_tier (essential=10, secondary=20, deep=30). The I0 tier and source is shown alongside the field as helpful context.

- Asset allocation: defaults reflect risk_appetite (aggressive: equity 70-90%, debt 5-25%, alternatives 5-15%; moderate: equity 50-70%, debt 20-40%, alternatives 5-15%; conservative: equity 30-50%, debt 40-60%, alternatives 5-15%). I0 risk_appetite source is shown.

- Single-position limit: default 5% (industry standard; not derived from I0).

- Sector cap: default 25% (industry standard; not derived from I0).

- Prohibited instruments: empty by default. Advisor adds entries.

The advisor can adjust any pre-populated value. If an adjustment significantly diverges from the I0 default (e.g., advisor changes liquidity floor from suggested 30 to 5 for a deep-tier investor), a soft warning surfaces explaining the divergence.

### 3.3 Decision: Form Submission and Initial Mandate Auto-Activation

**Locked answer:** On form submission, the system creates the Mandate entity and the MandateVersion entity (version 1) in a single transaction. The version is created with status=`active` directly because this is the initial mandate (no CIO approval needed; per cluster 2 ideation §1).

The advisor sees a success state showing the created mandate inline, with all constraint values displayed and an option to navigate to the investor's profile (which now shows the active mandate).

T1 telemetry emits `mandate_created`, `mandate_version_activated` events.

---

## 4. C0 Conversational Path (Chunk 2.2)

### 4.1 Decision: New Intent `mandate_creation`

**Locked answer:** C0's intent vocabulary expands from cluster 1 to include `mandate_creation`. Intent detection on the first message classifies between investor_onboarding, mandate_creation, and the other reserved intents.

When the advisor's first message indicates mandate creation (e.g., "I want to set up the mandate for Rajesh"), C0 detects the intent and starts the mandate_creation state machine.

### 4.2 Decision: Structured Investor Disambiguation

**Locked answer:** When the C0 mandate_creation intent is detected, C0 needs to identify which investor the advisor is referring to. Approach: structured disambiguation, not LLM fuzzy matching.

The flow:

1. C0 extracts any name-like reference from the advisor's first message via the same slot extraction pattern used in cluster 1.

2. C0 queries the advisor's investor book for matches. Match logic: exact name match, fuzzy substring match on name (case-insensitive), or by partial matches on PAN if the advisor included a PAN reference.

3. If exactly one match, C0 confirms with the advisor: "I found Rajesh Kumar (PAN ABCDE1234F). Is this the right investor?" Advisor confirms, C0 proceeds.

4. If multiple matches, C0 presents the options as a structured list: "I found multiple investors named Rajesh. Which one?" with a list of matching investors (name, PAN, age, last activity). Advisor selects.

5. If no matches, C0 asks for clarification: "I couldn't find an investor matching that name. Can you provide the PAN or full name?" Advisor responds, C0 retries lookup.

6. If still no match after retry, C0 offers to onboard a new investor first: "It looks like this investor isn't in your book yet. Should I onboard them first?" If yes, C0 transitions to investor_onboarding intent flow, then returns to mandate_creation after onboarding completes.

### 4.3 Decision: Mandate State Machine

**Locked answer:** The mandate_creation state machine has states:

- STATE_INVESTOR_DISAMBIGUATION: identifying which investor.
- STATE_COLLECTING_ASSET_ALLOCATION: collecting the three pairs (equity min/max, debt min/max, alternatives min/max). C0 presents I0-suggested defaults and asks if the advisor wants to use defaults or customise.
- STATE_COLLECTING_CONCENTRATION: collecting single-position max.
- STATE_COLLECTING_LIQUIDITY: collecting liquidity floor with I0 suggestion.
- STATE_COLLECTING_SECTOR: collecting sector cap.
- STATE_COLLECTING_PROHIBITED: collecting prohibited instruments list (advisor can say "none" or list specific items).
- STATE_AWAITING_CONFIRMATION: presenting the summary card.
- STATE_EXECUTING: creating the mandate.
- STATE_COMPLETED: success card.

The state machine reuses C0's underlying patterns from cluster 1 (templated prompts, slot extraction via LLM, validation, error fallback). Per FR Entry 14.0, the implementation pattern is bounded LLM scope: LLM extracts structured values from free-text answers, state machine drives the conversation flow.

### 4.4 Decision: Skip-To-Defaults Affordance

**Locked answer:** During the mandate_creation conversation, the advisor can say "use defaults" or "use I0 suggestions" at any state, and C0 fills the remaining slots with I0-suggested defaults and skips to STATE_AWAITING_CONFIRMATION. This affordance is for the common case where the advisor wants the suggested defaults and doesn't need to customise everything.

The slot extractor recognises this affordance with a templated prompt asking the LLM to detect "fill remaining with defaults" intent.

---

## 5. Amendment Workflow (Chunk 2.3)

### 5.1 Decision: Amendment Lifecycle

**Locked answer:** The amendment lifecycle:

1. **Advisor proposes.** From the investor profile, advisor clicks "Amend Mandate" on the active mandate. They see the active mandate's constraints in an editable form (same form as creation, pre-populated with current values). They make changes, click "Submit Amendment". A new MandateVersion is created with status=`draft`, parent_version_id pointing to the current active version.

2. **Submission for approval.** From the draft, the advisor clicks "Submit for Approval". Status moves to `pending_approval`. T1 emits `mandate_amendment_proposed`. The CIO sees it in their pending amendments queue.

3. **CIO review.** The CIO opens the pending amendment. They see the side-by-side view (current active vs proposed) plus the impact analysis. They click Approve, Reject, or Request Changes.

4. **Approve:** The proposed version's status moves to `active`; the previously-active version's status moves to `archived` with archived_at timestamp; the mandate's active_version_id updates to the new version. T1 emits `mandate_amendment_approved`.

5. **Reject:** The proposed version's status moves to `rejected` with rejection_reason. The current active version remains active. T1 emits `mandate_amendment_rejected`.

6. **Request Changes:** The proposed version's status moves back to `draft` with the CIO's comments. The advisor can edit and resubmit. T1 emits `mandate_amendment_changes_requested`.

### 5.2 Decision: Side-by-Side Diff View

**Locked answer:** The CIO's amendment review surface shows the current active version on the left, the proposed version on the right. Each constraint family is displayed with values shown in both columns. Changed values are highlighted: changed numerical values shown with the old value strikethrough plus the new value bold; added prohibited instruments shown in green; removed prohibited instruments shown in red strikethrough; unchanged constraints shown in muted color.

A summary at the top lists changes in plain language: "Changes proposed: equity max changing from 70 to 75; single-position limit changing from 5 to 7; tobacco stocks removed from prohibited list."

### 5.3 Decision: Impact Analysis with Option 3 Architecture

**Locked answer:** The impact analysis section sits below the side-by-side diff view. It has three subsections:

**Structural diff:** Plain-language list of what's changing (the same summary that appears at the top of the diff view, expanded with brief explanation per change).

**Portfolio implications:** A reserved panel showing "Portfolio analysis will be available when holdings data is loaded for this investor (cluster 4 onwards). For now, structural changes are visible above. Approving this amendment will not affect the portfolio until holdings data is integrated."

When cluster 4 ships and holdings exist for investors, this panel automatically populates with: current portfolio's relationship to new constraints (e.g., "Investor's current equity allocation: 62%, within new 55-75% band"; "Largest single position: 5.8% of portfolio, exceeds new 7% limit, no rebalance required"; "No tobacco holdings in current portfolio"). No code changes needed in the cluster 2 implementation; the panel renders based on availability of holdings data.

**Activation summary:** A single line confirming what approval would do (e.g., "Approving will activate version 2 of the mandate. The previous active version 1 will be archived but retained for audit. No automatic rebalancing is triggered.").

### 5.4 Decision: CIO Approval Three-Action Pattern

**Locked answer:** The CIO has three actions on a pending amendment:

**Approve:** Optional comment field; clicking confirms the amendment activation. Status moves to `active`.

**Request Changes:** Required comment field explaining what needs to change; clicking returns the amendment to the advisor with the CIO's comments. Status moves to `draft`.

**Reject:** Required comment field explaining why; clicking permanently rejects. Status moves to `rejected`. The mandate continues using the current active version.

The three actions are presented as primary buttons with the comment input shown for required-comment paths.

---

## 6. PDF Stub (Chunk 2.4)

### 6.1 Decision: Disabled UI Button with Stub Endpoint

**Locked answer:** The mandate creation form (chunk 2.1) shows an "Upload IPS PDF" button at the top of the form, prominently positioned. The button is visibly disabled (greyed out) with a tooltip on hover: "PDF parsing coming in production phase. Use the form below for now."

The backend endpoint `POST /api/v2/mandates/from-pdf` exists and returns HTTP 501 Not Implemented with an RFC 7807 problem detail: "PDF parsing not yet implemented. Use POST /api/v2/mandates with structured JSON instead."

### 6.2 Decision: Production-Readiness Migration Path

**Locked answer:** When PDF parsing is implemented in a future cluster (or production-readiness phase), the migration consists of:

1. Backend: replace the 501 stub with actual PDF parsing logic (LLM-based extraction or document-parsing service integration).
2. UI: enable the "Upload IPS PDF" button.
3. Workflow: PDF upload triggers extraction, populates the form with extracted values for advisor review, advisor confirms or adjusts, submits.
4. The mandate created via PDF path has `created_via=pdf`.

This is bounded migration work; the architecture supports it without changes to the mandate schema or amendment workflow.

---

## 7. Demo-Stage Carve-Outs

### 7.1 Decision: PDF Parsing Deferred

Per chunk 2.4. The capability is reserved with a stub endpoint and disabled UI button. Production-readiness phase implements it.

### 7.2 Decision: Multi-Approver Workflow Deferred

Some firms may want amendment approval to require multiple approvers (e.g., CIO plus compliance). Cluster 2 implements single-CIO approval. Multi-approver flows are deferred to production-readiness or to a dedicated cluster if firms request it.

### 7.3 Decision: Advanced Constraint Types Deferred

Beyond the five constraint families locked, production IPS documents may include: ESG screens, derivatives policies, leverage limits, geographic restrictions, currency exposure rules, jurisdictional considerations. All deferred. The mandate schema can be extended additively; new constraint families add columns without breaking existing data.

### 7.4 Decision: Mandate-Level Comments and Threading Deferred

Production amendment workflows often include comment threads (advisor and CIO discussing the amendment back-and-forth). Cluster 2 implements simple comment fields on approve/reject/request-changes actions; threaded discussion is deferred.

### 7.5 Decision: Mandate Effective-Date Scheduling Deferred

Some mandates may need to take effect on a future date (e.g., starting next quarter). Cluster 2 mandates take effect immediately on activation. Future-dated activation is deferred.

### 7.6 Decision: Bulk Mandate Operations Deferred

Cluster 2 handles one mandate at a time. Bulk operations (e.g., apply the same amendment to all investors in a household) are deferred.

### 7.7 Decision: Mandate Templates Deferred

Some firms might want CIO-approved mandate templates that advisors can select from rather than starting from scratch. Cluster 2 has no template system; advisors create each mandate from scratch (with I0 defaults). Templates are a deferred capability.

---

## 8. Cluster 2 Closure

### 8.1 Decisions Locked Summary

Decisions across seven topic areas:

Cluster scope: four chunks (form-based 2.1, conversational 2.2, amendments 2.3, PDF stub 2.4).

Mandate schema: Mandate plus MandateVersion entities; five constraint families (asset allocation bands, single-position limit, liquidity floor, sector cap, prohibited instruments); validation rules including cross-constraint checks.

Form-based path: single-page five-section form, I0 defaults pre-populated with source labels, soft warnings on significant divergence, initial mandate auto-active without CIO approval.

C0 conversational path: new mandate_creation intent, structured investor disambiguation (no LLM fuzzy matching), seven-state state machine, skip-to-defaults affordance.

Amendment workflow: advisor-proposes-CIO-approves pattern with three actions (approve, reject, request changes); side-by-side diff view with change highlighting; impact analysis with reserved portfolio implications panel that lights up in cluster 4.

PDF stub: disabled UI button with tooltip, 501 endpoint with clear problem detail, bounded migration path documented.

Demo-stage carve-outs: PDF parsing, multi-approver, advanced constraints, threaded comments, future-dated activation, bulk operations, templates all deferred.

### 8.2 Foundation Reference Entries to be Authored in Drafting Pass

Topic 12 Mandate Management:
- FR Entry 12.0 (M1 Overview)
- FR Entry 12.1 (Mandate Schema and Constraints)
- FR Entry 12.2 (Amendment Workflow)

Topic 14 Conversational and Notification:
- FR Entry 14.0 revision (mandate_creation intent added to C0's intent vocabulary; cross-references updated)

Topic 10 Data Layer:
- FR Entry 10.7 revision (Mandate and MandateVersion entities added to canonical schemas)

Plus chunk plan:
- cluster_02_chunk_plan.md with chunks 2.1, 2.2, 2.3, 2.4

Plus cluster 2 demo-stage addendum capturing the carve-outs.

### 8.3 Decisions Deferred

Per §7. Beyond those, two cluster-internal items are deferred for in-implementation discretion:

The exact visual treatment of the side-by-side diff view (colors, layout, transitions) is design discretion during implementation.

The exact wording of CIO's prompt for approve/reject/request-changes comments is implementation discretion.

### 8.4 Open Questions for Drafting Pass

Whether the cluster 2 telemetry events should distinguish "first mandate created" from "subsequent amendment activated" is open. Working answer: yes, separate event types (`mandate_initial_created`, `mandate_amendment_activated`) so audit can clearly distinguish baseline-setting from amendment activity.

Whether the I0 re-enrichment cascade (changing investor's risk_appetite triggers I0 re-enrichment which suggests new mandate liquidity floor) should be surfaced to the advisor as a notification when it happens is open. Working answer: yes, soft notification that says "I0 re-enrichment changed the suggested liquidity floor from 20 to 30 based on updated time horizon. Your existing mandate may need amendment." The notification doesn't auto-amend; it just informs.

The exact cascade behaviour when an investor's I0-relevant fields change (does the active mandate become "stale" in some way, or does it just continue using its locked liquidity floor) is open. Working answer: the active mandate remains active with its locked values; the soft notification surfaces the divergence; the advisor decides whether to propose an amendment. This preserves the mandate's audit integrity while making divergence visible.

---

**End of Cluster 2 Ideation Log. Ready for drafting pass.**
