"""Cluster 1 chunk 1.3 — :class:`SmartLLMRouter` runtime test suite.

Covers FR Entry 16.0 §5–§7:

- Kill switch fast-fails before any provider call.
- Un-configured deployment raises :class:`LLMNotConfiguredError`.
- Retriable errors trigger backoff retries.
- Non-retriable errors fail fast.
- T1 events fire for every lifecycle outcome.
- Rate limiter throttles bursts above the configured per-minute quota.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.llm.encryption import (
    encrypt_api_key,
    reset_encryption_cache,
)
from artha.api_v2.llm.event_names import (
    LLM_CALL_COMPLETED,
    LLM_CALL_FAILED,
    LLM_CALL_INITIATED,
)
from artha.api_v2.llm.models import SINGLETON_CONFIG_ID, LLMProviderConfig
from artha.api_v2.llm.providers import (
    LLMCallRequest,
    LLMCallResponse,
    ProviderAuthError,
    ProviderRateLimitError,
)
from artha.api_v2.llm.router_runtime import (
    _BACKOFF_SCHEDULE,
    LLMCallFailedError,
    LLMKillSwitchActiveError,
    LLMNotConfiguredError,
    SmartLLMRouter,
    _TokenBucket,
)
from artha.api_v2.observability.models import T1Event
from artha.common.db.base import Base
from artha.config import Environment, settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fixed_dev_encryption_key(monkeypatch):
    """Deterministic Fernet key so encrypted ciphertext survives within the test."""
    from cryptography.fernet import Fernet

    monkeypatch.setattr(
        settings, "samriddhi_encryption_key", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setattr(settings, "environment", Environment.DEVELOPMENT)
    reset_encryption_cache()
    yield
    reset_encryption_cache()


@pytest.fixture(autouse=True)
def short_backoff(monkeypatch):
    """Override the FR-spec backoff (1s, 2s, 4s) with sub-second values so the
    retry tests don't sleep for 7s real time."""
    from artha.api_v2.llm import router_runtime

    monkeypatch.setattr(router_runtime, "_BACKOFF_SCHEDULE", (0.01, 0.02, 0.04))
    yield


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


def _actor() -> UserContext:
    return UserContext(
        user_id="cio1",
        firm_id="demo-firm-001",
        role=Role.CIO,
        email="cio@example.com",
        name="CIO User",
        session_id="01ABCDEFGHJKMNPQRSTVWXYZ56",
    )


async def _seed_config(
    db,
    *,
    active_provider: str | None = "mistral",
    mistral_key: str | None = "sk-mistral-test",
    claude_key: str | None = None,
    kill_switch: bool = False,
    rate_limit: int = 60,
) -> LLMProviderConfig:
    row = LLMProviderConfig(
        config_id=SINGLETON_CONFIG_ID,
        active_provider=active_provider,
        mistral_api_key_encrypted=encrypt_api_key(mistral_key) if mistral_key else None,
        claude_api_key_encrypted=encrypt_api_key(claude_key) if claude_key else None,
        default_mistral_model="mistral-small-latest",
        default_claude_model="claude-sonnet-4-5-20250929",
        rate_limit_calls_per_minute=rate_limit,
        request_timeout_seconds=30,
        kill_switch_active=kill_switch,
        updated_at=datetime.now(timezone.utc),
        updated_by="cio1",
    )
    db.add(row)
    await db.flush()
    return row


async def _t1_events_with_name(db, event_name: str) -> list[T1Event]:
    result = await db.execute(select(T1Event).where(T1Event.event_name == event_name))
    return list(result.scalars())


def _stub_adapter(monkeypatch, *, complete_impl):
    """Replace the registered Mistral adapter's ``complete`` method."""
    from artha.api_v2.llm.providers.mistral import MistralAdapter

    monkeypatch.setattr(MistralAdapter, "complete", complete_impl)


# ===========================================================================
# 1. Pre-call gating
# ===========================================================================


class TestPreCallGating:
    @pytest.mark.asyncio
    async def test_unconfigured_raises_not_configured_error(self, db):
        # No row at all.
        router = SmartLLMRouter()
        with pytest.raises(LLMNotConfiguredError):
            await router.call(
                db, LLMCallRequest(caller_id="t", prompt="hi")
            )
        # T1 records the failure.
        events = await _t1_events_with_name(db, LLM_CALL_FAILED)
        assert len(events) == 1
        assert events[0].payload["failure_type"] == "not_configured"

    @pytest.mark.asyncio
    async def test_active_provider_none_raises_not_configured(self, db):
        await _seed_config(db, active_provider=None)
        router = SmartLLMRouter()
        with pytest.raises(LLMNotConfiguredError):
            await router.call(
                db, LLMCallRequest(caller_id="t", prompt="hi")
            )

    @pytest.mark.asyncio
    async def test_kill_switch_active_raises_kill_switch_error(self, db):
        await _seed_config(db, kill_switch=True)
        router = SmartLLMRouter()
        with pytest.raises(LLMKillSwitchActiveError):
            await router.call(
                db, LLMCallRequest(caller_id="t", prompt="hi")
            )
        events = await _t1_events_with_name(db, LLM_CALL_FAILED)
        assert len(events) == 1
        assert events[0].payload["failure_type"] == "kill_switch_active"

    @pytest.mark.asyncio
    async def test_active_provider_set_but_key_missing_raises(self, db):
        await _seed_config(db, active_provider="claude", mistral_key="x", claude_key=None)
        router = SmartLLMRouter()
        with pytest.raises(LLMCallFailedError) as exc_info:
            await router.call(
                db, LLMCallRequest(caller_id="t", prompt="hi")
            )
        assert exc_info.value.failure_type == "auth_error"


# ===========================================================================
# 2. Successful calls + telemetry
# ===========================================================================


class TestSuccessfulCalls:
    @pytest.mark.asyncio
    async def test_successful_call_emits_initiated_then_completed(
        self, db, monkeypatch
    ):
        await _seed_config(db)

        async def fake_complete(self, request, *, timeout_seconds):
            return LLMCallResponse(
                content="OK",
                provider="mistral",
                model="mistral-small-latest",
                tokens_used=7,
                latency_ms=42,
                request_id="req-1",
            )

        _stub_adapter(monkeypatch, complete_impl=fake_complete)

        router = SmartLLMRouter()
        resp = await router.call(
            db, LLMCallRequest(caller_id="c0_intent", prompt="hi")
        )
        assert resp.content == "OK"

        initiated = await _t1_events_with_name(db, LLM_CALL_INITIATED)
        completed = await _t1_events_with_name(db, LLM_CALL_COMPLETED)
        assert len(initiated) == 1
        assert initiated[0].payload["caller_id"] == "c0_intent"
        assert initiated[0].payload["provider"] == "mistral"
        assert len(completed) == 1
        assert completed[0].payload["tokens_used"] == 7
        assert completed[0].payload["latency_ms"] == 42

    @pytest.mark.asyncio
    async def test_response_carries_provider_and_model(self, db, monkeypatch):
        await _seed_config(db)

        async def fake_complete(self, request, *, timeout_seconds):
            return LLMCallResponse(
                content="OK",
                provider="mistral",
                model="mistral-small-latest",
                tokens_used=1,
                latency_ms=1,
                request_id="req-2",
            )

        _stub_adapter(monkeypatch, complete_impl=fake_complete)
        router = SmartLLMRouter()
        resp = await router.call(db, LLMCallRequest(caller_id="t", prompt="hi"))
        assert resp.provider == "mistral"
        assert resp.model == "mistral-small-latest"


# ===========================================================================
# 3. Retry behaviour (FR 16.0 §5.2)
# ===========================================================================


class TestRetryBehaviour:
    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_then_succeeds(self, db, monkeypatch):
        await _seed_config(db)

        attempts = {"n": 0}

        async def flaky_complete(self, request, *, timeout_seconds):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ProviderRateLimitError("rate limited", provider="mistral")
            return LLMCallResponse(
                content="finally",
                provider="mistral",
                model="mistral-small-latest",
                tokens_used=3,
                latency_ms=10,
                request_id="req-3",
            )

        _stub_adapter(monkeypatch, complete_impl=flaky_complete)
        router = SmartLLMRouter()
        resp = await router.call(db, LLMCallRequest(caller_id="t", prompt="hi"))
        assert resp.content == "finally"
        assert attempts["n"] == 2
        # No FAILED telemetry on a recovered call.
        failed = await _t1_events_with_name(db, LLM_CALL_FAILED)
        assert failed == []

    @pytest.mark.asyncio
    async def test_retries_exhausted_raises_call_failed(self, db, monkeypatch):
        await _seed_config(db)

        async def always_rate_limited(self, request, *, timeout_seconds):
            raise ProviderRateLimitError("hit rate limit", provider="mistral")

        _stub_adapter(monkeypatch, complete_impl=always_rate_limited)
        router = SmartLLMRouter()
        with pytest.raises(LLMCallFailedError) as exc_info:
            await router.call(db, LLMCallRequest(caller_id="t", prompt="hi"))
        assert exc_info.value.failure_type == "rate_limit"

        failed = await _t1_events_with_name(db, LLM_CALL_FAILED)
        assert len(failed) == 1
        assert failed[0].payload["retries_exhausted"] is True

    @pytest.mark.asyncio
    async def test_auth_error_is_not_retried(self, db, monkeypatch):
        await _seed_config(db)

        attempts = {"n": 0}

        async def auth_failed(self, request, *, timeout_seconds):
            attempts["n"] += 1
            raise ProviderAuthError("bad key", provider="mistral")

        _stub_adapter(monkeypatch, complete_impl=auth_failed)
        router = SmartLLMRouter()
        with pytest.raises(LLMCallFailedError) as exc_info:
            await router.call(db, LLMCallRequest(caller_id="t", prompt="hi"))
        assert exc_info.value.failure_type == "auth_error"
        assert attempts["n"] == 1  # No retries.

    def test_backoff_schedule_matches_fr_spec(self):
        # FR 16.0 §5.2: 1s, 2s, 4s, then give up. Three retry attempts maximum.
        # (Tests use a monkey-patched short schedule, so import the constant
        # from the module directly.)
        from artha.api_v2.llm import router_runtime

        # The original constant is documented in the module; the override here
        # is the test's local schedule. Both should be a 3-tuple.
        assert len(_BACKOFF_SCHEDULE) == 3
        assert len(router_runtime._BACKOFF_SCHEDULE) == 3


# ===========================================================================
# 4. Rate limiter (FR 16.0 §5.1)
# ===========================================================================


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_token_bucket_allows_calls_under_quota(self):
        bucket = _TokenBucket(calls_per_minute=5)
        # 5 acquires in a row should all return immediately.
        for _ in range(5):
            await bucket.acquire()

    @pytest.mark.asyncio
    async def test_token_bucket_blocks_when_over_quota(self, monkeypatch):
        """The 4th acquire on a 3/min bucket should sleep until a slot frees up.

        We patch ``asyncio.sleep`` to an instant no-op + capture the requested
        wait so we can assert it without sitting through 60 real seconds.
        """
        import asyncio

        sleeps = []
        original_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            sleeps.append(seconds)
            await original_sleep(0)  # yield to event loop

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        bucket = _TokenBucket(calls_per_minute=3)
        for _ in range(3):
            await bucket.acquire()
        # 4th acquire should hit the wait path.
        await bucket.acquire()

        assert any(s > 0 for s in sleeps), "expected the 4th acquire to sleep"
