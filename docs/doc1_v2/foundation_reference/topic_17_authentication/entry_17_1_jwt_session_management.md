# Foundation Reference Entry 17.1: JWT and Session Management

**Topic:** 17 Authentication and Identity
**Entry:** 17.1
**Title:** JWT and Session Management
**Status:** Locked (cluster 0; chunk 0.1 shipped May 2026)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 17.0 (OIDC Authentication; this entry consumes auth completion output)
- FR Entry 18.0 (SSE Channel Overview; SSE auth uses JWT issued here)
- CP Chunk 0.1 (walking skeleton chunk depends on this entry)
- All future authenticated API endpoints (this entry's JWT is the auth mechanism)

## Cross-references Out

- FR Entry 17.0 (OIDC Authentication; the upstream auth flow)
- Principles §6.0 (LLM provider strategy; not directly related)

---

## 1. Purpose

JWT and Session Management is the post-authentication session lifecycle. After OIDC authentication completes (per FR Entry 17.0), this component issues, refreshes, validates, and revokes the application JWT and refresh cookie that authorise every subsequent request.

The component implements the 15-minute access token plus 8-hour refresh cookie split that is locked in Doc 2 Pass 1 Decision 2 and the Principles document. This split balances three concerns: short access tokens limit blast radius if a token is compromised; long refresh sessions avoid forcing users to re-authenticate every 15 minutes; the HttpOnly refresh cookie cannot be exfiltrated by JavaScript even if the SPA is compromised.

## 2. Functional Specification

### 2.1 JWT Issuance

After OIDC auth completion, the backend issues an application JWT signed with the deployment's signing key (HS256 or RS256; HS256 is simpler for single-deployment firms, RS256 enables key rotation without full re-issuance). The signing key is per-deployment configuration; it does not need to be the same as the IdP's signing key.

The JWT has a 15-minute lifetime from issuance. Claims structure is per FR Entry 17.0 §3.1.

### 2.2 Refresh Cookie

A separate refresh cookie is set on auth completion. The cookie value is a cryptographically random opaque token (32 bytes, base64url-encoded). The cookie attributes:

`HttpOnly`: prevents JavaScript access, protecting against XSS-based exfiltration.

`Secure`: requires HTTPS, preventing interception over insecure channels.

`SameSite=Strict`: prevents the cookie being sent on cross-origin requests, protecting against CSRF.

`Path=/api/v2/auth/refresh`: the cookie is only sent on the refresh endpoint, minimising exposure.

`Max-Age=28800`: 8-hour expiry from issuance.

The refresh token's hashed value (SHA-256) is persisted in the session state in Postgres. The original refresh token value is set in the cookie but never logged, never persisted in plain text.

### 2.3 Refresh Flow

When the React app's access token approaches expiry (60 seconds before the 15-minute window closes), the SSE channel emits `token_refresh_required` (per FR Entry 18.0 §1.11). The React app calls `POST /api/v2/auth/refresh`, which sends the refresh cookie automatically (the browser includes the cookie because the request is to the cookie's Path).

The backend validates the refresh request:

Step 1: Read the refresh cookie value.

Step 2: Hash the cookie value (SHA-256).

Step 3: Look up the session in Postgres by `refresh_token_hash`.

Step 4: Verify the session is not revoked, has not expired (8-hour window), and has not been superseded (refresh token rotation per Step 6 below).

Step 5: Issue a new application JWT (15-minute lifetime, fresh `iat` and `exp`).

Step 6: Issue a new refresh token (cryptographically random, 32 bytes), hash it, update the session's `refresh_token_hash` to the new value, mark the old refresh token as superseded. Set the new refresh cookie with the same attributes as the original.

Step 7: Return the new application JWT in the response body. Update `last_used_at` on the session.

If any validation step fails, the response is HTTP 401 with a problem detail (per Doc 2 Pass 1 Decision 6 RFC 7807 envelope) indicating the failure mode (`token_invalid`, `session_revoked`, `session_expired`).

If a refresh token is presented that has already been superseded (i.e., it was used and a new one was issued, but somehow the original is being presented again), this is treated as potential token theft per FR Entry 17.0 §6.5. The session is revoked, all subsequent refresh attempts fail, and the user must re-authenticate via OIDC.

### 2.4 Access Token Validation on Requests

Every authenticated API request includes the application JWT in the `Authorization: Bearer <jwt>` header. FastAPI's dependency injection extracts the JWT, validates the signature against the deployment's signing key, validates the `iat` and `exp` (token must be currently valid), and parses the claims.

If the JWT is invalid, missing, or expired, the response is HTTP 401 with a problem detail. The React app catches this and triggers the refresh flow (or a redirect to login if refresh also fails).

### 2.5 Session Revocation

A session is revoked in three scenarios:

User-initiated logout (via the user menu in the React app): the refresh cookie is cleared, the session is marked revoked in Postgres, the access token is added to a short-lived denylist (until natural 15-minute expiry).

Refresh token theft detection (per §2.3): the session is revoked, all refresh attempts fail.

Administrative session revocation (firm IT or compliance revoking a user's access): an admin endpoint marks the session revoked. Any in-flight access token continues working until natural expiry; the next refresh attempt fails.

Revoked sessions are retained in Postgres for audit purposes (per the principles document's append-only T1 invariant).

### 2.6 Session Limits

The maximum number of concurrent active sessions per user is configurable per deployment. The default is 3 (e.g., a user's laptop, phone web, and tablet web sessions). When the user creates a fourth session, the oldest active session is automatically revoked.

This prevents stale session accumulation and limits exposure if a user forgets to log out from a public computer.

## 3. Schema

### 3.1 Application JWT

Per FR Entry 17.0 §3.1.

### 3.2 Session State (Postgres)

```
sessions:
  session_id (ULID, primary key)
  user_id (string, indexed)
  firm_id (string)
  role (string)
  created_at (timestamp with timezone)
  last_used_at (timestamp with timezone)
  expires_at (timestamp with timezone; created_at + 8 hours)
  refresh_token_hash (binary 32 bytes; SHA-256 of current refresh token)
  refresh_token_superseded_at (timestamp; null until rotation)
  revoked (boolean)
  revoked_at (timestamp; null unless revoked)
  revocation_reason (enum: user_logout, admin_revoked, theft_detected, expired)
  user_agent (string; for audit)
  ip_address (string; first request's IP, for audit)
```

Indexes: by `user_id` (for user's session list), by `refresh_token_hash` (for refresh validation), by `expires_at` (for cleanup of expired sessions).

### 3.3 Refresh Endpoint Response

```json
{
  "access_token": "<new JWT>",
  "expires_in": 900,
  "token_type": "Bearer"
}
```

The new refresh cookie is set via the `Set-Cookie` response header; not in the body.

## 4. Integration Points

### 4.1 Reads From

The deployment's signing key from environment configuration. The Postgres database for session state.

The refresh cookie from incoming requests to `/api/v2/auth/refresh`.

The Authorization header from incoming requests to authenticated endpoints.

### 4.2 Writes To

The Postgres `sessions` table on auth completion (insert) and on refresh (update).

The HTTP response on refresh and logout (Set-Cookie header for refresh cookie, response body for new access token).

T1 telemetry events: `session_created`, `session_refreshed`, `session_revoked`, `session_expired`. Per FR Entry 9.0.

The access token denylist (in-memory or Redis cache; short-lived, 15-minute TTL).

### 4.3 Read By

Every authenticated API endpoint reads the JWT to extract user context.

The SSE channel (FR Entry 18.0) for connection establishment authentication.

The session listing endpoint (`/api/v2/auth/sessions`, available to all authenticated users) returns the user's active sessions for review.

## 5. Telemetry and Observability

T1 captures four event types:

`session_created`: emitted on new session creation (after auth completion). Includes session_id, user_id, firm_id, role, user_agent, ip_address.

`session_refreshed`: emitted on each refresh. Includes session_id, refresh_count (incrementing), latency_ms.

`session_revoked`: emitted on revocation. Includes session_id, revocation_reason, revoking_actor_id (the user themselves for logout, the admin user for admin-revoked).

`session_expired`: emitted when a session's 8-hour expiry is reached without explicit revocation.

Operational metrics: refresh latency, refresh failure rate, sessions per user (monitoring for anomalies), session lifetime distribution. These are operational rather than audit; they live in Doc 4 Operations.

## 6. Failure Modes and EX1 Contract

### 6.1 JWT Signing Key Rotation

The deployment's signing key may need rotation (key compromise, scheduled rotation per security policy). The rotation process is documented in Doc 4 Operations. The application supports a rotation window: during the window, both old and new keys are accepted for validation; after the window, only the new key is accepted.

Tokens issued before rotation continue to validate during the rotation window; after the window, those tokens fail and the user is forced to re-authenticate via OIDC.

EX1 routing: planned operational event. Non-emergency.

### 6.2 Postgres Session Store Unavailable

The Postgres database is unreachable. Authenticated requests cannot be processed because session validation fails. The user sees a 503 error.

EX1 routing: critical failure mode. Same severity as IdP unavailable. Operations response is the same: monitoring alerts, incident response procedures.

### 6.3 Clock Skew

The deployment's clock is significantly off from the IdP's clock. JWT validation may fail spuriously (`exp` appears already past, or `iat` appears in the future). The deployment's NTP configuration must be correct; this is a Doc 4 Operations concern but the application surfaces clock-skew errors with sufficient detail for ops to diagnose.

A small skew tolerance (60 seconds) is built into JWT validation to handle minor clock differences.

### 6.4 Refresh Token Race Condition

Two refresh requests arrive concurrently with the same refresh token (e.g., two browser tabs both refreshing simultaneously). Without protection, both might succeed, leaving the session in an ambiguous state.

The race is prevented by atomic update on the session row in Postgres: the refresh request's UPDATE statement includes a WHERE clause that requires the current refresh_token_hash to match the presented token. If two requests race, only one will succeed; the other will see no rows updated and will return a 409 Conflict with a refresh-in-progress problem detail. The losing request retries, gets the new refresh token from the winner's cookie update, and succeeds.

### 6.5 Mass Session Revocation

Compliance or admin needs to revoke all active sessions firm-wide (incident response, suspected breach). An admin endpoint marks all sessions in the deployment as revoked. All access tokens become invalid on next refresh; new authentications via OIDC succeed normally.

EX1 routing: incident response. Standard security procedures apply.

## 7. Acceptance Criteria

**Test 1.** After OIDC auth completion, a new session is created in Postgres with correct fields, an application JWT is returned to the React app, and a refresh cookie is set with HttpOnly, Secure, SameSite=Strict.

**Test 2.** An authenticated request with a valid JWT succeeds; an authenticated request with no JWT, an expired JWT, or a malformed JWT fails with HTTP 401.

**Test 3.** A refresh request with a valid refresh cookie succeeds, returns a new JWT, and sets a new refresh cookie.

**Test 4.** A refresh request with an expired refresh cookie fails with HTTP 401 and the user is forced to re-authenticate via OIDC.

**Test 5.** A refresh token, once used and rotated, fails on subsequent use; the session is revoked.

**Test 6.** Logout clears the refresh cookie and marks the session revoked.

**Test 7.** Concurrent refresh requests for the same session race correctly; only one succeeds, the other fails cleanly with a retry-able error.

**Test 8.** Session limit enforcement: when a user creates a fourth session, the oldest active session is revoked automatically.

**Test 9.** Admin revocation of all firm sessions takes effect on next refresh attempt.

**Test 10.** T1 events for session_created, session_refreshed, session_revoked, session_expired are emitted with correct payload structure.

## 8. Open Questions

The session limit default of 3 may need adjustment per firm. Some firms may want 1 (single-device policy) or unlimited (developer-friendly). Configurable per deployment; the default is reasonable.

The signing key strategy (HS256 with shared secret vs RS256 with public/private keypair) is locked as configurable per deployment. The default is HS256 because it is simpler for single-deployment firms; RS256 is recommended when key rotation matters or when other services need to validate JWTs without the signing secret.

Step-up authentication for sensitive operations is deferred. If a firm policy requires re-authentication for overrides or model portfolio changes, a future cluster adds the mechanism.

## 9. Revision History

April 2026 (cluster 0 drafting pass): Initial entry authored. Locked in cluster 0 ideation log.

May 2026 (cluster 0 chunk 0.1 shipped): Implementation completed. `sessions` table created via Alembic migration `370839f7aeeb_cluster_0_sessions_t1_events.py`. All 10 acceptance tests in §7 verified via `tests/test_unit/test_api_v2_auth.py`. Two minor schema extensions over the §3.2 spec, both documented in `src/artha/api_v2/auth/models.py`: (1) ``previous_refresh_token_hash`` column added for refresh-token theft detection per §6.5 (FR text describes the behaviour but doesn't specify storage); (2) ``email`` and ``name`` columns added so the JWT contract (FR 17.0 §3.1 claims) survives refresh-token rotation without round-tripping to the IdP. Race-condition protection per §6.4 implemented via atomic UPDATE; lost-race returns HTTP 409.

---

**End of FR Entry 17.1.**
