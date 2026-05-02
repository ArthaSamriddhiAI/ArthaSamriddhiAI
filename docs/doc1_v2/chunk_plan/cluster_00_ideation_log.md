# Samriddhi AI: Cluster 0 Ideation Log

## Walking Skeleton, Architectural Decisions Locked

**Document:** Samriddhi AI, Cluster 0 Ideation Log
**Cluster:** 0 (Walking Skeleton)
**Pass:** 1 of 2 (Ideation)
**Status:** Complete; ready for drafting pass
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This is the cluster 0 ideation log. It captures the architectural decisions locked during the cluster's ideation pass, before drafting of foundation reference entries and chunk plan begins. The decisions here become the constraints under which the drafting pass operates.

Cluster 0 is the walking skeleton: the smallest possible end-to-end vertical slice that proves the architecture works. Two chunks: chunk 0.1 ships an authenticated user reaching a placeholder dashboard with a live SSE connection; chunk 0.2 adds role-based home tree routing. The decisions in this log are the load-bearing patterns that every subsequent cluster builds on.

The ideation pass locks eight decisions across four topic areas: authentication flow, SSE infrastructure, strangler-fig coexistence with the existing Alpine SPA, and CSS variable conventions for firm branding. Each decision is presented with its locked answer, the rationale, and the alternatives considered.

---

## 1. Authentication Flow

### 1.1 Decision: OIDC Authorization Code Flow with PKCE

**Locked answer:** OIDC Authorization Code Flow with PKCE (Proof Key for Code Exchange) is the authentication mechanism. The firm's existing identity provider issues OIDC tokens. The Samriddhi backend handles the redirect callback, exchanges the auth code for ID and access tokens using PKCE verification, validates the ID token signature against the IdP's JWKS, extracts user_id, firm_id, role, and email from claims, and issues its own application JWT (15-minute access token) plus sets the refresh cookie (HttpOnly, Secure, SameSite=Strict, 8-hour expiry).

**Rationale:** Authorization Code Flow with PKCE is the OAuth 2.1 industry-standard authentication for browser-based applications in 2026. PKCE protects against authorization code interception attacks, which matters because the React SPA cannot securely store a client secret. Implicit flow and password grant flow are both deprecated for SPAs; PKCE is the only OAuth 2.1-compliant option.

The 15-minute access token plus 8-hour refresh cookie split is the standard pattern for B2B applications. Short access tokens limit the blast radius of token compromise; the refresh cookie in HttpOnly storage cannot be exfiltrated by JavaScript. This matches the auth model locked in Doc 2 Pass 1 Decision 2.

**Alternatives considered:** Authorization Code Flow without PKCE (rejected: PKCE is now the standard for SPA clients per RFC 7636), Implicit Flow (rejected: deprecated by OAuth 2.1), session cookies without JWT (rejected: doesn't extend cleanly to API clients or future mobile, the JWT-with-refresh-cookie hybrid is the modern B2B standard).

**Implementation:** Authlib library in Python on the backend handles OIDC mechanics. The frontend uses standard PKCE (generate code_verifier, derive code_challenge, attach to authorization request).

### 1.2 Decision: Custom Claim Names for Firm and Role

**Locked answer:** The firm's identity provider must include two custom claims in ID tokens: `samriddhi_firm_id` (string, the firm's deployment identifier matching the deployment's configured firm_id) and `samriddhi_role` (string, one of `advisor`, `cio`, `compliance`, `audit`). The Samriddhi backend extracts these claims during ID token validation and populates the application JWT with them.

**Rationale:** Vendor-prefixed claim names prevent collision with standard OIDC claims and other identity-provider customisations. The `samriddhi_` prefix is unambiguous about which application owns the claim. Industry standard for custom claims in multi-tenant or multi-app IdP deployments.

The four roles match the role taxonomy from Doc 2 Pass 3a §2 (advisor, cio, compliance, audit). Future role additions (e.g., a senior_advisor role) are additive within the same claim.

**Alternatives considered:** Generic claim names like `firm_id` and `role` (rejected: collision risk with other applications using the same IdP), claim namespace via URL pattern (e.g., `https://samriddhi.ai/firm_id`; rejected: more verbose, no real benefit at this scale), embedding role in the user's IdP groups instead of custom claims (rejected: adds complexity for IdP admins, not all IdPs handle group claims uniformly).

**Implementation note:** The IdP configuration requirement (firm's IdP admin must add the two custom claim mappings) is documented in Doc 4 Operations. For cluster 0 development, a development-only Keycloak instance with these claims pre-configured serves as the test IdP.

### 1.3 Decision: Development IdP via Keycloak

**Locked answer:** Cluster 0 development uses a Keycloak container (run via Docker Compose alongside the FastAPI backend during development) as the test IdP. Two pre-configured users exist: `advisor1@samriddhi.test` (with role `advisor`, firm_id `dev-firm-001`) and `cio1@samriddhi.test` (with role `cio`, firm_id `dev-firm-001`). The Keycloak realm is configured with the custom claim mappings for `samriddhi_firm_id` and `samriddhi_role`.

**Rationale:** Keycloak is the de facto open-source OIDC provider for development and testing. It is industry-standard, well-documented, supports OIDC Authorization Code Flow with PKCE natively, and has a straightforward realm-and-claim configuration model. Production deployments use the firm's actual IdP (Okta, Azure AD, Google Workspace, Auth0, the firm's enterprise SSO); the OIDC contract is the same regardless of which IdP backs it.

**Alternatives considered:** Mock IdP via a custom FastAPI endpoint (rejected: doesn't exercise real OIDC mechanics, hides bugs that production IdPs would surface), Auth0 development tier (rejected: introduces a third-party dependency for development, less control over configuration), no IdP for cluster 0 (rejected: defeats the purpose of the walking skeleton, which is to prove the auth flow end-to-end).

---

## 2. SSE Infrastructure

### 2.1 Decision: Full Doc 2 Pass 4 SSE Contract Scaffolding

**Locked answer:** Cluster 0 implements the complete SSE contract specified in Doc 2 Pass 4 §1 (the EventEnvelope structure, the eleven event-type catalogue, the connection lifecycle, reconnect with Last-Event-ID, the 5-minute server-side buffer, the heartbeat every 30 seconds, the token-refresh-during-connection mechanism). Even though only `connection_established` and `connection_heartbeat` events fire in cluster 0 (because no agents or other event-emitting components are live yet), the scaffolding for the other nine event types is in place. Future clusters that introduce components which emit events plug into the existing scaffolding rather than building it from scratch.

**Rationale:** Building the full SSE contract once is cheaper than building two-thirds of it now and the rest later. The scaffolding work (EventEnvelope serialisation, event_id ULID generation, the per-connection event buffer, the reconnect handling, the heartbeat scheduler) is contract-level work that doesn't depend on which event types actually fire. Building it incrementally as each event type's component ships introduces risk that the contract drifts; building it once locks the contract at cluster 0.

**Alternatives considered:** Implement only `connection_established` and `connection_heartbeat` for cluster 0 and grow the scaffolding as event types accumulate (rejected: every cluster that adds an event type would have to revisit the SSE infrastructure, and the cumulative refactoring cost exceeds the upfront cost), implement minimal SSE without the multiplex scaffolding (rejected: locks us into a non-multiplex shape that doesn't scale to the eleven event types we need).

**Implementation:** FastAPI's `EventSourceResponse` (from sse-starlette) handles the SSE protocol. A custom middleware layer wraps it to enforce the EventEnvelope contract, generate event_ids, manage the per-connection buffer, and schedule heartbeats.

### 2.2 Decision: SSE Connection Authentication via Initial JWT, Decoupled from Token Refresh

**Locked answer:** The SSE connection is authenticated at establishment time by validating the JWT in the `Authorization` header. The server records the connection's user identity. Once established, the connection remains alive regardless of subsequent token expiry; the server emits `token_refresh_required` 60 seconds before access token expiry, the client refreshes via REST, and the SSE connection itself is unaffected.

**Rationale:** This pattern is locked in Doc 2 Pass 4 §1.15 (access-token-refresh-during-connection mechanism). It is the right pattern because SSE connections are long-lived (potentially hours during a working day) while access tokens are short (15 minutes). Forcing a reconnect every 15 minutes would defeat the purpose of long-lived connections; coupling the access-token lifecycle to the connection lifecycle is wrong; decoupling them via the explicit refresh event is the standard pattern for long-lived authenticated connections in 2026 B2B applications.

**Alternatives considered:** Reconnect on token expiry (rejected per above), use refresh cookie for SSE auth (rejected: SSE specification doesn't natively support cookie auth in the way fetch does, complicates the auth model), use a separate long-lived SSE-specific token (rejected: introduces a second auth mechanism, doubles the surface area).

---

## 3. Strangler-Fig Coexistence

### 3.1 Decision: Path-Based Routing Split

**Locked answer:** FastAPI's app routing uses path-based separation between the new React app and the existing Alpine SPA. Specifically: `app.mount("/app", StaticFiles(directory="dist", html=True))` serves the new React bundle for any path under `/app/&#42;`. `app.mount("/static", StaticFiles(directory="static"))` continues serving the Alpine SPA. The `html=True` flag on the React mount means non-file paths under `/app/&#42;` fall through to `/app/index.html`, allowing TanStack Router to handle client-side routing.

API endpoints under `/api/v2/&#42;` (the canonical contract from Doc 2 v2) are consumed by the React app. API endpoints under `/api/v1/&#42;` (legacy) are consumed by the Alpine SPA. Both `/api/v1/&#42;` and `/api/v2/&#42;` continue running until the strangler-fig migration completes.

**Rationale:** Path-based routing is the simplest possible coexistence pattern. Both apps live in the same FastAPI deployment, served from different mount points. The advisor's URL bar shows them where they are. Authentication is shared (the same OIDC session works in both because both authenticate against the same IdP and validate the same JWT). This matches the strategy locked in Doc 3 Pass 1 Decision 3.

**Alternatives considered:** Subdomain-based separation (`app.firm.samriddhi.ai` vs `legacy.firm.samriddhi.ai`, rejected: requires DNS configuration per firm, complicates the per-firm-deployment model), reverse proxy splitting in front of FastAPI (rejected: introduces an extra component, FastAPI's mount mechanics handle this natively), single-app with feature flag for new versus legacy surfaces (rejected: complex, error-prone, hard to debug, defeats the purpose of strangler-fig isolation).

### 3.2 Decision: Path Conflict Prevention

**Locked answer:** A naming convention prevents path conflicts between `/app/&#42;` and `/static/&#42;`. Specifically: any path that exists in the Alpine SPA at `/static/<X>` cannot be added at `/app/<X>` for the same surface concept. When the strangler-fig migration moves a surface from Alpine to React, the new surface is added at `/app/<X>` (typically a more specific path than the Alpine version) and the Alpine version is then deprecated. Before deprecation, both paths can coexist; after deprecation, the Alpine path returns a redirect or removal.

**Rationale:** Path conflicts during strangler-fig migration are the most common failure mode. Without explicit naming discipline, a developer adds `/app/cases` and a different developer adds `/static/cases` and both work but route to different code, producing user confusion and bugs. A simple naming convention prevents this; tooling (a CI lint check) can enforce it later.

**Alternatives considered:** No conflict prevention (rejected: causes the failure mode just described), unique-prefix-per-feature (rejected: too restrictive, prevents natural URLs).

---

## 4. CSS Variable Conventions for Firm Branding

### 4.1 Decision: Three Foundational CSS Variables

**Locked answer:** The firm-info response carries three branding fields: `primary_color` (hex string, e.g., `#0D2944`), `accent_color` (hex string, e.g., `#1A8A8A`), `logo_url` (URL string, served from the firm's deployment's static assets). On auth completion, the React app reads firm-info and writes three CSS variables to the document root: `--color-primary`, `--color-accent`, `--logo-url`. Tailwind configuration is set up so utility classes like `bg-primary`, `text-accent` resolve to these variables.

**Rationale:** Three variables are the minimum needed for visual differentiation per firm. Primary is the dominant brand colour (used for buttons, headers, focus states). Accent is the secondary brand colour (used for highlights, links, accent rules). Logo is the firm's logo image. More variables can be added later as firm branding requirements emerge; starting with three keeps the contract simple and the implementation tractable.

The CSS-variables-from-firm-info pattern is the standard 2026 approach for white-label B2B SaaS. It is what Linear, Notion, and similar B2B tools use for theming.

**Alternatives considered:** More variables upfront (`--color-warning`, `--color-success`, `--color-danger`, `--color-info`, etc.; rejected: over-specifies before we have firm-specific theming requirements; can add when needed), build-time theming with per-firm CSS bundles (rejected: requires per-firm rebuilds, defeats the single-bundle deployment model), no firm theming for MVP (rejected: even basic differentiation needs primary colour and logo, the three-variable solution is minimal).

**Implementation:** A React effect runs on auth completion, reads firm-info from the firm-info query, sets the CSS variables on `document.documentElement.style`, and re-renders. Subsequent style applications read from the variables; Tailwind utility classes resolve via the Tailwind config.

### 4.2 Decision: Logo Loading Strategy

**Locked answer:** The logo URL in firm-info points to a static asset served by the firm's deployment. The React app loads it via standard `<img>` tag with the URL from the `--logo-url` CSS variable (or directly from firm-info; both work). Caching is handled by HTTP response headers from the firm's deployment (typically `Cache-Control: public, max-age=86400` for the logo since it changes rarely).

**Rationale:** Static asset serving with HTTP caching is the standard pattern. No special infrastructure needed. Logo updates happen by replacing the static asset on the firm's deployment; advisors see the new logo on their next page load (or after the cache expires).

**Alternatives considered:** Embed logo as base64 in firm-info (rejected: bloats the firm-info response, no caching benefit), serve logo via API endpoint (rejected: unnecessary complexity, static file serving handles this well).

---

## 5. Role Tree Placeholders

### 5.1 Decision: Minimal Placeholder Content for Cluster 0

**Locked answer:** Each role tree (`/app/advisor`, `/app/cio`, `/app/compliance`, `/app/audit`) renders a placeholder page in cluster 0. The placeholder shows: the user's display name (from firm-info user context), the user's role (rendered as a colored badge using the firm's accent color), the firm's display name (from firm-info), a single welcome line ("Welcome to Samriddhi AI"), and the SSE connection status indicator (connected and heartbeating, disconnected, reconnecting, with appropriate visual treatment).

The sidebar renders placeholder navigation items per role (e.g., advisor sidebar shows "Cases", "Investors", "Alerts", "Monitoring" as disabled links until the corresponding clusters ship). The top utility bar renders the firm logo, user menu (with logout), and a notification badge (zero count for cluster 0 since no alerts are firing yet).

**Rationale:** The placeholder must be enough to verify that the routing, the role detection, the SSE connection, the firm branding, and the app shell all work. It must not be so much that cluster 0's scope expands beyond the walking skeleton. The proposed content (name, role, firm, welcome, SSE status) hits all the verification needs without inventing functionality.

The disabled sidebar links serve a secondary purpose: they communicate to the advisor what's coming. When cluster 1 ships and "Investors" lights up, the advisor experiences the system maturing rather than appearing fully formed.

**Alternatives considered:** Empty page with just the user's name (rejected: doesn't exercise the SSE indicator or firm branding visually), full dashboard mockup (rejected: scope creep, blurs the line between cluster 0 and later clusters), per-role customised welcomes ("Welcome, advisor; you have 0 cases pending"; rejected: invents content the system can't actually produce yet).

---

## 6. Backend Stack Confirmation

### 6.1 Decision: No Stack Change

**Locked answer:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, PostgreSQL 16. Same stack as Doc 1 v1 implementation. Same as Doc 2 specifications. No change.

**Rationale:** The existing stack is sound and well-understood. Changing it for the v2 build cycle introduces risk without benefit. The team is already proficient with this stack. The change-budget for v2 is better spent on the architectural revisions than on stack migration.

**Alternatives considered:** No alternatives genuinely considered. Stack stability is a feature, not a constraint.

### 6.2 Decision: Frontend Stack Confirmation

**Locked answer:** React 18, TypeScript 5.x, Vite 5.x, TanStack Router, TanStack Query, Tailwind CSS 3.x, shadcn/ui (Radix UI primitives), Zustand for ephemeral UI state, native EventSource for SSE. Per Doc 3 Pass 1 Decision 1.

**Rationale:** This is the 2026 industry-standard React SPA stack for production B2B applications. Locked in Doc 3 Pass 1; cluster 0 is the first cluster to actually exercise it, which is why it's confirmed here rather than assumed.

---

## 7. Development Environment Setup

### 7.1 Decision: Docker Compose for Local Development

**Locked answer:** A `docker-compose.yml` at the repository root spins up the local development environment with three services: FastAPI backend (with hot reload), PostgreSQL 16 (with persistent volume for development data), Keycloak (with realm and users pre-configured via init script). The Vite dev server runs separately (faster than dockerised, and the team is already used to running it directly with `npm run dev`).

Cluster 0 development requires only `docker-compose up` plus `npm run dev` to have a working environment.

**Rationale:** Industry-standard local development setup. Keycloak in Docker is the standard pattern for development OIDC. Postgres in Docker is the standard pattern for databases that need to match production. FastAPI hot-reload via uvicorn is the standard development workflow.

The Vite dev server outside Docker is a deliberate exception: dockerised Vite has well-known performance issues (slow HMR due to filesystem inotify limits in Docker on macOS especially), and the team's existing workflow with direct `npm run dev` is faster.

**Alternatives considered:** Everything in Docker (rejected per the Vite performance issue), nothing in Docker (rejected: makes IdP and Postgres setup tedious and divergent across team members), Vagrant (rejected: outdated for 2026, Docker is the standard).

### 7.2 Decision: Production Environment Provisioning

**Locked answer:** Production environment provisioning is deferred to Doc 4 Operations. Cluster 0 ships the application code; the deployment story (Kubernetes vs systemd vs PaaS, secret management, certificate management, observability stack) is operationally decided per firm and specified in Doc 4.

**Rationale:** Operations decisions are firm-specific (some firms have existing Kubernetes infrastructure, some prefer single-VM deployments, some use managed PaaS) and don't need to be locked at cluster 0. The application code that cluster 0 produces is portable across deployment targets.

**Alternatives considered:** Lock production deployment now (rejected: premature, varies per firm, Doc 4 owns this).

---

## 8. Cluster 0 Closure

### 8.1 Decisions Locked Summary

Eight decisions across four topic areas:

Authentication: OIDC Authorization Code Flow with PKCE; custom claim names `samriddhi_firm_id` and `samriddhi_role`; Keycloak for development IdP.

SSE Infrastructure: full Doc 2 Pass 4 contract scaffolding even though only two event types fire; connection authentication via initial JWT decoupled from token refresh.

Strangler-Fig: path-based routing split (`/app/&#42;` for React, `/static/&#42;` for Alpine, `/api/v1/&#42;` and `/api/v2/&#42;` both running); path conflict prevention through naming convention.

CSS Variables: three foundational variables (`--color-primary`, `--color-accent`, `--logo-url`); logo via standard static asset URL with HTTP caching.

Plus role tree placeholders, backend stack confirmation, frontend stack confirmation, development environment via Docker Compose plus direct Vite dev server.

### 8.2 Foundation Reference Entries to be Authored in Drafting Pass

Topic 17 Authentication: Entry 17.0 OIDC Authentication, Entry 17.1 JWT and Session Management, Entry 17.2 Role-Permission Vocabulary (skeleton; permissions accumulate in later clusters).

Topic 18 Real-Time SSE: Entry 18.0 SSE Channel Overview.

Plus chunk plan: cluster_00_walking_skeleton.md with chunks 0.1 and 0.2 fully fleshed out from the chunk template.

### 8.3 Decisions Deferred

Several cluster 0 questions are intentionally deferred because they don't block cluster 0 implementation:

The full role-permission vocabulary (per Doc 2 Pass 3a §2) is not locked at cluster 0 because permissions accumulate cluster by cluster as components ship. Entry 17.2 captures the four roles plus a placeholder permission list that grows over time.

The OpenAPI-generated TypeScript client (per Doc 3 Pass 1 Decision 8) is not exercised at cluster 0 because the only API endpoint cluster 0 calls is firm-info; cluster 0 hand-writes that one client call. Cluster 1 onwards uses the generated client.

The full SSE event payload schemas (other than `connection_established` and `connection_heartbeat`) are scaffolded but not implemented; later clusters that introduce event-emitting components implement those event payloads.

Production deployment provisioning, secret management, certificate management, observability stack are deferred to Doc 4 Operations.

Per-agent kill-switch behaviour (referenced in Doc 1 v1) is not exercised at cluster 0 because no agents are running; the kill-switch infrastructure is part of the SmartLLMRouter component, which is built when the first agent ships in cluster 5.

### 8.4 Open Questions for Drafting Pass

Two questions surfaced during ideation that don't block ideation closure but should be addressed during the drafting pass:

The exact UX of the SSE connection status indicator: a small dot in the top utility bar with green-yellow-red colour states is the most common pattern; confirming the exact placement and visual treatment is a Doc 3 Pass 2 onwards concern but cluster 0 needs to ship something. Working answer: top-right of the top utility bar, just left of the user menu, three states (green=connected and heartbeating, yellow=reconnecting, red=disconnected).

The Keycloak realm configuration scripts (the JSON or shell script that pre-configures the realm with the two test users and the custom claim mappings) need to be drafted as part of cluster 0's implementation deliverables. The drafting pass produces a placeholder; the actual scripts come during implementation.

---

**End of Cluster 0 Ideation Log. Ready for drafting pass.**
