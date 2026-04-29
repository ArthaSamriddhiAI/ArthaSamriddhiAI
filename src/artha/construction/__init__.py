"""§4.2 / §5.8 — construction pipeline.

Public surface:
  * `ConstructionOrchestrator` — composes `ConstructionRun` from agent artefacts.
  * `compute_blast_radius` / `compute_version_diff` / `should_use_shadow_mode`.
  * `compute_substitution_impacts` — L4 cascade for §5.13 Test 7.
"""

from artha.construction.canonical_blast_radius import (
    compute_blast_radius,
    compute_version_diff,
    should_use_shadow_mode,
)
from artha.construction.canonical_orchestrator import ConstructionOrchestrator
from artha.construction.canonical_substitution import compute_substitution_impacts

__all__ = [
    "ConstructionOrchestrator",
    "compute_blast_radius",
    "compute_substitution_impacts",
    "compute_version_diff",
    "should_use_shadow_mode",
]
