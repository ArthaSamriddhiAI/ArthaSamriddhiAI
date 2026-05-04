# Foundation Reference Entry 10.7: Canonical Entity Schemas

**Topic:** 10 Data Layer (D0)
**Entry:** 10.7
**Title:** Canonical Entity Schemas
**Status:** Locked partial (cluster 1 contributed Investor; cluster 2 adds Mandate and MandateVersion; other entities accumulate in subsequent clusters)
**Date:** April 2026 (revised for cluster 2)
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 11.0 (I0 Investor Context Engine; consumes the Investor schema and influences Mandate defaults)
- FR Entry 11.1 (I0 Active Layer; writes life_stage and liquidity_tier to the Investor record)
- FR Entry 12.0 (M1 Overview; consumes the Mandate and MandateVersion schemas)
- FR Entry 12.1 (Mandate Schema and Constraints; the detailed mandate specification)
- FR Entry 12.2 (Amendment Workflow; lifecycle for MandateVersion records)
- FR Entry 14.0 (C0 Conversational Orchestrator; produces Investor and Mandate records via conversational paths)
- CP Chunk 1.1, 1.2 (form and conversational onboarding chunks)
- CP Chunk 2.1, 2.2, 2.3 (form-based mandate creation, conversational mandate creation, amendment workflow)
- All future clusters that consume the Investor or Mandate entities

## Cross-references Out

- Principles §3.4 (skill.md per agent mechanism)
- Principles §4.1 (D0 as system-wide data layer)

---

## 1. Purpose

This foundation reference entry holds the canonical entity schemas for the Samriddhi AI system. Each canonical entity is a primary domain object that flows through the system and must have a stable, well-defined schema because changes to canonical entities ripple through every component that consumes them.

The entry grows incrementally as clusters introduce new entities. Cluster 1 contributed the Investor entity. Cluster 2 adds the Mandate and MandateVersion entities. Subsequent clusters will add Holding, Case, Model Portfolio, and others.

The schemas in this entry are the contract between data layer and consuming components. The data layer (D0) produces records conforming to these schemas. Consuming components (agents, governance, UI surfaces) read records conforming to these schemas. Schema changes are governed: a schema revision triggers a review of every component that reads the entity, and the foundation reference entry's revision history records the change.

## 2. The Investor Entity

The Investor entity represents an individual or jointly-held investment account holder for whom the firm provides advisory services. Each investor has a unique identifier (an internal `investor_id`) and a unique business identifier (PAN, the Permanent Account Number issued by the Indian Income Tax Department).

The Investor entity is the foundational entity for client-facing operations: cases are opened on behalf of investors, mandates are attached to investors, holdings belong to investors, recommendations target investors. Almost every other entity references the Investor.

### 2.1 Investor Schema

```
investors:
  investor_id (string, ULID, primary key, system-generated)
  
  # Identity fields (advisor-entered)
  name (string, required, 2 to 100 characters, must contain at least one space)
  email (string, required, valid email format, indexed)
  phone (string, required, E.164 international format with default +91 country code)
  pan (string, required, 10 characters matching ^[A-Z]{5}[0-9]{4}[A-Z]$, unique within deployment, indexed)
  age (integer, required, range 18 to 100)
  
  # Grouping and assignment (advisor-entered or system-determined)
  household_id (string, ULID, indexed; references households table)
  advisor_id (string, references users; defaults to logged-in advisor at creation)
  
  # Investment profile (advisor-entered)
  risk_appetite (enum, required: aggressive, moderate, conservative)
  time_horizon (enum, required: under_3_years, 3_to_5_years, over_5_years)
  
  # KYC (placeholder for cluster 1; integration deferred)
  kyc_status (enum: pending, verified, failed; defaults to pending in demo stage)
  kyc_verified_at (timestamp, nullable)
  kyc_provider (string, nullable; populated when KYC integration is implemented)
  
  # I0 enrichment (system-computed; written by I0 active layer)
  life_stage (enum, nullable until enrichment runs: accumulation, transition, distribution, legacy)
  life_stage_confidence (enum: high, medium, low)
  liquidity_tier (enum, nullable until enrichment runs: essential, secondary, deep)
  liquidity_tier_range (string; the percentage range associated with the tier, for display)
  enriched_at (timestamp, nullable)
  enrichment_version (string; tracks which version of I0 enrichment heuristics produced the values)
  
  # Provenance and audit
  created_at (timestamp with timezone, system-generated)
  created_by (string, references users)
  created_via (enum: form, conversational, api)
  duplicate_pan_acknowledged (boolean)
  last_modified_at (timestamp)
  last_modified_by (string)
  schema_version (integer; current = 1)
```

### 2.2 Investor Schema Field Notes

**investor_id:** ULID is preferred over UUID4 because ULIDs are time-ordered, which makes database indexes more efficient and human-readable timestamps trivial. ULID is 26 characters in canonical text representation.

**name:** Single field for full name rather than separated first/last. Indian naming conventions don't fit cleanly into first/last; storing the whole name as one field avoids forcing a Western-style split.

**pan:** PAN is the strongest unique identifier available in India. Cluster 1 ideation locked warn-and-proceed for duplicate handling. Future production-readiness work may harden this to strict prevention.

**household_id:** References the `households` table. Family relationships within a household are deferred to a later cluster.

**risk_appetite, time_horizon:** The simplified attitudinal profile fields. These drive I0 enrichment and Mandate constraint defaults. Changes to either trigger I0 re-enrichment per FR Entry 11.1; cluster 2 introduces the cascade where re-enrichment changes propagate to suggest mandate amendments per FR Entry 12.2.

**life_stage, liquidity_tier:** I0 enrichment outputs. Initially nullable because enrichment runs after the investor record is created. Cluster 2's mandate creation reads liquidity_tier as the default for the mandate's liquidity floor.

**created_via:** Distinguishes form-onboarded, conversational-onboarded, and API-onboarded investors.

### 2.3 Investor Indexes

- Primary key on `investor_id`.
- Unique index on `pan` (with duplicate_pan_acknowledged carve-out).
- Index on `email` for email lookup.
- Index on `household_id` for household-level queries.
- Index on `advisor_id` for advisor's-book queries.
- Composite index on `(advisor_id, created_at)` for advisor's-recently-created-investors queries.

### 2.4 Investor Validation Rules

| Field | Validation Rule |
|---|---|
| name | Required; 2 to 100 chars; must contain at least one space |
| email | Required; valid email format per RFC 5322 |
| phone | Required; E.164 format; default to +91 country code |
| pan | Required; matches `^[A-Z]{5}[0-9]{4}[A-Z]$`; auto-uppercased |
| age | Required; integer 18 to 100 |
| household_id | Required |
| advisor_id | Required (defaults to logged-in advisor) |
| risk_appetite | Required; enum |
| time_horizon | Required; enum |

Server-side validation produces an RFC 7807 problem detail per Doc 2 Pass 1 Decision 6 when validation fails.

## 3. The Mandate and MandateVersion Entities

The Mandate entity represents the investment policy mandate attached to an investor. Each investor has exactly one Mandate (one-to-one relationship); the Mandate's identity persists for the investor's lifetime in the system. The Mandate's content (the actual constraints) lives in MandateVersion records, which are versioned over time as amendments are made.

This separation of identity from content is the canonical versioning pattern: the Mandate identifier never changes, but the active version of constraints changes when amendments are approved.

### 3.1 Mandate Schema

```
mandates:
  mandate_id (string, ULID, primary key)
  investor_id (string, references investors, indexed, unique within mandates)
  active_version_id (string, references mandate_versions; current active version)
  created_at (timestamp with timezone)
  created_by (string, references users)
  schema_version (integer; current = 1)
```

The unique constraint on investor_id ensures one Mandate per investor.

### 3.2 MandateVersion Schema

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
  prohibited_instruments (JSON array of strings; max 50 items, each 1-200 characters)
  
  # Provenance
  created_at (timestamp with timezone)
  created_by (string, references users)
  created_via (enum: form, conversational, api, pdf)
  parent_version_id (string, references mandate_versions; nullable for the initial version)
  
  # Approval workflow
  proposed_at (timestamp; nullable)
  proposed_by (string; nullable)
  approved_at (timestamp; nullable)
  approved_by (string, references users; nullable)
  rejected_at (timestamp; nullable)
  rejected_by (string, references users; nullable)
  rejection_reason (string; nullable; required when rejected)
  approval_comments (string; nullable; optional)
  changes_requested_at (timestamp; nullable)
  changes_requested_by (string, references users; nullable)
  changes_requested_comments (string; nullable; required when changes are requested)
  
  # Activation
  activated_at (timestamp; when status moved to active)
  archived_at (timestamp; when status moved from active to archived; nullable)
```

### 3.3 MandateVersion Status Lifecycle

The status enum captures the full amendment lifecycle:

- **draft:** Initial state for an amendment-in-progress. Advisor is editing. Not visible in CIO's queue.
- **pending_approval:** Advisor has submitted for CIO review. Visible in CIO's pending amendments queue.
- **active:** Currently in force. Exactly one active MandateVersion per Mandate at any time.
- **archived:** Was previously active; a newer version has superseded it. Retained for audit.
- **rejected:** CIO rejected the amendment. Not in force; preserved for audit.

The initial MandateVersion (version_number = 1) created during mandate creation goes directly from creation to `active` status without passing through draft or pending_approval. This implements the "first mandate auto-active without CIO approval" decision.

Subsequent MandateVersions follow the full lifecycle: draft, then pending_approval, then either active (with simultaneous archival of the previous active) or rejected (returning to the previous active version unchanged) or back to draft (when CIO requests changes).

### 3.4 Mandate Field Notes

**mandate_id:** ULID, system-generated. Unique per mandate, persistent across versions.

**version_number:** Human-readable version sequence (1, 2, 3, ...). Auto-increments per mandate. Useful for display and audit ("This is version 4 of the mandate").

**parent_version_id:** Tracks the version that this amendment was based on. Initial versions have null parent_version_id. Amendments have parent_version_id pointing to the version that was active when the amendment was proposed.

**created_via:** Distinguishes form-created, conversational-created, API-created, and PDF-created mandates. PDF stub is implemented in chunk 2.4 as a 501 endpoint; this field exists to support future PDF parsing.

**Status timestamps:** The proposed_at, approved_at, rejected_at, changes_requested_at fields capture the full audit trail of an amendment's journey. T1 telemetry mirrors these state transitions.

### 3.5 Mandate Indexes

For mandates:
- Primary key on `mandate_id`.
- Unique index on `investor_id`.
- Index on `active_version_id`.

For mandate_versions:
- Primary key on `version_id`.
- Index on `mandate_id`.
- Composite index on `(mandate_id, version_number)`.
- Composite index on `(status, proposed_at)` for the CIO's pending amendments queue.
- Index on `parent_version_id` for amendment lineage queries.

### 3.6 Mandate Validation Rules

| Field | Validation Rule |
|---|---|
| equity_min_pct, equity_max_pct, debt_min_pct, debt_max_pct, alternatives_min_pct, alternatives_max_pct | Each integer 0-100; max >= min for each pair |
| Cross-constraint: sum of mins | sum(equity_min, debt_min, alternatives_min) <= 100 |
| Cross-constraint: sum of maxes | sum(equity_max, debt_max, alternatives_max) >= 100 |
| single_position_max_pct | Integer 0-100; soft warning if outside 3-10 range |
| liquidity_floor_pct | Integer 0-100; soft warning if significantly different from I0 suggested default |
| sector_max_pct | Integer 0-100; soft warning if outside 15-40 range |
| prohibited_instruments | Array of strings; each 1-200 characters; max 50 items |

Server-side validation produces an RFC 7807 problem detail on hard validation failure. Soft warnings are returned in a separate `warnings` array within the response so the advisor can see them without being blocked.

## 4. Other Canonical Entities (Placeholders)

The following canonical entities will be defined in subsequent clusters:

**Holding:** an investor's position in a specific instrument. Cluster 4 (model portfolio) or cluster 5 (first agent) introduces this.

**Case:** the central object representing an investment recommendation flow. Cluster 5 introduces this.

**Model Portfolio (and L1/L2/L3/L4 entities):** the firm's investment templates and approved instrument universe. Cluster 4 introduces this.

**Macro Signal, Industry Signal, Circular, Fund Offer Document, T1 Event, N0 Alert:** various data and event entities. Subsequent clusters introduce them per their relevance.

## 5. Schema Versioning

Each canonical entity has a `schema_version` integer. The current cluster 2 schemas are:

- Investor: schema_version = 1.
- Mandate: schema_version = 1.
- MandateVersion: schema_version = 1.

Schema changes follow the disciplined revision process: revision history recorded, schema_version incremented, Alembic migration authored, components reviewed for impact, T1 telemetry captures schema versions for audit replay.

## 6. Storage and Persistence

Investor and Mandate records are persisted in their respective tables in the deployment's database (SQLite for demo stage, Postgres for production). The SQLAlchemy declarative models for Investor, Mandate, and MandateVersion mirror the schemas in §2.1, §3.1, §3.2.

## 7. Read Patterns

The Investor entity is read by the advisor's investor list, I0, C0 onboarding, M1 (cluster 2 onwards), case orchestration (cluster 5 onwards), portfolio analytics (cluster 10 onwards), audit replay (cluster 15 onwards).

The Mandate and MandateVersion entities are read by:

- The investor profile page (active mandate display).
- The CIO's pending amendments queue (mandate_versions where status = 'pending_approval').
- The amendment review surface (current active version vs proposed version, side-by-side).
- C0 conversational mandate creation (when checking if an investor already has a mandate).
- The governance gate (cluster 8) for mandate compliance checking.
- The portfolio analytics (cluster 10) for drift monitoring against mandate-defined bands.
- Audit replay (cluster 15) for historical mandate version reconstruction.

## 8. Write Patterns

Writes to the Investor entity happen at form-based onboarding, conversational onboarding, API onboarding, and future profile edits.

Writes to the Mandate entity happen only at initial mandate creation.

Writes to MandateVersion happen at:

- Initial mandate creation: version_number=1, status=active.
- Amendment proposal: new version_number, status=draft, parent_version_id pointing to current active.
- Amendment submission: status moves draft to pending_approval.
- Amendment approval: status moves pending_approval to active; previously-active version moves active to archived.
- Amendment rejection: status moves pending_approval to rejected.
- Amendment changes-requested: status moves pending_approval back to draft.

## 9. Acceptance Criteria

The schema is considered locked when:

1. SQLAlchemy declarative models are implemented for Investor, Mandate, MandateVersion.
2. Alembic migrations create the tables with all required indexes.
3. Validation rules are enforced at the server-side validation layer.
4. The unique constraint on `investors.pan` is enforced.
5. The unique constraint on `mandates.investor_id` is enforced.
6. Cross-constraint validation on mandate_versions is enforced.
7. Records can be created through form, C0 conversational, and stub API/PDF paths.
8. The schema_version field is set correctly on all created records.
9. T1 telemetry captures `investor_created`, `mandate_created`, `mandate_version_created`, `mandate_amendment_proposed`, `mandate_amendment_approved`, `mandate_amendment_rejected`, `mandate_amendment_changes_requested`, `mandate_version_archived`.

## 10. Open Questions

The schema_version increment policy when only enrichment-related fields change is open. Working answer per cluster 1: enrichment-only changes don't bump schema_version; the `enrichment_version` field tracks enrichment lineage separately.

Whether MandateVersion should also include a `notes` field for advisor commentary on the amendment's rationale is open. Working answer: not in cluster 2; the comment fields on approval/rejection cover audit needs.

Whether the prohibited_instruments field should be normalised into a separate table for query-ability is open. Working answer: keep as JSON in cluster 2; refactor to normalised table if cluster 8 (governance gate) requires it.

## 11. Revision History

April 2026 (cluster 1 drafting pass): Initial entry authored. Investor entity schema locked at version 1. Other canonical entity placeholders reserved.

April 2026 (cluster 2 drafting pass): Mandate and MandateVersion entities added at schema_version 1. Cross-references updated. Section 3 added covering both new entities. Section 4 placeholders updated to reflect Mandate moving from placeholder to specified.

---

**End of FR Entry 10.7. Investor and Mandate entities locked; other entities accumulate in subsequent clusters.**
