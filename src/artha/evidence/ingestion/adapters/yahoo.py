"""Yahoo Finance data adapter — placeholder for real market data integration."""

from __future__ import annotations

from typing import Any

import httpx


class YahooFinanceSource:
    """Placeholder — real implementation would use yfinance or Yahoo API."""

    @property
    def source_name(self) -> str:
        return "yahoo"

    async def fetch(self, symbols: list[str]) -> dict[str, Any]:
        # TODO: Implement real Yahoo Finance integration
        raise NotImplementedError(
            "Yahoo Finance adapter is a placeholder. Use 'mock' source for development."
        )
