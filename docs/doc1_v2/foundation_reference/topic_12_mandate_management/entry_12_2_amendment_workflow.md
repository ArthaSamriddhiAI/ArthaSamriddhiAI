# Foundation Reference Entry 12.2: Amendment Workflow

**Topic:** 12 Mandate Management
**Entry:** 12.2
**Title:** Amendment Workflow
**Status:** Locked (cluster 2)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 10.7 (Canonical Entity Schemas; MandateVersion lifecycle status enum)
- FR Entry 12.0 (M1 Overview; this entry implements the lifecycle phases described there)
- FR Entry 12.1 (Mandate Schema and Constraints; the units of change in amendments)
- CP Chunk 2.3 (amendment workflow chunk)
- Future cluster references (cluster 14 N0 alerts surfaces pending amendments to CIO; cluster 15 audit replay reconstructs amendment lineage)

## Cross-references Out

- FR Entry 11.1 (I0 active layer; re-enrichment cascade triggers divergence notifications)
- FR Entry 14.0 (C0 may surface amendment proposals conversationally in future)

---

## 1. Purpose

The amendment workflow is the governance mechanism for changing an existing mandate. The workflow distinguishes initial mandate creation (which auto-activates without approval) from changes to active mandates (which require CIO approval).

The workflow has four required properties: complete audit trail (every state transition captured in T1 with timestamps and actor), versioned history (each amendment creates a new MandateVersion preserved indefinitely), deterministic state machine (clear transitions between draft, pending_approval, active, archived, rejected; no ambiguity about current state), three-action approval (approve, reject, request changes; covers the full range of CIO responses).

Cluster 2 implements the workflow with single-CIO approval. Multi-approver workflows are deferred to production-readiness phase.

## 2. Lifecycle States

The MandateVersion.status field captures all possible states. The state machine:

```
                  initial creation
                        |
                        v
                    [active]
                        |
                  amendment proposed
                        |
                        v
                    [draft] <----- changes_requested -----+
                        |                                 |
                  submit for approval                     |
                        |                                 |
                        v                                 |
                [pending_approval] -------------+---------+
                        |                       |
                  approve                  request changes
                        |                       |
              +---------+---------+
              |                   |
              v                   v
          [active]            [rejected]
              |
        next amendment proposed
              |
              v
          [archived] <-- (becomes archived when superseded)
```

Each state's meaning:

- **draft:** The amendment is being edited. Not visible in CIO's queue. Persists in the database; advisor can return to edit.
- **pending_approval:** The amendment has been submitted for CIO review. Visible in CIO's queue.
- **active:** Currently in force. Exactly one active MandateVersion per Mandate.
- **archived:** Was previously active; superseded by a newer version. Read-only audit record.
- **rejected:** CIO rejected this amendment. Permanently rejected; the previously-active version remains active.

## 3. Amendment Initiation

### 3.1 Triggering an Amendment

The advisor can trigger an amendment from several entry points in cluster 2:

- The investor profile page has an "Amend Mandate" button next to the active mandate display. Clicking takes the advisor to the amendment editor.
- The investor list shows a status indicator on rows where the I0-mandate divergence flag is set (per FR Entry 12.0 §4.3). Clicking the indicator surfaces the divergence detail and offers an "Amend Mandate" affordance.
- A direct URL `/app/advisor/investors/{investor_id}/mandate/amend` opens the amendment editor.

### 3.2 Pre-Amendment Validation

Before creating the draft, M1 validates:

- The investor exists and has an active mandate (otherwise: error, "No mandate to amend; create one first").
- No pending amendment exists for this mandate (otherwise: error, "An amendment is already pending CIO review. Wait for that amendment to be resolved before proposing another.").

The "no pending amendment" check enforces the strict-one-at-a-time rule per FR Entry 12.0 §7.4. This prevents the CIO from facing a queue of competing amendments for the same mandate.

### 3.3 Draft Creation

When validation passes, M1 creates a new MandateVersion record with:

- version_number = current active version's version_number + 1.
- status = `draft`.
- parent_version_id = current active version's version_id.
- All constraint fields copied from the active version.
- created_at = now.
- created_by = the advisor.
- created_via = form (or whatever path triggered the amendment).

The draft becomes the editable state. The advisor's editor displays the draft with the active version's values pre-populated, ready for edits.

### 3.4 Editing the Draft

The advisor edits the draft constraint values. Changes can be saved progressively (auto-save on field change) or on explicit save. The draft persists across sessions; the advisor can return to it.

While the version is in `draft` status, the active version remains active. Downstream consumers (governance gate, portfolio analytics) continue using the active version until an amendment is approved.

### 3.5 Submission for Approval

When the advisor is ready, they click "Submit for Approval". M1:

1. Validates the current draft state per FR Entry 12.1 (validation rules for all five constraint families).
2. If validation fails, returns RFC 7807 problem detail; the advisor corrects and resubmits.
3. If validation passes, transitions the draft's status from `draft` to `pending_approval`. Sets proposed_at = now, proposed_by = advisor.
4. T1 emits `mandate_amendment_proposed`.
5. The advisor sees a confirmation: "Amendment submitted for CIO approval. You'll be notified when it's reviewed."

## 4. CIO Review Surface

### 4.1 Pending Amendments Queue

The CIO sees pending amendments in their queue at `/app/cio/pending-amendments`. The queue lists all MandateVersion records with status='pending_approval', ordered by proposed_at descending (most recently proposed first).

Each row shows:
- Investor name and PAN.
- Amendment summary (e.g., "Equity max changing from 70 to 75; adding 'tobacco stocks' to prohibited list").
- Proposed by (advisor name).
- Proposed at (timestamp; e.g., "2 hours ago").
- Status indicator.
- "Review" button leading to the review surface.

The summary is computed at display time by diffing the pending version against the active version.

### 4.2 Side-by-Side Diff View

The amendment review surface at `/app/cio/pending-amendments/{version_id}` shows the active version on the left and the proposed version on the right. Each constraint family is displayed with values shown in both columns.

Visual treatment of the diff:

- Changed numerical values: old value strikethrough, new value bold, both shown side-by-side. Color: muted for old, prominent for new.
- Added items in lists (e.g., new prohibited instrument): green text or green badge.
- Removed items: red strikethrough or red badge.
- Unchanged constraints: muted color, shown for context.

A summary at the top of the diff view lists changes in plain language (e.g., "Changes proposed: equity max 70 to 75; single-position limit 5 to 7; sector cap unchanged; liquidity floor unchanged; added 'tobacco stocks' to prohibited list; removed 'XYZ Corp' from prohibited list").

### 4.3 Impact Analysis Section

Below the side-by-side diff, the impact analysis section provides three subsections:

**Structural diff** (always populated): The plain-language change list, expanded with brief explanation per change. E.g., "Equity max increasing from 70% to 75% gives more flexibility for equity exposure; previously capped at 70%, now up to 75%."

**Portfolio implications** (cluster 2 placeholder; cluster 4 onwards lights up): A panel that says "Portfolio analysis will be available when holdings data is loaded for this investor (cluster 4 onwards). For now, structural changes are visible above. Approving this amendment will not affect the portfolio until holdings data is integrated."

When cluster 4 ships and holdings exist for the investor, this panel automatically populates with:
- Current portfolio state vs new constraints.
- Compliance status under new constraints (e.g., "Investor's current equity allocation: 62%, within new 55-75% band: COMPLIANT").
- Highlighted breaches (e.g., "Largest single position: 5.8% of portfolio, exceeds new 5% limit: REQUIRES REBALANCE").
- Required actions if approved (e.g., "Approving this amendment will require rebalancing one position to come into compliance with the new single-position limit.").

The cluster 2 implementation reserves this panel in the UI. Cluster 4's holdings integration auto-fills it. No code changes to the cluster 2 implementation are required.

**Activation summary** (always populated): A single line confirming what approval would do. E.g., "Approving will activate version 3 of the mandate. The current active version 2 will be archived but retained for audit. No automatic rebalancing is triggered by mandate approval; rebalancing recommendations require separate case execution."

### 4.4 CIO Three-Action Pattern

The CIO has three actions, each as a primary button at the bottom of the review surface:

**Approve** (primary action):
- Optional comment field.
- Confirms the amendment activation.

**Request Changes** (secondary action):
- Required comment field explaining what needs to change.
- Returns the amendment to the advisor with the CIO's comments.

**Reject** (secondary action with confirmation):
- Required comment field explaining why.
- Confirmation dialog ("Are you sure you want to permanently reject this amendment?") to prevent accidental rejection.
- Permanently rejects the amendment.

Comment fields are stored in the MandateVersion record (approval_comments, rejection_reason, changes_requested_comments) for audit.

## 5. Approval Action Effects

### 5.1 Approve

When the CIO approves:

1. M1 begins a database transaction.
2. The proposed version's status changes from `pending_approval` to `active`. approved_at = now, approved_by = CIO, approval_comments = optional comment.
3. The Mandate's active_version_id changes to the proposed version's version_id.
4. The previously-active version's status changes from `active` to `archived`. archived_at = now.
5. The transaction commits.
6. T1 emits `mandate_amendment_approved`, `mandate_version_activated`, `mandate_version_archived` (three events from one approval action).
7. The CIO sees the success state. The advisor sees the amendment now active in the investor profile.

The transaction ensures atomicity: the mandate's active_version_id, the new version's status, and the old version's status all update together. There's never a moment where a mandate has zero active versions or two active versions.

### 5.2 Reject

When the CIO rejects:

1. M1 begins a database transaction.
2. The proposed version's status changes from `pending_approval` to `rejected`. rejected_at = now, rejected_by = CIO, rejection_reason = required comment.
3. The Mandate's active_version_id remains unchanged (the previously-active version stays active).
4. The transaction commits.
5. T1 emits `mandate_amendment_rejected`.
6. The CIO sees the rejection confirmation. The advisor sees the rejection notification with the CIO's reason.

### 5.3 Request Changes

When the CIO requests changes:

1. M1 begins a database transaction.
2. The proposed version's status changes from `pending_approval` to `draft`. changes_requested_at = now, changes_requested_by = CIO, changes_requested_comments = required comment.
3. The transaction commits.
4. T1 emits `mandate_amendment_changes_requested`.
5. The advisor sees the changes-requested notification with the CIO's comments. They can edit the draft and resubmit (which transitions back to pending_approval).

The version_number does not change; the same draft is updated, not a new version created. This preserves the lineage cleanly: the version_number reflects the amendment iteration, not internal back-and-forth.

## 6. Notifications

### 6.1 Cluster 2 Notification Approach

In cluster 2, notifications are surfaced via T1 telemetry events that downstream UI components can consume. The CIO's pending queue at `/app/cio/pending-amendments` is queried directly from the database (mandate_versions where status='pending_approval'); no real-time push needed.

The advisor's notification of approval/rejection/changes-requested can be surfaced via:
- Polling the investor's mandate state when the advisor visits the investor profile.
- A future cluster 14 (N0 alerts) integration that surfaces notifications in the advisor's alert inbox.

For demo stage in cluster 2, the SSE channel from cluster 0 can emit events that the advisor's UI listens for; when the advisor is on the investor profile page and an amendment they proposed is approved/rejected, the UI updates without a refresh. This is a small implementation detail in chunk 2.3.

### 6.2 I0-Mandate Divergence Notification

Per FR Entry 12.0 §4.3, when I0 re-enrichment for an investor produces values that diverge from the active mandate's locked values, M1 emits `mandate_io_divergence_detected`. The advisor sees this in:

- The investor profile page (a small badge indicates divergence exists; clicking the badge shows the detail).
- A future N0 alerts integration (cluster 14 onwards).

The notification is informational; it does not auto-amend. The advisor decides whether to propose an amendment.

## 7. Concurrent Amendment Conflicts

### 7.1 Strict One-at-a-Time Enforcement

Per FR Entry 12.0 §3.3 and §7.4: only one pending amendment per mandate is permitted at a time. Attempting to start a second amendment while one is pending returns an error to the advisor.

This enforcement happens at the database level via a partial unique index (or in application validation for SQLite where partial indexes are limited):

```sql
-- Postgres (production):
CREATE UNIQUE INDEX one_pending_per_mandate 
  ON mandate_versions (mandate_id) 
  WHERE status = 'pending_approval';

-- SQLite (demo): enforce at application validation layer
-- (SQLite does support partial unique indexes since 3.8; can use either approach)
```

### 7.2 Race Conditions

If two browser tabs of the same advisor (or two advisors) try to start an amendment for the same mandate at almost the same instant:

- The first one to commit succeeds. Their draft exists.
- The second one's commit fails on the unique constraint. M1 returns the error: "An amendment is already pending or in draft for this mandate."

The advisor in the second tab sees the error and can refresh to see the existing amendment in progress.

### 7.3 Approval Conflicts

Two CIOs cannot simultaneously approve the same pending amendment because the approval transaction takes a row-level lock on the MandateVersion record. Whichever transaction commits first wins; the second fails with a "this amendment has already been resolved" error.

## 8. Acceptance Criteria for Cluster 2

The amendment workflow is considered functional when:

1. The advisor can initiate an amendment from the investor profile.
2. Pre-amendment validation correctly blocks if no active mandate exists or if a pending amendment already exists.
3. Draft creation correctly copies all constraint values from the active version.
4. The advisor can edit the draft progressively; changes persist.
5. Submitting the draft transitions status to pending_approval; T1 emits `mandate_amendment_proposed`.
6. The CIO's pending queue at `/app/cio/pending-amendments` correctly lists pending amendments.
7. The amendment review surface displays side-by-side diff with correct visual highlighting.
8. The impact analysis structural diff and activation summary are correctly populated; portfolio implications panel shows the cluster 4 placeholder.
9. Approve action atomically transitions the new version to active and the old version to archived; updates Mandate.active_version_id.
10. Reject action transitions the proposed version to rejected; the previously-active version remains active.
11. Request Changes action transitions the proposed version back to draft with comments; the advisor can edit and resubmit.
12. T1 telemetry emits all events listed in FR Entry 12.0 §6 with correct payloads.
13. Concurrent amendment conflict (two attempts to start amendments simultaneously) is correctly prevented; second attempt returns clear error.
14. Approval transaction atomicity is enforced (no zero-active or two-active mandate states).

## 9. Open Questions

Whether the CIO should be able to edit the proposed amendment before approving (rather than requiring the advisor to resubmit via "request changes") is open. Working answer: not in cluster 2; CIO can only approve, reject, or request changes. Letting CIO edit directly creates ambiguity about authorship of the final amendment. If firms want CIO-edit capability later, can be added.

Whether the I0-mandate divergence notification should auto-trigger an amendment proposal (CIO sees a "divergence detected, here's a suggested amendment") is open. Working answer: not in cluster 2; the notification is informational. Auto-proposed amendments are too proactive for current scope.

Whether amendments should support a "scheduled effective date" (advisor proposes amendment to take effect on a future date, CIO approves, but activation is delayed) is open. Working answer: not in cluster 2; all approvals take effect immediately. Future-dated activation is deferred per cluster 2 ideation §7.5.

## 10. Revision History

April 2026 (cluster 2 drafting pass): Initial entry authored. Amendment lifecycle, CIO three-action pattern, impact analysis with reserved portfolio implications panel, concurrent conflict prevention all locked.

---

**End of FR Entry 12.2.**
