"""§14 — UI surface composers (deterministic, role-scoped).

Public surface:
  * `AdvisorViewComposer` — per-client view, N0 inbox, case detail.
  * `CIOViewComposer` — construction approval, firm drift dashboard.
  * `ComplianceViewComposer` — case reasoning trail, override history.
  * `PermissionDeniedError` + permission predicates.
"""

from artha.views.canonical_advisor import AdvisorViewComposer
from artha.views.canonical_cio import CIOViewComposer
from artha.views.canonical_compliance import ComplianceViewComposer
from artha.views.canonical_permissions import (
    PermissionDeniedError,
    assert_can_read_client,
    assert_can_read_firm,
    assert_can_write,
    is_in_scope_client,
)

__all__ = [
    "AdvisorViewComposer",
    "CIOViewComposer",
    "ComplianceViewComposer",
    "PermissionDeniedError",
    "assert_can_read_client",
    "assert_can_read_firm",
    "assert_can_write",
    "is_in_scope_client",
]
