"""Data source protocol for evidence ingestion."""

from __future__ import annotations

from typing import Any, Protocol


class DataSource(Protocol):
    """Protocol for market and context data sources."""

    @property
    def source_name(self) -> str: ...

    async def fetch(self, symbols: list[str]) -> dict[str, Any]:
        """Fetch data for given symbols. Returns raw data dict."""
        ...
