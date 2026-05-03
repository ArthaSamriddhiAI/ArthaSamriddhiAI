# Foundation Reference Entry 10.7: Canonical Entity Schemas

**Topic:** 10 Data Layer (D0)
**Entry:** 10.7
**Title:** Canonical Entity Schemas
**Status:** Locked partial (cluster 1 chunk 1.1 shipped May 2026 — Investor entity at v1 + Household; other entities accumulate in subsequent clusters)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 11.0 (I0 Investor Context Engine; consumes the Investor schema)
- FR Entry 11.1 (I0 Active Layer; writes life_stage and liquidity_tier to the Investor record)
- FR Entry 14.0 (C0 Conversational Orchestrator; produces Investor records via conversational onboarding)
- CP Chunk 1.1, 1.2 (the form and conversational onboarding chunks)
- All future clusters that consume the Investor entity (cluster 2 mandate management, cluster 5 case pipeline, cluster 10 portfolio analytics, etc.)

## Cross-references Out

- Principles §3.4 (skill.md per agent mechanism; not directly schema-related but contextually relevant)
- Principles §4.1 (D0 as system-wide data layer; this entry is part of D0)

---

## 1. Purpose

This foundation reference entry holds the canonical entity schemas for the Samriddhi AI system. Each canonical entity is a primary domain object that flows through the system and must have a stable, well-defined schema because changes to canonical entities ripple through every component that consumes them.

The entry grows incrementally as clusters introduce new entities. Cluster 1 contributes the Investor entity; subsequent clusters add Holding, Mandate, Case, Model Portfolio, and others as they become relevant. At system maturity, this entry contains the full canonical entity model.

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
  life_stage_confidence (enum: high, medium, low; reflects whether the heuristic produced a clean classification)
  liquidity_tier (enum, nullable until enrichment runs: essential, secondary, deep)
  liquidity_tier_range (string; the percentage range associated with the tier, for display)
  enriched_at (timestamp, nullable)
  enrichment_version (string; tracks which version of I0 enrichment heuristics produced the values)
  
  # Provenance and audit
  created_at (timestamp with timezone, system-generated)
  created_by (string, references users; the advisor or system actor who created the record)
  created_via (enum: form, conversational, api; records which onboarding path produced the investor)
  duplicate_pan_acknowledged (boolean; true if the advisor knowingly created a duplicate PAN record)
  last_modified_at (timestamp; updates on any field change)
  last_modified_by (string; user_id of the most recent modifier)
  schema_version (integer; increments when this entry's schema changes)
```

The schema is locked at this version (schema_version = 1) for cluster 1. Changes during demo stage that don't affect downstream components are allowed; changes that do affect downstream components require a foundation reference revision pass.

### 2.2 Investor Schema Field Notes

**investor_id:** ULID is preferred over UUID4 because ULIDs are time-ordered, which makes database indexes more efficient and human-readable timestamps trivial. ULID is 26 characters in canonical text representation (e.g., `01J9N6F7GZ3M8K2NQRBTYWVXA1`).

**name:** Single field for full name rather than separated first/last. Indian naming conventions (single names, multi-component names, regional naming patterns) don't fit cleanly into first/last; storing the whole name as one field avoids forcing a Western-style split.

**pan:** PAN is the strongest unique identifier available in India. Cluster 1 ideation locked warn-and-proceed for duplicate handling; the schema captures the acknowledgement flag (`duplicate_pan_acknowledged`) when an advisor knowingly creates a duplicate. Future production-readiness work may harden this to strict prevention.

**household_id:** References the `households` table (which is its own minimal schema for cluster 1: just `household_id`, `name`, `created_at`). Family relationships within a household are deferred to a later cluster.

**risk_appetite, time_horizon:** The simplified attitudinal profile fields. These drive I0 enrichment and are referenced by mandate compliance checks (cluster 8) and portfolio analytics (cluster 10).

**life_stage, liquidity_tier:** I0 enrichment outputs. Initially nullable because enrichment runs after the investor record is created (in the same transaction in cluster 1, but the schema permits async enrichment in future clusters).

**created_via:** Distinguishes form-onboarded, conversational-onboarded, and API-onboarded investors. Useful for usage analytics and for understanding which onboarding paths produce higher-quality data.

### 2.3 Investor Indexes

Required database indexes:

- Primary key on `investor_id`.
- Unique index on `pan` (allowing duplicates only when `duplicate_pan_acknowledged = true`; enforced as a partial unique index in Postgres or through application-level validation in SQLite).
- Index on `email` for email lookup.
- Index on `household_id` for household-level queries.
- Index on `advisor_id` for advisor's-book queries.
- Composite index on `(advisor_id, created_at)` for advisor's-recently-created-investors queries.

### 2.4 Investor Validation Rules

Validation runs both client-side (form layer for fast feedback) and server-side (canonical authority).

| Field | Validation Rule |
|---|---|
| name | Required; 2 to 100 chars; must contain at least one space (full name expectation) |
| email | Required; valid email format per RFC 5322 |
| phone | Required; E.164 format; default to +91 country code if 10-digit Indian number provided |
| pan | Required; matches `^[A-Z]{5}[0-9]{4}[A-Z]$`; auto-uppercased before validation |
| age | Required; integer 18 to 100 |
| household_id | Required (either references existing household or is a fresh ULID for new household) |
| advisor_id | Required (defaults to logged-in advisor in cluster 1) |
| risk_appetite | Required; enum |
| time_horizon | Required; enum |

Server-side validation produces an RFC 7807 problem detail per Doc 2 Pass 1 Decision 6 when validation fails. The `errors` array within the problem detail names each failing field and the specific validation that failed.

## 3. Other Canonical Entities (Placeholders)

The following canonical entities will be defined in subsequent clusters. Their placement in this entry is reserved.

**Holding:** an investor's position in a specific instrument. Cluster 4 (model portfolio) or cluster 5 (first agent) introduces this depending on whether holdings are needed to demonstrate the model portfolio first or the first case execution first.

**Mandate (and MandateVersion):** an investor's investment policy with versioned amendments. Cluster 2 introduces this.

**Case:** the central object representing an investment recommendation flow from triggering event to advisor decision. Cluster 5 introduces this.

**Model Portfolio (and Model Portfolio Versions, L1/L2/L3/L4 manifest):** the firm's investment templates and approved instrument universe. Cluster 4 introduces this.

**Macro Signal, Industry Signal, Circular, Fund Offer Document, T1 Event, N0 Alert:** various data and event entities. Subsequent clusters introduce them per their relevance.

When each of these entities is defined, a corresponding section is added to this entry following the pattern of the Investor section above (schema, field notes, indexes, validation rules).

## 4. Schema Versioning

Each canonical entity has a `schema_version` integer. The current cluster 1 Investor schema is version 1.

When the schema changes:

1. The foundation reference entry's revision history records the change.
2. The schema_version increments by 1.
3. An Alembic migration is authored to alter the database schema.
4. Components that consume the entity are reviewed for impact; any that need updating are flagged in the revision note.
5. T1 telemetry events that include the entity (or its derived data) capture the schema version used at the time, so audit replay can reconstruct correctly even after schema evolution.

Schema evolution is expected and acceptable. The discipline is making it explicit: schema changes happen through documented revisions, not through silent drift.

## 5. Storage and Persistence

Investor records are persisted in the `investors` table in the deployment's database (SQLite for demo stage per the demo-stage database addendum, Postgres for production). The SQLAlchemy declarative model for Investor mirrors the schema in §2.1.

Demo-stage storage uses SQLite via `aiosqlite`. The same SQLAlchemy model works on Postgres without changes when the production-readiness migration occurs.

## 6. Read Patterns

The Investor entity is read by:

- The advisor's investor list (the home tree placeholder in cluster 0 lights up in cluster 1 with real investors).
- I0 (FR Entry 11.0) for enrichment input.
- C0 (FR Entry 14.0) for conversational onboarding output (writes the record).
- M1 (cluster 2 onwards) for mandate attachment.
- Case orchestration (cluster 5 onwards) when opening a case for an investor.
- Portfolio analytics (cluster 10 onwards) when computing investor-level metrics.
- Audit replay (cluster 15 onwards) for case reconstruction.

The high read frequency and broad cross-cluster consumption is why the schema is documented prominently here: changes ripple widely.

## 7. Write Patterns

Writes to the Investor entity happen at:

- Form-based onboarding (chunk 1.1): full record creation including I0 enrichment.
- Conversational onboarding (chunk 1.2): full record creation through C0 + I0 enrichment.
- API onboarding (cluster 1 stub): full record creation through HTTP endpoint + I0 enrichment.
- Future: KYC verification updates (kyc_status, kyc_verified_at, kyc_provider).
- Future: re-enrichment runs (life_stage, liquidity_tier, enriched_at, enrichment_version) when I0 heuristics evolve.
- Future: advisor-initiated profile edits (any of the advisor-entered fields, with audit trail).

Updates always update `last_modified_at` and `last_modified_by`. Updates that affect enrichment-relevant fields (age, time_horizon, risk_appetite) trigger re-enrichment.

## 8. Acceptance Criteria

The Investor schema is considered locked when:

1. The SQLAlchemy declarative model for Investor is implemented matching §2.1.
2. The Alembic migration creates the `investors` table with all required indexes per §2.3.
3. All required validation rules from §2.4 are enforced at the server-side validation layer.
4. The `households` table exists with the minimal schema (household_id, name, created_at) and supports the household_id foreign key from investors.
5. Records can be created through form submission (chunk 1.1), C0 conversation (chunk 1.2), and API endpoint (cluster 1 stub) with the same schema.
6. I0 enrichment can write to life_stage, liquidity_tier, and related fields without violating any schema constraints.
7. The schema_version field is set to 1 on all created records.
8. T1 telemetry captures `investor_created` events with the investor_id and the enriched values when enrichment completes.

## 9. Open Questions

The schema_version increment policy when only enrichment-related fields change (e.g., I0 heuristic evolves) is open. Working answer: enrichment-only changes don't bump schema_version because the schema itself is unchanged; the `enrichment_version` field on the investor record tracks enrichment lineage separately. This matches the principle that schema_version is for structural changes, not for semantic re-enrichment.

The Indian regulatory category classification (resident, NRI, OCI, foreign portfolio investor, etc.) is not in cluster 1 schema. Whether to add it incrementally or as part of a dedicated regulatory cluster is open. Working answer: deferred until the first cluster that actually consumes regulatory category (likely cluster 8 governance gate when SEBI rules need to apply differently per category).

Family relationship modelling within a household (spouse, parent-child, etc.) is deferred. Whether the eventual addition is a separate `relationships` table or denormalised into investor records is open. Working answer: separate `relationships` table when the time comes; denormalising into investor records would require schema changes whenever relationships evolve.

## 10. Revision History

April 2026 (cluster 1 drafting pass): Initial entry authored. Investor entity schema locked at version 1. Other canonical entity placeholders reserved for subsequent clusters.

May 2026 (cluster 1 chunk 1.1 shipped): SQLAlchemy `Investor` + `Household` ORM in `src/artha/api_v2/investors/models.py`; Alembic migration `ae7473a43ba2` creates the tables. Physical table names are `v2_investors` and `v2_households` (not `investors`/`households`) due to v1 strangler-fig coexistence — see chunk plan retrospective note 1. Logical entity remains "Investor"; the prefix is namespacing only and drops in a rename migration when v1 is sunset. All 9 §2.4 validation rules enforced server-side via Pydantic `InvestorCreateRequest` (PAN regex auto-uppercased, phone E.164 with +91 default, name with required space, age 18-100, EmailStr). Schema version 1 written on every record. Records reachable via three onboarding paths in chunk 1.1: form (the demo-friendly default), API (functional, no UI per Demo-Stage Addendum §1.4), and the conversational path stub (full implementation in chunk 1.2).

---

**End of FR Entry 10.7. Investor entity locked; other entities accumulate in subsequent clusters.**
