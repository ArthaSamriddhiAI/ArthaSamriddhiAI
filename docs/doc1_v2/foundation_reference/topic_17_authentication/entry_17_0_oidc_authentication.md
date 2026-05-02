# Foundation Reference Entry 17.0: OIDC Authentication

**Topic:** 17 Authentication and Identity
**Entry:** 17.0
**Title:** OIDC Authentication
**Status:** Locked (cluster 0; chunk 0.1 shipped May 2026, demo-stage stub auth substituted per Dev-Mode Addendum)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- Principles §2.2 (the firm-info hook references this entry's auth completion trigger)
- Principles §3.1 (agent activation requires authenticated context per this entry)
- FR Entry 17.1 (JWT and Session Management; consumes this entry's auth completion output)
- FR Entry 17.2 (Role-Permission Vocabulary; uses claims extracted by this entry)
- FR Entry 18.0 (SSE Channel Overview; SSE auth depends on JWT issued here)
- CP Chunk 0.1 (walking skeleton chunk depends on this entry being locked)

## Cross-references Out

- Principles §2.1 (per-firm deployment model; this entry's IdP-per-firm pattern fits that model)
- Principles §6.0 (LLM provider strategy; not directly related but documented for completeness)

---

## 1. Purpose

OIDC Authentication is the entry point for every Samriddhi AI session. It establishes the user's identity, firm membership, and role through the firm's existing identity provider. The output of this component is the authenticated user context that every subsequent component (M0, agents, governance, SSE) consumes.

The component is invisible to the advisor in normal operation. The advisor visits the Samriddhi URL, gets redirected to their firm's IdP if not already logged in, completes their firm's standard authentication (which may include MFA, password, SSO, or whatever the firm's IdP enforces), and lands back in Samriddhi authenticated. From the advisor's perspective, Samriddhi inherits the firm's existing identity infrastructure rather than imposing a new one.

## 2. Functional Specification

### 2.1 Authorization Code Flow with PKCE

The authentication flow follows OAuth 2.1's Authorization Code Flow with PKCE (Proof Key for Code Exchange). The flow has six steps:

Step 1: The user attempts to access a protected route in the Samriddhi React app (any path under `/app/&#42;`). If no valid session exists, the React app redirects to `/auth/login` on the Samriddhi backend.

Step 2: The Samriddhi backend generates a PKCE code_verifier (cryptographically random string, 43 to 128 characters), derives the code_challenge as SHA-256 of code_verifier base64url-encoded, persists the code_verifier in a server-side session keyed by a state parameter, and constructs the authorization URL with the firm's IdP. The URL includes: client_id (the Samriddhi application's client identifier registered with the firm's IdP), redirect_uri (Samriddhi's callback endpoint), scope (`openid profile email`), state (random opaque value that ties the callback back to this session), code_challenge, code_challenge_method (`S256`).

Step 3: The user is redirected to the firm's IdP authorization endpoint. The user authenticates with the firm's standard mechanism (whatever the firm's IdP is configured to require). On successful authentication, the IdP redirects back to Samriddhi's callback endpoint with an authorization code and the state parameter.

Step 4: The Samriddhi backend's callback endpoint receives the authorization code and state. It looks up the session by state, retrieves the code_verifier, and POSTs to the IdP's token endpoint with: grant_type (`authorization_code`), code, redirect_uri, client_id, code_verifier. The IdP validates the code_verifier against the original code_challenge, and on success returns an ID token, access token, and (optionally) a refresh token.

Step 5: The Samriddhi backend validates the ID token: the signature is verified against the IdP's JWKS (JSON Web Key Set, fetched from the IdP's discovery endpoint and cached), the issuer matches the configured IdP, the audience matches the Samriddhi client_id, the expiration has not passed, and the nonce (if used) matches.

Step 6: The Samriddhi backend extracts claims from the ID token, issues its own application JWT (per FR Entry 17.1), sets the refresh cookie (per FR Entry 17.1), and redirects the user to the post-login destination (the original protected route they tried to access, or `/app/` if no specific destination was recorded).

### 2.2 Custom Claim Extraction

The Samriddhi backend extracts these claims from the ID token:

`sub`: the user's unique identifier within the firm's IdP. Becomes the user_id in the Samriddhi application JWT.

`samriddhi_firm_id`: the firm's deployment identifier. Must match the deployment's configured firm_id; if they differ, authentication fails with a clear error (the user is trying to log into the wrong firm's deployment).

`samriddhi_role`: one of `advisor`, `cio`, `compliance`, `audit`. Determines which role tree the user is redirected to and which permissions are attached to their session.

`email`: the user's email address. Used for display and audit purposes.

`name` (optional, falls back to email if absent): the user's display name. Used in UI surfaces.

If `samriddhi_firm_id` or `samriddhi_role` are absent from the ID token, authentication fails with an explicit error indicating that the firm's IdP is not properly configured. This is a deployment-time configuration failure that operations resolves; the application surfaces it clearly rather than silently failing.

### 2.3 Logout

Logout has two parts. Local logout invalidates the Samriddhi session: the access token is added to a short-lived denylist (until natural expiry), the refresh cookie is cleared. IdP logout (optional, controlled by firm policy) redirects the user to the IdP's end-session endpoint to clear their IdP session as well; if not configured, the user remains logged into the IdP and re-authentication during their IdP session lifetime is silent.

The logout flow is initiated from the user menu in the React app's top utility bar.

## 3. Schema

### 3.1 Application JWT Claims (after auth completion)

The Samriddhi application JWT (issued by the backend after OIDC completion, distinct from the ID token issued by the IdP) carries:

```json
{
  "sub": "<user_id from IdP sub claim>",
  "firm_id": "<from samriddhi_firm_id IdP claim>",
  "role": "<from samriddhi_role IdP claim>",
  "email": "<from email IdP claim>",
  "name": "<from name IdP claim, or email>",
  "iat": <issued at unix timestamp>,
  "exp": <expiration unix timestamp; iat + 900 (15 minutes)>,
  "session_id": "<ULID for this session>",
  "iss": "samriddhi-backend",
  "aud": "samriddhi-app"
}
```

### 3.2 Session State (server-side)

The Samriddhi backend maintains session state for refresh-cookie validation:

```
session_id (ULID, primary key)
user_id
firm_id
role
created_at
last_used_at
expires_at (created_at + 8 hours)
refresh_token_hash (SHA-256 of refresh token; for verification on refresh)
revoked (boolean, set true on logout)
```

The session state lives in Postgres (per the deployment's database). Refresh requests (per FR Entry 17.1) verify against this state.

## 4. Integration Points

### 4.1 Reads From

The firm's IdP via OIDC standard endpoints (authorization, token, userinfo, JWKS, end-session). The IdP's discovery document at `/.well-known/openid-configuration` provides the endpoint URLs.

The deployment's environment configuration provides: IdP issuer URL, client_id, client_secret (for backchannel calls; not exposed to the SPA), redirect_uri, the deployment's firm_id (for validation).

### 4.2 Writes To

The Samriddhi application JWT (returned to the React app via redirect fragment or set as a short-lived auth cookie that the React app reads then clears).

The refresh cookie (HttpOnly, Secure, SameSite=Strict; readable only by the backend on subsequent requests).

The session state in Postgres (insert on auth completion, update on refresh, mark revoked on logout).

T1 telemetry events: `auth_login_initiated`, `auth_login_completed`, `auth_login_failed`, `auth_logout`. Per FR Entry 9.0 (T1 telemetry contract).

### 4.3 Read By

Every authenticated endpoint reads the application JWT (from the Authorization header) to extract user_id, firm_id, role.

The SSE channel (FR Entry 18.0) authenticates connection establishment via the application JWT.

The firm-info endpoint (consumed by the React app on auth completion) returns firm-specific configuration; the firm_id from the JWT scopes the response.

## 5. Telemetry and Observability

T1 captures four event types:

`auth_login_initiated`: emitted when the user redirects to the IdP. Includes anonymous request_id (no user identity yet), initiating IP address, user_agent.

`auth_login_completed`: emitted on successful auth completion. Includes user_id, firm_id, role, session_id, request_id.

`auth_login_failed`: emitted on auth failure. Includes failure reason (invalid_state, invalid_code, signature_failure, claim_mismatch, claim_missing), partial details if available, request_id.

`auth_logout`: emitted on logout (local or IdP-initiated). Includes user_id, session_id, logout_type (local, idp_initiated, session_expired).

Operational metrics: auth flow latency (time from authorization redirect to callback completion), failure rate, IdP availability (fraction of token endpoint calls that succeed). These are operational rather than audit; they live in Doc 4 Operations.

## 6. Failure Modes and EX1 Contract

### 6.1 IdP Unavailable

The firm's IdP is unreachable (network failure, IdP service down, JWKS endpoint not responding). The user sees a clear error page indicating that the firm's IdP is unavailable, with guidance to retry or contact firm IT support. The Samriddhi backend logs the failure to T1 and operational metrics.

EX1 routing: critical failure mode. If the IdP is down, no users can log in. The firm's IT team is notified through their existing IdP monitoring; Samriddhi operations is notified through the firm's standard incident channel. There is no graceful degradation possible; without authentication, the system cannot operate.

### 6.2 IdP Configuration Error

The IdP returns an ID token without the required `samriddhi_firm_id` or `samriddhi_role` claims. The user sees an error indicating that the firm's IdP is misconfigured for Samriddhi access, with instructions to contact firm IT. The Samriddhi backend logs the specific missing claims for the operations team to address.

EX1 routing: configuration error. The firm's IT team adds the missing claim mappings; Samriddhi operations verifies after the change.

### 6.3 Firm ID Mismatch

The IdP returns an ID token with `samriddhi_firm_id` that does not match the deployment's configured firm_id. The user sees an error indicating that they are attempting to log into the wrong firm's deployment, with the correct deployment URL if known.

EX1 routing: configuration error or user error. The firm's IT team is notified; the user is redirected to the correct firm's deployment.

### 6.4 Token Validation Failure

The ID token signature does not validate against the IdP's JWKS, or the issuer/audience/expiration is wrong. The user sees a generic authentication failure error; the specific failure reason is logged for security review.

EX1 routing: potential security issue. The operations team reviews; if it is a transient JWKS rotation issue, a JWKS cache refresh resolves it; if it is a persistent issue, the IdP integration is reviewed.

### 6.5 Refresh Token Compromise Detection

If a refresh request arrives with a refresh token that has already been used and superseded (refresh tokens rotate per RFC 6749 best practice), this is treated as potential token theft. The session is revoked, the user is forced to re-authenticate, and the security team is notified.

EX1 routing: security incident. Standard security response procedures apply.

## 7. Acceptance Criteria

The acceptance criteria for FR Entry 17.0 to be considered locked:

**Test 1.** A user can navigate to a protected route in the Samriddhi React app, get redirected to the firm's IdP, authenticate, and land back at the original route as an authenticated user.

**Test 2.** The application JWT issued after auth completion contains the correct claims (user_id, firm_id matching the deployment, role from the IdP claim, email, name, session_id).

**Test 3.** The refresh cookie is set with HttpOnly, Secure, SameSite=Strict flags and an 8-hour expiry.

**Test 4.** A user attempting to log into a deployment with a different firm_id than their IdP claim fails with a clear error.

**Test 5.** A user authenticated against an IdP that does not include the `samriddhi_role` claim fails with a clear configuration error.

**Test 6.** The PKCE code_verifier is correctly generated, persisted, and validated against the code_challenge by the IdP.

**Test 7.** Logout clears the refresh cookie, invalidates the access token, and revokes the session.

**Test 8.** T1 events for auth_login_initiated, auth_login_completed, auth_login_failed, auth_logout are emitted with the correct payload structure.

**Test 9.** The IdP's JWKS is correctly cached and refreshed; signature validation works against rotated keys.

**Test 10.** The Keycloak development IdP integration works end-to-end with the two pre-configured users.

## 8. Open Questions

None blocking cluster 0 closure. Future considerations:

Multi-IdP support per firm (some firms may want different IdPs for different user populations) is deferred. The current architecture assumes one IdP per deployment.

IdP-initiated logout (the IdP redirects users to Samriddhi's logout endpoint when their IdP session ends) is documented as optional in the firm's IdP configuration. Specific implementation pattern is firm-policy.

Step-up authentication (re-authenticating for sensitive operations like overriding governance) is deferred. Current architecture treats all authenticated sessions as equally trusted; if step-up is required by firm policy, it is added in a later cluster.

## 9. Revision History

April 2026 (cluster 0 drafting pass): Initial entry authored. Locked in cluster 0 ideation log.

May 2026 (cluster 0 chunk 0.1 shipped): Demo-stage stub auth implementation completed per Cluster 0 Dev-Mode Addendum §3.2 — `/api/v2/auth/dev-login` mints byte-identical JWTs against `dev/test_users.yaml`. Production OIDC endpoints (`/api/v2/auth/login`, `/api/v2/auth/callback`) return HTTP 501 with RFC 7807 problem details. The 10 OIDC-specific acceptance tests in §7 are deferred to the production-readiness cluster; downstream JWT-consuming code (FR 17.1, FR 17.2, FR 18.0) is unaffected because the JWT contract is unchanged. Defence-in-depth firm-id mismatch check (§6.3) is wired at the firm-info endpoint.

---

**End of FR Entry 17.0.**
