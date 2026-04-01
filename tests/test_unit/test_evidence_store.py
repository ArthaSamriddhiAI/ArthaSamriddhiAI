"""Tests for the evidence artifact store."""

from __future__ import annotations

import pytest

from artha.common.errors import NotFoundError
from artha.evidence.schemas import ArtifactType
from artha.evidence.store.artifact import ArtifactStore


@pytest.mark.asyncio
async def test_save_and_retrieve(db_session, frozen_clock):
    store = ArtifactStore(db_session)
    aid = await store.save(ArtifactType.MARKET_SNAPSHOT, {"price": 100.0})
    artifact = await store.get(aid)
    assert artifact.artifact_type == ArtifactType.MARKET_SNAPSHOT
    assert artifact.data["price"] == 100.0


@pytest.mark.asyncio
async def test_get_latest_by_type(db_session, frozen_clock):
    store = ArtifactStore(db_session)
    await store.save(ArtifactType.MARKET_SNAPSHOT, {"v": 1})
    aid2 = await store.save(ArtifactType.MARKET_SNAPSHOT, {"v": 2})
    latest = await store.get_latest_by_type(ArtifactType.MARKET_SNAPSHOT)
    assert latest is not None
    assert latest.id == aid2


@pytest.mark.asyncio
async def test_get_nonexistent_raises(db_session, frozen_clock):
    store = ArtifactStore(db_session)
    with pytest.raises(NotFoundError):
        await store.get("nonexistent-id")


@pytest.mark.asyncio
async def test_artifacts_are_immutable_via_append_only(db_session, frozen_clock):
    store = ArtifactStore(db_session)
    aid = await store.save(ArtifactType.RISK_ESTIMATE, {"score": 0.5})
    artifact = await store.get(aid)
    assert artifact.data["score"] == 0.5
    # New save creates a new artifact, doesn't modify the old one
    aid2 = await store.save(ArtifactType.RISK_ESTIMATE, {"score": 0.8})
    old = await store.get(aid)
    new = await store.get(aid2)
    assert old.data["score"] == 0.5
    assert new.data["score"] == 0.8
