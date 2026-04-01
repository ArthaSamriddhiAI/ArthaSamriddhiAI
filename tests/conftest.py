"""Shared test fixtures."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from artha.common.clock import FrozenClock, set_clock
from artha.common.db.base import Base
from artha.llm.providers.mock import MockProvider


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite async session for tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def frozen_clock():
    """Frozen clock for deterministic timestamps."""
    clock = FrozenClock()
    set_clock(clock)
    yield clock
    from artha.common.clock import SystemClock
    set_clock(SystemClock())


@pytest.fixture
def mock_llm():
    """Mock LLM provider."""
    return MockProvider()
