"""Volatility modeling service."""

from __future__ import annotations

from typing import Any

from artha.common.types import ArtifactID
from artha.evidence.schemas import ArtifactType
from artha.evidence.store.artifact import ArtifactStore


class VolatilityEstimator:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def estimate(self, feature_artifact_id: ArtifactID) -> ArtifactID:
        artifact = await self._store.get(feature_artifact_id)
        features = artifact.data.get("features", {})

        vol_estimates: dict[str, Any] = {}
        for symbol, feat in features.items():
            vol_proxy = feat.get("volatility_proxy", 0.2)
            vol_estimates[symbol] = {
                "realized_vol_proxy": round(vol_proxy, 4),
                "vol_regime": "high" if vol_proxy > 0.3 else "normal" if vol_proxy > 0.15 else "low",
            }

        avg_vol = (
            sum(v["realized_vol_proxy"] for v in vol_estimates.values()) / len(vol_estimates)
            if vol_estimates
            else 0.0
        )

        return await self._store.save(
            artifact_type=ArtifactType.VOLATILITY_ESTIMATE,
            data={
                "source_artifact": feature_artifact_id,
                "per_symbol": vol_estimates,
                "portfolio_avg_volatility": round(avg_vol, 4),
            },
        )
