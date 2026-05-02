"""Subscription scope resolution from role.

Per FR Entry 18.0 §2.6 and FR Entry 17.2 §6:

- Advisor → ``own_scope`` for alerts/cases/monitoring (sees only own-book data).
- CIO, Compliance, Audit → ``firm_scope`` for everything (firm-wide visibility).

The scope is applied at emission time on the backend (FR 18.0 §2.6: "The
filter is applied at emission time on the backend, not at receive time on
the client. This protects scope confidentiality (an advisor cannot see
another advisor's events even by inspecting network traffic)."). For
cluster 0, no events outside the connection lifecycle actually fire, so
the filter has no observable behaviour yet — but the scope is recorded on
the connection so future-cluster emitters use it.
"""

from __future__ import annotations

from artha.api_v2.auth.user_context import Role
from artha.api_v2.events.envelope import SubscriptionScope

OWN_SCOPE = "own_scope"
FIRM_SCOPE = "firm_scope"


def scope_for_role(role: Role) -> SubscriptionScope:
    """Return the per-event-family scope this role gets at connection establishment.

    Advisor is the only role with ``own_scope`` for any family; the other three
    roles have firm-wide visibility consistent with their data access scope
    (FR 17.2 §2).
    """
    if role is Role.ADVISOR:
        return SubscriptionScope(
            alerts=OWN_SCOPE,
            cases=OWN_SCOPE,
            monitoring=OWN_SCOPE,
        )
    return SubscriptionScope(
        alerts=FIRM_SCOPE,
        cases=FIRM_SCOPE,
        monitoring=FIRM_SCOPE,
    )


def event_passes_scope(
    *,
    role: Role,
    user_id: str,
    firm_id: str,
    event_firm_id: str | None,
    event_owner_user_id: str | None = None,
) -> bool:
    """Return True if the given event should be delivered to a connection
    with the given role/user/firm context.

    Cluster 0 events are all connection-lifecycle (per-connection by definition),
    so this function isn't called by anything in cluster 0's emit path. It
    lives here as the contract for future emitters.

    Rules:

    - Different ``firm_id``: never delivered (cross-firm isolation; per-firm
      deployment model means this shouldn't happen, but defence-in-depth).
    - Advisor with ``own_scope``: only events the advisor owns
      (``event_owner_user_id == user_id``) or events without owner scope
      (system-wide for the firm).
    - Other roles: all firm events.
    """
    if event_firm_id is not None and event_firm_id != firm_id:
        return False
    if role is Role.ADVISOR:
        if event_owner_user_id is not None and event_owner_user_id != user_id:
            return False
    return True
