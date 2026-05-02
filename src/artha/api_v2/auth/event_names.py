"""T1 event names emitted by the auth + sessions flow.

Names are exactly those listed in FR Entry 17.0 §5 and FR Entry 17.1 §5.
Centralised here so the router and tests reference the same string constants
(typos in T1 event names would silently break audit queries).

Note: ``auth_login_initiated`` is intentionally absent in cluster 0 demo
stage — the event corresponds to the IdP redirect step which the stub auth
flow does not have. When production-readiness phase swaps in real OIDC, this
constant will be added and emitted from the ``/api/v2/auth/login`` handler.
"""

from __future__ import annotations

# FR 17.0 §5
AUTH_LOGIN_COMPLETED = "auth_login_completed"
AUTH_LOGIN_FAILED = "auth_login_failed"
AUTH_LOGOUT = "auth_logout"

# FR 17.1 §5
SESSION_CREATED = "session_created"
SESSION_REFRESHED = "session_refreshed"
SESSION_REVOKED = "session_revoked"
SESSION_EXPIRED = "session_expired"
