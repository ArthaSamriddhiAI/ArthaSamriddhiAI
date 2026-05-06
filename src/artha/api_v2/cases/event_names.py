"""T1 event-name constants for the cluster 5 case framework.

Per FR Entry 20.1 §8 (failure modes) and chunk plan §8.1.

Cluster 5 emits these events as cases move through the pipeline. Each
constant is module-level so callers grep cleanly and typos become import
errors.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Lifecycle events (FR 20.1 §1.5 + §8)
# ---------------------------------------------------------------------------

CASE_CREATED = "case_created"
CASE_STATUS_TRANSITION = "case_status_transition"
CASE_FAILED = "case_failed"
CASE_DECIDED = "case_decided"
CASE_ARCHIVED = "case_archived"

# ---------------------------------------------------------------------------
# Snapshot pinning (FR 20.1 §5)
# ---------------------------------------------------------------------------

CASE_CREATION_SNAPSHOT_PINNED = "case_creation_snapshot_pinned"
CASE_CREATION_SNAPSHOT_FAILED = "case_creation_snapshot_failed"

# ---------------------------------------------------------------------------
# Materiality + pipeline (FR 20.1 §6, chunk 5.4 §8.1)
# ---------------------------------------------------------------------------

CASE_MATERIALITY_ASSESSED = "case_materiality_assessed"
PIPELINE_STAGE_COMPLETED = "pipeline_stage_completed"
STUB_DISPATCHED = "stub_dispatched"

# ---------------------------------------------------------------------------
# Decision recording (FR 20.4)
# ---------------------------------------------------------------------------

CASE_DECISION_RECORDING_FAILED = "case_decision_recording_failed"
DECISION_ARTIFACT_HASH_MISMATCH = "decision_artifact_hash_mismatch"

# ---------------------------------------------------------------------------
# Per-stage failure events (FR 20.1 §8 table)
# ---------------------------------------------------------------------------

CASE_EVIDENCE_GATHERING_FAILED = "case_evidence_gathering_failed"
CASE_SYNTHESIS_FAILED = "case_synthesis_failed"
CASE_DELIBERATION_FAILED = "case_deliberation_failed"
CASE_GOVERNANCE_FAILED = "case_governance_failed"
CASE_GOVERNANCE_ESCALATED = "case_governance_escalated"
CASE_CHALLENGE_UNAVAILABLE = "case_challenge_unavailable"
CASE_AWAITING_DECISION_LONG_PENDING = "case_awaiting_decision_long_pending"

# ---------------------------------------------------------------------------
# Skill.md infrastructure (chunk 5.2 §8.1)
# ---------------------------------------------------------------------------

SKILL_MD_HOT_RELOADED = "skill_md_hot_reloaded"

# ---------------------------------------------------------------------------
# Demo seed (chunk 5.6 §8.1)
# ---------------------------------------------------------------------------

SEED_LOAD_STARTED = "seed_load_started"
SEED_LOAD_PROGRESS = "seed_load_progress"
SEED_LOAD_COMPLETED = "seed_load_completed"
SEED_LOAD_FAILED = "seed_load_failed"
SEED_RESET_STARTED = "seed_reset_started"
SEED_RESET_COMPLETED = "seed_reset_completed"
