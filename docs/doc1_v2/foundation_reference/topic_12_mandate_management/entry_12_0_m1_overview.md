# Foundation Reference Entry 12.0: M1 Mandate Management Overview

**Topic:** 12 Mandate Management
**Entry:** 12.0
**Title:** M1 Overview
**Status:** Locked (cluster 2)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 10.7 (Canonical Entity Schemas; Mandate and MandateVersion definitions)
- FR Entry 12.1 (Mandate Schema and Constraints; the detailed five-constraint specification)
- FR Entry 12.2 (Amendment Workflow; the amendment lifecycle)
- FR Entry 14.0 (C0 Conversational Orchestrator; mandate_creation intent)
- CP Chunks 2.1, 2.2, 2.3, 2.4 (mandate management chunks)
- Future cluster references (cluster 8 governance gate consumes active mandates; cluster 10 portfolio analytics monitors drift against mandate bands; cluster 15 audit replay reconstructs historical mandate versions)

## Cross-references Out

- FR Entry 11.0, 11.1 (I0; mandate creation reads I0 enrichment for defaults)
- Principles §3.10 (mandate is consumed by the governance gate)

---

## 1. Purpose

M1 is the system's mandate management component. It owns the lifecycle of mandates: creation, amendment, version management, activation, archival. M1 produces the active mandate version that downstream components consume: the governance gate checks proposed actions against active mandate constraints; portfolio analytics monitors drift against mandate-defined bands; audit replay reconstructs historical mandate versions for case reproduction.

The mandate is the structured representation of the investor's IPS (Investment Policy Statement). Where the IPS in production is typically a multi-page PDF document with prose constraints, the mandate is the system's machine-readable, versioned, validated equivalent. M1 produces and maintains this representation.

M1's design priorities are: bit-perfect versioning (every constraint change creates a new version, never overwrites), defensible governance (amendments require explicit approval), I0 integration (mandate defaults derive from investor enrichment signals, with override capability), audit completeness (every state transition is captured in T1 with timestamps and actor attribution).

## 2. Architecture

M1 is a service that lives in the application backend. It owns:

- The mandate lifecycle service (creates mandates, proposes amendments, executes approvals).
- The mandate validation layer (cross-constraint validation per FR Entry 10.7 §3.6).
- The CIO approval queue mechanism (queries pending_approval status, surfaces in CIO UI).
- The I0 integration logic (reads I0 enrichment to suggest defaults; soft-warns on divergence).
- The T1 telemetry emission for all mandate lifecycle events.

M1 does not own:

- The mandate data storage (Postgres/SQLite tables; that's D0's responsibility).
- The form UI or C0 conversational UI (those are presentation layers; M1 is a backend service).
- The governance gate logic (cluster 8 owns G1 mandate compliance; M1 just produces the mandate that G1 reads).

## 3. Mandate Lifecycle

The mandate lifecycle has five logical phases, each with explicit state transitions captured in MandateVersion.status:

### 3.1 Initial Creation Phase

The advisor creates the first mandate for an investor (after the investor has been onboarded per cluster 1). The path can be form-based (chunk 2.1), conversational via C0 (chunk 2.2), API (functional but no UI), or PDF (stubbed in chunk 2.4).

Regardless of path, the creation flow:

1. M1 verifies the investor exists and does not already have a mandate (the unique constraint on `mandates.investor_id` enforces this; attempting to create a second mandate for the same investor returns an error).

2. The advisor (via form/C0/API) supplies the five constraint families' values. Where applicable, I0 defaults are pre-populated:
   - liquidity_floor_pct defaulted from investor's I0 liquidity_tier (essential=10, secondary=20, deep=30).
   - asset allocation defaulted from investor's risk_appetite (aggressive: equity 70-90 / debt 5-25 / alternatives 5-15; moderate: 50-70 / 20-40 / 5-15; conservative: 30-50 / 40-60 / 5-15).
   - Other fields (single_position_max_pct, sector_max_pct, prohibited_instruments) default to industry-standard or empty values.

3. M1 validates the supplied values per FR Entry 10.7 §3.6. Hard validation failures are returned as RFC 7807 problem details. Soft warnings (e.g., divergence from I0 default) are returned alongside but don't block.

4. On valid input, M1 creates the Mandate record (with active_version_id pending) and the MandateVersion record (version_number=1, status=`active`). The Mandate's active_version_id is set to the new version's ID. Both writes happen in a single database transaction.

5. T1 telemetry events fire: `mandate_created`, `mandate_version_created`, `mandate_version_activated`.

6. The advisor sees the success response (form path: inline display of the active mandate; C0 path: success card in chat; API path: HTTP 201 with the created mandate JSON).

### 3.2 Active Phase

A mandate has exactly one active MandateVersion at any time. The active version is what downstream components read when they need the mandate's constraints.

During the active phase, no state transitions occur on the active version. The version is read-only from the perspective of mutations; it's read by:

- Investor profile UI (displays the active mandate's constraints).
- Governance gate (cluster 8) when checking proposed actions.
- Portfolio analytics (cluster 10) for drift monitoring.

The active phase ends when an amendment is approved (transitioning the current active version to `archived`) or when the mandate is deleted (not implemented in cluster 2).

### 3.3 Amendment Proposal Phase

When the advisor wants to change the mandate's constraints, they propose an amendment per FR Entry 12.2. The proposal flow:

1. The advisor (from the investor profile or another entry point) initiates an amendment. M1 creates a new MandateVersion with version_number incremented from the current active, status=`draft`, parent_version_id pointing to the current active version, and constraint values copied from the active version (so the advisor edits a copy rather than editing the active version directly).

2. The advisor edits the draft version. Changes are saved to the database as the advisor types or on explicit save.

3. When ready, the advisor submits the draft for approval. M1 transitions the version's status from `draft` to `pending_approval`, sets proposed_at and proposed_by.

4. T1 emits `mandate_amendment_proposed`. The amendment appears in the CIO's pending queue.

### 3.4 Approval Phase

The CIO reviews pending amendments per FR Entry 12.2. The review surface shows side-by-side current active vs proposed, with diff highlighting and impact analysis.

The CIO has three actions:

**Approve.** M1 transitions the proposed version's status from `pending_approval` to `active`. M1 simultaneously transitions the previously-active version's status from `active` to `archived`. M1 updates the Mandate's active_version_id to the new version. T1 emits `mandate_amendment_approved`, `mandate_version_archived`.

**Reject.** M1 transitions the proposed version's status from `pending_approval` to `rejected`. The previously-active version remains active (no state change). T1 emits `mandate_amendment_rejected`.

**Request Changes.** M1 transitions the proposed version's status from `pending_approval` back to `draft`, with changes_requested_at, changes_requested_by, changes_requested_comments populated. The advisor can edit and resubmit. T1 emits `mandate_amendment_changes_requested`.

### 3.5 Archival Phase

When an amendment is approved, the previously-active version transitions to `archived`. Archived versions are retained indefinitely for audit purposes. They are not deleted from the database.

Archived versions are read-only. Audit replay (cluster 15) queries archived versions to reconstruct historical decision contexts.

## 4. I0 Integration

M1 integrates with I0 in two directions: reading I0 outputs as defaults during mandate creation, and reacting to I0 re-enrichment events with soft notifications during active mandate phase.

### 4.1 Defaults During Creation

When the form path or C0 conversational path loads the mandate creation flow for a specific investor, M1 reads the investor's I0 enrichment fields (life_stage, liquidity_tier) and computes default values for the constraint families:

- Liquidity floor: liquidity_tier maps to default percentage (essential=10, secondary=20, deep=30).
- Asset allocation: risk_appetite maps to default bands (aggressive/moderate/conservative).
- Sector cap, single_position max, prohibited list: do not derive from I0; defaulted to industry standards or empty.

The defaults are pre-populated in the form. The advisor can adjust any value. The form/C0 surface shows the I0 source alongside the field (e.g., "Liquidity floor 30% (suggested by I0 deep liquidity tier)") so the advisor sees where the default came from.

### 4.2 Soft Warnings on Divergence

When the advisor adjusts a default to a value significantly different from the I0 suggestion, M1's validation layer returns a soft warning alongside the value. The warning describes the divergence: "Liquidity floor of 5% diverges significantly from I0-suggested 30% (deep liquidity tier). This may not align with the investor's needs. Confirm if this is intentional."

The warning is informational; it does not block submission. The advisor can override.

### 4.3 Re-Enrichment Notifications

When an investor's I0-relevant fields change (age, risk_appetite, time_horizon edited via cluster 1's investor profile, when edit is implemented), I0 re-enrichment runs and produces new life_stage and liquidity_tier values. The active mandate's constraints don't auto-change; the mandate retains its locked values.

However, M1 detects when the new I0 values would have suggested different defaults than the active mandate's actual values. When detected, M1 emits a soft notification to the advisor: "I0 re-enrichment for [investor name] suggests new mandate defaults (liquidity floor: 30 vs current 20). The active mandate is unchanged; consider proposing an amendment if the new defaults better fit the investor's circumstances."

The notification surfaces in the advisor's notification feed (N0; cluster 14) once that's implemented; in cluster 2, the notification is logged in T1 with event type `mandate_io_divergence_detected` and the investor profile shows a small badge indicating I0-mandate divergence exists.

## 5. Integration Points

### 5.1 Reads From

- The Investor entity (FR Entry 10.7 §2) for investor identity and I0 enrichment fields.
- The current active MandateVersion when initiating an amendment (the new draft is a copy of active).
- The MandateVersion records when constructing CIO pending queue or the amendment review surface.

### 5.2 Writes To

- The Mandate table (initial creation).
- The MandateVersion table (initial version, drafts, status transitions on submit/approve/reject/request-changes).
- T1 telemetry events.

### 5.3 Read By

- Investor profile UI (displays active mandate).
- Governance gate (cluster 8) for mandate compliance checking on proposed actions.
- Portfolio analytics (cluster 10) for drift monitoring.
- Audit replay (cluster 15) for historical reconstruction.
- The CIO's pending amendments queue.

## 6. Telemetry

M1 emits T1 events for every mandate lifecycle transition:

- `mandate_created`: emitted on initial mandate creation. Payload: mandate_id, investor_id, version_id, created_via.
- `mandate_version_created`: emitted on every MandateVersion creation (initial or amendment draft). Payload: version_id, mandate_id, version_number, status, created_via.
- `mandate_version_activated`: emitted when status moves to `active`. Payload: version_id, mandate_id, version_number, activated_at.
- `mandate_version_archived`: emitted when previously-active version moves to `archived`. Payload: version_id, mandate_id, version_number, archived_at, replaced_by_version_id.
- `mandate_amendment_proposed`: emitted on draft to pending_approval transition. Payload: version_id, mandate_id, version_number, proposed_by.
- `mandate_amendment_approved`: emitted on pending_approval to active transition. Payload: version_id, mandate_id, version_number, approved_by, approval_comments.
- `mandate_amendment_rejected`: emitted on pending_approval to rejected transition. Payload: version_id, mandate_id, version_number, rejected_by, rejection_reason.
- `mandate_amendment_changes_requested`: emitted on pending_approval back to draft transition. Payload: version_id, mandate_id, version_number, changes_requested_by, changes_requested_comments.
- `mandate_io_divergence_detected`: emitted when I0 re-enrichment produces values diverging from active mandate. Payload: investor_id, mandate_id, divergence_summary.

These events feed audit replay and provide the full lifecycle trail for compliance review.

## 7. Failure Modes and EX1 Contract

### 7.1 Duplicate Mandate Creation

An advisor attempts to create a mandate for an investor who already has one. M1 returns an error: "Investor already has an active mandate. To change constraints, propose an amendment instead." The error includes a link/reference to the existing mandate.

EX1 routing: user error, not a system failure. Logged in T1 as `mandate_creation_blocked_existing` for usage analytics.

### 7.2 Validation Failure

The submitted mandate values fail validation (e.g., sum of mins exceeds 100, max < min for an asset class). M1 returns an RFC 7807 problem detail with the specific failure(s). The advisor corrects and resubmits.

EX1 routing: user error.

### 7.3 Concurrent Amendment Conflict

Two advisors (or two browser tabs of the same advisor) try to amend the same mandate concurrently. The second amendment proposal sees that the parent_version_id no longer points to the active version (because the first amendment has already been activated, or vice versa). M1 detects this and returns a 409 Conflict: "The mandate has been changed since you started this amendment. Please refresh and start again."

The implementation uses optimistic concurrency control: when transitioning a draft to pending_approval, M1 checks that the parent_version_id still matches the mandate's active_version_id. If not, conflict.

EX1 routing: user error, but worth surfacing to ops if it happens frequently (might indicate a race condition in the UI).

### 7.4 Approval of Stale Pending Amendment

A pending amendment exists. Meanwhile, somehow the active version changes (e.g., another amendment was approved through a different path). The CIO opens the pending amendment, but the diff view is now against a stale active version.

In cluster 2, this is unlikely because the system enforces "exactly one pending amendment per mandate at a time" via the validation layer. Two simultaneous pending amendments for the same mandate are not permitted; the second proposal fails with a "mandate already has a pending amendment" error.

EX1 routing: not applicable in cluster 2 due to the prevention.

## 8. Acceptance Criteria for Cluster 2

M1 is considered functional in cluster 2 when:

1. An advisor can create an initial mandate for an investor via form, C0 conversational, or API path. The mandate immediately becomes active without CIO approval.

2. The mandate creation reads I0 enrichment for the investor and pre-populates defaults correctly per §4.1.

3. Soft warnings are returned for I0 divergence per §4.2; the advisor can override.

4. Attempting to create a duplicate mandate for an investor returns the appropriate error.

5. An advisor can propose an amendment to an existing mandate. The proposal creates a new MandateVersion in `draft` status with constraint values copied from active.

6. The advisor can edit the draft and submit for approval. Status transitions to `pending_approval`.

7. The CIO sees the pending amendment in their queue. The amendment review surface shows side-by-side diff with change highlighting plus impact analysis with the reserved portfolio implications panel.

8. The CIO can approve, reject, or request changes. State transitions follow the lifecycle in §3.4. Comments are captured per the validation rules.

9. Approving an amendment transitions the previously-active version to `archived` and the new version to `active`. The mandate's active_version_id updates atomically.

10. I0 re-enrichment that produces values diverging from active mandate triggers `mandate_io_divergence_detected` event and surfaces a notification.

11. T1 telemetry emits all events listed in §6 with correct payload structure.

12. Concurrent amendment conflict (§7.3) is detected and returns 409 with a clear error message.

## 9. Open Questions

Whether the cluster 2 implementation should enforce "one pending amendment per mandate at a time" strictly, or allow multiple pending amendments with the CIO selecting which to approve, is open. Working answer per §7.4: enforce strict one-at-a-time. The CIO can request changes on a pending amendment; the advisor revises; the cycle continues. Multiple parallel pending amendments add complexity without clear product benefit.

Whether M1 should auto-archive amendments that have been in `draft` status for an extended period (e.g., 30 days inactive) is open. Working answer: not in cluster 2; drafts persist indefinitely. Future cluster can add cleanup if needed.

Whether the mandate_io_divergence_detected event should be configurable (e.g., advisor can mute notifications for a specific divergence) is open. Working answer: not in cluster 2; the notification is informational and infrequent. Mute capability can be added later.

## 10. Revision History

April 2026 (cluster 2 drafting pass): Initial entry authored. M1 architecture, lifecycle, I0 integration, telemetry, failure modes, acceptance criteria all locked.

---

**End of FR Entry 12.0.**
