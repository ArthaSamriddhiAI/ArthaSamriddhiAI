# Samriddhi AI: Cluster 1 Ideation Log

## Investor Onboarding, Architectural Decisions Locked

**Document:** Samriddhi AI, Cluster 1 Ideation Log
**Cluster:** 1 (Investor Onboarding)
**Pass:** 1 of 2 (Ideation)
**Status:** Complete; ready for drafting pass
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This is the cluster 1 ideation log. It captures the architectural decisions locked during the cluster's ideation pass, before drafting of foundation reference entries and the chunk plan begins.

Cluster 1 ships investor onboarding as the first real product capability of Samriddhi AI. Where cluster 0 proved the transport stack works end-to-end (auth, SSE, app shell), cluster 1 proves that an actual product workflow flows through the system: an advisor adds a new investor, the system enriches the investor's profile through I0, and the investor appears in the advisor's book ready for subsequent cluster work to consume.

The cluster ships three paths but only two visible chunks. Form-based onboarding (chunk 1.1) is the demo-friendly default. Conversational onboarding via C0 (chunk 1.2) demonstrates the conversational orchestrator with a bounded LLM scope. The API onboarding path is stubbed (endpoint exists, accepts the canonical investor JSON, creates the investor) but has no UI and is not demoed; it exists to prove the canonical investor schema is reachable through structured input. A third visible chunk (1.3) ships the SmartLLMRouter settings UI with API key configuration, because cluster 1 is the first cluster to need the LLM provider toggle and the configuration surface should land in the same cluster as the first LLM consumer.

The decisions in this log span seven topic areas: cluster scope and chunk boundaries, the canonical investor schema, the form-based onboarding path, I0 enrichment scope, the C0 conversational orchestrator design with Option 3 bounded LLM scope, the SmartLLMRouter settings UI, and demo-stage carve-outs.

---

## 1. Cluster Scope and Chunk Boundaries

### 1.1 Decision: Three Chunks, Three Paths, Two Visible

**Locked answer:** Cluster 1 ships three chunks. Chunk 1.1 is the form-based investor onboarding with I0 enrichment, the demo-friendly default. Chunk 1.2 is the C0 conversational onboarding with bounded LLM scope per Option 3. Chunk 1.3 is the SmartLLMRouter settings UI with API key configuration. The API onboarding path (HTTP endpoint accepting canonical investor JSON) is implemented as part of chunk 1.1's backend work but has no dedicated UI and no separate chunk.

**Rationale:** The form path is the production-accurate-but-demo-able default that shows enrichment visibly. The conversational path demonstrates C0 as a real component (rather than a placeholder), which matters for system credibility. The settings UI is the first time the LLM provider toggle becomes a real product surface; it lands in cluster 1 because cluster 1 is the first LLM consumer and the configuration surface should not lag the first consumption.

The API path is stubbed because it adds limited demo value. Demos focus on visible advisor experience; an HTTP endpoint that accepts JSON is invisible. The stub exists for architectural completeness (proving the canonical schema is reachable through structured input), not for demonstration.

**Alternatives considered:** Three visible chunks (separate API chunk; rejected because API has no demo surface and would consume drafting effort without proportional value), one chunk for cluster 1 (combine all paths; rejected because the form and the conversational paths have substantially different acceptance criteria and conflating them in one chunk obscures the contract).

### 1.2 Decision: Cluster Acceptance Criterion

**Locked answer:** Cluster 1 ships when an advisor can: (a) onboard a new investor via the form path with I0 enrichment producing visible inferred signals; (b) onboard a new investor via C0 conversational path producing the same canonical investor record; (c) configure the platform's LLM provider through a settings UI with API key entry; (d) see the onboarded investor in their investor list as a persistent record.

If all four are demonstrably working for at least one investor through each path, cluster 1 is shipped.

---

## 2. Canonical Investor Schema

### 2.1 Decision: Simplified Demo-Stage Schema with Reading 1 Enrichment

**Locked answer:** The canonical investor schema for demo stage is a simplified version of the eventual production schema. The advisor-entered fields are:

- `name`: full name (string, required)
- `email`: contact email (string, required, validated)
- `phone`: contact phone with country code (string, required, validated)
- `pan`: Permanent Account Number (string, required, validated against PAN format `[A-Z]{5}[0-9]{4}[A-Z]`)
- `age`: in years (integer, required, range 18 to 100)
- `household_id`: household identifier (string; either selected from existing households if the advisor is adding a family member, or auto-generated for new households)
- `advisor_id`: assigned advisor (string; defaults to the logged-in advisor for demo, but can be reassigned by CIO in later clusters)
- `risk_appetite`: enum (`aggressive`, `moderate`, `conservative`)
- `time_horizon`: enum (`under_3_years`, `3_to_5_years`, `over_5_years`)

Plus system-generated fields:
- `investor_id`: ULID, primary key
- `created_at`: timestamp
- `created_by`: user_id of the advisor who onboarded
- `created_via`: enum (`form`, `conversational`, `api`); records which path produced the investor
- `kyc_status`: enum (`pending`, `verified`, `failed`); always `pending` in demo stage (no KYC integration)

I0 enrichment fields (computed by I0, displayed in the investor profile, not entered by advisor):
- `life_stage`: enum (`accumulation`, `transition`, `distribution`, `legacy`)
- `liquidity_tier`: enum (`essential`, `secondary`, `deep`)
- `enriched_at`: timestamp of last enrichment run

**Rationale:** This schema is rich enough to be useful for subsequent clusters (cluster 2 mandate management consumes the investor; cluster 5 case pipeline consumes the investor; cluster 10 portfolio analytics consumes the investor) without imposing the operational overhead of a full production schema (KYC document upload, family tree relationships, detailed wealth breakdown, income details, tax jurisdiction nuance, regulatory category classification, all of which are deferred).

The Reading 1 enrichment pattern (advisor enters basics; I0 infers life_stage and liquidity_tier from those basics) makes enrichment visibly active rather than a passive label. The advisor sees the form values become richer signals after I0 runs.

**Alternatives considered:** Full production schema (rejected as premature; demo stage doesn't need it), even simpler schema with just risk and horizon (rejected as too thin; subsequent clusters need PAN for uniqueness, age for life-stage inference, household for family-level analysis later), Reading 2 with life_stage as a form field (rejected because it makes enrichment invisible).

### 2.2 Decision: PAN as Unique Identifier with Warn-and-Proceed Duplicate Handling

**Locked answer:** PAN is the unique identifier across investors within a deployment. When the advisor enters a PAN that already exists in the system, the form (and C0) shows a warning displaying the existing investor's name and creation date, and asks "Do you want to proceed creating a new record, or view the existing investor?" Proceeding creates a new record despite the duplicate (with a `duplicate_pan_acknowledged: true` field stored in metadata for audit). Viewing the existing investor takes the advisor to that investor's profile.

**Rationale:** Warn-and-proceed is the demo-stage pragmatic choice. Production hardening might want strict duplicate prevention (return an error and force the advisor to use the existing record), but demo stage handles edge cases that come up in live demos (e.g., same PAN entered as a typo from the advisor onboarding the same family unit twice) without blocking the flow. The acknowledgement field preserves the audit trail.

**Alternatives considered:** Strict block (rejected as too rigid for demo edge cases), silent overwrite (rejected as data-destructive), silent duplication (rejected as auditless).

### 2.3 Decision: Household Identifier Logic

**Locked answer:** When onboarding an investor, the advisor can either select an existing household from a dropdown of households they've previously created, or enter a household name to create a new household. The household name is normalised (trimmed, title-cased) and a household_id is generated as a ULID; the household_id is stored alongside the investor.

Household relationships (parent, spouse, child, etc.) are not captured in cluster 1; the household is just a grouping mechanism. Family-tree relationships are deferred to a later cluster.

**Rationale:** Household grouping is useful for subsequent clusters that aggregate at family level (mandate management for shared mandates, portfolio analytics for family-level concentration). The minimum needed is just the grouping; relationships within the household are richer features that can come later.

**Alternatives considered:** Skip household entirely in cluster 1 (rejected; household-level aggregation is referenced too widely in later clusters), capture full family-tree relationships now (rejected as scope creep; can be added later without breaking the simple grouping).

---

## 3. Form-Based Onboarding Path

### 3.1 Decision: Single-Page Form, Not a Multi-Step Wizard

**Locked answer:** The form is a single page with all fields visible at once, grouped into three sections: Identity (name, email, phone, PAN, age), Household and Assignment (household selector, advisor assignment), Investment Profile (risk appetite, time horizon). Each section has a header and explanatory text; fields within a section are laid out in a 2-column grid where the screen is wide enough.

Submit button is at the bottom; on submit, validation runs, then the form posts to the backend, then the advisor sees a transient loading state ("Creating investor and running enrichment...") for 1-2 seconds, then the enriched investor profile is displayed inline as the success state with the I0 inferred signals shown alongside the entered fields.

**Rationale:** Single-page form is faster, more transparent, and easier to demo than a multi-step wizard. The total field count is small enough (about 9 advisor-entered fields) that the form fits on one screen comfortably. Multi-step wizards add complexity without proportional benefit at this field count.

The transient loading state matters for demo: it creates a moment of visible work happening, which signals to the demo audience that the system is doing something. The enriched profile then appearing reinforces that the work was meaningful.

**Alternatives considered:** Multi-step wizard with separate pages per section (rejected as over-engineered for 9 fields), modal dialogue (rejected as too lightweight for the importance of investor onboarding).

### 3.2 Decision: Field Validation Rules

**Locked answer:** Validation rules per field:

- `name`: required, 2 to 100 characters, must contain at least one space (full name).
- `email`: required, valid email format.
- `phone`: required, validates against E.164 international format. Demo stage defaults to +91 country code if user enters a 10-digit number without country code.
- `pan`: required, regex `^[A-Z]{5}[0-9]{4}[A-Z]$`, auto-uppercased. Duplicate check per §2.2.
- `age`: required, integer 18 to 100.
- `household_id`: required (either existing or new household).
- `advisor_id`: required (defaults to logged-in advisor; CIO can change for cluster 1 demo).
- `risk_appetite`: required, enum.
- `time_horizon`: required, enum.

Validation runs client-side on field blur (for fast feedback) and server-side on submit (for security). Server-side errors are displayed inline next to the offending field plus a summary banner at the top.

**Rationale:** These rules are the minimum to ensure data quality without adding excessive friction. The PAN regex matches India's standard PAN format. The age range 18 to 100 is the practical investing age range. Phone E.164 format with default country code matches Indian mobile number conventions while supporting international clients.

### 3.3 Decision: Form Saves Draft on Field Change

**Locked answer:** As the advisor fills the form, partial form state is saved to the browser's `sessionStorage` (not `localStorage`, so the draft expires when the tab closes). If the advisor navigates away and returns to the form within the session, the partial draft is restored. On successful submission, the draft is cleared.

**Rationale:** Demo audiences sometimes navigate away to show another part of the system mid-onboarding-form; losing the partially-entered data is awkward. Session-scoped draft saving is a small UX nicety that avoids that awkwardness without needing server-side draft persistence.

**Alternatives considered:** No draft saving (rejected; demos are messy), full server-side draft saving (rejected as overkill for demo stage).

---

## 4. I0 Enrichment Scope

### 4.1 Decision: I0 Active Layer Only for Cluster 1

**Locked answer:** I0 in cluster 1 implements only the active layer: rule-based heuristics that take the advisor-entered investor fields and produce `life_stage` and `liquidity_tier` outputs. The dormant layer (long-term pattern memory) and the pattern library (cross-investor pattern recognition) are deferred to later clusters because they require accumulated case history and behavioural data that don't exist at cluster 1.

**Rationale:** The active layer is sufficient to demonstrate enrichment visibly. Pattern library work requires data that hasn't been generated yet; building it at cluster 1 would produce empty patterns that don't actually classify anything useful.

### 4.2 Decision: Life Stage Inference Heuristics

**Locked answer:** Life stage is inferred from age, time_horizon, and (when available) implicit accumulation signals:

- `accumulation`: age 25 to 45 with time_horizon `over_5_years` or `3_to_5_years`. Wealth is being built; investment focus is growth-oriented.
- `transition`: age 45 to 55 with any time_horizon, or age 25 to 45 with time_horizon `under_3_years`. Approaching retirement or in a transitional life event; balance shifting toward preservation.
- `distribution`: age 55 to 70 with time_horizon `under_3_years` or `3_to_5_years`. Drawing on accumulated wealth; preservation and income generation are primary.
- `legacy`: age over 70, or any age with `risk_appetite: conservative` and `time_horizon: under_3_years`. Estate planning and inter-generational transfer.

Edge cases (e.g., young investor with conservative risk and short horizon, which is unusual) get classified by the most-restrictive matching tier with a `low_confidence: true` flag visible to the advisor.

**Rationale:** These heuristics are deliberately simple and rule-based, not LLM-based. They produce defensible, transparent classifications. The advisor can see why a particular investor was classified as `accumulation` (their age and horizon match the rule) and can override if firm policy disagrees in edge cases.

### 4.3 Decision: Liquidity Tier Inference Heuristics

**Locked answer:** Liquidity tier reflects how much of the investor's portfolio should be readily accessible. Inferred from time_horizon and risk_appetite:

- `essential`: 5-15% of portfolio in highly liquid instruments. Default for `over_5_years` time horizon with `aggressive` or `moderate` risk.
- `secondary`: 15-30% of portfolio in liquid-to-semi-liquid instruments. Default for `3_to_5_years` time horizon with any risk, or `over_5_years` with `conservative` risk.
- `deep`: 30%+ of portfolio in highly liquid instruments. Default for `under_3_years` time horizon, regardless of risk.

The percentage range is shown to the advisor alongside the tier label, so the inference is interpretable.

**Rationale:** These ranges reflect standard wealth advisory liquidity frameworks; an experienced advisor will recognise them as reasonable defaults. The ranges become inputs to subsequent clusters' analyses (mandate compliance checks if portfolio liquidity is within mandate, drift monitoring against the investor's liquidity tier).

### 4.4 Decision: I0 Enrichment Runs Synchronously on Investor Creation

**Locked answer:** I0 enrichment runs synchronously as part of the investor creation transaction. The form submission flow is: validate → create investor record → run I0 enrichment → display enriched profile. Total flow time is sub-second because I0 in cluster 1 is rule-based with no external calls.

The synchronous design simplifies the demo experience (no "enrichment pending" state to manage) and matches what production async enrichment would look like wrapped in synchronous orchestration.

**Rationale:** Synchronous enrichment is the right choice when enrichment is fast and deterministic (rule-based heuristics). It becomes the wrong choice if enrichment ever depends on external API calls or LLM inference; if I0 grows to include LLM-based pattern recognition in a later cluster, the enrichment becomes async and the form's success state shows a "enrichment running, refresh to see updated profile" affordance. That migration is a future-cluster concern.

---

## 5. C0 Conversational Orchestrator Design (Option 3)

### 5.1 Decision: Option 3 Bounded LLM Scope for Cluster 1

**Locked answer:** C0 in cluster 1 uses Option 3: real LLM (Mistral or Claude per platform toggle) for intent detection on the first message and slot extraction from free-text answers. The rest of the conversation is template-driven by a state machine that knows what fields it still needs to collect.

The conversation flow is:

1. Advisor types their first message: "I want to onboard a new client."
2. C0 sends to the LLM: "Classify the intent of this message. Available intents: investor_onboarding, case_opening, alert_response, briefing_request, general_question."
3. LLM returns: `investor_onboarding`.
4. C0 starts the onboarding state machine: presents a templated message asking for the investor's name.
5. Advisor responds with the name (potentially with extra context, e.g., "His name is Rajesh Kumar and he's in his early 40s").
6. C0 sends to the LLM: "Extract these fields from the user's message: name, age. Return as structured JSON."
7. LLM returns: `{"name": "Rajesh Kumar", "age": 41}`.
8. C0 fills the matching slots in the canonical investor schema and presents the next templated question for missing slots: "What's Rajesh's email and phone?"
9. The conversation continues until all required fields are filled.
10. C0 presents a confirmation: "Here's the investor I have so far: <summary>. Should I create the record?"
11. On confirmation, C0 creates the investor record (same backend path as the form), I0 enrichment runs, the enriched profile is displayed in the chat as a card.

**Rationale:** This pattern is bounded enough to be demo-safe (the LLM can't go off-topic because it only sees scoped intent and extraction prompts) but production-accurate enough to show real LLM-powered conversation (the LLM does the natural-language understanding work).

The state-machine fallback ensures the LLM doesn't have to manage the conversation flow itself; if the LLM extracts incomplete or invalid fields, the state machine simply asks for the missing or invalid fields again with templated prompts.

### 5.2 Decision: C0 Renders as a Chat UI in the App Shell

**Locked answer:** C0 has a dedicated chat surface within the React app, accessible from a sidebar item ("Conversational" or similar) or via a keyboard shortcut. The chat surface is a standard chat layout: message thread on top, input box at the bottom, send button. Messages from the advisor appear right-aligned; messages from C0 appear left-aligned with a small avatar indicating it's the system.

System-rendered cards (such as the enriched investor profile after creation) appear inline in the message thread as structured rich content rather than plain text.

**Rationale:** Standard chat UX. Demo audiences immediately recognise the pattern. Inline rich content for system messages (cards, structured data) elevates the conversation from a text-only chatbot to a productive assistant.

### 5.3 Decision: C0 Conversation State Persists Per Session

**Locked answer:** Each C0 conversation is a session-scoped thread. The advisor can navigate away and come back to the chat surface, finding the conversation where they left off, until they explicitly start a new conversation or until the session ends.

Conversations are stored in the database (the `c0_conversations` table) for audit and (in later clusters) T1 telemetry consumption. Each message has an event_id, sender, content, timestamp, and any structured metadata (extracted slots, intent classifications).

**Rationale:** Persisting conversations is the standard pattern for any conversational interface and matters more in production than in demo. For demo stage, persistence helps because the advisor can show the chat history during a demo without re-running the conversation from scratch.

### 5.4 Decision: LLM Failure Handling in C0

**Locked answer:** If the LLM call fails (provider unavailable, rate limit, timeout), C0 falls back to pure template-driven behaviour: it asks the advisor to enter each field directly with structured prompts, bypassing intent detection and slot extraction. The advisor sees a small notice ("Conversational understanding is temporarily unavailable; please enter fields directly") and the conversation continues in a more form-like mode.

The fallback ensures C0 never breaks the demo if the LLM provider has an issue.

**Rationale:** Resilience matters even in demo stage because LLM provider availability is genuinely variable and demos are public-facing. Template fallback is the simplest possible degradation that keeps the conversation functional.

**Alternatives considered:** Hard error blocking C0 until LLM recovers (rejected as demo-fragile), silent retry with exponential backoff (rejected as it makes the conversation feel slow), full failover to alternate LLM provider (deferred to later clusters when SmartLLMRouter has multi-provider failover).

---

## 6. SmartLLMRouter Settings UI (Chunk 1.3)

### 6.1 Decision: Settings Page UI Surface

**Locked answer:** The SmartLLMRouter configuration is exposed as a settings page within the firm's admin surface. Accessible via the user menu (a "Settings" item, visible only to CIO role for cluster 1) or via a dedicated route at `/app/cio/settings/llm-router`.

The settings page has:

- Provider selection: a radio button with options "Mistral (free)" and "Claude (paid)". Selection is the platform-level toggle.
- API key entry: text inputs for "Mistral API key" and "Claude API key". The fields are masked by default with a "show" button. Keys are stored encrypted server-side (per principles document confidentiality requirements).
- Test connection button: when clicked, makes a test call to the selected provider to verify the API key works. Shows green check or red error inline.
- Status display: shows the current provider, last successful call timestamp, last error if any.
- Save button: persists the configuration. On save, T1 emits an `llm_router_configuration_changed` event for audit.

**Rationale:** This is the natural product surface for the SmartLLMRouter. CIO-only access matches the role-permission model (configuring LLM providers is firm-level governance, not per-advisor work). The test-connection button is the small UX nicety that makes API key entry less anxiety-inducing.

### 6.2 Decision: API Key Storage Strategy

**Locked answer:** API keys are stored in the database (the `llm_provider_config` table) encrypted at rest using a deployment-level encryption key. The encryption key is in the deployment's environment configuration (not in the database). On each LLM call, the SmartLLMRouter decrypts the key, makes the call, never logs the key.

For demo stage running on SQLite, this means the key is in the local SQLite file encrypted; if the laptop is compromised, the key is at risk only if the encryption key is also leaked. For production with Postgres, the same pattern applies but the key management can be more sophisticated (KMS, secrets manager).

**Rationale:** Encryption-at-rest is the minimum bar for storing API credentials. The deployment-level encryption key separation prevents trivial compromise from a database leak alone. Production may layer additional controls.

### 6.3 Decision: Default Configuration on First Run

**Locked answer:** When the system first runs, no LLM provider is configured. The CIO must visit the settings page to configure at least one provider before any LLM-consuming feature works. C0's intent detection and slot extraction will fail with the template-driven fallback (per §5.4) until configuration is complete.

A first-run banner ("Configure your LLM provider to enable conversational features") is displayed prominently on the CIO's home tree until configuration is complete.

**Rationale:** Forcing explicit configuration prevents accidental no-op usage and makes the LLM provider a deliberate setup step. The banner ensures the requirement is visible without forcing a blocking modal.

---

## 7. Demo-Stage Carve-Outs

### 7.1 Decision: API Onboarding Path Stubbed but Real

**Locked answer:** The API onboarding endpoint at `POST /api/v2/investors` accepts the canonical investor JSON, validates it against the same rules as the form, calls the same backend service that creates the investor and runs I0 enrichment, and returns the created investor record. The endpoint is functional and tested but has no UI.

Documentation for the API path lives in the OpenAPI spec produced by FastAPI; consumers in the future can call this endpoint directly.

**Rationale:** The API path has architectural value (proves the canonical schema is reachable through structured input) without UI cost. Stubbing the endpoint as functional is straightforward; not building UI saves time. Future clusters or external integrations can use this endpoint directly.

### 7.2 Decision: KYC Integration Deferred

**Locked answer:** KYC verification is not implemented in cluster 1. The `kyc_status` field on the investor record exists and is always set to `pending`. No KYC document upload, no integration with KYC service providers, no KYC status workflow.

When production-readiness phase begins (or earlier if a specific firm requires it), a dedicated cluster implements KYC: document upload, integration with KYC provider, status workflow, blocking effects on investments until KYC is verified.

**Rationale:** KYC is a substantial integration effort (provider integration, document handling, regulatory compliance) that doesn't add demo value. The schema field is reserved so the integration plugs in cleanly later.

### 7.3 Decision: Family Tree Relationships Deferred

**Locked answer:** The household_id grouping is implemented but household-level relationships (spouse, parent-child, etc.) are not. Each investor has a household_id; relationships within the household are not modelled.

A later cluster (likely after cluster 5 when cases are running and family-level analysis matters) can add relationship modelling.

**Rationale:** Relationships are richer features than grouping. Demo can show "Mr. and Mrs. Sharma are in the same household" without needing to model that they're spouses. Relationship modelling adds complexity that's not yet needed.

### 7.4 Decision: Wealth Details Beyond Risk and Horizon Deferred

**Locked answer:** Cluster 1 captures risk_appetite and time_horizon as the attitudinal investment profile fields. Detailed wealth breakdown (current portfolio composition, real estate, business interests, debts, insurance, succession context) is deferred. These will be captured in cluster 2 (mandate management) or in a dedicated wealth-profile cluster.

**Rationale:** Wealth details are extensive and many of them belong with mandate management or with the investor's first portfolio onboarding (cluster 4 model portfolio context). Capturing them in cluster 1 is premature.

---

## 8. Cluster 1 Closure

### 8.1 Decisions Locked Summary

Decisions across seven topic areas:

Cluster scope: three chunks (1.1 form, 1.2 conversational, 1.3 settings UI), three onboarding paths (form visible, conversational visible, API stubbed without UI).

Canonical investor schema: nine advisor-entered fields, six system-generated fields, two I0-enriched fields. PAN as unique identifier with warn-and-proceed duplicate handling. Household as grouping mechanism; relationships deferred.

Form-based path: single-page form with three field groups; client-side validation on blur, server-side on submit; sessionStorage draft persistence; transient loading state followed by enriched profile inline display.

I0 enrichment: active layer only; rule-based life_stage and liquidity_tier heuristics; synchronous enrichment as part of investor creation.

C0 conversational: Option 3 bounded LLM scope (intent detection + slot extraction by LLM, conversation flow by state machine); chat UI in app shell; per-session conversation persistence; template-driven fallback on LLM failure.

SmartLLMRouter settings: dedicated settings page with provider selection, API key entry, test connection button, status display; CIO-only access; encrypted-at-rest API key storage; first-run configuration banner.

Demo-stage carve-outs: API onboarding stubbed (functional but no UI); KYC deferred; family tree relationships deferred; detailed wealth fields deferred.

### 8.2 Foundation Reference Entries to be Authored in Drafting Pass

Topic 10 Data Layer:
- FR Entry 10.7 (Canonical Entity Schemas; partial: investor schema only, other entities accumulate in later clusters)

Topic 11 Investor Context Engine:
- FR Entry 11.0 (I0 Overview)
- FR Entry 11.1 (I0 Active Layer with life_stage and liquidity_tier inference)

Topic 14 Conversational and Notification:
- FR Entry 14.0 (C0 Conversational Orchestrator with cluster 1 bounded scope)

Topic 16 LLM Provider Strategy:
- FR Entry 16.0 (SmartLLMRouter Overview with platform toggle and configuration)

Plus chunk plan:
- cluster_01_chunk_plan.md with chunks 1.1 (form), 1.2 (conversational), 1.3 (settings UI)

Plus cluster 1 demo-stage addendum capturing the carve-outs (API stubbed, KYC deferred, etc.).

### 8.3 Decisions Deferred

Several cluster 1 questions are intentionally deferred:

The full I0 dormant layer and pattern library are deferred to a cluster after enough case history exists for pattern recognition to be meaningful (likely cluster 11 watch tier or beyond).

Multi-provider LLM failover (Mistral fails, automatically retry with Claude) is deferred. The platform toggle is single-provider; failover comes when production reliability matters.

Per-agent LLM tiering (different model per agent based on task complexity) is deferred per the principles document.

KYC integration, family tree relationships, detailed wealth fields are all deferred to dedicated future clusters or to production-readiness.

Conversation summarisation and topic detection across multi-turn conversations are deferred. Cluster 1 C0 handles single-intent linear conversations.

### 8.4 Open Questions for Drafting Pass

The exact visual rendering of the enriched investor profile card (life_stage and liquidity_tier alongside entered fields) needs design discretion during implementation. The foundation reference entry specifies what fields are shown; the visual treatment (badges, icons, colours) is a Doc 3 Pass 2 onwards concern but cluster 1 ships something. Working answer: clean two-column layout with section headers, life_stage and liquidity_tier shown as colored badges with brief explanatory tooltips.

The C0 conversation history persistence schema (the `c0_conversations` table structure) needs final field-level specification during the FR Entry 14.0 drafting pass. Working answer: conversation_id, user_id, started_at, last_message_at, status (active, completed, abandoned), plus a related `c0_messages` table with message_id, conversation_id, sender, content, timestamp, metadata_json.

The exact LLM prompts for intent detection and slot extraction need final wording during chunk 1.2 implementation. Working answer: intent detection prompt is a fixed template with the five candidate intents listed; slot extraction prompt is dynamically generated from the state machine's current expected fields. Both prompts are versioned and stored in the C0 skill.md file per the per-agent skill.md mechanism.

---

**End of Cluster 1 Ideation Log. Ready for drafting pass.**
