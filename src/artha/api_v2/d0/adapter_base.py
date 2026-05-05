"""D0Adapter abstract base (FR Entry 10.1 §2).

Every adapter — JSONFixtureAdapter (cluster 3) and future live-source
adapters (cluster 17) — conforms to this interface so the rest of D0
can call into them uniformly.

Cluster 3 keeps the interface narrow: ``run`` for fetch-and-write,
``health_check`` for connectivity probes. Both are async because future
adapters will be I/O-bound (HTTP calls, webhook receivers).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AdapterError:
    """One error encountered during an adapter run.

    The error_type vocabulary is open; common values include
    ``schema_mismatch``, ``database_write_failure``, ``source_unavailable``,
    ``classification_uncertain``.
    """

    error_type: str
    message: str
    record_identifier: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterRunResult:
    """Metadata about one adapter run (FR 10.1 §2)."""

    run_id: str
    started_at: datetime
    completed_at: datetime
    status: str  # success | partial_success | failure
    staging_records_created: int = 0
    canonical_entities_created: dict[str, int] = field(default_factory=dict)
    canonical_entities_updated: dict[str, int] = field(default_factory=dict)
    errors: list[AdapterError] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterHealth:
    """Health-probe result (FR 10.1 §2)."""

    healthy: bool
    last_successful_fetch_at: datetime | None = None
    error_message: str | None = None


class D0Adapter(ABC):
    """Abstract base for D0 adapters."""

    @property
    @abstractmethod
    def source_identifier(self) -> str:
        """Stable identifier for this adapter's source. Used in staging
        records, the registry, and admin endpoints."""

    @property
    @abstractmethod
    def supported_entity_types(self) -> list[str]:
        """Canonical entity types this adapter produces.

        Examples: ``["Instrument"]``, ``["Instrument", "MacroSnapshot",
        "IndustryReport"]``. The registry and admin UI display this so the
        audit role knows which entities each adapter feeds.
        """

    @abstractmethod
    async def run(
        self, db: AsyncSession, *, mode: str = "full"
    ) -> AdapterRunResult:
        """Execute one fetch cycle.

        ``mode`` controls behaviour:

        - ``"full"``: fetch all available data; cluster 3's only mode for
          the JSONFixtureAdapter.
        - ``"incremental"``: cluster 17 introduces this for live adapters.
        - ``"validation"``: read + validate, do NOT write to canonical
          entity tables (cluster 3 ideation §10.4 working answer).
        """

    @abstractmethod
    async def health_check(self) -> AdapterHealth:
        """Connectivity + authentication probe; does not modify state."""
