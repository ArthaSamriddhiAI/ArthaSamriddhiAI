"""T1 event-name constants for D0 (FR 10.0 §5.2 + 10.1 + 10.2 + 10.3 + 10.4 + 10.5).

Each name is a module-level constant so callers don't pass raw strings
around (typos are caught at import time, refs are easy to grep).
"""

from __future__ import annotations

# ---- Adapter lifecycle (FR 10.1) ----
ADAPTER_RUN_STARTED = "adapter_run_started"
ADAPTER_RUN_COMPLETED = "adapter_run_completed"
ADAPTER_RUN_FAILED = "adapter_run_failed"
ADAPTER_RECORD_QUALITY_ISSUE = "adapter_record_quality_issue"

# ---- Staging (FR 10.2) ----
STAGING_RECORD_CREATED = "staging_record_created"

# ---- Normalization (FR 10.3) ----
NORMALIZATION_COMPLETED = "normalization_completed"
NORMALIZATION_FAILED = "normalization_failed"
NORMALIZATION_VALIDATION_FAILED = "normalization_validation_failed"
NORMALIZATION_PARTIAL_QUALITY = "normalization_partial_quality"

# ---- Canonical entities (FR 10.0 §5.2) ----
CANONICAL_ENTITY_CREATED = "canonical_entity_created"
CANONICAL_ENTITY_UPDATED = "canonical_entity_updated"

# ---- Snapshot (FR 10.4) ----
SNAPSHOT_CREATED = "snapshot_created"
SNAPSHOT_VERIFICATION_RUN = "snapshot_verification_run"
SNAPSHOT_VERIFICATION_FAILED = "snapshot_verification_failed"
SNAPSHOT_RETRIEVED = "snapshot_retrieved"
SNAPSHOT_DIFF_COMPUTED = "snapshot_diff_computed"

# ---- Freshness (FR 10.5 §5) ----
FRESHNESS_THRESHOLD_EXCEEDED = "freshness_threshold_exceeded"

# ---- Cluster-2 revision migration (chunk 3.1) ----
MANDATE_VERSION_SCHEMA_MIGRATED = "mandate_version_schema_migrated"

# ---- Cluster 3.2 instrument-classification edge case ----
INSTRUMENT_CLASSIFICATION_UNCERTAIN = "instrument_classification_uncertain"
