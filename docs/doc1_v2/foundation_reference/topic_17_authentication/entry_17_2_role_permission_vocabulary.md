# Foundation Reference Entry 17.2: Role-Permission Vocabulary

**Topic:** 17 Authentication and Identity
**Entry:** 17.2
**Title:** Role-Permission Vocabulary
**Status:** Locked skeleton (cluster 0; chunk 0.1 shipped May 2026); permission list grows in subsequent clusters
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 17.0 (OIDC Authentication; this entry's roles come from IdP claims)
- FR Entry 17.1 (JWT Session Management; this entry's roles are encoded in JWTs)
- All future endpoint specifications (consume permission flags from this entry)
- CP Chunk 0.2 (role-based home tree routing depends on this entry)

## Cross-references Out

- FR Entry 17.0 (where the role claim originates)
- Doc 2 Pass 3a §2 (the candidate role-permission vocabulary that this entry inherits)

---

## 1. Purpose

The Role-Permission Vocabulary defines the four user roles in Samriddhi AI and the permission flags that gate access to specific operations. Roles are coarse-grained categories matching the firm's organisational structure; permissions are fine-grained capabilities that compose to authorise specific actions.

This entry is a skeleton in cluster 0. The four roles are locked. The permissions list contains only the cluster 0 minimum (auth and SSE permissions). As subsequent clusters introduce components and endpoints, they add the permissions they need to this vocabulary. The complete vocabulary emerges incrementally cluster by cluster.

Doc 2 Pass 3a §2 specified a candidate vocabulary covering the full v1.0 endpoint surface. That vocabulary is the target end-state; this entry's growth path leads to it.

## 2. The Four Roles

### 2.1 Advisor

The advisor role is the firm's wealth advisor. They manage their own book of clients (typically 50 to 200 HNI investors), open cases on behalf of those clients, review evidence and synthesis output, record decisions, and respond to alerts.

The advisor's data scope is "own book": they see their own investors, their own cases, their own alerts. They do not see firm-wide aggregates or other advisors' books unless firm policy explicitly grants broader access.

Default permissions in cluster 0: `auth:session:read`, `auth:session:logout`, `events:subscribe:own_scope`, `system:firm_info:read`.

### 2.2 CIO

The CIO (Chief Investment Officer) role is the firm's investment leader. They oversee the model portfolio, govern construction-pipeline approvals, review IC1 deliberations, approve overrides, set firm-level policy that affects investment governance.

The CIO's data scope is firm-wide: they see all advisors' books, all cases, all alerts, all model portfolio versions, all proposals from T2.

Default permissions in cluster 0: `auth:session:read`, `auth:session:logout`, `events:subscribe:firm_scope`, `system:firm_info:read`.

### 2.3 Compliance

The compliance role is the firm's regulatory officer. They review override events, audit decision trails, oversee the rule corpus, ensure regulatory alignment.

The compliance role's data scope is firm-wide read-only for most surfaces, plus mutation rights on specific compliance surfaces (rule corpus updates, override post-hoc review).

Default permissions in cluster 0: `auth:session:read`, `auth:session:logout`, `events:subscribe:firm_scope`, `system:firm_info:read`.

### 2.4 Audit

The audit role is the firm's auditor (internal audit team or external auditor). They reconstruct cases from T1 telemetry, verify replay invariants, produce audit reports.

The audit role's data scope is firm-wide read-only. Audit cannot mutate any state; the role exists to verify, not to act.

Default permissions in cluster 0: `auth:session:read`, `auth:session:logout`, `events:subscribe:firm_scope`, `system:firm_info:read`.

## 3. Permission Naming Convention

Permissions follow the format `<resource>:<verb>:<scope>` where:

`<resource>` is the resource family (e.g., `cases`, `investors`, `alerts`, `model_portfolio`, `governance`, `telemetry`).

`<verb>` is the action (e.g., `read`, `write`, `approve`, `override`, `subscribe`).

`<scope>` is optional and constrains the access (e.g., `own_book` for advisor-scoped data, `firm_scope` for firm-wide, `own_scope` for user-only).

Examples that will appear in later clusters:

`cases:read:own_book` (advisor reads cases for their own clients)

`cases:read:firm_scope` (CIO, compliance, audit read all cases)

`cases:write:own_book` (advisor creates and modifies cases for their clients)

`model_portfolio:approve` (CIO approves model portfolio versions)

`overrides:approve` (CIO and compliance cosign overrides)

`telemetry:read:firm_scope` (audit reads all telemetry)

This naming convention is consistent with industry practice (similar patterns in AWS IAM, GCP IAM, Auth0, Okta).

## 4. Permission Composition

Permissions compose via union: a user has a permission if their role grants it. There is no permission revocation per user (deny rules); the role-to-permission mapping is the authoritative source.

If a user has multiple roles (rare in MVP, but possible in some firm structures), permissions union across roles. For example, a user with both advisor and compliance roles has the union of advisor permissions and compliance permissions.

The role-to-permission mapping is configured per deployment (some firms may want to grant or revoke specific permissions for specific roles, e.g., a firm where the advisor role can also approve overrides). The configuration is in the deployment's environment settings; defaults are provided.

## 5. Permission Enforcement

Permissions are checked at the API endpoint level. FastAPI dependency injection extracts the JWT, resolves the user's role, looks up the role's permissions, and checks whether the required permission for the endpoint is granted.

Each endpoint declares its required permission(s) in its FastAPI route declaration. A request that lacks the required permission returns HTTP 403 with a problem detail (per Doc 2 Pass 1 Decision 6 RFC 7807 envelope) indicating the missing permission.

## 6. Cluster 0 Permission Set

The cluster 0 minimum permissions are:

`auth:session:read`: read the current session details (user identity, role, firm, expiration). All four roles have this permission.

`auth:session:logout`: invalidate the current session. All four roles.

`events:subscribe:own_scope`: subscribe to SSE events scoped to the user's own data (advisor receives events for their own book; events outside their scope are not delivered).

`events:subscribe:firm_scope`: subscribe to SSE events firm-wide. CIO, compliance, audit have this; advisor does not.

`system:firm_info:read`: read the firm-info endpoint (firm name, branding, feature flags). All four roles.

These five permissions are sufficient for cluster 0's chunks (0.1 placeholder dashboard with SSE connection, 0.2 role-based home tree routing).

## 7. Future Cluster Permission Growth

As clusters ship, they add permissions to this entry. The pattern:

Cluster 1 (investor onboarding) adds: `investors:read:own_book`, `investors:write:own_book` for advisor; `investors:read:firm_scope` for CIO/compliance/audit.

Cluster 2 (mandate management) adds: `mandates:read:own_book`, `mandates:write:own_book`; `mandates:approve` for CIO.

And so on through subsequent clusters.

When a cluster adds permissions, this entry is revised: new permissions are added to Section 6 (now retitled "Permission Set as of Current Cluster" or similar), the role-to-permission mapping is extended, and the revision history records the change.

By the time cluster 17 ships, this entry contains the complete permission set for v1.0. At that point, it should match the candidate vocabulary in Doc 2 Pass 3a §2 (modulo any specific changes that emerged during cluster work).

## 8. Acceptance Criteria for Cluster 0 Skeleton

**Test 1.** The four roles (advisor, cio, compliance, audit) are recognised by the auth layer.

**Test 2.** The five cluster 0 permissions are correctly granted to the four roles per the role-to-permission mapping in Section 6.

**Test 3.** A user with role `advisor` cannot subscribe to firm-scope SSE events; the subscription returns HTTP 403.

**Test 4.** A user with role `cio` can subscribe to firm-scope SSE events.

**Test 5.** All four roles can read firm-info.

**Test 6.** The role-based home tree routing in chunk 0.2 correctly redirects each role to their respective home tree.

## 9. Open Questions

The role-to-permission mapping is locked at deployment time but firm policy may require runtime adjustments (e.g., CIO temporarily delegates approval authority to a senior advisor). Whether this is supported in v1.0 or deferred to v2 is open. Working answer: deferred to v2; v1.0 has static role-to-permission mappings per deployment.

Multi-role users (a user with both advisor and CIO roles) are theoretically supported via permission union but not exercised at cluster 0. Whether the IdP claim allows multiple roles in a single token, or whether multi-role users authenticate twice (once per role), is open. Working answer: deferred until first multi-role user requirement actually emerges.

Permission inheritance (e.g., compliance role inherits all audit permissions plus has additional compliance-specific permissions) is not used in cluster 0. Whether to introduce hierarchical permissions later is open. Working answer: keep flat composition for now; inheritance can be added if it simplifies policy expression.

## 10. Revision History

April 2026 (cluster 0 drafting pass): Initial skeleton authored with four roles and five cluster 0 permissions. Subsequent clusters will extend.

May 2026 (cluster 0 chunk 0.1 shipped): Implementation completed. `Permission` enum + `ROLE_PERMISSIONS` dict + `require_permission(*perms, mode='all'|'any')` FastAPI dep factory in `src/artha/api_v2/auth/permissions.py`. Wired to whoami (AUTH_SESSION_READ), firm-info (SYSTEM_FIRM_INFO_READ), events/stream (EVENTS_SUBSCRIBE_OWN_SCOPE OR EVENTS_SUBSCRIBE_FIRM_SCOPE, mode='any'). All 6 acceptance tests in §8 verified via `tests/test_unit/test_api_v2_permissions.py`. Logout endpoint not gated on AUTH_SESSION_LOGOUT (cookie-based, not Bearer); the permission stays reserved for the future admin-revoke endpoint described in FR 17.1 §2.5.

---

**End of FR Entry 17.2 (skeleton; locked for cluster 0; subsequent revisions append permissions).**
