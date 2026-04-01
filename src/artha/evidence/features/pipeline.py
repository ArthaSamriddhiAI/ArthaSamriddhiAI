"""Feature computation pipeline — transforms raw market data into structured features."""

from __future__ import annotations

import math
from typing import Any

from artha.common.types import ArtifactID
from artha.evidence.schemas import ArtifactType
from artha.evidence.store.artifact import ArtifactStore


class FeaturePipeline:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def compute_features(self, market_artifact_id: ArtifactID) -> ArtifactID:
        """Compute features from a market snapshot artifact."""
        artifact = await self._store.get(market_artifact_id)
        prices = artifact.data.get("prices", {})

        features: dict[str, Any] = {}
        for symbol, data in prices.items():
            price = data.get("price", 0)
            high = data.get("high_52w", price)
            low = data.get("low_52w", price)
            change = data.get("change_pct", 0)

            range_52w = high - low if high > low else 1.0
            position_in_range = (price - low) / range_52w if range_52w > 0 else 0.5

            features[symbol] = {
                "price": price,
                "return_1d": change,
                "position_in_52w_range": round(position_in_range, 4),
                "distance_from_high_pct": round((high - price) / high * 100, 2) if high > 0 else 0,
                "volatility_proxy": round(abs(change) * math.sqrt(252), 4),
            }

        return await self._store.save(
            artifact_type=ArtifactType.FEATURE_SET,
            data={"source_artifact": market_artifact_id, "features": features},
        )
