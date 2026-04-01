"""Market data ingestion service."""

from __future__ import annotations

from typing import Any

from artha.common.clock import get_clock
from artha.common.types import ArtifactID
from artha.evidence.ingestion.base import DataSource
from artha.evidence.schemas import ArtifactType
from artha.evidence.store.artifact import ArtifactStore


class MarketDataIngestionService:
    def __init__(self, source: DataSource, store: ArtifactStore) -> None:
        self._source = source
        self._store = store

    async def ingest(self, symbols: list[str]) -> ArtifactID:
        raw_data = await self._source.fetch(symbols)
        artifact_id = await self._store.save(
            artifact_type=ArtifactType.MARKET_SNAPSHOT,
            data={"symbols": symbols, "source": self._source.source_name, "prices": raw_data},
        )
        return artifact_id
