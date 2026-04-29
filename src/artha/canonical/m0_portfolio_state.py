"""Section 15.6.3 — M0.PortfolioState canonical query schemas.

Section 8.4 — PortfolioState is the semantic data layer over canonical holdings.
Downstream agents query it for holdings slices, look-through views, cascade
events, and conflict detection rather than reaching into the database directly.

The query envelope carries `run_mode` so PortfolioState can serve both pipelines:
in CASE mode it queries per-client; in CONSTRUCTION mode it queries firm-level
data (e.g. all clients in a bucket for blast radius preview). Pass 6 ships the
CASE mode; CONSTRUCTION mode is wired in Phase F.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.holding import (
    CascadeEvent,
    ConflictReport,
    Holding,
    IngestionReport,
    LookThroughResponse,
    SliceResponse,
)
from artha.common.types import InputsUsedManifest, RunMode


class M0PortfolioStateQueryCategory(str, Enum):
    """Section 8.4.2 — which family of query the caller is making."""

    HOLDINGS = "holdings"
    SLICE = "slice"
    LOOK_THROUGH = "look_through"
    CASCADE = "cascade"
    INGESTION = "ingestion"
    CONFLICT_DETECTION = "conflict_detection"


class M0PortfolioStateQuery(BaseModel):
    """Section 15.6.3 input.

    `query_parameters` is per-category — slices take filter fields, look-through
    takes a parent instrument_id, cascade takes a horizon window, etc. Pass 6
    keeps the shape permissive; per-category typed sub-schemas land in Phase C/F
    when consumers stabilise their needs.
    """

    model_config = ConfigDict(extra="forbid")

    query_category: M0PortfolioStateQueryCategory
    client_id: str
    query_parameters: dict[str, Any] = Field(default_factory=dict)
    as_of_date: date | None = None
    run_mode: RunMode = RunMode.CASE


class M0PortfolioStateResponse(BaseModel):
    """Section 15.6.3 output envelope.

    Exactly one of the result fields is populated, matching `query.query_category`.
    The `flags` array carries propagation flags (`tax_basis_stale`, `look_through_unavailable`,
    etc.) per Section 8.4.7. `inputs_used_manifest` enables T1 replay.
    """

    model_config = ConfigDict(extra="forbid")

    query_category: M0PortfolioStateQueryCategory
    client_id: str
    as_of_date: date | None = None

    # Per-category result; exactly one populated per response.
    holdings: list[Holding] | None = None
    slice_result: SliceResponse | None = None
    look_through: LookThroughResponse | None = None
    cascade_events: list[CascadeEvent] | None = None
    ingestion: IngestionReport | None = None
    conflicts: list[ConflictReport] | None = None

    flags: list[str] = Field(default_factory=list)
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
