"""Cluster 1 chunk 1.2 — abandonment-job test suite.

Verifies the background-job helper :func:`abandon_stale_conversations`:

- Conversations idle for less than the threshold are left active.
- Conversations idle for more than the threshold are marked abandoned and
  emit ``c0_conversation_abandoned`` with the threshold reason.
- Already-completed and already-abandoned conversations are not touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from ulid import ULID

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.c0 import service as c0_service
from artha.api_v2.c0.event_names import C0_CONVERSATION_ABANDONED
from artha.api_v2.c0.models import Conversation
from artha.api_v2.c0.state_machine import ConversationState
from artha.api_v2.observability.models import T1Event
from artha.common.db.base import Base


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_convo(
    *,
    last_message_at: datetime,
    status: str = "active",
    state: str = ConversationState.COLLECTING_BASICS.value,
) -> Conversation:
    return Conversation(
        conversation_id=str(ULID()),
        user_id="advisor1",
        firm_id="demo-firm-001",
        intent="investor_onboarding",
        state=state,
        collected_slots={},
        status=status,
        started_at=last_message_at,
        last_message_at=last_message_at,
    )


class TestAbandonmentJob:
    @pytest.mark.asyncio
    async def test_active_conversation_younger_than_threshold_is_kept(self, db):
        now = datetime.now(timezone.utc)
        recent = _make_convo(last_message_at=now - timedelta(hours=1))
        db.add(recent)
        await db.commit()

        n = await c0_service.abandon_stale_conversations(db, now=now)
        await db.commit()
        assert n == 0

        row = (await db.execute(select(Conversation))).scalar_one()
        assert row.status == "active"

    @pytest.mark.asyncio
    async def test_active_conversation_older_than_threshold_is_abandoned(self, db):
        now = datetime.now(timezone.utc)
        stale = _make_convo(last_message_at=now - timedelta(hours=5))
        db.add(stale)
        await db.commit()

        n = await c0_service.abandon_stale_conversations(db, now=now)
        await db.commit()
        assert n == 1

        row = (await db.execute(select(Conversation))).scalar_one()
        assert row.status == "abandoned"
        assert row.state == ConversationState.ABANDONED.value
        assert row.completed_at is not None

        events = (
            await db.execute(
                select(T1Event).where(T1Event.event_name == C0_CONVERSATION_ABANDONED)
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].payload["abandonment_reason"] == "inactivity_threshold_4h"

    @pytest.mark.asyncio
    async def test_completed_conversations_are_not_touched(self, db):
        now = datetime.now(timezone.utc)
        completed = _make_convo(
            last_message_at=now - timedelta(hours=10),
            status="completed",
            state=ConversationState.COMPLETED.value,
        )
        db.add(completed)
        await db.commit()

        n = await c0_service.abandon_stale_conversations(db, now=now)
        assert n == 0

        row = (await db.execute(select(Conversation))).scalar_one()
        assert row.status == "completed"

    @pytest.mark.asyncio
    async def test_already_abandoned_not_touched_again(self, db):
        now = datetime.now(timezone.utc)
        abandoned = _make_convo(
            last_message_at=now - timedelta(hours=10),
            status="abandoned",
            state=ConversationState.ABANDONED.value,
        )
        db.add(abandoned)
        await db.commit()

        n = await c0_service.abandon_stale_conversations(db, now=now)
        assert n == 0

        events = (
            await db.execute(
                select(T1Event).where(T1Event.event_name == C0_CONVERSATION_ABANDONED)
            )
        ).scalars().all()
        # No new abandonment event fired.
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_threshold_constant_is_4h(self):
        assert c0_service.ABANDONMENT_THRESHOLD == timedelta(hours=4)
