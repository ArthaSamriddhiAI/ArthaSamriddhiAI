"""Portfolio state construction from holdings and market data."""

from __future__ import annotations

from typing import Any

from artha.common.types import ArtifactID
from artha.evidence.schemas import ArtifactType, PortfolioStateResponse
from artha.evidence.store.artifact import ArtifactStore

# Simplified sector mapping for demonstration
SECTOR_MAP: dict[str, str] = {
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology",
    "JPM": "Financials", "BAC": "Financials", "GS": "Financials",
    "JNJ": "Healthcare", "PFE": "Healthcare", "UNH": "Healthcare",
    "XOM": "Energy", "CVX": "Energy",
    "PG": "Consumer Staples", "KO": "Consumer Staples",
}


class PortfolioStateBuilder:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def build_state(
        self,
        holdings: dict[str, float],
        market_artifact_id: ArtifactID,
    ) -> tuple[ArtifactID, PortfolioStateResponse]:
        artifact = await self._store.get(market_artifact_id)
        prices = artifact.data.get("prices", {})

        # Compute portfolio value and weights
        total_value = 0.0
        position_values: dict[str, float] = {}
        for symbol, shares in holdings.items():
            price = prices.get(symbol, {}).get("price", 0.0)
            val = shares * price
            position_values[symbol] = val
            total_value += val

        weights = {
            s: round(v / total_value, 4) if total_value > 0 else 0.0
            for s, v in position_values.items()
        }

        # Sector exposure
        sector_exposure: dict[str, float] = {}
        for symbol, weight in weights.items():
            sector = SECTOR_MAP.get(symbol, "Other")
            sector_exposure[sector] = sector_exposure.get(sector, 0.0) + weight

        # Basic risk metrics
        max_weight = max(weights.values()) if weights else 0.0
        hhi = sum(w ** 2 for w in weights.values())  # Herfindahl index

        state = PortfolioStateResponse(
            holdings=weights,
            total_value=round(total_value, 2),
            sector_exposure={k: round(v, 4) for k, v in sector_exposure.items()},
            risk_metrics={
                "max_single_position": round(max_weight, 4),
                "herfindahl_index": round(hhi, 4),
                "position_count": len(weights),
            },
        )

        artifact_id = await self._store.save(
            artifact_type=ArtifactType.PORTFOLIO_STATE,
            data=state.model_dump(),
        )
        return artifact_id, state
