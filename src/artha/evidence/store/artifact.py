"""Append-only artifact persistence. Artifacts are immutable once created."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.clock import get_clock
from artha.common.errors import NotFoundError
from artha.common.types import ArtifactID
from artha.evidence.models import EvidenceArtifactRow
from artha.evidence.schemas import ArtifactType, EvidenceArtifact


class ArtifactStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, artifact_type: ArtifactType, data: dict[str, Any]) -> ArtifactID:
        artifact_id = ArtifactID(str(uuid.uuid4()))
        row = EvidenceArtifactRow(
            id=artifact_id,
            artifact_type=artifact_type.value,
            data_json=json.dumps(data),
            created_at=get_clock().now(),
        )
        self._session.add(row)
        await self._session.flush()
        return artifact_id

    async def get(self, artifact_id: ArtifactID) -> EvidenceArtifact:
        stmt = select(EvidenceArtifactRow).where(EvidenceArtifactRow.id == artifact_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Artifact {artifact_id} not found")
        return EvidenceArtifact(
            id=row.id,
            artifact_type=ArtifactType(row.artifact_type),
            data=json.loads(row.data_json),
            version=row.version,
            created_at=row.created_at,
        )

    async def get_latest_by_type(self, artifact_type: ArtifactType) -> EvidenceArtifact | None:
        stmt = (
            select(EvidenceArtifactRow)
            .where(EvidenceArtifactRow.artifact_type == artifact_type.value)
            .order_by(EvidenceArtifactRow.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return EvidenceArtifact(
            id=row.id,
            artifact_type=ArtifactType(row.artifact_type),
            data=json.loads(row.data_json),
            version=row.version,
            created_at=row.created_at,
        )

    async def list_by_type(
        self, artifact_type: ArtifactType, limit: int = 50
    ) -> list[EvidenceArtifact]:
        stmt = (
            select(EvidenceArtifactRow)
            .where(EvidenceArtifactRow.artifact_type == artifact_type.value)
            .order_by(EvidenceArtifactRow.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            EvidenceArtifact(
                id=row.id,
                artifact_type=ArtifactType(row.artifact_type),
                data=json.loads(row.data_json),
                version=row.version,
                created_at=row.created_at,
            )
            for row in result.scalars()
        ]
