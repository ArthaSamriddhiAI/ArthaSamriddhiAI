# Chunk Plan: Cluster 1 - Investor Onboarding

**Document:** Samriddhi AI, Chunk Plan, Cluster 1
**Cluster:** 1 (Investor Onboarding)
**Status:** Chunks 1.1 + 1.3 shipped May 2026; chunk 1.2 ready for implementation
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cluster Header

### Purpose

Cluster 1 ships investor onboarding as the first real product capability of Samriddhi AI. By the end of this cluster, an advisor can add new investors to the system through two visible paths (form-based or conversational via C0), the system enriches each investor's profile through I0 (life stage and liquidity tier inference), and the investors appear in the advisor's investor list ready for subsequent cluster work to consume.

This cluster proves that an actual product workflow flows through the system. Where cluster 0 demonstrated transport (auth, SSE, app shell), cluster 1 demonstrates capability: a full-stack feature from form input to enriched data record with visible UX.

A third chunk (1.3) ships the SmartLLMRouter settings UI, because cluster 1 is the first cluster to require LLM provider configuration and the configuration surface should land in the same cluster as the first LLM consumer.

### Foundation References Produced

- FR Entry 10.7: Canonical Entity Schemas (Investor entity locked at v1; other entities accumulate later)
- FR Entry 11.0: I0 Investor Context Engine Overview
- FR Entry 11.1: I0 Active Layer (life_stage and liquidity_tier inference heuristics)
- FR Entry 14.0: C0 Conversational Orchestrator (investor onboarding intent fully specified)
- FR Entry 16.0: SmartLLMRouter Overview

### Foundation References Consumed

- Principles of Operation (sections on agent architecture §3, data layer §4, LLM provider strategy §6)
- Foundation Reference and Chunk Plan Structure
- FR Entry 17.0, 17.1, 17.2 (auth; cluster 0)
- FR Entry 18.0 (SSE channel; cluster 0)
- Cluster 0 Dev-Mode Addendum (stub auth carries forward)
- Demo-Stage Database Addendum (SQLite carries forward)

### Cluster-Level Acceptance Criterion

Cluster 1 ships when an advisor can:

1. Add a new investor through the form path with all 9 advisor-entered fields, see the form validate, see I0 enrichment produce visible life_stage and liquidity_tier signals.
2. Add a new investor through the C0 conversational path by typing natural-language responses to bounded prompts, with the same backend service producing the same canonical investor record.
3. Configure the platform's LLM provider through the CIO settings UI: select Mistral or Claude, enter the API key, test the connection, save.
4. See the onboarded investors in their investor list as a persistent record across sessions.
5. View an investor's enriched profile showing entered fields plus the I0 signals.

If all five points work for at least one investor through each path, cluster 1 is shipped.

---

## Chunk 1.1: Form-Based Investor Onboarding with I0 Enrichment

### Header

- **Chunk ID:** 1.1
- **Title:** Form-Based Investor Onboarding with I0 Enrichment
- **Status:** Shipped (May 2026)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 1 ideation log)
  - Drafting completed: April 2026 (this document)
  - Implementation started: May 2026
  - Shipped: May 2026

**Chunk-shipped retrospective notes** (full retrospective at cluster 1 close):

1. **Strangler-fig table prefix.** v1 already has an ``investors`` table for its own Investor module; cluster 1 namespaces all new tables with ``v2_`` (so ``v2_investors``, ``v2_households``, etc.) to coexist. FR 10.7 §2.1 says the table is ``investors`` — that's the logical entity; the physical table carries the prefix during coexistence. When v1 is fully sunset, a rename migration drops the prefix.

2. **PAN format vs Demo-Stage Addendum example.** Addendum §3.1 suggested test PAN values like ``DEMO12345A`` — but PAN format is 5 letters + 4 digits + 1 letter (10 chars), and ``DEMO12345A`` is 4+5+1 (also 10 but wrong shape). Seed script uses ``TESTA1234A`` / ``TESTB1234B`` / etc. Recommendation: revise Addendum §3.1 to use a compliant example.

3. **EmailStr rejects reserved TLDs.** Pydantic's ``EmailStr`` (via ``email-validator`` strict mode) rejects ``.test`` / ``.example`` / ``.local`` / ``.invalid`` / ``.localhost`` per RFC 6761. Seed uses ``@example.com`` (RFC 2606 example domain, NOT reserved). Worth flagging for any future seed/test data work.

4. **TS 6 + Zod v4 surprise pair.** TypeScript 6's ``erasableSyntaxOnly`` mode rejects parameter-property class syntax (constructor `public readonly` shortcuts). Zod v4 changed the error config from ``{ invalid_type_error: ... }`` to ``{ error: ... }``. Both caught by ``npm run build`` first try; both fixed in step 4.

5. **TanStack Router relative paths.** Within nested routes (e.g., `advisor/investors/$investorId`), Link/navigate `to` props are relative to the current route's nesting — write `/investors/$investorId`, not `/advisor/investors/$investorId`. Tripped me up in 4 places; documented for cluster 2 frontend work.

### Purpose

Chunk 1.1 ships the form-based onboarding path: a single-page form that collects the canonical investor fields, server-side validation, persistence to the canonical Investor entity, synchronous I0 enrichment, and inline display of the enriched profile.

This is the demo-friendly default path. An advisor opens the form, fills it out, clicks Submit, watches a brief loading state, and sees the investor's profile (with enriched signals) appear inline. The whole flow takes well under 30 seconds for a normal-pace advisor.

The chunk also implements the API onboarding path as a stub (functional endpoint, no UI). The API path uses the same backend services as the form path, proving the canonical schema is reachable through structured input.

### Dependencies

**Foundation reference:**
- FR Entry 10.7 (Canonical Entity Schemas; Investor entity)
- FR Entry 11.0 and 11.1 (I0 active layer)

**Other chunks:**
- Cluster 0 chunks (0.1, 0.2) must be shipped: provides auth, app shell, role routing, SSE.

### Scope: In

- Investor entity table in the database with the schema from FR Entry 10.7 §2.1; Alembic migration for table creation.
- Households table (minimal: household_id, name, created_at) with FK from investors.
- Investor creation service in the backend, callable from form path, conversational path (chunk 1.2), and API stub.
- Validation layer enforcing FR Entry 10.7 §2.4 rules; produces RFC 7807 problem details on failure.
- I0 active layer implementation per FR Entry 11.1, called synchronously from the investor creation service.
- API endpoints:
  - `POST /api/v2/investors` (creates investor; no UI but functional)
  - `GET /api/v2/investors` (list investors visible to the advisor; for the investor list UI)
  - `GET /api/v2/investors/{investor_id}` (fetch one investor)
  - `GET /api/v2/households` (list households for the form's household selector)
  - `POST /api/v2/households` (create new household; called inline from form when advisor enters new household name)
- Form UI at `/app/advisor/investors/new` (and equivalent for CIO if CIO can also onboard):
  - Three-section single-page form (Identity, Household and Assignment, Investment Profile).
  - Field-level validation on blur (client-side).
  - sessionStorage draft persistence as advisor types.
  - Submit triggers validation, then POST to `/api/v2/investors`, then transient loading state, then enriched profile display inline.
  - Duplicate PAN handling: warn-and-proceed with existing investor display option.
- Investor profile display component (used by form success state and future investor list detail pages):
  - Two-column layout: entered fields on left, enrichment signals on right.
  - Life stage badge with label ("Accumulation: Wealth Building") plus tooltip.
  - Liquidity tier badge with range ("Essential: 5-15% liquid") plus tooltip.
  - "Confidence: low" indicator visible when applicable.
- Investor list UI at `/app/advisor/investors`:
  - Table or card layout listing the advisor's investors.
  - Columns: name, PAN, life_stage badge, liquidity_tier badge, age, household, created_at.
  - "Add New Investor" button leading to `/app/advisor/investors/new`.
  - Click row to view investor profile detail.
- Investor profile detail page at `/app/advisor/investors/{investor_id}`:
  - Full profile display.
  - "Edit" button (deferred functionality; cluster 1 ships read-only profile detail).
- Sidebar navigation item "Investors" lights up for advisor role (was greyed-out placeholder in cluster 0).
- T1 telemetry events emitted: `investor_created`, `investor_enrichment_completed`, `household_created` (if a new household is created during onboarding).

### Scope: Out

- Investor edit functionality. Cluster 1 ships read-only profile detail; edit comes in a later cluster.
- KYC document upload, KYC status workflow, KYC integration with external providers. All deferred.
- Family relationship modeling within a household. Cluster 1 stores household_id only.
- Detailed wealth profile beyond risk_appetite and time_horizon. Deferred.
- Advanced search/filter on the investor list. Cluster 1 lists the advisor's full book; filtering can be added later.
- Bulk import (CSV upload) of investors. Deferred.
- Email notifications to the investor on account creation. Deferred.
- C0 conversational path (chunk 1.2 ships this).
- Settings UI for LLM provider (chunk 1.3 ships this; chunk 1.1 doesn't need LLM since I0 active layer is rule-based).

### Acceptance Criteria

1. The Investor table is created in the database with all fields and indexes per FR Entry 10.7 §2.1 and §2.3. The Alembic migration runs cleanly against SQLite.

2. The form at `/app/advisor/investors/new` renders correctly with three field sections.

3. Field-level validation on blur shows clear error messages for invalid inputs (bad PAN format, age out of range, missing required field, etc.).

4. sessionStorage draft persistence works: filling part of the form, navigating away, and returning shows the partial draft restored.

5. Submitting a valid form produces an investor record in the database with all fields correctly populated.

6. I0 enrichment runs as part of the creation transaction; the resulting investor record has life_stage, life_stage_confidence, liquidity_tier, liquidity_tier_range, enriched_at, enrichment_version all populated.

7. The enrichment heuristics produce expected outputs for standard cases (per FR Entry 11.1 §2.1 and §3.1):
   - Age 30, moderate, over_5_years → life_stage=accumulation, liquidity_tier=essential.
   - Age 50, moderate, 3_to_5_years → life_stage=transition, liquidity_tier=secondary.
   - Age 60, conservative, under_3_years → life_stage=distribution, liquidity_tier=deep.
   - Age 75, any, any → life_stage=legacy.

8. Edge cases produce classifications with `life_stage_confidence: low` rather than failing.

9. The success state after form submission shows the enriched investor profile inline, with badges for life_stage and liquidity_tier, plus a transition to the new investor's profile detail page.

10. Duplicate PAN entry triggers the warn-and-proceed dialog with the existing investor's name and creation date, and the option to view the existing investor or proceed creating a new record.

11. Creating a duplicate-PAN record (after acknowledgement) sets the `duplicate_pan_acknowledged` flag to true on the new record.

12. Household selector shows existing households the advisor has previously created, plus an option to create a new household by name.

13. The investor list at `/app/advisor/investors` shows the advisor's investors with all required columns; click-through to detail page works.

14. The investor detail page shows the full profile (entered fields plus enrichment signals).

15. The sidebar navigation item "Investors" is now active (no longer greyed) for the advisor role.

16. The API endpoint `POST /api/v2/investors` accepts canonical investor JSON, validates per the same rules as the form, creates the record, runs I0 enrichment, returns the created investor record. (No UI; tested via curl or API testing tool.)

17. T1 telemetry events fire correctly: `investor_created`, `investor_enrichment_completed`, plus `household_created` when a new household is created.

18. The form respects the firm-info branding (primary and accent colors apply to buttons, badges, accent rules).

### Out-of-Scope Notes

- The form is single-page; multi-step wizard is not implemented.
- Advisor cannot edit investors after creation in cluster 1; investor profile detail is read-only.
- Household relationships (spouse, parent, child) are not captured; just the household_id grouping.
- Address fields are not captured; not needed for cluster 1's downstream consumers.
- Bank account or custodian details are not captured; cluster 4 (model portfolio) or cluster 17 (custodian sync) handle these.

### Implementation Notes

- The Investor SQLAlchemy model corresponds field-for-field to FR Entry 10.7 §2.1.
- The I0 active layer is a pure Python module (no external dependencies); test cases per FR Entry 11.1 §9 are good fixture data.
- The form's three-section layout uses shadcn/ui components: Form, Input, Select, Card. The two-column grid within sections uses Tailwind grid utilities.
- Field validation: client-side uses Zod schemas (matched to the API's Pydantic schemas for consistency).
- Loading state during form submission: a centred spinner with "Creating investor and running enrichment..." text. Aim for sub-2-second total flow.
- Inline enriched profile display: appears in place of the form on success, with a "Continue to Investor List" or "Add Another Investor" call-to-action.
- Tooltip on life_stage and liquidity_tier badges: shows the description text from FR Entry 11.1 §2.3 and §3.3.

### Open Questions

The visual treatment of the duplicate-PAN warning dialog is design discretion. Implementation can iterate.

The exact wording of validation error messages can iterate based on demo feedback.

### Revision History

April 2026 (cluster 1 drafting pass): Initial chunk plan authored.

---

## Chunk 1.2: C0 Conversational Onboarding with Bounded LLM Scope

### Header

- **Chunk ID:** 1.2
- **Title:** C0 Conversational Onboarding with Bounded LLM Scope
- **Status:** Planned (drafting complete; ready for implementation)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 1 ideation log §5)
  - Drafting completed: April 2026

### Purpose

Chunk 1.2 ships the C0 conversational onboarding path. The advisor types natural-language messages, C0 detects investor_onboarding intent via LLM, drives a state machine through field collection with LLM-powered slot extraction, and produces the same canonical investor record as the form path with I0 enrichment.

This is the demonstrably-conversational path. Demo audiences see actual LLM-powered natural-language understanding (intent detection, slot extraction from free-text), but the conversation is bounded enough not to go off-rails.

### Dependencies

**Foundation reference:**
- FR Entry 14.0 (C0 Conversational Orchestrator)
- FR Entry 16.0 (SmartLLMRouter; chunk 1.3 must be shipped first or in parallel)

**Other chunks:**
- Chunk 1.1 (provides investor creation service, I0 enrichment, canonical schema)
- Chunk 1.3 (provides LLM provider configuration; required before C0 can make LLM calls)

### Scope: In

- `c0_conversations` and `c0_messages` tables in the database; Alembic migration.
- C0 backend service:
  - Intent detector module (calls LLM via SmartLLMRouter with templated prompt; returns intent classification).
  - Slot extractor module (calls LLM via SmartLLMRouter with templated prompt; returns extracted field values).
  - Conversation state machine for investor_onboarding intent (per FR Entry 14.0 §2.4).
  - Action executor (invokes the same investor creation service that chunk 1.1 uses).
  - Conversation persistence (writes to c0_conversations and c0_messages on each turn).
  - Abandonment detection (background job marks conversations abandoned after 4 hours of inactivity).
- C0 API endpoints:
  - `POST /api/v2/conversations` (start a new conversation).
  - `POST /api/v2/conversations/{conversation_id}/messages` (send a message; receive C0's response).
  - `GET /api/v2/conversations/{conversation_id}` (fetch full conversation history).
  - `GET /api/v2/conversations` (list user's conversations).
- C0 chat UI at `/app/<role>/conversational`:
  - Standard chat layout: thread on top, input box at bottom.
  - Send button + Enter-to-send.
  - "C0 is thinking..." typing indicator during LLM calls.
  - Past conversations sidebar (collapsible).
  - Rich content cards for confirmation summary and success state.
- C0 skill.md file containing the intent detection and slot extraction prompt templates.
- Failure handling per FR Entry 14.0 §5: LLM unavailable falls back to template-driven mode; malformed LLM output triggers re-prompts; invalid user input triggers validation error prompts.
- T1 telemetry events: `c0_conversation_started`, `c0_intent_detected`, `c0_slot_extracted`, `c0_state_transitioned`, `c0_conversation_completed`, `c0_conversation_abandoned`, `c0_llm_failure`.
- Sidebar navigation item "Conversational" lights up for advisor role.

### Scope: Out

- Other intents (case_opening, alert_response, briefing_request, general_question). Cluster 1 only ships investor_onboarding intent. Other intents return a "not yet implemented" template response.
- Voice input. Deferred.
- Edit-after-completion (user changing fields after the investor was created). Deferred.
- Cross-conversation context (C0 remembering prior conversations to inform current). Deferred.
- Multi-turn intent disambiguation (user is unclear and C0 asks clarifying questions). Cluster 1 takes the LLM's first intent classification.
- LLM provider configuration UI (chunk 1.3 ships this).

### Acceptance Criteria

1. The c0_conversations and c0_messages tables are created in the database; Alembic migration runs cleanly.

2. The C0 chat UI at `/app/<role>/conversational` renders correctly with thread, input, send button, sidebar.

3. The advisor can type "I want to onboard a new client" and C0 correctly classifies the intent as `investor_onboarding`.

4. C0 starts the state machine and prompts the advisor for the next missing field.

5. The advisor can respond with free-text (e.g., "His name is Rajesh Kumar and he's 41 years old"); C0 extracts name and age via LLM and proceeds.

6. The conversation collects all required fields through templated state-machine prompts.

7. The confirmation summary is displayed as a rich content card with all collected fields, plus Confirm and Edit buttons.

8. On confirmation, the investor record is created via the same service chunk 1.1 uses, I0 enrichment runs, and the success card with enriched profile is rendered in the chat.

9. Conversation persistence works: navigating away and returning shows the conversation in progress.

10. Abandonment detection: after 4 hours of inactivity, the conversation is marked abandoned and no longer appears as active.

11. LLM provider unavailable triggers template-fallback mode; the conversation continues without LLM-powered understanding, asking single-field questions.

12. Malformed LLM output triggers a re-prompt for the failing field with a hint.

13. Invalid user input (bad PAN, out-of-range age) triggers validation error prompts; already-collected slots are preserved.

14. The "C0 is thinking..." indicator shows during LLM calls.

15. Past conversations sidebar shows the user's recent conversations with intent, status, and timestamp.

16. Tapping a past completed conversation shows its full history (read-only).

17. T1 telemetry events fire correctly for all conversation lifecycle events.

18. The C0 skill.md file contains the prompt templates and is loaded at runtime; modifying skill.md and restarting the application picks up the new prompts.

19. The investor created via C0 is identical to the form-created investor in schema and enrichment.

20. Sidebar navigation item "Conversational" is active for advisor role.

### Out-of-Scope Notes

- C0 in cluster 1 only handles investor_onboarding intent. Other intents return placeholder responses.
- Voice and rich media (images, voice notes) are not supported.
- C0 cannot currently look up existing investors by name during a conversation; if the advisor refers to an existing investor, C0 doesn't recognise the reference.

### Implementation Notes

- The conversation state machine is a finite state machine in pure Python; no LLM dependency for state transitions.
- The LLM client uses the SmartLLMRouter (per FR Entry 16.0); intent detection and slot extraction call go through the router with caller_id="c0_intent_detector" and "c0_slot_extractor" respectively.
- The chat UI uses shadcn/ui components: Card for messages, Input for the text box, ScrollArea for the thread.
- Past conversations sidebar uses TanStack Query for the conversation list with periodic refresh.
- Rich content cards (confirmation, success, error) reuse the same components as chunk 1.1's inline display.
- Conversation persistence writes happen on each user message and each system message; the database becomes the source of truth for conversation history.

### Open Questions

The exact tone and personality of C0's prompts is design discretion. Implementation can iterate.

The threshold for "low extraction confidence" triggering a re-prompt is open. Working answer: any extraction with explicit `extraction_confidence: low` from the LLM, plus any extraction that fails server-side validation.

### Revision History

April 2026 (cluster 1 drafting pass): Initial chunk plan authored.

---

## Chunk 1.3: SmartLLMRouter Settings UI with API Key Configuration

### Header

- **Chunk ID:** 1.3
- **Title:** SmartLLMRouter Settings UI with API Key Configuration
- **Status:** Shipped (May 2026)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 1 ideation log §6)
  - Drafting completed: April 2026
  - Implementation started: May 2026
  - Shipped: May 2026

**Chunk-shipped retrospective notes** (full retrospective at cluster 1 close):

1. **Fernet over hand-rolled AES-256-GCM.** The chunk-plan implementation
   notes leave the choice open ("Fernet is simpler and adequate for cluster
   1"). Cluster 1 went with Fernet — the cryptography library ships it
   pre-built; HMAC + IV management is solved; round-trip test fits in
   ~30 lines. Production-readiness migration to AEAD with associated data
   (firm_id, config_id) is straightforward via a versioned ciphertext
   envelope when needed.

2. **Singleton config row.** The FR §4.1 schema is "effectively a singleton
   row per deployment, but versioned for audit." Cluster 1 ships the
   singleton: ``config_id="singleton"`` is a hardcoded constant. The
   column-level PK is a string, so a future cluster can move to
   per-write ULIDs without a schema migration. T1 already captures the
   change history; the column-level versioning is duplication today.

3. **Encryption-key persistence in DEV.** With ``SAMRIDDHI_ENCRYPTION_KEY``
   unset, the encryption helper generates a per-process random key —
   ciphertext written under it is unreadable after backend restart. This
   is documented behaviour (FR §4.1) but trips up demo flows that survive
   restarts. Demo prep step: generate a Fernet key once with
   ``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``
   and pin it in ``.env`` so the same demo data persists across restarts.

4. **TanStack Router relative paths (again).** Carrying the chunk 1.1
   retrospective note forward: nested-route children's ``Link to=`` props
   are scoped to the current parent. ``LLMConfigBanner`` lives under the
   CIO tree (it returns ``null`` for other roles), so its link to the
   settings page must be ``to="/settings/llm-router"`` (relative), not
   ``to="/cio/settings/llm-router"`` (absolute). TS type-checks this at
   build time. The Sidebar config exception: ``href`` is a typed-string
   variable, so TS doesn't narrow it; absolute paths work there.

5. **TestClient lifespan + fresh-per-request DB sessions.** Two test
   patterns from this chunk worth carrying forward:
   - Always use ``with TestClient(app) as client:`` so the FastAPI
     lifespan handler runs and ``Base.metadata.create_all`` populates the
     SQLite schema. Bare ``TestClient(app)`` skips lifespan and SELECTs
     hit "no such table".
   - Multi-write test fixtures need an ``async_sessionmaker`` factory in
     the dependency override (``async with factory() as session: yield``)
     so each request gets a fresh session — exactly mirroring production's
     ``get_session``. A shared session across requests trips
     "transaction is already begun" once the second write hits
     ``async with db.begin():``.

6. **Permission scope.** ``system:llm_config:read`` and
   ``system:llm_config:write`` are CIO-only. Compliance + Audit have
   firm-wide read on investors/households (chunk 1.1) but NOT on the LLM
   config — by design. The audit trail flows through T1 (where they
   already see ``llm_provider_configuration_changed``,
   ``llm_kill_switch_*``, ``llm_call_*`` events firm-wide), which is the
   accountability surface that matters; reading the masked config + API
   keys is operational, not auditable.

### Purpose

Chunk 1.3 ships the SmartLLMRouter settings UI: a CIO-only page for configuring the platform's active LLM provider and API keys. This is the first time the LLM provider toggle becomes a real product surface, and it must land before C0 (chunk 1.2) can make any LLM calls.

The chunk also ships the underlying SmartLLMRouter backend per FR Entry 16.0: provider adapters for Mistral and Claude, configuration storage, the test-connection mechanism, the rate limiter, the kill switch, telemetry.

### Dependencies

**Foundation reference:**
- FR Entry 16.0 (SmartLLMRouter Overview)

**Other chunks:**
- Cluster 0 chunks (auth, app shell, role routing).

### Scope: In

- `llm_provider_config` table in the database with the schema from FR Entry 16.0 §4.1; Alembic migration.
- Encryption infrastructure: AES-256-GCM encryption for API keys with deployment-level encryption key in environment configuration.
- Provider adapter implementations:
  - Mistral adapter: HTTP client, prompt translation, response parsing, error handling.
  - Claude adapter: HTTP client (Anthropic Messages API), prompt translation, response parsing, error handling.
- Router runtime: provider selection logic, call executor with retry and timeout, rate limiter (token bucket per provider).
- Kill switch implementation: a flag in `llm_provider_config` plus runtime check on every LLM call.
- API endpoints:
  - `GET /api/v2/llm/config` (CIO-only; returns active provider, masked API keys, rate limit settings, kill switch status).
  - `PUT /api/v2/llm/config` (CIO-only; updates configuration; validates API keys are present for the selected provider).
  - `POST /api/v2/llm/test-connection` (CIO-only; makes a test call to the selected provider; returns success or error).
  - `POST /api/v2/llm/kill-switch/activate` and `POST /api/v2/llm/kill-switch/deactivate` (CIO-only; activates or deactivates kill switch).
- Settings UI at `/app/cio/settings/llm-router`:
  - Provider selection: radio buttons for Mistral and Claude.
  - API key entry: masked text inputs with show/hide toggle for both providers.
  - Test Connection button: makes the test call; shows green check or red error inline.
  - Status display: current provider, last successful call timestamp, last error.
  - Save button: persists changes; shows confirmation toast.
  - Kill switch section: visible toggle with confirmation dialog on activation.
- First-run banner on CIO home tree: visible until LLM provider is configured; links to the settings page.
- T1 telemetry events: `llm_call_initiated`, `llm_call_completed`, `llm_call_failed`, `llm_provider_configuration_changed`, `kill_switch_activated`, `kill_switch_deactivated`.

### Scope: Out

- Per-agent LLM tiering. Cluster 1 has platform-level provider only. Per-agent tiering is v2.
- Multi-provider failover. Cluster 1 has single active provider. Failover is v2.
- Cost monitoring and budget alerts. Cluster 1 captures token counts in T1 but does not aggregate or alert.
- Prompt caching. Deferred.
- Self-hosted LLM provider option. Deferred.
- LLM call logs viewer in the UI. T1 captures the events but cluster 1 does not surface them in a UI.

### Acceptance Criteria

1. The `llm_provider_config` table is created with the correct schema; Alembic migration runs cleanly.

2. The settings UI at `/app/cio/settings/llm-router` renders correctly and is accessible only to CIO role (advisor and other roles see HTTP 403 or are redirected to their home tree).

3. The CIO can select Mistral or Claude as the active provider via radio buttons.

4. API key entry fields are masked by default with show/hide toggle.

5. Saving a configuration without an API key for the selected provider shows a validation error.

6. The "Test Connection" button makes a test call to the selected provider with the entered API key:
   - Valid key: shows green check with "Connection successful" inline.
   - Invalid key: shows red error with the specific failure reason (e.g., "Authentication failed").
   - Network failure: shows red error with "Provider unreachable" message.

7. Saving the configuration persists it to the database with the API keys encrypted at rest.

8. Subsequent LLM calls (e.g., from C0 in chunk 1.2) successfully route to the configured provider.

9. Switching providers (e.g., from Mistral to Claude with both API keys configured) takes effect immediately for subsequent calls.

10. The kill switch can be activated; activation halts all LLM calls (C0 falls back to template mode).

11. The kill switch can be deactivated; deactivation resumes LLM calls.

12. First-run banner shows on CIO home tree when no provider is configured; banner disappears after configuration.

13. Rate limiting prevents bursts above 60 calls per minute (configurable but cluster 1 default).

14. Retries on retriable errors work as specified (3 attempts, exponential backoff).

15. Timeouts on slow provider responses (>30s) are enforced.

16. T1 telemetry events fire correctly for all LLM lifecycle events.

17. API keys never appear in logs in plaintext; encryption-at-rest is verified by inspecting the database file directly (the `&#42;_api_key_encrypted` columns are bytes, not strings).

18. Sidebar navigation item "Settings" is visible only to CIO role; clicking takes them to settings index with LLM Router as one option.

### Out-of-Scope Notes

- The settings page in cluster 1 only has the LLM Router section. Other settings sections (firm settings, user settings, etc.) come in later clusters.
- API keys are entered manually; bulk import or external secret manager integration is deferred.
- Audit log viewer for configuration changes is deferred (T1 captures the events; future clusters surface them).

### Implementation Notes

- Encryption: use the `cryptography` Python library's Fernet (AES-256-CBC with HMAC) or a custom AES-256-GCM implementation. Fernet is simpler and adequate for cluster 1.
- The deployment-level encryption key is read from `SAMRIDDHI_ENCRYPTION_KEY` environment variable. If not set, application startup fails with a clear error.
- Mistral adapter uses `httpx` for HTTP calls; same for Claude adapter.
- The "Test Connection" call uses a minimal prompt ("Reply with the word 'OK'") with low max_tokens to keep cost negligible.
- The settings UI uses shadcn/ui's Form, RadioGroup, Input components. The kill switch is a Switch component with a confirmation Dialog.
- The first-run banner is a top-of-page Alert component with a link to the settings page; controlled by a simple "is LLM configured" check on the CIO's home tree.

### Open Questions

Whether to allow configuration of both API keys simultaneously (so the CIO can switch providers without re-entering keys) is open. Working answer: yes; both keys can be stored, only the active provider's key is used. Storing both makes provider switching frictionless.

Whether the rate limit should be exposed in the settings UI for tuning is open. Working answer: not in cluster 1; hardcoded default with configuration via environment variable for now.

### Revision History

April 2026 (cluster 1 drafting pass): Initial chunk plan authored.

May 2026 (chunk shipped): Status flipped to "Shipped". Retrospective
notes captured at top of chunk header. All 18 chunk-1.3 acceptance
criteria verified end-to-end: provider config CRUD + masked reads,
test-connection flow, kill switch activate/deactivate with T1 audit,
first-run banner on CIO home tree, sidebar Settings item lit up,
permission gating (CIO only) verified for advisor / compliance / audit.
Backend tests: 69 new passing (encryption: 13, providers: 19,
router_runtime: 12, endpoints: 24, permissions: 1 new). Frontend build
clean (483 KB JS / 148 KB gzipped). Alembic migration chain runs cleanly
end-to-end (cluster 0 → 1.1 → 1.3).

---

## Cluster 1 Closing Notes

When chunks 1.1, 1.2, and 1.3 all ship, cluster 1 is complete. The advisor can onboard investors through two visible paths plus a stub API. The system enriches each investor with I0 active layer signals. The CIO has configured the LLM provider that powers the conversational path.

The retrospective from cluster 1 should answer:
- Did the canonical investor schema feel right? Should any fields have been included or excluded?
- Did the I0 enrichment heuristics produce reasonable classifications? Edge cases that need refinement?
- Did the C0 conversational path feel natural to demo audiences? Where did it break?
- Did the settings UI cover the operational surface adequately, or were there configuration needs missed?

Updates flow back into the foundation reference entries (10.7, 11.0, 11.1, 14.0, 16.0) and into this chunk plan's revision history.

Cluster 2 (Mandate Management) opens after cluster 1 ships. Cluster 2 builds on the Investor entity to attach investment policy statements, capture mandate constraints, and run amendment workflows.

---

**End of Cluster 1 Chunk Plan.**
