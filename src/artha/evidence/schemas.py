"""API request/response schemas for the Evidence layer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ArtifactType(str, Enum):
    MARKET_SNAPSHOT = "market_snapshot"
    FEATURE_SET = "feature_set"
    RISK_ESTIMATE = "risk_estimate"
    VOLATILITY_ESTIMATE = "volatility_estimate"
    REGIME_CLASSIFICATION = "regime_classification"
    PORTFOLIO_STATE = "portfolio_state"


class EvidenceArtifact(BaseModel):
    id: str
    artifact_type: ArtifactType
    data: dict[str, Any]
    version: int
    created_at: datetime


class EvidenceSnapshot(BaseModel):
    id: str
    decision_id: str
    artifact_ids: list[str]
    frozen_at: datetime


class IngestMarketDataRequest(BaseModel):
    symbols: list[str]
    source: str = "mock"


class IngestMarketDataResponse(BaseModel):
    artifact_id: str
    symbol_count: int


class PortfolioStateResponse(BaseModel):
    holdings: dict[str, float] = Field(default_factory=dict, description="Symbol -> weight")
    total_value: float = 0.0
    sector_exposure: dict[str, float] = Field(default_factory=dict)
    risk_metrics: dict[str, float] = Field(default_factory=dict)


class RegimeClassification(BaseModel):
    regime: str  # bull, bear, volatile, stable
    confidence: float
    indicators: dict[str, float] = Field(default_factory=dict)
