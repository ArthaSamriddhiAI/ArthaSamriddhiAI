"""T1 event names emitted by chunk 1.1 (investor onboarding + I0 enrichment).

Per chunk 1.1 §scope_in:
    "T1 telemetry events emitted: investor_created, investor_enrichment_completed,
     household_created (if a new household is created during onboarding)."

Plus the I0 re-enrichment event from FR 11.1 §8.
"""

from __future__ import annotations

INVESTOR_CREATED = "investor_created"
INVESTOR_ENRICHMENT_COMPLETED = "investor_enrichment_completed"
INVESTOR_ENRICHMENT_RECOMPUTED = "investor_enrichment_recomputed"  # FR 11.1 §8
HOUSEHOLD_CREATED = "household_created"
