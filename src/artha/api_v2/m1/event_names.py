"""T1 event-name constants for M1 (FR Entry 12.0 §6).

Each name is a module-level constant so callers don't pass raw strings
around (typos are caught at import time, refs are easy to grep).
"""

from __future__ import annotations

# ---- Initial creation + activation (chunk 2.1) ----
MANDATE_CREATED = "mandate_created"
MANDATE_VERSION_CREATED = "mandate_version_created"
MANDATE_VERSION_ACTIVATED = "mandate_version_activated"
MANDATE_VERSION_ARCHIVED = "mandate_version_archived"

# ---- Amendment lifecycle (chunk 2.3) ----
MANDATE_AMENDMENT_PROPOSED = "mandate_amendment_proposed"
MANDATE_AMENDMENT_APPROVED = "mandate_amendment_approved"
MANDATE_AMENDMENT_REJECTED = "mandate_amendment_rejected"
MANDATE_AMENDMENT_CHANGES_REQUESTED = "mandate_amendment_changes_requested"

# ---- I0 cascade (FR 12.0 §4.3; mechanism present, trigger deferred) ----
MANDATE_IO_DIVERGENCE_DETECTED = "mandate_io_divergence_detected"

# ---- Operational analytics (chunk 2.4 PDF stub) ----
PDF_ENDPOINT_CALLED = "pdf_endpoint_called"

# ---- Failure modes (FR 12.0 §7) ----
MANDATE_CREATION_BLOCKED_EXISTING = "mandate_creation_blocked_existing"
