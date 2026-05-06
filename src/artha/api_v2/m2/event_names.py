"""T1 event-name constants for M2 model portfolio (FR Entry 13.0 §5.2).

Each name is a module-level constant so callers can grep for usage and
typos surface at import time. Cluster 4 chunks 4.1, 4.2, 4.3 collectively
emit these.
"""

from __future__ import annotations

# ---- Default loader (chunk 4.1) ----
INSTRUMENT_TAGS_DEFAULTED = "instrument_tags_defaulted"
INSTRUMENT_DEFAULT_TAGGING_FAILED = "instrument_default_tagging_failed"
PMS_STRATEGY_CLASSIFICATION_UNCERTAIN = "pms_strategy_classification_uncertain"
DEFAULT_PREFERRED_ENTRY_LOADED = "default_preferred_entry_loaded"
DEFAULT_PREFERRED_ENTRY_SKIPPED_MISSING_INSTRUMENT = (
    "default_preferred_entry_skipped_missing_instrument"
)

# ---- Tag operations (chunk 4.2) ----
INSTRUMENT_TAGS_CHANGED = "instrument_tags_changed"
INSTRUMENT_TAGS_BULK_FAILED = "instrument_tags_bulk_failed"
MODEL_PORTFOLIO_TAGS_BULK_RESET = "model_portfolio_tags_bulk_reset"

# ---- Preferred portfolio entry operations (chunk 4.3) ----
PREFERRED_PORTFOLIO_ENTRY_CREATED = "preferred_portfolio_entry_created"
PREFERRED_PORTFOLIO_ENTRY_MODIFIED = "preferred_portfolio_entry_modified"
PREFERRED_PORTFOLIO_ENTRY_DELETED = "preferred_portfolio_entry_deleted"
PREFERRED_PORTFOLIO_ENTRY_WITHOUT_MATCHING_TAG = (
    "preferred_portfolio_entry_without_matching_tag"
)
PREFERRED_PORTFOLIO_CELL_REORDERED = "preferred_portfolio_cell_reordered"
PREFERRED_PORTFOLIO_CELL_DUPLICATED = "preferred_portfolio_cell_duplicated"
PREFERRED_PORTFOLIO_CELL_RESET = "preferred_portfolio_cell_reset"
MODEL_PORTFOLIO_PREFERRED_BULK_RESET = "model_portfolio_preferred_bulk_reset"
