"""DEPRECATED — pre-consolidation decision package.

§16 deployment plan: this module is scheduled for removal in Pass 21.
It has zero external imports anywhere in the canonical pipeline; the
canonical decision flow lives on T1 (`T1EventType.DECISION`) + the
governance layer (`G3Evaluation`).

Importing this package emits a `DeprecationWarning`. Callers should
migrate to canonical T1 events; the migration shim
`artha.legacy_migration.legacy_decision_record_to_t1_payload` projects
legacy `DecisionRecord` instances onto T1 payloads.
"""

from artha.common.deprecation import mark_module_deprecated

mark_module_deprecated(
    "artha.decision",
    canonical_replacement=(
        "artha.accountability.t1.T1Event "
        "(event_type=T1EventType.DECISION) + artha.canonical.governance.G3Evaluation"
    ),
    removed_in_pass=21,
    reason="zero external imports; decision flow lives on T1 + governance layer",
)
