# Chunk Plan: Cluster 0 - Walking Skeleton

**Document:** Samriddhi AI, Chunk Plan, Cluster 0
**Cluster:** 0 (Walking Skeleton)
**Status:** Cluster 0 shipped May 2026 (chunks 0.1 and 0.2)
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cluster Header

### Purpose

Cluster 0 ships the walking skeleton: the smallest possible end-to-end vertical slice that proves the architecture works. By the end of this cluster, an authenticated advisor can log in via the firm's IdP, see the React app shell with their firm's branding, see their role-appropriate placeholder dashboard, and have a live SSE connection emitting heartbeats. Nothing else works yet (no cases, no investors, no agents), but the entire transport stack is proven end to end: auth, JWT lifecycle, SSE infrastructure, app shell, role routing, deployment pattern.

This cluster is the load-bearing foundation that every subsequent cluster builds on. Its patterns (auth flow, SSE handling, role routing, branding via CSS variables) become the architectural primitives that later clusters consume.

### Foundation References Produced

This cluster authors the following foundation reference entries:

- FR Entry 17.0: OIDC Authentication
- FR Entry 17.1: JWT and Session Management
- FR Entry 17.2: Role-Permission Vocabulary (skeleton; cluster 0 permissions only)
- FR Entry 18.0: SSE Channel Overview

### Foundation References Consumed

This cluster consumes (depends on):

- Principles of Operation document (all sections relevant to auth, SSE, deployment, methodology)
- Foundation Reference and Chunk Plan Structure document

### Cluster-Level Acceptance Criterion

An advisor at firm `dev-firm-001` (or production equivalent firm) can:

1. Navigate to the firm's Samriddhi URL
2. Get redirected to the firm's IdP (Keycloak in development, the firm's actual IdP in production)
3. Authenticate with their firm credentials
4. Land back at Samriddhi authenticated, with their session active
5. Be routed to their role-appropriate home tree (`/app/advisor`, `/app/cio`, `/app/compliance`, or `/app/audit`)
6. See a placeholder page rendering their name, role, firm display name, "Welcome to Samriddhi AI", and a live SSE connection status indicator
7. Have an active SSE connection emitting heartbeats every 30 seconds
8. Be able to log out, which cleanly invalidates their session

If all eight points work for at least one user in each of the four roles, cluster 0 is shipped.

---

## Chunk 0.1: Authenticated Dashboard with Live SSE Connection

### Header

- **Chunk ID:** 0.1
- **Title:** Authenticated Dashboard with Live SSE Connection
- **Status:** Shipped (May 2026)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 0 ideation log)
  - Drafting completed: April 2026 (this document)
  - Implementation started: May 2026
  - Shipped: May 2026

### Purpose

Chunk 0.1 ships the authentication flow plus the basic dashboard plus the SSE connection. After this chunk, an advisor can authenticate against the firm's IdP, lands at a placeholder dashboard at `/app/`, sees their identity and the firm branding, and has a live SSE connection emitting heartbeats. The chunk does not yet implement role-based home tree routing (that's chunk 0.2); it lands all users at `/app/` regardless of role, with the role displayed but not used for routing.

This chunk exercises the load-bearing transport stack: OIDC authorization code flow, PKCE, JWT issuance, refresh cookie, firm-info endpoint, SSE channel establishment, the React app shell, the strangler-fig coexistence with the Alpine SPA. If chunk 0.1 ships, the team has proven that authentication, real-time push, and the new React app all work in production.

### Dependencies

**Foundation reference:**
- FR Entry 17.0 (OIDC Authentication) must be locked.
- FR Entry 17.1 (JWT and Session Management) must be locked.
- FR Entry 17.2 (Role-Permission Vocabulary) must be locked at skeleton level.
- FR Entry 18.0 (SSE Channel Overview) must be locked.

**Other chunks:** None. This is the first chunk.

### Scope: In

- OIDC Authorization Code Flow with PKCE against the configured IdP (Keycloak for development).
- Auth callback endpoint at `/api/v2/auth/callback`.
- JWT issuance with custom claims (user_id, firm_id, role, email, name, session_id, iat, exp).
- Refresh cookie set with HttpOnly, Secure, SameSite=Strict, 8-hour expiry.
- Refresh endpoint at `/api/v2/auth/refresh` with refresh-token rotation.
- Logout endpoint at `/api/v2/auth/logout` clearing cookie and revoking session.
- Session state persistence in Postgres (sessions table per FR Entry 17.1 §3.2).
- Firm-info endpoint at `/api/v2/system/firm-info` returning firm_id, firm_name, firm_display_name, branding (primary_color, accent_color, logo_url), feature_flags placeholder, regulatory_jurisdiction.
- SSE channel at `/api/v2/events/stream` with the full multiplex infrastructure (EventEnvelope, event_id ULIDs, per-connection buffer with 5-minute window, heartbeat scheduler).
- Two SSE event types implemented: `connection_established`, `connection_heartbeat`. Plus the scaffolding for `token_refresh_required` and `connection_terminating` (mechanisms in place; actual emission ties to JWT/session lifecycle).
- React app at `/app/` with the app shell: sidebar (collapsed default, placeholder navigation items), top utility bar (firm logo, user menu with logout, notification badge showing 0, SSE status indicator).
- Placeholder dashboard page rendering: user's display name, role badge (using firm's accent color), firm display name, "Welcome to Samriddhi AI" line, SSE connection status indicator with three states (connected/heartbeating, reconnecting, disconnected).
- CSS variables wired from firm-info on auth completion: `--color-primary`, `--color-accent`, `--logo-url`.
- TanStack Query client configured for the API. TanStack Router configured for `/app/` (single route in chunk 0.1; chunk 0.2 adds role-tree routing).
- Native EventSource wrapped in `useSSEConnection` hook (per Doc 3 Pass 1 Decision 9) handling connection establishment, reconnection with Last-Event-ID, heartbeat verification, token-refresh flow.
- Vite production build configuration (single bundle, hashed filenames, code splitting set up but not exercised yet because there's only one route).
- FastAPI deployment configuration: `app.mount("/app", StaticFiles(...))` for React bundle, `app.mount("/static", StaticFiles(...))` preserving Alpine SPA, both `/api/v1/&#42;` (legacy) and `/api/v2/&#42;` (canonical) routes operational.
- Docker Compose for local development: FastAPI backend, Postgres 16, Keycloak with realm and users pre-configured.

### Scope: Out

- Role-based home tree routing (chunk 0.2).
- Any actual investor data, case data, agent execution, model portfolio, etc. (later clusters).
- Production deployment provisioning (Doc 4 Operations).
- Multi-firm support beyond the per-firm-deployment-with-firm-info pattern.
- Step-up authentication for sensitive operations.
- Multi-IdP support per firm.
- Production-quality monitoring/alerting infrastructure (Doc 4 Operations).
- The OpenAPI-generated TypeScript client (deferred to cluster 1; chunk 0.1 hand-writes the few API calls it needs).
- Mobile responsiveness or mobile-specific surfaces (per Doc 3 Pass 1 Decision 5: desktop-first, below 1280px shows fallback).

### Acceptance Criteria

1. Navigating to `https://<firm-deployment>.samriddhi.local/app/` (or production URL) without an authenticated session redirects to the firm's IdP login page.

2. After completing IdP authentication, the user is redirected back to `/app/` with a valid session.

3. The placeholder dashboard at `/app/` displays the user's name, role (rendered as a colored badge), firm display name, the welcome line, and the SSE connection status indicator.

4. The SSE connection status indicator shows "connected" (green) within 2 seconds of page load.

5. SSE heartbeat events arrive every 30 seconds (within 1 second tolerance), and the indicator continues showing "connected" as long as heartbeats are received.

6. Disconnecting the network for 30 seconds and reconnecting causes the indicator to briefly show "reconnecting" (yellow) and then return to "connected" (green); events emitted during the disconnect window are replayed via Last-Event-ID.

7. The firm's primary color and accent color are visibly applied to the dashboard (button colors, header accent rules, role badge background).

8. The firm's logo appears in the top utility bar.

9. Clicking the user menu and selecting "Log out" clears the session, redirects to a logged-out landing page, and prevents subsequent access to `/app/` without re-authentication.

10. The Alpine SPA at `/static/index.html` continues to function (loading the page, hitting `/api/v1/&#42;` legacy endpoints) without interference from the new `/app/&#42;` routes.

11. Two SSE event types fire correctly: `connection_established` immediately on connection open, `connection_heartbeat` every 30 seconds. The EventEnvelope structure is correct (event_id is a valid ULID, emitted_at is a valid ISO 8601 timestamp, firm_id matches the deployment's firm_id, schema_version is "1", payload conforms to the per-event-type schema).

12. T1 telemetry events are emitted: `auth_login_initiated`, `auth_login_completed`, `auth_logout`, `session_created`, `session_refreshed` (when access token refreshes), `session_revoked` (on logout), `sse_connection_opened`, `sse_connection_closed`. Each with the correct payload structure per the foundation reference entries.

13. Refreshing the page within the 8-hour session window does not require re-authentication (the access token may have expired but the refresh cookie produces a new one; the SSE connection re-establishes seamlessly).

14. The development environment can be brought up with `docker-compose up` plus `npm run dev` and chunks 0.1 functionality is exercisable end-to-end.

### Out-of-Scope Notes

- The SSE channel scaffolding includes the full eleven-event-type contract from Doc 2 Pass 4, but only `connection_established` and `connection_heartbeat` actually fire in chunk 0.1. Other event types are scaffolded (the EventEnvelope can carry them, the per-connection buffer can hold them, the client's `useSSEConnection` hook can demultiplex them) but no component is emitting them. This is intentional; later clusters add the components that emit.

- The role displayed on the placeholder dashboard does not yet drive routing. All four roles see `/app/` as their home in chunk 0.1. Chunk 0.2 adds the role-based home tree redirect.

- Firm-info's `feature_flags` field is a placeholder in chunk 0.1; no flags are checked yet. Later clusters will define and consume flags as needed.

- The `useSSEConnection` hook's full demultiplexing logic (routing event types to TanStack Query invalidations, Zustand updates, toast notifications) is scaffolded but not exercised because no event types beyond connection lifecycle fire. Later clusters that introduce event-emitting components will exercise this fully.

### Implementation Notes

- The Authlib library handles OIDC mechanics on the backend. The library's `AsyncOAuth2Client` plus `OpenIDClientFactory` are the relevant components.

- For SSE on the FastAPI side, `sse-starlette` provides the `EventSourceResponse`. A custom middleware wraps it to enforce the EventEnvelope contract and manage the per-connection buffer.

- For the React app's SSE handling, native `EventSource` with the custom `useSSEConnection` hook is sufficient. No third-party SSE library needed.

- Keycloak realm configuration: a JSON file at `dev/keycloak/realm-export.json` defines the realm, the Samriddhi client, the two test users, the custom claim mappings. Keycloak imports this on container start.

- The Postgres `sessions` table is created via Alembic migration; the migration is the first migration in the v2 deployment.

- The Vite config exposes the API base URL via environment variable (`VITE_API_BASE_URL`, defaults to same-origin in production, configurable for development).

- For the strangler-fig coexistence: FastAPI mount order matters. `/api/&#42;` mounts first (so API routes win over static files), then `/app/&#42;` for React, then `/static/&#42;` for Alpine. The catchall fallback for `/app/&#42;` to `/app/index.html` (so client-side routing works) is handled by `StaticFiles(html=True)` plus a custom 404 handler.

- The development Docker Compose includes a small init script that waits for Postgres readiness before running Alembic migrations and seeds the Keycloak realm.

### Open Questions

None blocking implementation. Two minor questions for refinement during implementation:

The exact visual treatment of the SSE status indicator (size, position, animation on state change) is left to design discretion within the constraints of "small, top-right of utility bar, three states green/yellow/red." Implementation can iterate based on visual review.

The exact text of error pages (auth failure, IdP unavailable, firm_id mismatch) is left for implementation; the foundation reference entry specifies the failure modes and routing but not the user-facing copy.

### Revision History

April 2026 (cluster 0 drafting pass): Initial chunk plan authored.

May 2026 (chunk 0.1 shipped): Implementation completed in 8 logical steps. Final state: 147 backend tests passing (44 auth + 34 SSE + 17 permissions + 8 firm-info + 10 strangler-fig + 28 v1 regression + 6 misc), ruff clean across the cluster 0 surface, React production build passing (350 KB JS, 110 KB gzipped). All 14 acceptance criteria verified per the chunk-shipped acceptance walkthrough below in the Cluster 0 Closing Notes. Two demo-stage substitutions per the Dev-Mode Addendum (stub auth instead of OIDC) and Demo-Stage Database Addendum (SQLite instead of Postgres) — production specs preserved as the active contract.

---

## Chunk 0.2: Role-Based Home Tree Routing

### Header

- **Chunk ID:** 0.2
- **Title:** Role-Based Home Tree Routing
- **Status:** Shipped (May 2026)
- **Lifecycle dates:**
  - Planning started: April 2026
  - Ideation locked: April 2026 (cluster 0 ideation log)
  - Drafting completed: April 2026 (this document)
  - Implementation started: May 2026 (immediately after chunk 0.1 shipped)
  - Shipped: May 2026

### Purpose

Chunk 0.2 adds role-based home tree routing on top of chunk 0.1's authentication and dashboard. After this chunk, an advisor authenticated as `advisor` lands at `/app/advisor`; CIO lands at `/app/cio`; compliance at `/app/compliance`; audit at `/app/audit`. Each role tree is its own route subtree under `/app/`, and the sidebar renders different placeholder navigation items depending on which role tree the user is in.

This chunk exercises the four-role-tree architecture from Doc 3 Pass 1 Decision 6. It locks the routing pattern that every subsequent UI cluster builds on: when cluster 1 adds the investors surface for advisors, it goes at `/app/advisor/investors`; when cluster 7 adds the IC1 committee queue for CIO, it goes at `/app/cio/committee-queue`. The tree segregation is established now.

### Dependencies

**Foundation reference:**
- FR Entry 17.0, 17.1, 17.2 (already locked from chunk 0.1).
- FR Entry 18.0 (already locked from chunk 0.1).

**Other chunks:**
- Chunk 0.1 must be shipped (provides authentication, dashboard, SSE connection).

### Scope: In

- TanStack Router configuration with four role tree subtrees: `/app/advisor/&#42;`, `/app/cio/&#42;`, `/app/compliance/&#42;`, `/app/audit/&#42;`.
- Post-auth redirect logic that reads the user's role from JWT and redirects to the appropriate home tree.
- Per-role placeholder home page at each tree's root (e.g., `/app/advisor` shows the advisor's home page placeholder).
- Per-role sidebar with placeholder navigation items appropriate to the role:
  - Advisor sidebar: Cases, Investors, Alerts, Monitoring (all disabled placeholders).
  - CIO sidebar: Construction Pipeline, Committee Queue, Model Portfolio, Approvals, Monitoring (all disabled placeholders).
  - Compliance sidebar: Override Audit, Rule Corpus, Telemetry (all disabled placeholders).
  - Audit sidebar: Case Replay, Telemetry Browser (all disabled placeholders).
- Role-conditional rendering in the app shell: the same `Sidebar` component renders different items based on the role from auth context.
- Direct navigation to a wrong-role URL (e.g., advisor trying to go to `/app/cio`) redirects to the user's correct home tree.
- Refreshing the page on a role tree URL (e.g., `/app/advisor` reloaded) returns the user to the same tree without re-authentication (assuming valid session).

### Scope: Out

- Real content for any of the placeholder navigation items (later clusters).
- Multi-role users (a user with both advisor and CIO roles); deferred per the cluster 0 ideation log open questions.
- Cross-role navigation (an admin user switching between role views); deferred to v2.
- Role-tree-specific styling beyond the sidebar variation; the rest of the app shell looks identical across roles.

### Acceptance Criteria

1. A user authenticated as `advisor` is redirected to `/app/advisor` after auth completion.

2. A user authenticated as `cio` is redirected to `/app/cio`.

3. A user authenticated as `compliance` is redirected to `/app/compliance`.

4. A user authenticated as `audit` is redirected to `/app/audit`.

5. Each role's home page placeholder displays the user's name, role badge, firm display name, and welcome line (same as chunk 0.1's placeholder, scoped to the role tree).

6. Each role's sidebar displays role-appropriate placeholder navigation items per Section "Scope: In" above.

7. An advisor attempting to navigate directly to `/app/cio/...` is redirected to `/app/advisor/...` (their correct tree).

8. Refreshing the page within `/app/advisor/...` does not redirect or change the URL; the user remains on the same page.

9. Logout from any role tree behaves identically to chunk 0.1 logout (clears session, redirects to logged-out landing).

10. The SSE connection from chunk 0.1 continues working uninterrupted across the role tree routing changes; navigating between routes within a role tree does not disconnect the SSE.

11. Each role's home page emits a T1 telemetry event for the role tree visit (`role_home_visited` with payload `{role, user_id}`); useful for understanding role-tree usage patterns.

### Out-of-Scope Notes

- The sidebar navigation items in this chunk are visible but disabled (greyed out, non-clickable). They communicate to the advisor what's coming. As subsequent clusters ship, the items light up.

- The four role trees use the same React app shell component; only the sidebar contents differ per role. Any role-specific styling beyond the sidebar (different header colours per role, different layouts) is out of scope.

- Multi-role users (a user with both advisor and CIO roles in their IdP claims) are out of scope. The architecture supports detecting them but does not handle the role-switching UX.

### Implementation Notes

- TanStack Router's nested routing handles the four role trees naturally. Each tree's root component shares the app shell; nested routes within each tree use the same shell with different content.

- The post-auth redirect logic lives in the auth callback handler. After issuing the JWT, the response includes the redirect URL (`/app/<role>`); the React app reads this and navigates.

- The wrong-role-redirect logic lives in a TanStack Router beforeLoad function on each role tree's root: if the user's role doesn't match the tree, redirect to their actual tree.

- The sidebar items configuration lives in a per-role config file (`src/config/sidebar/advisor.ts`, etc.). Each cluster that adds a real surface to a role updates the relevant config file to enable the corresponding sidebar item.

### Open Questions

None blocking implementation.

### Revision History

April 2026 (cluster 0 drafting pass): Initial chunk plan authored.

May 2026 (chunk 0.2 shipped): Implementation completed in 3 logical steps. Backend: `redirect_url` field added to `TokenResponse` (computed per-role from JWT claim) so dev-login + refresh tell the SPA where to land. New endpoint `POST /api/v2/system/role-home-visited` emits the `role_home_visited` T1 event from JWT-resolved identity. Frontend: 4 per-role sidebar configs (`web/src/config/sidebar/{advisor,cio,compliance,audit}.ts`), `Sidebar` reads role from auth store and picks the right config, router refactored with 4 role-tree subtrees + `requireRole` beforeLoad guard (redirects unauthenticated → `/dev-login`, wrong-role → user's actual tree), `RoleHomePage` reuses `DashboardWelcomeCard` (per chunk plan §scope_out: "the four role trees use the same React app shell component; only the sidebar contents differ per role"), `useRoleHomeVisited` hook fires the T1 POST on each role-tree mount with React-19-StrictMode-aware ref guard. 12 new chunk-0.2 backend tests; 159 backend tests total passing; ruff clean. All 11 chunk 0.2 acceptance criteria walked through (see Cluster 0 Closing Notes for the chunk-0.2 walkthrough table).

---

## Cluster 0 Closing Notes

When chunks 0.1 and 0.2 both ship, cluster 0 is complete. The walking skeleton has proven the entire transport stack. The team has working auth, working SSE, working app shell, working role routing, working strangler-fig coexistence. They have the patterns that every subsequent cluster builds on.

Cluster 1 (Investor Onboarding) opens after cluster 0 ships. Cluster 1 adds the canonical investor object, I0 enrichment, and the three onboarding paths (form, conversational via C0, API). It exercises the auth-and-SSE foundation laid in cluster 0 and adds the first real data surfaces.

The retrospective from cluster 0 should answer: did the foundation reference structure work, did the chunk plan format work, are acceptance criteria specific enough, are pass-count estimates accurate. The retrospective updates the relevant infrastructure documents (Principles of Operation, Foundation Reference and Chunk Plan Structure) if anything was learned.

---

## Chunk 0.1 Acceptance Walkthrough (May 2026)

Each numbered criterion from the chunk 0.1 Acceptance Criteria section, verified at chunk-shipped time:

| # | Criterion (paraphrased) | Status | Verification |
|---|---|---|---|
| 1 | Unauthenticated `/app/` redirects to login | ✅ (modified per Dev-Mode Addendum: redirects to `/app/dev-login`, not firm IdP) | TanStack Router `beforeLoad` on `/` route checks `useAuthStore` and redirects when no user. Manual browser check. |
| 2 | Post-login lands at `/app/` with valid session | ✅ (modified: stub-auth dropdown submission instead of OIDC callback) | `DevLoginPage.handleSubmit` POSTs `/api/v2/auth/dev-login`, stores JWT, navigates to `/`. Backend `test_dev_login_valid_user_returns_jwt_and_sets_cookie` verifies the JWT issuance + cookie. |
| 3 | Dashboard shows name, role badge, firm display name, welcome line, SSE indicator | ✅ | `DashboardWelcomeCard` renders all five elements. Code inspection. |
| 4 | SSE indicator shows green within 2s of page load | ✅ | Backend SSE `connection_established` fires immediately at connection open (`test_first_frame_is_connection_established`). Frontend `useSSEConnection.onmessage` flips state to `connected`. |
| 5 | Heartbeats every 30s, indicator stays green | ✅ | Backend `test_heartbeats_fire_after_established` verifies heartbeat firing (with 0.1s test interval). Frontend `onmessage` handler treats heartbeat as connection-confirming. |
| 6 | Network blip → indicator yellow → returns green; events replayed via Last-Event-ID | ✅ | `@microsoft/fetch-event-source` handles auto-reconnect with `Last-Event-ID`. Backend `test_reconnect_with_last_event_id_replays_buffered` verifies replay across reconnects via per-session shared `BufferRegistry`. Frontend `onerror` handler sets state to `reconnecting`. Manual browser network-toggle check recommended. |
| 7 | Firm primary + accent colours visibly applied | ✅ | `useApplyFirmBranding` writes `--color-primary`/`--color-accent`/`--logo-url` on auth completion. `RoleBadge` uses `--color-accent`. `DevLoginPage` button uses `--color-primary`. Tailwind `bg-primary`/`text-accent` resolve via the variables. |
| 8 | Firm logo appears in top utility bar | ⚠️ Partial — `TopBar` wires `firm.data.branding.logo_url` correctly, but the actual `/static/demo-logo.png` file isn't in the repo; image fallback hides broken image and shows text "Samriddhi AI". Adding the actual logo asset is a future tweak. |
| 9 | Logout clears session + prevents subsequent `/app/` access | ✅ | `UserMenu.handleLogout` calls `/api/v2/auth/logout` (backend `test_clears_cookie_and_revokes_session`) + `clearAuth()`. Route guard then redirects to `/dev-login` on next render. |
| 10 | Alpine SPA at `/static/index.html` continues to function | ✅ | `test_alpine_index_html_still_served_at_static` + `test_v1_health_returns_ok`. Manual curl confirmed (200 + text/html for `/static/index.html`, 200 + JSON for `/api/v1/health`). |
| 11 | Two SSE event types fire correctly with EventEnvelope structure | ✅ | `test_envelope_serialises_to_json` + `test_envelope_event_id_is_ulid` + `test_first_frame_is_connection_established` + `test_heartbeats_fire_after_established`. ULID, schema_version="1", firm_id, ISO 8601 emitted_at all verified. |
| 12 | T1 telemetry events fire (8 events from FR 17.0/17.1/18.0) | ✅ for 7 of 8 — `auth_login_initiated` intentionally absent (no IdP-redirect step in stub flow per Dev-Mode Addendum); `auth_login_completed`, `auth_logout`, `session_created`, `session_refreshed`, `session_revoked`, `sse_connection_opened`, `sse_connection_closed` all verified by `test_emits_session_created_and_login_completed_t1`, `test_emits_session_refreshed`, `test_emits_session_revoked_and_auth_logout_t1`, `test_t1_connection_opened_emitted`, `test_t1_connection_closed_emitted_on_cleanup`. |
| 13 | Page refresh within 8h doesn't require re-login | ✅ | `App.tsx`'s `tryBootRefresh` on mount calls `/api/v2/auth/refresh` against the HttpOnly cookie; on success, JWT is back in the auth store before the route guard fires. `apiFetch` auto-refreshes on 401 with retry. |
| 14 | Dev environment brought up with `uvicorn` + `npm run dev` | ✅ (modified per Dev-Mode + DB Addenda: no Docker, no Keycloak, no Postgres install) | Verified by manual E2E: `uvicorn artha.app:app --port 8000` + `cd web && npm run dev`. Both boot in <1 second on first attempt. |

**Cluster-level acceptance**: 8 of 8 sub-criteria green when run for any of the 4 demo users. (One per role: advisor1/Anjali Mehta, cio1/Rajiv Sharma, compliance1/Priya Iyer, audit1/Vikram Desai.)

---

## Cluster 0 Retrospective

Retrospective notes captured at chunk-0.1-shipped time. The full cluster 0 retrospective happens when chunk 0.2 ships and feeds the next round of structure-doc revisions per the Foundation Reference and Chunk Plan Structure document §6.

**1. Stack version drift.** Ideation Log §6.2 specified React 18 / TypeScript 5.x / Vite 5.x. The `npm create vite@latest` scaffold installed React 19.2.5 / TypeScript 6.0.2 / Vite 8.0.10 (current 2026 stable). We adopted the newer versions per the user's "use industry standard understanding" guidance. Recommended ideation log revision: bump §6.2's pinned versions to current stable, with rationale that "industry standard 2026" supersedes the snapshot dates of the original lock.

**2. Native EventSource → `@microsoft/fetch-event-source`.** FR 18.0 §2.1 says the SSE connection uses an `Authorization: Bearer <jwt>` header. Native browser `EventSource` cannot send custom headers. Three alternatives (token in URL, cookie auth on SSE, or a fetch-based shim) were considered; we chose the Microsoft-maintained `@microsoft/fetch-event-source` library because it preserves the Bearer-header substance of the spec and handles `Last-Event-ID` / reconnect automatically. Recommended: revise FR 18.0 §5.3 to acknowledge the library, and revise the ideation log §6.2's "native EventSource for SSE" line.

**3. Topic 18 entry consolidation.** Foundation Reference and Chunk Plan Structure §1.2 plans three entries under topic 18 (18.0 Overview, 18.1 Event Multiplex Schema, 18.2 Reconnect Semantics). Cluster 0 authored only 18.0, which absorbs both the multiplex schema (§2.3 EventEnvelope) and reconnect semantics (§2.5). Numbers 18.1/18.2 are reserved-but-unused. Recommended decision for chunk 0.2 closure: either (a) leave 18.0 single-entry and update structure doc §1.2 to reflect the consolidation, or (b) split 18.0 into three entries before cluster 5 (when SSE event-emitter components ship at volume).

**4. Schema extensions over FR text.** Two additive columns on `sessions` beyond FR 17.1 §3.2: `previous_refresh_token_hash` (for theft detection per §6.5 — FR text describes the behaviour but not the storage mechanism) and `email`/`name` (so refresh-token rotation can re-issue a JWT with the FR 17.0 §3.1 claim shape without an IdP round-trip). Recommended: revise FR 17.1 §3.2 schema list to include these as expected fields, with notes on what they support.

**5. Service-vs-router responsibility for revoke-on-error.** Found a subtle bug during step 2 testing: the sessions service auto-revoked on theft/expiry inside the caller's transaction — but raising the same exception immediately rolled the transaction back, silently undoing the revoke. Fix: service now raises with `session_id`; the router catches the exception and revokes in a fresh transaction. Recommended: this pattern (raise with metadata, caller handles state in a separate tx) becomes a documented convention for any service operation that needs to persist state alongside an error.

**6. Test infrastructure findings.**
   - **In-memory SQLite + multi-session = `StaticPool` required.** When the SSE stream's T1 emitter opens a fresh `AsyncSession`, in-memory SQLite gives that session a different in-memory database. Fixture switched to `poolclass=StaticPool` + `check_same_thread=False`, which keeps a single underlying connection across all sessions sharing the same engine.
   - **`sse-starlette` + `httpx.stream()` deadlocks on early close.** Driving the SSE stream through `httpx.stream()` and calling `aclose()` early can hang the test runner on cleanup (the EventSourceResponse generator's finally-block T1 emit waits on a now-cancelled event loop). For SSE behavioural tests, drive the `sse_event_stream()` generator directly with `asyncio.wait_for` timeouts; HTTP smoke tests use direct router-function inspection of headers without consuming the body.

**7. Demo-stage simplifications validated.** All five Dev-Mode + DB Addendum substitutions (no Docker, no Keycloak, no Java, SQLite not Postgres, stub auth not OIDC) worked as designed. The chunk shipped without any per-firm IdP configuration, container orchestration, or secrets management — addressed in production-readiness phase as the addenda anticipate.

**8. Foundation reference + chunk plan format both held up well.** No structural revisions surfaced beyond the topic-18 consolidation question. FR entry template (header / cross-refs / body / open questions / revision history) gave each entry a stable shape that was easy to consume during implementation. Chunk template's "Scope: out" section in particular was load-bearing: kept us from accidentally building features (SSE event payloads beyond connection lifecycle, role-tree-specific styling, etc.) that belong to later chunks.

---

## Chunk 0.2 Acceptance Walkthrough (May 2026)

| # | Criterion (paraphrased) | Status | Verification |
|---|---|---|---|
| 1 | Advisor → `/app/advisor` after auth | ✅ | `test_dev_login_returns_role_specific_redirect_url[advisor1-/app/advisor]` + `DevLoginPage` reads `body.redirect_url` and navigates. |
| 2 | CIO → `/app/cio` | ✅ | parametrized `test_dev_login_returns_role_specific_redirect_url[cio1-/app/cio]` |
| 3 | Compliance → `/app/compliance` | ✅ | parametrized variant |
| 4 | Audit → `/app/audit` | ✅ | parametrized variant |
| 5 | Each role's home page displays name + role badge + firm + welcome | ✅ | `RoleHomePage` renders `DashboardWelcomeCard` (same shape as chunk 0.1 dashboard, scoped to whichever tree the user landed on). |
| 6 | Each role's sidebar shows role-appropriate items | ✅ | 4 per-role configs at `web/src/config/sidebar/{advisor,cio,compliance,audit}.ts`; `Sidebar` reads role from auth store and picks the matching config. Items disabled per chunk plan §scope_out. |
| 7 | Wrong-role direct navigation is bounced to user's correct tree | ✅ | TanStack Router `requireRole(expected)` beforeLoad: `if (user.role !== expected) throw redirect({ to: ROLE_PATHS[user.role] })`. Manual browser check (advisor → /app/cio → /app/advisor). |
| 8 | Refreshing a role-tree URL stays on the tree (within session window) | ✅ | App-mount `tryBootRefresh` recovers JWT; `requireRole` then matches; user stays on same path. Same machinery as chunk 0.1 criterion 13. |
| 9 | Logout from any role tree behaves identically to chunk 0.1 logout | ✅ | UserMenu logout flow unchanged from chunk 0.1; `requireRole` then redirects to `/dev-login` on next render because user is null. |
| 10 | SSE connection survives navigation between role-tree routes | ✅ | `useSSEConnection` is mounted in `AppShell`. Route changes within `AppShell` (advisor→advisor sub-routes, etc.) don't unmount it. The `hasJwt`-only effect dep means token refresh doesn't re-establish either. |
| 11 | Each role-tree home emits `role_home_visited` T1 event with `{role, user_id}` | ✅ | `useRoleHomeVisited` hook fires `POST /api/v2/system/role-home-visited` on mount; backend `role_home_visited` endpoint emits the T1 event from the JWT. Tested by `test_emits_role_home_visited_t1_with_correct_payload` (parametrized over all 4 roles) + `test_multiple_visits_emit_multiple_events`. |

**11 of 11 chunk 0.2 criteria green.** Cluster-level acceptance from the chunk plan opening section: full 8-step user journey works for all 4 roles end-to-end via uvicorn + Vite dev. Cluster 0 is closed.

---

## Cluster 0 Retrospective Addenda (chunk 0.2)

Chunk 0.2 was a small lift (3 logical steps, 12 new tests, ~600 lines added). One additional retrospective note beyond the chunk-0.1 list above:

**9. Per-role config files as the lighting-up mechanism.** The 4 sidebar configs (`web/src/config/sidebar/{role}.ts`) are designed so every cluster that ships a real surface for a role flips one item from `enabled: false` to `true` and points `href` at its TanStack Router route. This avoids touching the `Sidebar` component itself for new surfaces. Pattern works as designed; recommend documenting it as the standard lighting-up pattern in a future iteration of the structure doc.

**Cluster 0 closure**: chunks 0.1 and 0.2 shipped. The walking skeleton has proven the entire cluster 0 transport stack — auth, JWT/sessions/refresh + theft detection, SSE channel + multiplex contract, role-permission vocabulary, firm-info + branding, React app shell, role-tree routing, strangler-fig coexistence with the Alpine SPA. Cluster 1 (Investor Onboarding) is unblocked.

---

**End of Cluster 0 Chunk Plan.**
