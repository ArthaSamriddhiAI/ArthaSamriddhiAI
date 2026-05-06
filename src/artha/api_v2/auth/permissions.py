"""Role-permission vocabulary + FastAPI gate dependencies.

Per FR Entry 17.2:

- §2: four roles (advisor, cio, compliance, audit).
- §3: naming convention ``<resource>:<verb>:<scope>``.
- §4: union composition; no per-user deny rules.
- §5: enforcement at the API endpoint level via FastAPI dependency injection.
- §6: cluster 0 ships exactly five permissions (the auth-and-events minimum).

This module is the SKELETON the FR entry describes. Subsequent clusters
extend :class:`Permission` and :data:`ROLE_PERMISSIONS` as they introduce new
endpoints (cluster 1 adds ``investors:read:own_book`` etc., cluster 2 adds
``mandates:*``, and so on through cluster 17 — at which point the vocabulary
matches the candidate set originally drafted in Doc 2 Pass 3a §2).

Wire-up pattern at the route level::

    @router.get("/some-endpoint")
    async def handler(user: Annotated[UserContext, Depends(require_permission(Permission.X))]):
        ...

For "user must have at least one of these permissions"::

    Depends(require_permission(Permission.A, Permission.B, mode="any"))
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status

from artha.api_v2.auth.dependencies import get_current_user
from artha.api_v2.auth.user_context import Role, UserContext


class Permission(str, Enum):
    """The active permission set. Cluster 0 introduced 5 entries; subsequent
    clusters APPEND new entries per FR 17.2 §7's growth pattern.

    String values follow ``<resource>:<verb>:<scope>`` (FR 17.2 §3) so they
    survive serialisation cleanly (JWT scope claim, audit log, admin UI).
    """

    # ---- Cluster 0 (chunks 0.1, 0.2) ----
    AUTH_SESSION_READ = "auth:session:read"
    AUTH_SESSION_LOGOUT = "auth:session:logout"
    EVENTS_SUBSCRIBE_OWN_SCOPE = "events:subscribe:own_scope"
    EVENTS_SUBSCRIBE_FIRM_SCOPE = "events:subscribe:firm_scope"
    SYSTEM_FIRM_INFO_READ = "system:firm_info:read"

    # ---- Cluster 1 chunk 1.1 (investor onboarding + I0 enrichment) ----
    INVESTORS_READ_OWN_BOOK = "investors:read:own_book"
    INVESTORS_READ_FIRM_SCOPE = "investors:read:firm_scope"
    INVESTORS_WRITE_OWN_BOOK = "investors:write:own_book"
    HOUSEHOLDS_READ_OWN_BOOK = "households:read:own_book"
    HOUSEHOLDS_READ_FIRM_SCOPE = "households:read:firm_scope"
    HOUSEHOLDS_WRITE_OWN_BOOK = "households:write:own_book"

    # ---- Cluster 1 chunk 1.3 (SmartLLMRouter settings UI) ----
    # CIO-only — provider configuration, API keys, kill switch (FR 16.0 §4.2,
    # §6, §7). Compliance + Audit get firm-wide visibility into who configured
    # what via the T1 ledger but cannot read/write the keys themselves.
    SYSTEM_LLM_CONFIG_READ = "system:llm_config:read"
    SYSTEM_LLM_CONFIG_WRITE = "system:llm_config:write"

    # ---- Cluster 1 chunk 1.2 (C0 conversational onboarding) ----
    # Each advisor owns their own conversations; CIO/compliance/audit see
    # firm-wide for governance. The same own-book vs firm-scope split that
    # investors use, applied to the conversation thread.
    CONVERSATIONS_READ_OWN_BOOK = "conversations:read:own_book"
    CONVERSATIONS_READ_FIRM_SCOPE = "conversations:read:firm_scope"
    CONVERSATIONS_WRITE_OWN_BOOK = "conversations:write:own_book"

    # ---- Cluster 2 chunks 2.1, 2.3 (mandate management) ----
    # Advisor creates + amends mandates on their own book. CIO/compliance/audit
    # read firm-wide for governance. The CIO additionally holds
    # ``mandates:approve:firm_scope`` for amendment approval (FR 12.2 §4.4).
    MANDATES_READ_OWN_BOOK = "mandates:read:own_book"
    MANDATES_READ_FIRM_SCOPE = "mandates:read:firm_scope"
    MANDATES_WRITE_OWN_BOOK = "mandates:write:own_book"
    MANDATES_APPROVE_FIRM_SCOPE = "mandates:approve:firm_scope"

    # ---- Cluster 3 chunks 3.1–3.4 (D0 admin surface) ----
    # Audit-role-only — adapter management, staging queries, canonical-entity
    # browsing, snapshot demo tool, freshness UI. Per cluster 3 demo addendum
    # §1.18: cluster 3 grants the audit role full access; finer-grained RBAC
    # is deferred to production-readiness. Compliance + CIO get read access
    # for governance visibility but cannot trigger adapter runs.
    D0_ADMIN_READ = "d0:admin:read"
    D0_ADMIN_WRITE = "d0:admin:write"

    # ---- Cluster 4 (M2 Model Portfolio) ----
    # CIO is the sole editor (FR 13.0 §5.1: "no multi-approver flow"). Advisor
    # gets read so they can understand the firm's preferred portfolio for case
    # construction. Compliance + audit get read for governance visibility.
    MODEL_PORTFOLIO_READ = "model_portfolio:read"
    MODEL_PORTFOLIO_WRITE = "model_portfolio:write"

    # ---- Cluster 5 (Case framework) ----
    # Per cluster 5 chunk plan §8.2 + FR Entry 17.2 cluster-5 revision.
    #
    # Advisors open + view their own book's cases. CIO opens cases firm-wide
    # AND records decisions on cases sent up for committee review. Compliance
    # + audit see firm-wide cases for governance trail. Senior-advisor
    # case-decision authority is reserved for production-readiness; cluster 5
    # ships CIO-only decision recording per FR 20.4 §7.1.
    CASES_CREATE_OWN_BOOK = "cases:create:own_book"
    CASES_CREATE_FIRM_SCOPE = "cases:create:firm_scope"
    CASES_READ_OWN_BOOK = "cases:read:own_book"
    CASES_READ_FIRM_SCOPE = "cases:read:firm_scope"
    CASES_DECIDE_FIRM_SCOPE = "cases:decide:firm_scope"
    # Demo seed framework — CIO-only per FR 19.0 §3.2 and chunk 5.6 plan.
    SEED_ADMIN = "seed:admin"


# Cluster 0 role-to-permission mapping per FR 17.2 §2 / §6.
# Frozen so accidental mutation at module level is prevented; configurable
# per-deployment overrides (FR 17.2 §4 final paragraph) come in a future cluster.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADVISOR: frozenset({
        # Cluster 0
        Permission.AUTH_SESSION_READ,
        Permission.AUTH_SESSION_LOGOUT,
        Permission.EVENTS_SUBSCRIBE_OWN_SCOPE,
        Permission.SYSTEM_FIRM_INFO_READ,
        # Cluster 1 chunk 1.1 — advisor manages their own book of investors
        Permission.INVESTORS_READ_OWN_BOOK,
        Permission.INVESTORS_WRITE_OWN_BOOK,
        Permission.HOUSEHOLDS_READ_OWN_BOOK,
        Permission.HOUSEHOLDS_WRITE_OWN_BOOK,
        # Cluster 1 chunk 1.2 — advisor drives their own conversations
        Permission.CONVERSATIONS_READ_OWN_BOOK,
        Permission.CONVERSATIONS_WRITE_OWN_BOOK,
        # Cluster 2 — advisor creates + amends mandates on their own book
        Permission.MANDATES_READ_OWN_BOOK,
        Permission.MANDATES_WRITE_OWN_BOOK,
        # Cluster 4 — advisor reads model portfolio for case construction
        # context (FR 11.0 cluster 4 revision §2.3); only CIO writes.
        Permission.MODEL_PORTFOLIO_READ,
        # Cluster 5 — advisor opens + views cases on their own book.
        # Decision recording is CIO-only (FR 20.4 §7.1).
        Permission.CASES_CREATE_OWN_BOOK,
        Permission.CASES_READ_OWN_BOOK,
    }),
    Role.CIO: frozenset({
        # Cluster 0
        Permission.AUTH_SESSION_READ,
        Permission.AUTH_SESSION_LOGOUT,
        Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE,
        Permission.SYSTEM_FIRM_INFO_READ,
        # Cluster 1 chunk 1.1 — CIO has firm-wide read for oversight, no write
        # (investor onboarding is the advisor's surface; CIO governance comes
        # in later clusters via mandate / model-portfolio surfaces).
        Permission.INVESTORS_READ_FIRM_SCOPE,
        Permission.HOUSEHOLDS_READ_FIRM_SCOPE,
        # Cluster 1 chunk 1.3 — CIO is the sole role that configures the
        # SmartLLMRouter (FR 16.0 §4.2). Other roles see neither the page
        # nor the API.
        Permission.SYSTEM_LLM_CONFIG_READ,
        Permission.SYSTEM_LLM_CONFIG_WRITE,
        # Cluster 1 chunk 1.2 — CIO reads firm-wide conversations for
        # governance; advisor onboarding flow is the advisor's own surface,
        # so CIO does not write here.
        Permission.CONVERSATIONS_READ_FIRM_SCOPE,
        # Cluster 2 chunk 2.3 — CIO is the sole approver of mandate
        # amendments (single-CIO approval per cluster 2 demo addendum §1.2).
        # Read firm-wide for the pending queue + diff review.
        Permission.MANDATES_READ_FIRM_SCOPE,
        Permission.MANDATES_APPROVE_FIRM_SCOPE,
        # Cluster 3 — CIO reads D0 admin surfaces for governance visibility.
        Permission.D0_ADMIN_READ,
        # Cluster 4 — CIO is the sole editor of the model portfolio
        # (FR 13.0 §5.1). Read + write.
        Permission.MODEL_PORTFOLIO_READ,
        Permission.MODEL_PORTFOLIO_WRITE,
        # Cluster 5 — CIO opens cases firm-wide, reviews + decides on cases
        # sent up via materiality gate (FR 20.4 §7.1). Also runs the demo
        # seed framework (FR 19.0 §3.2).
        Permission.CASES_CREATE_FIRM_SCOPE,
        Permission.CASES_READ_FIRM_SCOPE,
        Permission.CASES_DECIDE_FIRM_SCOPE,
        Permission.SEED_ADMIN,
    }),
    Role.COMPLIANCE: frozenset({
        # Cluster 0
        Permission.AUTH_SESSION_READ,
        Permission.AUTH_SESSION_LOGOUT,
        Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE,
        Permission.SYSTEM_FIRM_INFO_READ,
        # Cluster 1 chunk 1.1 — compliance has firm-wide read for audit trail.
        Permission.INVESTORS_READ_FIRM_SCOPE,
        Permission.HOUSEHOLDS_READ_FIRM_SCOPE,
        # Cluster 1 chunk 1.2 — compliance reads firm-wide conversations.
        Permission.CONVERSATIONS_READ_FIRM_SCOPE,
        # Cluster 2 — compliance reads firm-wide mandates for audit trail.
        Permission.MANDATES_READ_FIRM_SCOPE,
        # Cluster 3 — compliance reads D0 admin surfaces.
        Permission.D0_ADMIN_READ,
        # Cluster 4 — compliance reads model portfolio for governance audit.
        Permission.MODEL_PORTFOLIO_READ,
        # Cluster 5 — compliance reads cases firm-wide for governance trail.
        Permission.CASES_READ_FIRM_SCOPE,
    }),
    Role.AUDIT: frozenset({
        # Cluster 0
        Permission.AUTH_SESSION_READ,
        Permission.AUTH_SESSION_LOGOUT,
        Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE,
        Permission.SYSTEM_FIRM_INFO_READ,
        # Cluster 1 chunk 1.1 — audit reads everything firm-wide read-only.
        Permission.INVESTORS_READ_FIRM_SCOPE,
        Permission.HOUSEHOLDS_READ_FIRM_SCOPE,
        # Cluster 1 chunk 1.2 — audit reads firm-wide conversations.
        Permission.CONVERSATIONS_READ_FIRM_SCOPE,
        # Cluster 2 — audit reads everything firm-wide read-only.
        Permission.MANDATES_READ_FIRM_SCOPE,
        # Cluster 3 — audit role is the primary D0 admin actor (chunk plan
        # §3.1 §scope_in: "admin endpoints (audit role only)"). Audit gets
        # both read AND write so they can trigger adapter runs + create
        # snapshots from the demo tool.
        Permission.D0_ADMIN_READ,
        Permission.D0_ADMIN_WRITE,
        # Cluster 4 — audit reads model portfolio for governance audit.
        Permission.MODEL_PORTFOLIO_READ,
        # Cluster 5 — audit reads cases firm-wide read-only for governance.
        Permission.CASES_READ_FIRM_SCOPE,
    }),
}


def permissions_for(role: Role) -> frozenset[Permission]:
    """Return the active permission set for one role."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def user_has_permission(user: UserContext, permission: Permission) -> bool:
    """Return True if the user's role grants the given permission."""
    return permission in permissions_for(user.role)


# ---------------------------------------------------------------------------
# FastAPI dependency factories
# ---------------------------------------------------------------------------


def _forbidden(missing: list[str], required_mode: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Missing required permission ({required_mode} of): {', '.join(missing)}"
        ),
    )


def require_permission(
    *permissions: Permission,
    mode: Literal["all", "any"] = "all",
) -> Callable[[UserContext], UserContext]:
    """Return a FastAPI dependency that gates on the given permissions.

    ``mode="all"`` (default): user must have every listed permission.
    ``mode="any"``: user must have at least one listed permission.
    """

    if not permissions:
        raise ValueError("require_permission needs at least one Permission")

    permission_values = [p.value for p in permissions]

    async def _dep(
        user: Annotated[UserContext, Depends(get_current_user)],
    ) -> UserContext:
        granted = permissions_for(user.role)
        if mode == "all":
            missing = [p.value for p in permissions if p not in granted]
            if missing:
                raise _forbidden(missing, "all")
        else:  # any
            if not any(p in granted for p in permissions):
                raise _forbidden(permission_values, "any")
        return user

    return _dep
