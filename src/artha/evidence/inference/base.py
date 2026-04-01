"""Estimator protocol for inference services."""

from __future__ import annotations

from typing import Any, Protocol

from artha.common.types import ArtifactID


class Estimator(Protocol):
    """Protocol for evidence inference services."""

    async def estimate(self, feature_artifact_id: ArtifactID) -> ArtifactID: ...
