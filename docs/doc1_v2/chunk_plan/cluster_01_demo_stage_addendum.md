# Samriddhi AI: Cluster 1 Demo-Stage Addendum

## Investor Onboarding Carve-Outs for Internal Demo Stage

**Document:** Samriddhi AI, Cluster 1 Demo-Stage Addendum
**Cluster:** 1 (Investor Onboarding)
**Status:** Active for internal demo stage; superseded when production-readiness phase begins
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This addendum modifies cluster 1 implementation for the internal demo stage. The production-grade investor onboarding capability would include KYC integration, family relationship modelling, detailed wealth profiles, and full UI for the API path. Cluster 1's foundation reference entries describe the production architecture; this addendum specifies what is intentionally not implemented yet for demo stage.

The addendum follows the same pattern as the cluster 0 dev-mode addendum: production specs preserved, demo-stage carve-outs explicit, focused migration cluster when production matters.

---

## 1. What This Addendum Changes

### 1.1 KYC Integration Deferred

Production investor onboarding would include KYC (Know Your Customer) verification: document upload (PAN card, address proof, bank details), integration with a KYC service provider (CKYC, KRA, or in-house verification), KYC status workflow with provider responses, blocking effects on investments until KYC is verified.

For demo stage, none of this is implemented. The Investor schema (FR Entry 10.7) reserves the `kyc_status`, `kyc_verified_at`, `kyc_provider` fields; in demo stage, `kyc_status` is always set to `pending` on creation and never updated. No documents are uploaded. No external KYC provider is called.

When production-readiness phase begins, a dedicated cluster implements KYC: document upload UI, KYC provider integration, status webhook handling, blocking effects on subsequent operations (mandate creation, case execution, etc.) until KYC is verified.

### 1.2 Family Relationship Modelling Deferred

Production investor onboarding would capture family relationships within a household: spouse, parent, child, dependent. These relationships matter for advisory work (joint accounts, family-level mandate aggregation, inter-generational wealth transfer planning).

For demo stage, the household_id grouping is implemented but relationships within the household are not. Each investor has a household_id; the relationships between investors in the same household are not modelled.

A future cluster (likely after cluster 5 when cases are running and family-level analysis becomes relevant) adds relationship modelling.

### 1.3 Detailed Wealth Profile Deferred

Production investor onboarding would capture a detailed wealth profile: estimated net worth, asset breakdown (real estate, equities, debt instruments, alternatives, business interests), liability profile, income sources, spending patterns, succession context. This is substantial profile work, often requiring multiple meetings with the client.

For demo stage, only `risk_appetite` and `time_horizon` are captured as the attitudinal investment profile fields. Detailed wealth and liability fields are deferred. Cluster 2 (mandate management) or a dedicated wealth-profile cluster handles them.

### 1.4 API Path Has No Dedicated UI

The API onboarding path (`POST /api/v2/investors`) is functional but has no UI. External integrations or scripted bulk-import would call this endpoint directly. Cluster 1 does not provide:

- Bulk CSV import UI
- External API consumer registration or API key management
- Webhook notifications to external systems on investor creation

The endpoint is documented in the OpenAPI spec produced by FastAPI. Future clusters or production-readiness work expose UI surfaces for bulk operations if needed.

### 1.5 Investor Edit Functionality Limited

Cluster 1 ships read-only investor profile detail. Editing an investor's fields after creation is deferred. Specifically:

- The advisor cannot edit the investor's name, email, phone, PAN, age, household, advisor assignment, risk_appetite, or time_horizon through any UI in cluster 1.
- Re-enrichment is triggered only when the underlying fields change, but in cluster 1 those fields don't change because edit is not possible.

A later cluster ships the edit surface. For demo stage, if a field is wrong, the advisor creates a new investor with corrected fields (the original record stays in the database).

The exception: investors created during a demo can be deleted via direct database manipulation if the demo state needs reset. Cluster 1 does not implement an in-app delete function (prevents accidental deletion); for demo stage, ad-hoc database resets are acceptable.

### 1.6 No Email Notifications

Production onboarding might send email notifications: to the investor confirming account creation, to the firm's CIO when high-net-worth investors are added, etc. Cluster 1 does not implement any email infrastructure. T1 telemetry captures investor creation events; future clusters can wire those events to email if needed.

### 1.7 No Mobile-Specific Surfaces

Per Doc 3 Pass 1 Decision 5 (desktop-first, below 1280px shows fallback), the form path and C0 chat path render on desktop. Mobile-responsive layouts are deferred. Demo-stage assumption: demos run on desktop or large tablet; mobile demos are not in scope.

---

## 2. What This Addendum Does Not Change

### 2.1 Investor Schema Locked at v1

The Investor schema in FR Entry 10.7 §2.1 is fully locked. The fields that exist in the schema are present and correct. Fields that are not yet exercised (KYC fields, the placeholder for future relationships) exist as schema-reserved fields ready for future use.

The schema is forward-compatible: when KYC is implemented later, the schema evolves with new fields added; existing demo-stage records have null KYC fields and are migrated forward without data loss.

### 2.2 I0 Active Layer Fully Implemented

The I0 active layer in FR Entry 11.1 is fully implemented for cluster 1. Life stage and liquidity tier inference work as specified. The dormant layer and pattern library are deferred per FR Entry 11.0 §2.2 and §2.3, but those are deferred at the architectural level, not just for demo stage.

### 2.3 C0 Onboarding Intent Fully Implemented

C0's investor_onboarding intent in FR Entry 14.0 is fully implemented for cluster 1. The bounded LLM scope (Option 3) works end-to-end: intent detection, slot extraction, state machine, action execution, persistence. Other intents (case_opening, alert_response, etc.) return placeholder responses.

### 2.4 SmartLLMRouter Fully Implemented

The SmartLLMRouter in FR Entry 16.0 is fully implemented for cluster 1. Provider selection, configuration storage with encryption, test connection, retries, rate limiting, kill switch, telemetry all work. Per-agent tiering and multi-provider failover are deferred per the entry's §8, but again that's architectural deferral, not demo-stage carve-out.

### 2.5 Form Validation Fully Implemented

All field validation rules in FR Entry 10.7 §2.4 are enforced both client-side and server-side. Validation does not relax for demo stage; producing invalid investor records is not acceptable even in demo.

---

## 3. Demo-Stage Operational Notes

### 3.1 Test Investor Population

For demos, a small population of test investors should be created in advance to populate the investor list and demonstrate the system's capability with realistic data. Recommended test population:

- 3-5 investors per advisor across the four roles
- Mix of life stages (1-2 in each life stage)
- Mix of risk appetites and time horizons
- Plausible names (use Indian names common in HNI demographics)
- PAN values that match the format but are obviously test (e.g., DEMO12345A through DEMO12345E to make them visually identifiable as test)

The test population is created via the API path (chunk 1.1) using a seeding script. The script is in `dev/seed_investors.py` and is run after Alembic migrations complete.

### 3.2 LLM Cost Management

Demo stage uses Mistral free tier by default; no cost incurred. If a demo session warrants Claude (higher-quality conversational experience), the CIO can flip the toggle for the demo.

A few demo runs through C0 cost cents to single dollars on Claude pricing; not a meaningful cost concern but worth noting that LLM calls in demos do consume API budget.

### 3.3 Database State Reset Between Demos

If demos require a fresh state (e.g., showing the "first investor onboarding" experience), the SQLite database can be deleted and Alembic re-run; the seed script can re-populate test investors selectively.

The reset is destructive (all data lost). Demo scripts that need partial resets (e.g., remove the last-onboarded investor without losing the test population) can be added to `dev/` if needed.

### 3.4 LLM API Key Storage in Demos

For demo deployments running on a personal laptop, the LLM API keys are stored encrypted in the local SQLite file. The encryption key is in environment variables; if the laptop is compromised, the keys are recoverable only by also obtaining the encryption key.

For production deployments, key management is more sophisticated (KMS, secrets manager); that is Doc 4 Operations.

---

## 4. Migration Path to Production

When cluster 1 features need production-readiness, the migration consists of:

### 4.1 KYC Integration

A dedicated cluster (likely sequenced before the first pilot deployment) implements KYC:

1. Document upload UI added to the investor profile.
2. KYC provider integration (selected per the firm's regulatory context).
3. KYC status workflow: pending → in_progress → verified | failed.
4. Webhook handling for KYC provider responses.
5. Blocking effects on downstream operations until kyc_status = verified.

This is significant implementation work, several days minimum.

### 4.2 Family Relationships

A cluster adds the relationships table and UI:

1. `relationships` table with from_investor_id, to_investor_id, relationship_type, established_at.
2. UI in the investor profile to add/edit relationships.
3. Family-level views (e.g., household summary showing all family members).

Smaller scope than KYC; days of work.

### 4.3 Detailed Wealth Profile

This may be combined with cluster 2 (mandate management) since wealth context is needed for IPS construction, or a separate cluster:

1. Wealth profile schema (additional Investor fields or a related `wealth_profiles` table).
2. UI for capturing and editing wealth details.
3. Integration with mandate constraints (wealth bands trigger different mandate rules).

Substantial work; comparable to KYC in scope.

### 4.4 Edit Functionality

Smaller cluster:

1. UI for editing each editable field on the investor profile.
2. Validation re-applied on edit.
3. Re-enrichment triggered for enrichment-relevant field changes.
4. Audit trail for edits (who changed what when).

Days of work.

### 4.5 Mobile-Responsive Layouts

Larger UX work that touches every UI surface. Probably deferred until late in production-readiness.

---

## 5. Acceptance Criteria for This Addendum

The addendum is considered correctly applied when:

1. KYC fields exist in the Investor schema but are never populated in demo stage; `kyc_status` is always `pending`.
2. Household_id grouping works but no relationship modelling exists.
3. Only `risk_appetite` and `time_horizon` are captured for investment profile; no detailed wealth fields.
4. The API endpoint `POST /api/v2/investors` works but has no UI; OpenAPI spec documents it.
5. Investor profile detail is read-only; no edit UI exists.
6. No email infrastructure is implemented.
7. Test investor seed script exists in `dev/seed_investors.py` for demo preparation.
8. The original cluster 1 acceptance criteria (in the chunk plan) all pass for the demo-stage scope.

---

## 6. Revision History

April 2026 (cluster 1 drafting pass): Initial addendum authored. Active for internal demo stage. Will be superseded as production-readiness clusters implement KYC, relationships, wealth profile, edit, and other deferred capabilities.

---

**End of Cluster 1 Demo-Stage Addendum.**
