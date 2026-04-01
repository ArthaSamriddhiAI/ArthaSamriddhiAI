"""FastAPI endpoints for the Evidence layer."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session
from artha.evidence.schemas import (
    ArtifactType,
    EvidenceArtifact,
    IngestMarketDataRequest,
    IngestMarketDataResponse,
)
from artha.evidence.service import EvidenceService

router = APIRouter(prefix="/evidence", tags=["evidence"])


def _get_service(session: AsyncSession = Depends(get_session)) -> EvidenceService:
    return EvidenceService(session)


@router.post("/ingest", response_model=IngestMarketDataResponse)
async def ingest_market_data(
    request: IngestMarketDataRequest,
    service: EvidenceService = Depends(_get_service),
    session: AsyncSession = Depends(get_session),
):
    artifact_id = await service.ingest_market_data(request.symbols, request.source)
    await session.commit()
    return IngestMarketDataResponse(artifact_id=artifact_id, symbol_count=len(request.symbols))


@router.post("/compute", response_model=dict[str, str])
async def compute_full_evidence(
    symbols: list[str],
    holdings: dict[str, float] | None = None,
    service: EvidenceService = Depends(_get_service),
    session: AsyncSession = Depends(get_session),
):
    result = await service.compute_full_evidence(symbols, holdings)
    await session.commit()
    return result


@router.get("/artifacts/{artifact_id}", response_model=EvidenceArtifact)
async def get_artifact(
    artifact_id: str,
    service: EvidenceService = Depends(_get_service),
):
    return await service.get_artifact(artifact_id)


@router.get("/latest/{artifact_type}", response_model=EvidenceArtifact | None)
async def get_latest_artifact(
    artifact_type: ArtifactType,
    service: EvidenceService = Depends(_get_service),
):
    return await service.get_latest(artifact_type)
