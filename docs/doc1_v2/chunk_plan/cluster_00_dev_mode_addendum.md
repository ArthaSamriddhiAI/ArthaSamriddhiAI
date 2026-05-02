# Samriddhi AI: Cluster 0 Dev-Mode Addendum

## Stub Authentication for Internal Demo Stage

**Document:** Samriddhi AI, Cluster 0 Dev-Mode Addendum
**Cluster:** 0 (Walking Skeleton)
**Status:** Active for internal demo stage; superseded when production-readiness phase begins
**Date:** April 2026
**Authors:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 0. Document Purpose

This addendum modifies cluster 0 implementation for the internal demo stage of Samriddhi AI. The production specifications (FR Entry 17.0 OIDC Authentication, the Keycloak development IdP requirement in the cluster 0 ideation log §1.3) remain locked as the canonical production behaviour. This addendum specifies a simpler stub authentication implementation suitable for internal demos where OIDC mechanics are not the demo value.

The addendum is active during the internal demo stage. When the project transitions to production-readiness (first pilot firm deployment, real client data, real firm IdP integration), this addendum is superseded and the production specs in FR Entry 17.0 plus the Keycloak setup in the ideation log become the active implementation contract.

This is a deliberate divergence between specification and implementation, made explicit. The architectural integrity argument: the production specs describe what the system will be when it ships to firms; the demo implementation gets there in stages, building enough at each stage for that stage's purpose. Cluster 0 demo stage builds enough auth for an internal demo; production-readiness builds the rest.

---

## 1. What This Addendum Changes

### 1.1 OIDC Flow Replaced by Stub

FR Entry 17.0's six-step OIDC Authorization Code Flow with PKCE is not implemented in demo stage. In its place, the demo implements a stub authentication endpoint that accepts a test user identifier, looks up the user's profile in a hardcoded YAML configuration, and issues the same JWT that the production OIDC flow would have issued.

The downstream behaviour (FR Entry 17.1 JWT and Session Management, FR Entry 17.2 Role-Permission Vocabulary, FR Entry 18.0 SSE Channel) is unchanged because the JWT issued by the stub looks identical to the JWT issued by the production OIDC flow.

### 1.2 Keycloak Not Required

The Keycloak development IdP setup specified in the cluster 0 ideation log §1.3 is not required for demo stage. The dev environment runs without Keycloak; auth is the FastAPI stub.

### 1.3 PKCE, JWKS, Custom Claim Extraction Deferred

The PKCE mechanics (code_verifier, code_challenge, S256 derivation), the JWKS validation (signature verification against IdP-published keys), and the custom claim extraction from external IdP tokens are all production concerns. Demo stage does not implement them.

### 1.4 Per-Firm IdP Configuration Deferred

Production deployments require per-firm IdP configuration (issuer URL, client_id, client_secret, redirect_uri). Demo stage runs against a single hardcoded "demo firm" with no per-firm configuration; the firm-info endpoint returns demo firm data.

---

## 2. What This Addendum Does Not Change

### 2.1 FR Entry 17.1 JWT and Session Management

Unchanged. The stub auth endpoint issues the same JWT structure (claims, signing key, 15-minute lifetime) and sets the same refresh cookie (HttpOnly, Secure, SameSite=Strict, 8-hour expiry) as the production OIDC flow would. The Postgres `sessions` table is unchanged. Refresh flow with token rotation works exactly as specified. Logout works exactly as specified. Session limits work exactly as specified.

### 2.2 FR Entry 17.2 Role-Permission Vocabulary

Unchanged. The four roles (advisor, CIO, compliance, audit) and the cluster 0 permission set are exactly as specified. The stub auth attaches role and firm_id to the JWT in exactly the same way the production OIDC flow does.

### 2.3 FR Entry 18.0 SSE Channel Overview

Unchanged. The SSE channel authenticates connections via the JWT. Whether the JWT was issued by stub auth or production OIDC is irrelevant to the SSE layer; the JWT is the contract.

### 2.4 React App Shell, Role Routing, Branding

Unchanged. The React app reads the JWT, fetches firm-info, applies CSS variables, renders the role-appropriate placeholder dashboard exactly as specified in the chunk plan.

### 2.5 Cluster 0 Chunk Plan Structure

Chunks 0.1 and 0.2 still exist as the two implementation chunks. Their scope and dependency structure is unchanged. Their acceptance criteria simplify because the OIDC mechanics are not under test; replacement criteria are in §4 below.

---

## 3. Stub Authentication Specification

### 3.1 Test User YAML Configuration

A YAML file at `dev/test_users.yaml` (or equivalent location) defines the demo test users:

```yaml
firm:
  firm_id: "demo-firm-001"
  firm_name: "Demo Wealth Advisory"
  firm_display_name: "Demo Wealth Advisory Pvt Ltd"
  primary_color: "#0D2944"
  accent_color: "#1A8A8A"
  logo_url: "/static/demo-logo.png"
  regulatory_jurisdiction: "IN"

users:
  - user_id: "advisor1"
    email: "advisor1@demo.test"
    name: "Anjali Mehta"
    role: "advisor"
  - user_id: "cio1"
    email: "cio1@demo.test"
    name: "Rajiv Sharma"
    role: "cio"
  - user_id: "compliance1"
    email: "compliance1@demo.test"
    name: "Priya Iyer"
    role: "compliance"
  - user_id: "audit1"
    email: "audit1@demo.test"
    name: "Vikram Desai"
    role: "audit"
```

The four users cover the four roles. Names are illustrative. Adjust as needed for the demo audience.

### 3.2 Stub Auth Endpoint

A FastAPI endpoint at `POST /api/v2/auth/dev-login` accepts a JSON body:

```json
{
  "user_id": "advisor1"
}
```

The endpoint:

1. Looks up the user in the YAML configuration. If not found, returns HTTP 404.
2. Constructs the JWT claims using the user's profile and the firm configuration: `sub` (user_id), `firm_id` (from YAML firm config), `role` (from user profile), `email`, `name`, `iat` (current timestamp), `exp` (current + 900 seconds), `session_id` (new ULID), `iss` (`samriddhi-backend`), `aud` (`samriddhi-app`).
3. Signs the JWT with the deployment's signing key (HS256 in demo; same as FR Entry 17.1 §2.1).
4. Creates a session row in Postgres per FR Entry 17.1 §3.2 with the user's identity, generates a refresh token (cryptographically random 32 bytes), hashes it, persists the hash.
5. Sets the refresh cookie with HttpOnly, Secure (with development exception for HTTP localhost), SameSite=Strict, Path=/api/v2/auth/refresh, Max-Age=28800.
6. Returns the JWT in the response body: `{"access_token": "<jwt>", "expires_in": 900, "token_type": "Bearer"}`.

### 3.3 Stub Login UI

A simple React route at `/app/dev-login` renders a login page with a dropdown of the four test users (read from a `/api/v2/auth/dev-users` endpoint that returns the user list from the YAML, minus any sensitive fields). Selecting a user and clicking "Log in" calls `POST /api/v2/auth/dev-login`, receives the JWT, stores it in memory, redirects to the user's role tree (chunk 0.2 routing).

The UI does not need polish. It is a developer-facing affordance, not a product surface. It can look like a basic form with a dropdown and a button.

### 3.4 Production Endpoint Coexistence

The production OIDC endpoints (`/api/v2/auth/login`, `/api/v2/auth/callback`) are not implemented in demo stage. Their routes can be left unregistered or stubbed to return HTTP 501 Not Implemented with a problem detail saying "production auth not enabled in this build."

When production-readiness phase begins, the production endpoints are implemented per FR Entry 17.0, the dev-login endpoint is removed (or guarded behind a development-only feature flag that is not enabled in production builds), and the dev-login UI route is removed.

### 3.5 Firm-Info Endpoint Behaviour

The firm-info endpoint at `/api/v2/system/firm-info` returns the firm configuration from the YAML's `firm:` section. In demo stage, all authenticated users see the same firm-info because there is only one firm. The firm_id from the JWT must match `demo-firm-001` (the only firm); a JWT with a different firm_id is rejected (which can't happen with stub auth but the validation is preserved for defence-in-depth).

---

## 4. Modified Acceptance Criteria for Demo Stage

### 4.1 Chunk 0.1 Modified Acceptance Criteria

The chunk plan's chunk 0.1 has 14 acceptance criteria. In demo stage, criteria 1, 2, and 13 are modified; the others are unchanged.

**Modified Criterion 1:** Navigating to the demo URL without an authenticated session redirects to the dev-login page at `/app/dev-login`. (Production: redirects to firm IdP; demo: redirects to stub login.)

**Modified Criterion 2:** After selecting a test user and clicking "Log in" on the dev-login page, the user is redirected to their role tree home with a valid session. (Production: completes OIDC; demo: stub login.)

**Modified Criterion 13:** Refreshing the page within the 8-hour session window does not require re-login (the access token may have expired but the refresh cookie produces a new one; the SSE connection re-establishes seamlessly). The refresh mechanism is identical to production; only the initial auth differs.

**Unchanged Criteria 3-12 and 14:** These cover JWT structure, refresh cookie behaviour, dashboard rendering, SSE establishment, heartbeat behaviour, branding, logout, T1 telemetry, and dev environment bringup. None depend on the OIDC mechanics; all apply to demo stage as written.

### 4.2 Chunk 0.2 Acceptance Criteria

Unchanged. Role-based home tree routing depends on the JWT's role claim, not on how the JWT was issued.

### 4.3 Removed Criteria

Three criteria from the cluster-level acceptance criterion section in the chunk plan ("Cluster-Level Acceptance Criterion") are not testable in demo stage and are deferred to production:

- "Get redirected to the firm's IdP (Keycloak in development, the firm's actual IdP in production)" → replaced by "Get redirected to the dev-login page".
- "Authenticate with their firm credentials" → replaced by "Select a test user from the dropdown".
- The acceptance tests in FR Entry 17.0 §7 (10 OIDC-specific tests) are deferred. The acceptance tests in FR Entries 17.1, 17.2, 18.0 are all preserved.

---

## 5. Dev Environment Without Docker

### 5.1 Required Components

The demo dev environment requires:

- **Python 3.12** with venv. Install dependencies via `pip install -r requirements.txt`.
- **PostgreSQL 16** running locally. Create a dev database (e.g., `createdb samriddhi_dev`). Connection string in `.env` points to local Postgres.
- **Node.js 20+** with npm. Install dependencies via `npm install`. Run Vite dev server via `npm run dev`.

That is the entire dev environment for demo stage. No Java, no Keycloak, no Docker.

### 5.2 Bringup Sequence

1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `alembic upgrade head` (creates the `sessions` table and any other tables cluster 0 needs)
4. `uvicorn main:app --reload --port 8000`
5. In a second terminal: `npm install && npm run dev` (Vite serves at port 5173 or similar)
6. Navigate to `http://localhost:5173/app/` (or wherever Vite is serving)
7. Get redirected to dev-login, select a user, click Log in, land on role tree home

### 5.3 Production Environment Note

When production-readiness phase begins, the dev environment description in this addendum is superseded by Doc 4 Operations. Production deployments include real OIDC infrastructure (Keycloak in firm-managed deployments, or the firm's existing IdP), proper TLS, secret management, etc.

---

## 6. Migration Path to Production

When the project transitions out of internal demo stage to production-readiness (first pilot firm), the following work happens in a dedicated cluster (likely cluster 17.5 or a new cluster ahead of the pilot):

1. The dev-login endpoint and UI are removed (or guarded behind a development-only feature flag that production builds disable).
2. The production OIDC endpoints (`/api/v2/auth/login`, `/api/v2/auth/callback`) are implemented per FR Entry 17.0 §2.
3. PKCE, JWKS validation, custom claim extraction are implemented per FR Entry 17.0 §2.1 and §2.2.
4. The firm's IdP configuration is added to the deployment config (issuer URL, client_id, client_secret, redirect_uri). This is per-deployment, not in code.
5. The 10 OIDC-specific acceptance tests in FR Entry 17.0 §7 become testable and must pass.
6. This addendum is marked superseded; FR Entry 17.0 becomes the active implementation contract.

The migration is bounded: it touches the auth endpoints, the auth callback handler, the firm's IdP integration. The rest of the application (FR Entries 17.1, 17.2, 18.0, all subsequent clusters) is unchanged because the JWT contract is unchanged.

This is the architectural integrity payoff for using stub auth in demo stage: when production comes, only the auth boundary changes, not the rest of the system.

---

## 7. Acceptance Criteria for This Addendum

The addendum itself is considered correctly applied when:

1. The dev-login endpoint exists at `POST /api/v2/auth/dev-login` and works against the YAML configuration.
2. The dev-login UI at `/app/dev-login` allows selecting a test user and logging in.
3. JWTs issued by stub auth have the correct claim structure per FR Entry 17.0 §3.1.
4. FR Entry 17.1 (JWT and Session Management), 17.2 (Role-Permission Vocabulary), 18.0 (SSE Channel) all work as specified, regardless of the auth source.
5. The dev environment can be brought up with venv, Postgres, and npm only; no Docker, no Keycloak, no Java required.
6. The four test users (one per role) all log in successfully and land on their correct role tree.
7. Logout, refresh, session limits work as specified in FR Entry 17.1.
8. The production OIDC endpoints (`/api/v2/auth/login`, `/api/v2/auth/callback`) either return HTTP 501 with a clear "production auth not enabled" problem detail, or are not registered.

---

## 8. Revision History

April 2026 (cluster 0 addendum authoring): Initial addendum created. Active for internal demo stage. Will be superseded when production-readiness phase begins.

---

**End of Cluster 0 Dev-Mode Addendum.**
