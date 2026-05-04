# Chunk Plan: Cluster 2 - Mandate Management

**Document:** Samriddhi AI, Chunk Plan, Cluster 2
**Cluster:** 2 (Mandate Management)
**Status:** Chunks 2.1 + 2.3 + 2.4 shipped May 2026; chunk 2.2 ready for implementation
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cluster Header

### Purpose

Cluster 2 ships mandate management as the second product capability of Samriddhi AI. By the end of this cluster, an advisor can attach an investment policy mandate to an investor through two creation paths (form-based or C0 conversational), the system uses I0 enrichment to suggest defaults for constraint values, the CIO can review and approve amendments to existing mandates with side-by-side diff and impact analysis, and the system maintains a complete audit trail of all mandate versions through the amendment lifecycle.

This cluster connects directly to cluster 1: investors onboarded in cluster 1 receive their mandates in cluster 2. The I0 enrichment from cluster 1 provides defaults for mandate constraints. The C0 conversational orchestrator from cluster 1 gains a new intent (mandate_creation). The patterns established here (versioned entities, advisor-proposes-CIO-approves workflows, side-by-side diff reviews) will recur in subsequent clusters.

### Foundation References Produced

This cluster authors:
- FR Entry 12.0: M1 Overview
- FR Entry 12.1: Mandate Schema and Constraints
- FR Entry 12.2: Amendment Workflow
- FR Entry 14.0 Cluster 2 Revision Note (mandate_creation intent added to C0)
- FR Entry 10.7 Revised (Mandate and MandateVersion entities added to canonical schemas)

### Foundation References Consumed

- Principles of Operation (sections on agent architecture, data layer, governance and accountability)
- Foundation Reference and Chunk Plan Structure
- FR Entry 10.7 (Investor entity from cluster 1)
- FR Entry 11.0, 11.1 (I0 from cluster 1; provides mandate defaults)
- FR Entry 14.0 (C0 from cluster 1; mandate_creation intent extends this)
- FR Entry 16.0 (SmartLLMRouter from cluster 1; C0 still depends on this)
- FR Entry 17.0, 17.1, 17.2 (auth from cluster 0)
- FR Entry 18.0 (SSE from cluster 0)
- Cluster 0 Dev-Mode Addendum (stub auth carries forward)
- Cluster 1 Demo-Stage Addendum (its carve-outs continue)
- Demo-Stage Database Addendum (SQLite carries forward)

### Cluster-Level Acceptance Criterion

Cluster 2 ships when an advisor can:

1. Create an initial mandate for an investor via the form path with all five constraint families captured. The form pre-populates I0-suggested defaults that the advisor can adjust.
2. Create an initial mandate via C0 conversational path producing the same canonical mandate record. The conversation handles structured investor disambiguation and offers a skip-to-defaults affordance.
3. Propose an amendment to an existing mandate. The CIO can review with side-by-side diff, see structural impact analysis with the reserved portfolio implications panel, and approve, reject, or request changes.
4. See the active mandate version on the investor profile after creation or amendment approval.
5. (PDF stub) See the disabled "Upload IPS PDF" button on the mandate creation form with the appropriate tooltip.

If all five points work for at least one investor through each path, cluster 2 is shipped.

---

## Chunk 2.1: Form-Based Mandate Creation with I0 Defaults

### Header

- **Chunk ID:** 2.1
- **Title:** Form-Based Mandate Creation with I0 Defaults
- **Status:** Shipped (May 2026)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 2 ideation log)
  - Drafting completed: April 2026
  - Implementation started: May 2026
  - Shipped: May 2026

**Chunk-shipped retrospective notes** (full retrospective at cluster 2 close):

1. **Circular FK between Mandate and MandateVersion needs ``use_alter=True``.**
   :class:`Mandate.active_version_id` → :class:`MandateVersion.version_id`
   AND :class:`MandateVersion.mandate_id` → :class:`Mandate.mandate_id`.
   SQLAlchemy + Alembic both need ``ForeignKey(..., use_alter=True)`` on
   one side so the migration can create either table first without
   tripping a circular-FK error. Pattern documented for future
   versioned-entity tables (cluster 4 model portfolio, cluster 5 cases).

2. **Audit T1 event for failed creates needs a separate transaction.** When
   the duplicate-mandate guard raises, the create transaction rolls back
   — and any T1 event emitted inside that transaction rolls back with it.
   Solution: the service raises without emitting; the router catches the
   exception, opens a fresh ``async with db.begin():`` block, emits the
   ``mandate_creation_blocked_existing`` event, and only then returns the
   409. Pattern: emit blocked-action audit events from the router's
   exception handler, never inside the failing transaction.

3. **Soft warnings ride alongside the success response, not the failure
   path.** Hard rules raise :class:`MandateValidationError` → 400 with a
   ``failures`` list; soft warnings (sector cap outside typical, liquidity
   floor diverges from I0) ride in the 201 response's ``warnings`` array.
   The advisor sees them inline AFTER the create succeeds.

4. **Pre-populated form via ``GET .../mandate/defaults`` keeps the form
   stateless.** The form fetches defaults on mount + restores any
   sessionStorage draft if present (mirroring chunk 1.1's pattern).
   The ``MandateDefaults.sources`` map flows through to per-field
   "I0 suggested by..." labels without the form knowing I0's internals.

5. **PDF stub (chunk 2.4) bundled into chunk 2.1's commit.** The disabled
   "Upload IPS PDF" button lives at the top of chunk 2.1's form, so the
   two chunks ship in a single commit even though they're logically
   separate in the plan.

### Purpose

Chunk 2.1 ships the form-based mandate creation path: a single-page form with five sections corresponding to the constraint families, I0-suggested defaults pre-populated, validation with hard rules and soft warnings, and submission that creates the Mandate and the initial MandateVersion (auto-active) atomically.

This is the demo-friendly default path. An advisor onboards an investor (cluster 1), navigates to the investor's profile, clicks "Create Mandate", fills the five-section form (with I0 defaults already populated), reviews any soft warnings, and submits. The active mandate appears on the investor profile.

### Dependencies

**Foundation reference:**
- FR Entry 10.7 (revised; Mandate and MandateVersion entities)
- FR Entry 11.0, 11.1 (I0 active layer for defaults)
- FR Entry 12.0, 12.1 (M1 overview and constraint specification)

**Other chunks:**
- Cluster 0 chunks (auth, app shell)
- Cluster 1 chunks (investor onboarding; provides Investor records)

### Scope: In

- `mandates` and `mandate_versions` tables in the database with schemas from FR Entry 10.7 §3.1, §3.2; Alembic migration.
- Mandate creation service in the backend: validates inputs, computes I0 defaults, creates Mandate and MandateVersion records atomically.
- API endpoints:
  - `POST /api/v2/investors/{investor_id}/mandate` (create initial mandate; returns 409 if mandate already exists for investor)
  - `GET /api/v2/investors/{investor_id}/mandate` (fetch active mandate; returns 404 if no mandate exists)
  - `GET /api/v2/investors/{investor_id}/mandate/versions` (fetch all versions, ordered by version_number)
  - `GET /api/v2/mandates/{mandate_id}` (fetch by mandate_id)
- Form UI at `/app/advisor/investors/{investor_id}/mandate/new`:
  - Five-section single-page form (Asset Allocation, Single-Position Limit, Liquidity Floor, Sector Cap, Prohibited Instruments).
  - I0 defaults pre-populated based on investor's risk_appetite and liquidity_tier.
  - I0 source labels alongside fields (e.g., "Liquidity floor 30% (suggested by I0 deep liquidity tier)").
  - Field-level validation on blur (client-side).
  - Cross-constraint validation feedback (sum of mins, sum of maxes).
  - Soft warnings displayed inline when values diverge from I0 defaults or industry-standard ranges.
  - Submit triggers full validation, POST to creation endpoint, then transitions to mandate display on success.
  - sessionStorage draft persistence as advisor types.
- Mandate display on investor profile:
  - The investor profile detail page (cluster 1) gains a "Mandate" section showing the active mandate's constraints in a read-only summary view.
  - "Amend Mandate" button visible (linked to chunk 2.3 amendment editor).
  - Constraint families displayed in a clean structured layout matching the form section order.
- "Create Mandate" button on investor profile (visible when no mandate exists yet).
- T1 telemetry events emitted: `mandate_created`, `mandate_version_created`, `mandate_version_activated`.

### Scope: Out

- C0 conversational mandate creation (chunk 2.2 ships this).
- Mandate amendments (chunk 2.3 ships this).
- PDF parsing (chunk 2.4 ships the stub; chunk 2.1 doesn't include PDF UI).
- Sector classification per instrument (deferred to cluster 4 D0 data integration).
- Mandate templates or copying mandates from other investors (deferred per cluster 2 ideation §7.7).
- Bulk mandate operations (deferred per cluster 2 ideation §7.6).
- Mandate effective-date scheduling (deferred per cluster 2 ideation §7.5).

### Acceptance Criteria

1. The mandates and mandate_versions tables are created in the database with all fields and indexes per FR Entry 10.7 §3.1, §3.2, §3.5. Alembic migration runs cleanly against SQLite.

2. The form at `/app/advisor/investors/{investor_id}/mandate/new` renders correctly with five sections.

3. I0 defaults are pre-populated correctly:
   - Liquidity floor matches the investor's I0 liquidity_tier (essential=10, secondary=20, deep=30).
   - Asset allocation matches the investor's risk_appetite (aggressive: 70-90/5-25/5-15; moderate: 50-70/20-40/5-15; conservative: 30-50/40-60/5-15).
   - Single-position limit defaults to 5%.
   - Sector cap defaults to 25%.
   - Prohibited instruments defaults to empty.

4. I0 source labels are visible alongside the relevant fields, explaining the default's source.

5. Field-level validation on blur shows clear error messages for invalid inputs (out-of-range percentages, max < min, sum constraints violated).

6. Cross-constraint validation is enforced: sum of mins must be <= 100; sum of maxes must be >= 100. Violations block submission.

7. Soft warnings are displayed inline when values diverge significantly from I0 defaults (more than 10 points off liquidity_floor) or fall outside industry-standard ranges (single_position_max_pct outside 3-10, sector_max_pct outside 15-40). Warnings do not block.

8. sessionStorage draft persistence works: filling part of the form, navigating away, and returning shows the partial draft restored.

9. Submitting a valid form creates a Mandate record (with active_version_id set to the new version) and a MandateVersion record (version_number=1, status=active) in a single transaction.

10. Attempting to create a mandate when one already exists for the investor returns HTTP 409 with a problem detail pointing to the existing mandate.

11. The success state after submission redirects to the investor profile, which now shows the active mandate.

12. The investor profile's "Mandate" section displays the active mandate's constraints correctly. The "Amend Mandate" button is visible.

13. The "Create Mandate" button on the investor profile is hidden once a mandate exists.

14. T1 telemetry emits `mandate_created`, `mandate_version_created`, `mandate_version_activated` with correct payload structure.

15. The form respects firm-info branding (primary and accent colors apply to buttons, labels, accent rules).

16. The PDF upload button (per chunk 2.4) is visible and disabled at the top of the form with the appropriate tooltip.

### Out-of-Scope Notes

- The form is single-page, not a multi-step wizard.
- Sector classification of holdings (cluster 4) is not yet implemented; the sector_max_pct field exists and is validated but the runtime check against actual holdings is deferred.
- Editing investor fields (which would trigger I0 re-enrichment and potentially divergence notifications) is deferred per cluster 1 demo-stage addendum; the I0-mandate divergence notification mechanism is implemented in chunk 2.3 amendment workflow but is exercised meaningfully only when investor edit ships.

### Implementation Notes

- The Mandate and MandateVersion SQLAlchemy models correspond field-for-field to FR Entry 10.7 §3.1, §3.2.
- I0 default computation is a small pure function in M1 that takes an Investor record and returns suggested constraint values. Test fixtures should cover all (risk_appetite x liquidity_tier) combinations.
- The form's five-section layout uses shadcn/ui components: Form, Input, NumberInput, Tags (for prohibited instruments list), Card. Each section has a header and explanatory text.
- Soft warnings render as Alert components with informational tone (yellow/orange, not red).
- The investor profile's Mandate section is a new component; reuse the constraint display layout from the form's success card.

### Open Questions

The exact wording of soft warning messages is design discretion during implementation.

The visual treatment of the "I0 source label" alongside default values can iterate; working answer: small text below the field with an info icon and tooltip.

### Revision History

April 2026 (cluster 2 drafting pass): Initial chunk plan authored.

---

## Chunk 2.2: C0 Conversational Mandate Creation with mandate_creation Intent

### Header

- **Chunk ID:** 2.2
- **Title:** C0 Conversational Mandate Creation with mandate_creation Intent
- **Status:** Planned (drafting complete)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 2 ideation log)
  - Drafting completed: April 2026

### Purpose

Chunk 2.2 ships the conversational mandate creation path. An advisor types "I want to set up the mandate for [investor]" in C0's chat surface, C0 detects mandate_creation intent, structurally disambiguates the investor reference, walks through the five constraint families with I0 defaults, applies skip-to-defaults if the advisor wants the suggested values, and creates the mandate.

This chunk demonstrates that C0 is a reusable pattern, not a one-off cluster 1 feature. The C0 infrastructure (state machine, slot extraction, persistence, error handling) from cluster 1 is reused; this chunk adds a new intent and a new state machine.

### Dependencies

**Foundation reference:**
- FR Entry 14.0 (C0; cluster 1 base) plus the cluster 2 revision note
- FR Entry 12.0, 12.1 (M1 service called by STATE_EXECUTING)
- FR Entry 11.1 (I0 active layer for defaults)
- FR Entry 16.0 (SmartLLMRouter; C0's LLM dependency)

**Other chunks:**
- Chunk 2.1 (provides M1 mandate creation service)
- Chunk 1.2 (provides C0 base infrastructure)

### Scope: In

- C0's intent vocabulary expanded to include `mandate_creation`. Updated intent detection prompt in C0's skill.md.
- mandate_creation state machine in C0 backend, with eight states per FR Entry 14.0 Cluster 2 Revision §2.3.
- Investor disambiguation backend logic: query advisor's investor book by name (exact, fuzzy substring, case-insensitive), or by partial PAN match.
- Skip-to-defaults affordance: slot extractor recognises "use defaults" intent and skips to STATE_AWAITING_CONFIRMATION with I0-suggested values populated.
- Confirmation card for STATE_AWAITING_CONFIRMATION: structured display of all five constraint families' values plus Confirm/Edit buttons.
- Success card for STATE_COMPLETED: displays the active mandate and a button to view the investor profile.
- Error handling per FR Entry 14.0 §5: LLM unavailable falls back to template mode; malformed extraction triggers re-prompts; validation errors trigger correction prompts.
- C0 chat surface reuses the cluster 1 chat UI; no new UI surfaces needed beyond the new card types.
- T1 telemetry events: same C0 events as cluster 1 (`c0_conversation_started`, `c0_intent_detected`, `c0_slot_extracted`, etc.) plus the M1 events from mandate creation.

### Scope: Out

- Other C0 intents (case_opening, alert_response, briefing_request). Reserved for future clusters.
- Voice input. Deferred.
- Multi-turn intent disambiguation (user is unclear about intent). Cluster 2 takes the LLM's first classification.
- Single-utterance mandate creation (advisor expresses entire mandate in one message). Deferred per cluster 2 ideation open questions.

### Acceptance Criteria

1. The advisor can type "I want to set up the mandate for Rajesh" and C0 correctly classifies the intent as `mandate_creation`.

2. The investor disambiguation flow works correctly:
   - Single match: C0 confirms with the advisor and proceeds.
   - Multiple matches: C0 presents structured list of options with name, PAN, age, last activity. Advisor selects.
   - No match: C0 asks for clarification with PAN or full name.
   - Still no match after retry: C0 offers to onboard a new investor first.

3. The mandate_creation state machine progresses through all eight states correctly, collecting the five constraint families.

4. I0 defaults are surfaced in the conversation (e.g., "Based on Rajesh's I0 deep liquidity tier, I'm suggesting a liquidity floor of 30%. Use this default or customise?").

5. The skip-to-defaults affordance correctly skips to STATE_AWAITING_CONFIRMATION when the advisor says "use defaults" or similar.

6. The confirmation summary card displays all five constraint families' values with correct visual treatment.

7. On confirmation, the mandate is created via the same M1 service that chunk 2.1 uses. The created_via field is set to `conversational`.

8. The success card with active mandate is rendered in the chat.

9. LLM provider unavailable triggers template-fallback mode; the conversation continues asking single-field questions.

10. Malformed LLM extraction triggers re-prompt with hint.

11. Invalid user input (out-of-range percentage, max < min) triggers validation error prompts; already-collected slots preserved.

12. Conversation persistence works: navigating away and returning shows the conversation in progress.

13. T1 telemetry events fire correctly for all conversation lifecycle plus mandate creation events.

14. The investor disambiguation result (which investor was selected) is captured in the conversation's metadata for audit.

### Out-of-Scope Notes

- The C0 chat surface is the same as cluster 1; only the intent detection prompt and state machine logic are added.
- The investor lookup uses simple substring matching, not LLM-powered fuzzy matching.

### Implementation Notes

- The state machine reuses the C0 framework from cluster 1. Adding a new intent is mostly: register the intent name, define the state machine states and transitions, define templated prompts per state, define validation per state.
- The investor lookup query is a simple SQL query against the investors table filtered by advisor_id and name/PAN matching. For SQLite, case-insensitive matching uses the `LOWER()` function or `COLLATE NOCASE`.
- The disambiguation list UI in the chat surface uses interactive cards: each match is a clickable card showing the investor's identity. Click selects.
- The skip-to-defaults intent recognition is a small additional prompt the slot extractor runs against each user response: "Does this message indicate the user wants to fill remaining fields with defaults? Return JSON: {use_defaults: true/false}". If true, fill and skip.

### Open Questions

The threshold for "no match found, offer to onboard" is open. Working answer: zero matches after the second clarification attempt triggers the onboarding offer.

The visual treatment of the disambiguation list (interactive cards, list with select buttons, etc.) is design discretion.

### Revision History

April 2026 (cluster 2 drafting pass): Initial chunk plan authored.

---

## Chunk 2.3: Mandate Amendments with CIO Approval and Impact Analysis

### Header

- **Chunk ID:** 2.3
- **Title:** Mandate Amendments with CIO Approval and Impact Analysis
- **Status:** Shipped (May 2026)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 2 ideation log)
  - Drafting completed: April 2026
  - Implementation started: May 2026
  - Shipped: May 2026

**Chunk-shipped retrospective notes** (full retrospective at cluster 2 close):

1. **`version_number` must be `MAX(version_number) + 1`, not `active.version_number + 1`.**
   Caught by E2E during reject → propose-again: rejected versions retain
   their slot in the unique `(mandate_id, version_number)` constraint, so
   "active + 1" trips on the next propose. Fix: `SELECT MAX(version_number) + 1`
   across all rows. Regression test pinned in
   ``test_propose_after_reject_uses_next_version_number``.

2. **Atomic approve = three writes in one transaction.** Per FR 12.2 §5.1:
   proposed.status → active, mandate.active_version_id → proposed,
   previously_active.status → archived. All three live in one
   ``async with db.begin():`` boundary; three T1 events fire
   (`mandate_amendment_approved` + `mandate_version_activated` +
   `mandate_version_archived`). Never observable in 0-active or 2-active
   state.

3. **`request_changes` keeps the same version_number.** Per FR 12.2 §5.3:
   "the version_number does not change; the same draft is updated."
   Implementation: status → draft, set `changes_requested_*`, NULL out
   `proposed_at` / `proposed_by` so resubmit re-stamps cleanly.

4. **Pending-queue scope mirrors read permissions.** Advisor sees their own
   pending amendments; CIO/compliance/audit see firm-wide. The CIO is the
   sole role that can resolve rows.

5. **Strict one-at-a-time enforced at application layer.** Cluster 2 ships
   `_find_pending_or_draft` checking for any draft OR pending row before
   allowing a new propose; SQLite supports partial unique indexes from 3.8
   but the application check is portable. Error response carries the
   existing version_id so the advisor can pivot to editing it.

6. **Diff is a pure function over Pydantic read shapes.** `compute_diff`,
   `summarise_diff`, `build_impact_analysis` all take `MandateVersionRead`
   instances — unit-testable without a DB session, reusable for future
   audit replay surfaces.

7. **Cluster 4 placeholder panel is the contract.** The portfolio
   implications response carries `status="cluster_4_placeholder"` in
   cluster 2 with a fixed message. Cluster 4: flip `status="populated"`
   and fill `rows`. No code changes to chunk 2.3's surface — frontend
   already conditionally renders both.

8. **TanStack Router relative paths (third time).** CIO sidebar uses
   absolute `/cio/pending-amendments` (sidebar parent context = role
   tree); PendingAmendmentsPage row link uses relative
   `/pending-amendments/$versionId` (rendered inside cio tree). Same
   lesson as chunks 1.2 + 1.3 + 2.1.

### Purpose

Chunk 2.3 ships the amendment workflow: advisor proposes a change to an existing mandate, the proposal becomes a draft MandateVersion, the advisor submits for approval, the CIO reviews with side-by-side diff and impact analysis, and approves/rejects/requests-changes. The cluster's most complex chunk because it implements the full amendment lifecycle plus the impact analysis with the cluster 4-reserved portfolio implications panel.

### Dependencies

**Foundation reference:**
- FR Entry 12.0, 12.1, 12.2 (M1 service, constraint specification, amendment workflow)
- FR Entry 11.1 (I0 active layer; for I0-mandate divergence detection)

**Other chunks:**
- Chunk 2.1 (provides Mandate and MandateVersion infrastructure plus the form layout reused for amendment editing)

### Scope: In

- Amendment proposal service in M1: creates a draft MandateVersion with constraint values copied from the active version; validates pre-conditions (active mandate exists, no pending amendment exists).
- Amendment editor UI at `/app/advisor/investors/{investor_id}/mandate/amend`: reuses the form layout from chunk 2.1 with current active values pre-populated. Shows what's changed visually as the advisor edits.
- Submission service: transitions draft to pending_approval with proposed_at, proposed_by populated.
- API endpoints:
  - `POST /api/v2/investors/{investor_id}/mandate/amend` (creates draft)
  - `PUT /api/v2/mandate-versions/{version_id}` (updates draft fields)
  - `POST /api/v2/mandate-versions/{version_id}/submit` (transitions to pending_approval)
  - `GET /api/v2/cio/pending-amendments` (CIO queue)
  - `GET /api/v2/mandate-versions/{version_id}/diff` (returns diff against active version)
  - `POST /api/v2/mandate-versions/{version_id}/approve` (CIO approves)
  - `POST /api/v2/mandate-versions/{version_id}/reject` (CIO rejects)
  - `POST /api/v2/mandate-versions/{version_id}/request-changes` (CIO requests changes)
- CIO pending amendments queue UI at `/app/cio/pending-amendments`: lists pending amendments with summary; row click opens review surface.
- Amendment review surface at `/app/cio/pending-amendments/{version_id}`:
  - Side-by-side diff view (current active on left, proposed on right) with change highlighting per FR Entry 12.2 §4.2.
  - Plain-language change summary at top.
  - Impact analysis section with three subsections: structural diff (always populated), portfolio implications panel (cluster 4 placeholder), activation summary.
  - Three-action buttons (Approve, Request Changes, Reject) with appropriate comment field requirements.
- Approval transaction: atomic update of new version to active, old version to archived, Mandate's active_version_id update.
- I0-mandate divergence detection: when an investor's I0-relevant fields change (which doesn't happen in cluster 2 since investor edit is deferred, but the mechanism is in place for future), M1 detects divergence between new I0 values and active mandate values, emits `mandate_io_divergence_detected` event.
- I0-mandate divergence badge on investor profile when divergence exists.
- Notifications via SSE: when an amendment proposed by an advisor is approved/rejected/changes-requested, the advisor's UI updates without refresh if they're on the investor profile.
- Concurrent amendment conflict prevention: unique partial index on `(mandate_id, status='pending_approval')` or application-layer validation. Second attempt to start amendment returns clear error.
- T1 telemetry events: `mandate_amendment_proposed`, `mandate_amendment_approved`, `mandate_amendment_rejected`, `mandate_amendment_changes_requested`, `mandate_version_archived`, `mandate_io_divergence_detected`.

### Scope: Out

- Multi-approver workflow (CIO + compliance both required to approve). Deferred per cluster 2 ideation §7.2.
- Threaded comments on amendments. Deferred per cluster 2 ideation §7.4.
- Future-dated amendment activation. Deferred per cluster 2 ideation §7.5.
- Bulk amendment (apply same change to all investors in household). Deferred per cluster 2 ideation §7.6.
- The portfolio implications panel populated with real holdings analysis. Cluster 4 onwards lights this up; cluster 2 ships only the placeholder UI.

### Acceptance Criteria

1. The advisor can click "Amend Mandate" on the investor profile and reach the amendment editor.

2. Pre-amendment validation correctly blocks if no active mandate exists (returns 404 or shows error in UI).

3. Pre-amendment validation correctly blocks if a pending amendment already exists (returns 409 with clear error).

4. Draft creation copies all constraint values from the active version into the new draft.

5. The advisor can edit the draft. Changes persist progressively (auto-save on field change or on explicit save).

6. The visual indication of what's changed is clear in the editor (e.g., changed fields highlighted with a "modified" badge).

7. Submitting the draft validates per the same rules as creation; on success, transitions status to pending_approval; T1 emits `mandate_amendment_proposed`.

8. The CIO's pending queue at `/app/cio/pending-amendments` correctly lists pending amendments ordered by proposed_at descending.

9. Each row in the queue shows correct summary (investor, advisor, change summary, timestamp).

10. The amendment review surface at `/app/cio/pending-amendments/{version_id}` displays:
    - Side-by-side diff with correct visual highlighting (changed values, added/removed list items).
    - Plain-language change summary at top.
    - Impact analysis section with three subsections.
    - Portfolio implications panel showing the cluster 4 placeholder text.
    - Three action buttons.

11. Approve action atomically transitions the new version to active and the old version to archived; updates Mandate.active_version_id; emits T1 events.

12. Reject action transitions the proposed version to rejected; previously-active version remains active; emits T1 event.

13. Request Changes action transitions the proposed version back to draft with comments; the advisor can resubmit; emits T1 event.

14. Comment field requirements are enforced: optional on Approve, required on Request Changes, required on Reject (with confirmation dialog).

15. Concurrent amendment conflict is detected and returns clear error.

16. Approval transaction atomicity is enforced: no zero-active or two-active mandate states ever observable.

17. SSE notifications: when the CIO approves/rejects/requests changes on an amendment, and the advisor is on the relevant investor profile, the UI updates without refresh.

18. The I0-mandate divergence detection logic is implemented (M1 has the function); it doesn't fire in cluster 2 because investor edit isn't shipped, but the mechanism is in place. The investor profile shows the divergence badge if the divergence flag is set (e.g., manually set in test data).

19. T1 telemetry emits all amendment-related events with correct payloads.

### Out-of-Scope Notes

- The portfolio implications panel cannot show real holdings analysis because holdings don't exist yet. Cluster 4 lights it up.
- Investor field editing (which would trigger I0 re-enrichment and exercise the divergence detection) is deferred; the mechanism is in place but the trigger isn't ready.

### Implementation Notes

- The amendment editor reuses the form layout from chunk 2.1; the difference is the values are pre-populated from the active version and a "Modified" indicator appears next to changed fields.
- The diff computation is a pure function: given two MandateVersion records, return a structured diff object listing added/removed/changed fields.
- The plain-language change summary is generated from the diff object using simple template strings.
- The impact analysis structural diff section uses the same diff object with brief explanation per change.
- The portfolio implications panel is a React component that conditionally renders: in cluster 2, it always renders the placeholder; cluster 4 onwards adds logic to render real holdings analysis when holdings exist for the investor.
- The approval transaction uses SQLAlchemy's transaction context manager to ensure atomicity. The unique partial index on pending_approval prevents two simultaneous pending amendments.
- SSE notifications use the existing SSE infrastructure from cluster 0 (FR Entry 18.0). When the CIO acts on an amendment, M1 emits an SSE event that the advisor's UI listens for.

### Open Questions

The exact visual treatment of the side-by-side diff (column layout, highlighting style, transitions) is design discretion. Working answer: clean two-column layout with Tailwind grid, changed values shown with strikethrough+new pattern, list additions/removals shown with badges.

The exact wording of CIO action confirmation dialogs (especially for Reject) is design discretion.

### Revision History

April 2026 (cluster 2 drafting pass): Initial chunk plan authored.

---

## Chunk 2.4: PDF Stub

### Header

- **Chunk ID:** 2.4
- **Title:** PDF Stub
- **Status:** Shipped (May 2026, bundled with chunk 2.1's commit)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 2 ideation log §6)
  - Drafting completed: April 2026
  - Implementation started: May 2026
  - Shipped: May 2026

**Chunk-shipped retrospective notes** (full retrospective at cluster 2 close):

1. **Bundled with chunk 2.1.** The disabled "Upload IPS PDF" button lives
   at the top of chunk 2.1's form, so the two ship in one commit. The
   chunk plan's logical separation stays intact (acceptance criteria
   independently checked) but the shipping atom is a single commit.

2. **PDF endpoint reads + discards the upload body.** The 501 endpoint
   accepts the multipart upload (so client multipart parsers don't error
   mid-stream) but discards the bytes. The ``pdf_endpoint_called`` T1
   event captures filename + size for usage analytics, useful for
   prioritising production-readiness work later.

### Purpose

Chunk 2.4 ships the architectural placeholder for PDF-based mandate creation. The endpoint exists, returns a clear "not yet implemented" response, and the UI shows a disabled button with an explanatory tooltip. This reserves the capability for production-readiness phase without building it now.

### Dependencies

**Foundation reference:**
- FR Entry 12.0 (M1; the stub endpoint lives in M1's API)
- FR Entry 12.1 (constraint families; future PDF parsing extracts these)

**Other chunks:**
- Chunk 2.1 (provides the form UI where the disabled PDF button is added)

### Scope: In

- API endpoint `POST /api/v2/mandates/from-pdf`: accepts multipart/form-data with PDF file, returns HTTP 501 Not Implemented with RFC 7807 problem detail: "PDF parsing not yet implemented. Use POST /api/v2/investors/{investor_id}/mandate with structured JSON instead."
- "Upload IPS PDF" button on the mandate creation form (chunk 2.1): visibly present at the top of the form, disabled (greyed out), with a tooltip on hover: "PDF parsing coming in production phase. Use the form below for now."
- OpenAPI spec correctly documents the endpoint with the 501 response.
- T1 telemetry: optional event `pdf_endpoint_called` when the endpoint is invoked, for usage analytics.

### Scope: Out

- Actual PDF parsing logic. Deferred to production-readiness phase.
- LLM-based PDF extraction. Deferred.
- OCR for scanned PDFs. Deferred.
- Validation of extracted values against the canonical schema. Deferred.

### Acceptance Criteria

1. The endpoint `POST /api/v2/mandates/from-pdf` exists and accepts multipart/form-data uploads.

2. The endpoint returns HTTP 501 with an RFC 7807 problem detail clearly stating that PDF parsing is not yet implemented and pointing to the alternative endpoint.

3. The "Upload IPS PDF" button is visible on the mandate creation form (chunk 2.1's form).

4. The button is visibly disabled (CSS class indicating disabled state) and not clickable.

5. Hovering on the button shows the tooltip text.

6. The OpenAPI spec correctly documents the endpoint with the 501 response and includes a description of the deferred capability.

### Out-of-Scope Notes

- The button does nothing visually beyond showing the tooltip; clicks are intercepted and produce no action.

### Implementation Notes

- The endpoint is a simple FastAPI route that accepts the multipart form data, ignores the PDF file content, and returns the 501 problem detail.
- The disabled button is a styled `<button disabled>` with shadcn/ui Tooltip component.
- The OpenAPI documentation is generated automatically by FastAPI; the route's docstring should describe the deferred behaviour.

### Open Questions

Whether to log the PDF upload attempt (so we have data on how often advisors try the disabled feature) is open. Working answer: yes, T1 telemetry event `pdf_endpoint_called` for analytics.

### Revision History

April 2026 (cluster 2 drafting pass): Initial chunk plan authored.

---

## Cluster 2 Closing Notes

When chunks 2.1, 2.2, 2.3, and 2.4 all ship, cluster 2 is complete. Investors have mandates. Advisors can create them in two ways. CIO approves amendments with rich diff and impact analysis. The PDF capability is reserved for later.

The retrospective from cluster 2 should answer:
- Did the five constraint families feel like the right scope, or were any constraints missing in demos?
- Did the I0 defaults integration feel natural, or did advisors override them frequently?
- Did the side-by-side diff and impact analysis make CIO review easy?
- Did the C0 conversational mandate flow feel as natural as the form path, or did demos prefer the form?

Cluster 3 (D0 data foundation) opens after cluster 2 ships. Cluster 3 builds the data layer infrastructure that enables holdings to flow into the system. Once cluster 3 (and cluster 4 model portfolio infrastructure) ships, the portfolio implications panel in cluster 2's amendment review surface lights up with real analysis.

---

**End of Cluster 2 Chunk Plan.**
