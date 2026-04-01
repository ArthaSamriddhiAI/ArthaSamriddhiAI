"""Mock data source for testing — generates deterministic market data."""

from __future__ import annotations

import hashlib
from typing import Any


class MockDataSource:
    @property
    def source_name(self) -> str:
        return "mock"

    async def fetch(self, symbols: list[str]) -> dict[str, Any]:
        prices = {}
        for symbol in symbols:
            # Deterministic price based on symbol hash
            h = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
            base_price = 50.0 + (h % 1000) / 10.0
            prices[symbol] = {
                "price": round(base_price, 2),
                "change_pct": round(((h % 200) - 100) / 100.0, 4),
                "volume": h % 10_000_000,
                "high_52w": round(base_price * 1.3, 2),
                "low_52w": round(base_price * 0.7, 2),
            }
        return prices
