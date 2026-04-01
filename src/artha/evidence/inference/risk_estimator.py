"""Risk estimation service — produces structured risk estimates."""

from __future__ import annotations

from typing import Any

from artha.common.types import ArtifactID
from artha.evidence.schemas import ArtifactType
from artha.evidence.store.artifact import ArtifactStore


class RiskEstimator:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def estimate(self, feature_artifact_id: ArtifactID) -> ArtifactID:
        artifact = await self._store.get(feature_artifact_id)
        features = artifact.data.get("features", {})

        risk_scores: dict[str, Any] = {}
        for symbol, feat in features.items():
            vol = feat.get("volatility_proxy", 0.2)
            position = feat.get("position_in_52w_range", 0.5)
            distance_from_high = feat.get("distance_from_high_pct", 0)

            # Simple composite risk score
            risk_score = (vol * 0.4) + ((1 - position) * 0.3) + (distance_from_high / 100 * 0.3)
            risk_level = "high" if risk_score > 0.6 else "medium" if risk_score > 0.3 else "low"

            risk_scores[symbol] = {
                "risk_score": round(risk_score, 4),
                "risk_level": risk_level,
                "components": {
                    "volatility_contribution": round(vol * 0.4, 4),
                    "position_contribution": round((1 - position) * 0.3, 4),
                    "drawdown_contribution": round(distance_from_high / 100 * 0.3, 4),
                },
            }

        portfolio_risk = (
            sum(s["risk_score"] for s in risk_scores.values()) / len(risk_scores)
            if risk_scores
            else 0.0
        )

        return await self._store.save(
            artifact_type=ArtifactType.RISK_ESTIMATE,
            data={
                "source_artifact": feature_artifact_id,
                "per_symbol": risk_scores,
                "portfolio_risk_score": round(portfolio_risk, 4),
            },
        )
