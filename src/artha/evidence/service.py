"""Evidence service — orchestrates ingestion, feature computation, and inference."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.types import ArtifactID
from artha.evidence.features.pipeline import FeaturePipeline
from artha.evidence.features.regime import RegimeClassifier
from artha.evidence.features.state import PortfolioStateBuilder
from artha.evidence.inference.risk_estimator import RiskEstimator
from artha.evidence.inference.volatility import VolatilityEstimator
from artha.evidence.ingestion.adapters.mock import MockDataSource
from artha.evidence.ingestion.base import DataSource
from artha.evidence.ingestion.market_data import MarketDataIngestionService
from artha.evidence.schemas import ArtifactType, EvidenceArtifact, PortfolioStateResponse
from artha.evidence.store.artifact import ArtifactStore
from artha.evidence.store.repository import EvidenceRepository


class EvidenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._store = ArtifactStore(session)
        self._repo = EvidenceRepository(self._store)

    async def ingest_market_data(
        self, symbols: list[str], source: str = "mock"
    ) -> ArtifactID:
        data_source: DataSource
        if source == "mock":
            data_source = MockDataSource()
        elif source == "yahoo":
            from artha.evidence.ingestion.adapters.yahoo import YahooFinanceSource
            data_source = YahooFinanceSource(self._session)
        else:
            raise ValueError(f"Unknown data source: {source}")

        ingestion = MarketDataIngestionService(data_source, self._store)
        return await ingestion.ingest(symbols)

    async def compute_full_evidence(
        self, symbols: list[str], holdings: dict[str, float] | None = None
    ) -> dict[str, ArtifactID]:
        """Run the full evidence pipeline: ingest → features → inference."""
        # 1. Ingest
        market_id = await self.ingest_market_data(symbols)

        # 2. Features
        pipeline = FeaturePipeline(self._store)
        feature_id = await pipeline.compute_features(market_id)

        # 3. Regime
        classifier = RegimeClassifier(self._store)
        regime_id, _ = await classifier.classify(feature_id)

        # 4. Risk estimation
        risk_estimator = RiskEstimator(self._store)
        risk_id = await risk_estimator.estimate(feature_id)

        # 5. Volatility
        vol_estimator = VolatilityEstimator(self._store)
        vol_id = await vol_estimator.estimate(feature_id)

        result = {
            "market_snapshot": market_id,
            "feature_set": feature_id,
            "regime_classification": regime_id,
            "risk_estimate": risk_id,
            "volatility_estimate": vol_id,
        }

        # 6. Portfolio state if holdings provided
        if holdings:
            state_builder = PortfolioStateBuilder(self._store)
            state_id, _ = await state_builder.build_state(holdings, market_id)
            result["portfolio_state"] = state_id

        return result

    async def get_artifact(self, artifact_id: ArtifactID) -> EvidenceArtifact:
        return await self._repo.get_artifact(artifact_id)

    async def get_latest(self, artifact_type: ArtifactType) -> EvidenceArtifact | None:
        return await self._repo.get_latest(artifact_type)
