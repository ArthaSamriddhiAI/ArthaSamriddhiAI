"""Query interface for evidence artifacts."""

from __future__ import annotations

from artha.common.types import ArtifactID
from artha.evidence.schemas import ArtifactType, EvidenceArtifact
from artha.evidence.store.artifact import ArtifactStore


class EvidenceRepository:
    """High-level query interface wrapping the artifact store."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def get_artifact(self, artifact_id: ArtifactID) -> EvidenceArtifact:
        return await self._store.get(artifact_id)

    async def get_latest(self, artifact_type: ArtifactType) -> EvidenceArtifact | None:
        return await self._store.get_latest_by_type(artifact_type)

    async def get_latest_of_each(
        self, types: list[ArtifactType]
    ) -> dict[ArtifactType, EvidenceArtifact]:
        result = {}
        for t in types:
            artifact = await self._store.get_latest_by_type(t)
            if artifact is not None:
                result[t] = artifact
        return result
