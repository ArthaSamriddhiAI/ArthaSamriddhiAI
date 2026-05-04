# Samriddhi AI: Cluster 2 Demo-Stage Addendum

## Mandate Management Carve-Outs for Internal Demo Stage

**Document:** Samriddhi AI, Cluster 2 Demo-Stage Addendum
**Cluster:** 2 (Mandate Management)
**Status:** Active for internal demo stage; superseded when production-readiness phase begins
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This addendum modifies cluster 2 implementation for the internal demo stage. The production-grade mandate management capability would include PDF parsing, multi-approver workflows, advanced constraint families, threaded comments, future-dated activation, bulk operations, and mandate templates. Cluster 2's foundation reference entries describe the production architecture; this addendum specifies what is intentionally not implemented yet for demo stage.

The addendum follows the same pattern as the cluster 0 dev-mode addendum and the cluster 1 demo-stage addendum: production specs preserved, demo-stage carve-outs explicit, focused migration when production matters.

---

## 1. What This Addendum Changes

### 1.1 PDF Parsing Stubbed

Per chunk 2.4, the PDF endpoint exists but returns 501. The UI button is visibly disabled. Future production-readiness phase implements actual PDF parsing (LLM-based extraction with validation logic).

### 1.2 Multi-Approver Workflow Deferred

Some firms may want amendment approval to require multiple approvers (CIO plus compliance). Cluster 2 implements single-CIO approval. Multi-approver flows are deferred to production-readiness or to a dedicated cluster if firms request it.

### 1.3 Advanced Constraint Types Deferred

Beyond the five constraint families (asset allocation bands, single-position concentration, liquidity floor, sector cap, prohibited instruments), production IPS documents may include:

- ESG screens (environmental, social, governance criteria; e.g., "minimum ESG score of 7", "exclude companies with poor governance ratings").
- Derivatives policies (allowed/prohibited derivatives, hedging permissions, leverage caps via derivatives).
- Leverage limits (maximum leverage at portfolio level, per-instrument leverage caps).
- Geographic restrictions (e.g., "no holdings in jurisdictions on the FATF blacklist").
- Currency exposure rules (maximum non-INR exposure, hedging requirements for foreign currency holdings).
- Jurisdictional categories (specific NRI/OCI/FPI rules).
- Maturity-based debt allocation (e.g., laddering requirements, duration buckets).
- Tax-efficiency constraints (e.g., tax-loss harvesting policies).

All of these are deferred to future clusters or production-readiness. The mandate schema can be extended additively; new constraint families add columns to MandateVersion without breaking existing data.

### 1.4 Threaded Comments Deferred

Production amendment workflows often include comment threads where advisor and CIO discuss the amendment back-and-forth. Cluster 2 implements simple comment fields on approve/reject/request-changes actions; threaded discussion (multiple back-and-forth comments captured in sequence) is deferred.

### 1.5 Future-Dated Effective Activation Deferred

Some mandates may need to take effect on a future date (e.g., starting next quarter, or after a specific event like a planned wealth event). Cluster 2 mandates take effect immediately on activation. Future-dated activation is deferred.

### 1.6 Bulk Mandate Operations Deferred

Cluster 2 handles one mandate at a time. Bulk operations (e.g., apply the same amendment to all investors in a household, batch-create mandates for multiple newly-onboarded investors) are deferred.

### 1.7 Mandate Templates Deferred

Some firms might want CIO-approved mandate templates that advisors can select from rather than starting from scratch. Cluster 2 has no template system; advisors create each mandate from scratch (with I0 defaults). Templates are deferred.

### 1.8 Portfolio Implications Panel Stubbed

Per chunk 2.3 and FR Entry 12.2 §4.3, the portfolio implications panel in the amendment review surface shows a placeholder in cluster 2: "Portfolio analysis will be available when holdings data is loaded for this investor (cluster 4 onwards)."

When cluster 4 ships, the panel auto-populates with real holdings analysis. No code changes to cluster 2's implementation are required; the panel renders based on availability of holdings data.

### 1.9 I0-Mandate Divergence Notification Mechanism Implemented But Unexercised

The mechanism for detecting I0-mandate divergence (per FR Entry 12.0 §4.3) is implemented in cluster 2. However, it is unexercised because investor field editing (which would trigger I0 re-enrichment) is deferred per cluster 1 demo-stage addendum.

In cluster 2, the divergence detection function exists in M1, the SSE event for `mandate_io_divergence_detected` is registered, the badge UI is implemented in the investor profile. They activate when investor edit ships in a future cluster.

### 1.10 No Mandate Cloning or Copy-Investor

Cluster 2 has no facility to copy a mandate from one investor to another (e.g., setting up similar mandates for spouses in the same household). Each mandate is created from scratch. Mandate cloning could be added as a small feature in a future cluster.

---

## 2. What This Addendum Does Not Change

### 2.1 Mandate Schema Locked at v1

The Mandate and MandateVersion schemas in FR Entry 10.7 §3 are fully locked. The five constraint families exist; validation rules are enforced; the lifecycle is complete.

### 2.2 Five Constraint Families Fully Implemented

All five constraint families (asset allocation bands, single-position concentration, liquidity floor, sector cap, prohibited instruments) are fully implemented per FR Entry 12.1. Validation, I0 defaults, soft warnings all work.

### 2.3 Amendment Workflow Fully Functional

The amendment workflow per FR Entry 12.2 is fully functional: advisor proposes, CIO reviews with side-by-side diff and impact analysis, CIO approves/rejects/requests changes, state transitions are atomic, T1 captures all events.

### 2.4 C0 Mandate Creation Intent Fully Implemented

The mandate_creation intent in C0 is fully implemented per the FR Entry 14.0 cluster 2 revision: structured investor disambiguation, eight-state state machine, skip-to-defaults affordance, error handling.

### 2.5 SSE Notifications Fully Functional

When the CIO acts on an amendment, SSE events propagate to the advisor's UI in real-time. This is fully functional per chunk 2.3.

### 2.6 I0 Integration Fully Functional

I0 defaults are read for mandate creation; soft warnings on divergence are surfaced; the divergence detection mechanism is in place even though the trigger (investor edit) isn't shipped yet.

---

## 3. Demo-Stage Operational Notes

### 3.1 Test Mandate Population

For demos, after cluster 1's seed script populates test investors, a complementary seed script `dev/seed_mandates.py` creates active mandates for each test investor. The mandates use I0-suggested defaults so the visible mandate values match what the form would auto-populate.

This ensures the demo investor list shows mandates in place for each investor, demonstrating the connection between investor enrichment and mandate constraints.

### 3.2 Test Amendment for Demo

The seed script can optionally create a draft amendment for at least one investor, so the CIO's pending amendments queue is non-empty during demos. The amendment shows realistic changes (e.g., increasing equity max from 70 to 75, adding a new prohibited instrument) so the diff view has visible content.

### 3.3 LLM Cost for C0 Mandate Creation

C0 mandate creation calls LLM via the SmartLLMRouter, similar to cluster 1 investor onboarding. Demo stage uses Mistral free tier by default; flipping to Claude for polish-quality demos remains an option.

A typical C0 mandate creation conversation makes 7-12 LLM calls (intent detection plus slot extraction across the constraint families). Free-tier rate limits should not be a constraint for typical demo usage.

### 3.4 Database State Management

Mandate state is part of the persistent database state. The same database reset procedures from cluster 1 demo-stage addendum apply: deleting the SQLite file and rerunning Alembic plus seed scripts produces a fresh demo state.

For partial resets (e.g., remove a specific draft amendment without losing the test mandate population), ad-hoc database manipulation is acceptable for demo stage.

---

## 4. Migration Path to Production

When cluster 2 features need production-readiness, the migration consists of several focused work items:

### 4.1 PDF Parsing

A dedicated cluster (sequenced before the first pilot deployment that requires PDF support) implements:

1. Backend: replace the 501 stub with actual PDF parsing logic (LLM-based extraction using Claude or another capable model, or integration with a document parsing service).
2. UI: enable the "Upload IPS PDF" button.
3. Workflow: PDF upload triggers extraction, populates the form with extracted values for advisor review, advisor confirms or adjusts, submits.
4. The mandate created via PDF path has `created_via=pdf`.

This is significant implementation work, typically 1-2 weeks depending on PDF parsing approach.

### 4.2 Multi-Approver Workflow

Add fields to MandateVersion for multi-approver state (e.g., `compliance_approved_at`, `compliance_approved_by`). Update the approval lifecycle to track multiple approvers. UI for routing to multiple approvers in sequence or parallel.

### 4.3 Advanced Constraint Families

Add columns to MandateVersion for each new constraint family. Update the form, the C0 state machine, the validation, the diff view, the impact analysis. Each family is its own focused implementation work.

### 4.4 Threaded Comments

Add `mandate_comments` table with conversation_id, version_id, sender, content, timestamp. Update the amendment review surface to show comment threads. Update the advisor's amendment view to support reading and adding comments.

### 4.5 Future-Dated Activation

Add `effective_at` field to MandateVersion. Update the activation logic to defer status transition until the effective date. Add background job to activate scheduled amendments.

### 4.6 Bulk Operations

Add bulk endpoint to apply the same amendment to multiple mandates. Add UI for bulk selection and applying. Validation needs to handle per-investor variations.

### 4.7 Mandate Templates

Add `mandate_templates` table for CIO-defined templates. Update the form to allow selecting a template as starting point. Add CIO surface for creating and managing templates.

These migration items are independent; they can be implemented in any order based on firm priorities.

---

## 5. Acceptance Criteria for This Addendum

The addendum is considered correctly applied when:

1. PDF endpoint returns 501 with correct problem detail; PDF button is disabled in UI.
2. Single-CIO approval is the only approval flow.
3. Only the five locked constraint families are captured; no advanced constraint families exist in the schema or UI.
4. Comment fields are simple strings (one per action); no comment threading.
5. All approvals take immediate effect; no future-dated activation.
6. Bulk operations are not available; single-mandate workflows only.
7. No mandate templates exist.
8. Portfolio implications panel shows the cluster 4 placeholder.
9. The I0-mandate divergence mechanism is implemented but not exercised (because investor edit isn't shipped).
10. No mandate cloning is available.
11. The original cluster 2 acceptance criteria (in the chunk plan) all pass for the demo-stage scope.

---

## 6. Revision History

April 2026 (cluster 2 drafting pass): Initial addendum authored. Active for internal demo stage. Will be superseded as production-readiness clusters implement PDF parsing, multi-approver workflows, advanced constraints, and other deferred capabilities.

---

**End of Cluster 2 Demo-Stage Addendum.**
