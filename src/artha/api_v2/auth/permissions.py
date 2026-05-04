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
