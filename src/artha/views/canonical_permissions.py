"""§14.5 — deterministic permission enforcement.

The view composer is the access gate. Per §14.5 access control is enforced
at the data-access layer, not just the UI: when a viewer requests a view
on a client, the composer first validates the request against the role's
permission scope and raises `PermissionDeniedError` on out-of-scope
access.

Three role scopes:

  * **ADVISOR** — own assigned clients only (`assigned_client_ids` must
    contain the requested `client_id`). Same-firm requirement enforced
    too — an advisor's `firm_id` must match the requested client.
  * **CIO** — any client/case in the same firm. Read + write authority
    on construction proposals, model approvals, fund universe, etc.
  * **COMPLIANCE** — any client/case in the same firm. Read-only —
    write attempts raise `PermissionDeniedError`.

The functions here surface as deterministic predicates the composers
call before producing each view. They never silently filter; they raise
on violation so the boundary is loud.
"""

from __future__ import annotations

from artha.canonical.views import (
    Role,
    ViewerContext,
)
from artha.common.errors import ArthaError


class PermissionDeniedError(ArthaError):
    """Raised when a viewer's role/scope doesn't permit the requested view."""


def assert_can_read_client(
    viewer: ViewerContext,
    *,
    client_id: str,
    client_firm_id: str,
) -> None:
    """Raise unless the viewer can read this client's data."""
    if viewer.firm_id != client_firm_id:
        raise PermissionDeniedError(
            f"viewer firm_id={viewer.firm_id!r} cannot access client in "
            f"firm_id={client_firm_id!r}"
        )

    if viewer.role is Role.ADVISOR:
        if client_id not in viewer.assigned_client_ids:
            raise PermissionDeniedError(
                f"advisor {viewer.user_id!r} is not assigned to client "
                f"{client_id!r}"
            )
        return

    # CIO + COMPLIANCE + AUDIT: firm-wide read.
    if viewer.role in (Role.CIO, Role.COMPLIANCE, Role.AUDIT):
        return

    raise PermissionDeniedError(f"unsupported viewer role {viewer.role!r}")


def assert_can_read_firm(viewer: ViewerContext, *, firm_id: str) -> None:
    """Firm-level reads (CIO dashboards, compliance aggregates).

    ADVISOR is denied firm-level reads — they only see their own clients.
    CIO and COMPLIANCE are allowed in their own firm.
    """
    if viewer.firm_id != firm_id:
        raise PermissionDeniedError(
            f"viewer firm_id={viewer.firm_id!r} cannot access firm "
            f"{firm_id!r}"
        )
    if viewer.role is Role.ADVISOR:
        raise PermissionDeniedError(
            f"advisor {viewer.user_id!r} cannot access firm-level views"
        )


def assert_can_write(viewer: ViewerContext, *, action: str) -> None:
    """Raise on write attempts the role can't perform.

    Pass 18 enforces the read-only contract for COMPLIANCE; Doc 2 (API spec)
    adds AUDIT with the same read-only constraint. CIO + ADVISOR write
    authorities are differentiated downstream by the individual write-
    handlers (e.g. ConstructionOrchestrator already expects CIO authority).
    """
    if viewer.role in (Role.COMPLIANCE, Role.AUDIT):
        raise PermissionDeniedError(
            f"{viewer.role.value} role is read-only; cannot perform {action!r}"
        )


def is_in_scope_client(viewer: ViewerContext, *, client_id: str) -> bool:
    """Non-throwing scope check used by composers that aggregate across clients.

    CIO and COMPLIANCE see every client in their firm; ADVISOR sees only
    `assigned_client_ids`.
    """
    if viewer.role is Role.ADVISOR:
        return client_id in viewer.assigned_client_ids
    return True


__all__ = [
    "PermissionDeniedError",
    "assert_can_read_client",
    "assert_can_read_firm",
    "assert_can_write",
    "is_in_scope_client",
]
