"""Regime classification — rule-based market regime detection."""

from __future__ import annotations

from typing import Any

from artha.common.types import ArtifactID
from artha.evidence.schemas import ArtifactType, RegimeClassification
from artha.evidence.store.artifact import ArtifactStore


class RegimeClassifier:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def classify(self, feature_artifact_id: ArtifactID) -> tuple[ArtifactID, RegimeClassification]:
        artifact = await self._store.get(feature_artifact_id)
        features = artifact.data.get("features", {})

        if not features:
            result = RegimeClassification(regime="stable", confidence=0.5, indicators={})
            aid = await self._store.save(artifact_type=ArtifactType.REGIME_CLASSIFICATION, data=result.model_dump())
            return aid, result

        # Aggregate indicators
        avg_return = sum(f.get("return_1d", 0) for f in features.values()) / len(features)
        avg_vol = sum(f.get("volatility_proxy", 0) for f in features.values()) / len(features)
        avg_position = sum(f.get("position_in_52w_range", 0.5) for f in features.values()) / len(features)

        # Simple rule-based classification
        if avg_vol > 0.4:
            regime = "volatile"
            confidence = min(avg_vol / 0.6, 1.0)
        elif avg_return > 0.02 and avg_position > 0.6:
            regime = "bull"
            confidence = min(avg_return * 20, 1.0)
        elif avg_return < -0.02 and avg_position < 0.4:
            regime = "bear"
            confidence = min(abs(avg_return) * 20, 1.0)
        else:
            regime = "stable"
            confidence = 0.6

        indicators = {
            "avg_return_1d": round(avg_return, 6),
            "avg_volatility_proxy": round(avg_vol, 4),
            "avg_52w_position": round(avg_position, 4),
        }

        result = RegimeClassification(
            regime=regime, confidence=round(confidence, 3), indicators=indicators
        )
        artifact_id = await self._store.save(
            artifact_type=ArtifactType.REGIME_CLASSIFICATION, data=result.model_dump()
        )
        return artifact_id, result
