"""SmartLLMRouter call executor — FR Entry 16.0 §2.1, §5–§7.

The :class:`SmartLLMRouter` instance is the single entry point every
LLM-consuming component talks to. It:

1. Reads the active :class:`LLMProviderConfig` from the database.
2. Refuses the call if the kill switch is active or no provider is configured
   (FR §4.3 + §7).
3. Acquires a rate-limit token from the per-provider bucket (FR §5.1).
4. Decrypts the API key + instantiates the matching adapter.
5. Invokes the adapter, retrying on retriable errors with exponential
   backoff (FR §5.2).
6. Emits T1 events (``llm_call_initiated`` / ``llm_call_completed`` /
   ``llm_call_failed``) per FR §6.

Cluster 1's :class:`SmartLLMRouter` is wired into the FastAPI app via the
``get_smart_llm_router`` dependency in :mod:`artha.api_v2.llm.dependencies`.
C0 (chunk 1.2) calls it during intent detection + slot extraction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.llm.encryption import decrypt_api_key
from artha.api_v2.llm.event_names import (
    LLM_CALL_COMPLETED,
    LLM_CALL_FAILED,
    LLM_CALL_INITIATED,
)
from artha.api_v2.llm.models import LLMProviderConfig
from artha.api_v2.llm.providers import (
    PROVIDER_REGISTRY,
    LLMCallRequest,
    LLMCallResponse,
    ProviderAdapter,
    ProviderAuthError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
)
from artha.api_v2.llm.service import load_config
from artha.api_v2.observability.t1 import emit_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions surfaced to callers
# ---------------------------------------------------------------------------


class LLMRouterError(Exception):
    """Base error raised by the router to its callers (C0 today)."""


class LLMNotConfiguredError(LLMRouterError):
    """No provider has been configured yet (FR 16.0 §4.3 first-run state)."""


class LLMKillSwitchActiveError(LLMRouterError):
    """The CIO has activated the kill switch (FR 16.0 §7)."""


class LLMCallFailedError(LLMRouterError):
    """The call exhausted retries or hit a non-retriable error.

    Carries the underlying provider-error failure type (auth_error,
    timeout, rate_limit, …) so the caller can decide on degraded-mode
    behaviour.
    """

    def __init__(self, message: str, *, failure_type: str, provider: str | None) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.provider = provider


# ---------------------------------------------------------------------------
# Per-provider token bucket (FR 16.0 §5.1)
# ---------------------------------------------------------------------------


@dataclass
class _TokenBucket:
    """A simple per-minute call-counting bucket.

    Cluster 1 keeps the implementation in-process: a deque of recent call
    timestamps; each :meth:`acquire` drops timestamps older than 60s and
    blocks until the bucket is below ``calls_per_minute``. Future deployments
    that need cross-process rate limiting plug in a Redis-backed bucket
    behind the same interface.
    """

    calls_per_minute: int

    def __post_init__(self) -> None:
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            cutoff = now - 60.0
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.calls_per_minute:
                # Sleep until the oldest timestamp ages out, then re-check.
                wait_for = 60.0 - (now - self._timestamps[0])
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
                # Re-clean after sleeping.
                now = time.monotonic()
                cutoff = now - 60.0
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()
            self._timestamps.append(now)


# ---------------------------------------------------------------------------
# Retry policy (FR 16.0 §5.2)
# ---------------------------------------------------------------------------

#: Errors that should trigger a retry with exponential backoff.
_RETRIABLE = (
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
)

#: Backoff schedule from the FR (1s, 2s, 4s).
_BACKOFF_SCHEDULE = (1.0, 2.0, 4.0)


# ---------------------------------------------------------------------------
# The SmartLLMRouter
# ---------------------------------------------------------------------------


class SmartLLMRouter:
    """In-process LLM router (one per FastAPI process).

    Holds the per-provider rate-limit buckets between calls; the
    :class:`LLMProviderConfig` is re-read from the DB on each call so config
    changes (kill switch, provider switch) take effect immediately without
    restart (FR 16.0 §2.3).
    """

    def __init__(self) -> None:
        # Bucket keyed by provider name. Lazily created on first call so
        # no process state is held when no LLM consumers run yet.
        self._buckets: dict[str, _TokenBucket] = {}

    async def call(
        self, db: AsyncSession, request: LLMCallRequest
    ) -> LLMCallResponse:
        """Execute one LLM call end-to-end with full lifecycle telemetry."""
        config = await load_config(db)

        if config is None or not config.active_provider:
            await emit_event(
                db,
                event_name=LLM_CALL_FAILED,
                payload={
                    "caller_id": request.caller_id,
                    "failure_type": "not_configured",
                    "provider": None,
                },
            )
            raise LLMNotConfiguredError(
                "LLM provider not configured. Please configure in "
                "Settings > LLM Provider before using conversational features."
            )
        if config.kill_switch_active:
            await emit_event(
                db,
                event_name=LLM_CALL_FAILED,
                payload={
                    "caller_id": request.caller_id,
                    "failure_type": "kill_switch_active",
                    "provider": config.active_provider,
                },
            )
            raise LLMKillSwitchActiveError(
                "LLM calls are currently disabled (kill switch active). "
                "Contact your CIO to re-enable."
            )

        adapter = self._build_adapter(config)
        bucket = self._bucket_for(config.active_provider, config.rate_limit_calls_per_minute)

        # Estimate prompt tokens at ~4 chars per token (matches FR-style rough
        # accounting; T1 carries the exact count from the response).
        estimated_prompt_tokens = _estimate_token_count(request)

        await emit_event(
            db,
            event_name=LLM_CALL_INITIATED,
            payload={
                "caller_id": request.caller_id,
                "provider": adapter.provider_name,
                "model": request.model or config_default_model(config, adapter.provider_name),
                "prompt_token_count_estimate": estimated_prompt_tokens,
            },
        )

        last_error: ProviderError | None = None
        for attempt_index, _ in enumerate([None, *_BACKOFF_SCHEDULE]):
            await bucket.acquire()
            try:
                response = await adapter.complete(
                    request, timeout_seconds=config.request_timeout_seconds
                )
            except _RETRIABLE as exc:
                last_error = exc
                # Final attempt? give up after the schedule is exhausted.
                if attempt_index >= len(_BACKOFF_SCHEDULE):
                    break
                backoff_s = _BACKOFF_SCHEDULE[attempt_index]
                logger.warning(
                    "LLM call to %s failed (%s); retrying in %.1fs",
                    adapter.provider_name,
                    exc.failure_type,
                    backoff_s,
                )
                await asyncio.sleep(backoff_s)
                continue
            except (ProviderAuthError, ProviderInvalidResponseError) as exc:
                # Non-retriable: surface immediately.
                await emit_event(
                    db,
                    event_name=LLM_CALL_FAILED,
                    payload={
                        "caller_id": request.caller_id,
                        "provider": adapter.provider_name,
                        "failure_type": exc.failure_type,
                    },
                )
                raise LLMCallFailedError(
                    str(exc),
                    failure_type=exc.failure_type,
                    provider=adapter.provider_name,
                ) from exc
            except ProviderError as exc:  # pragma: no cover — defensive
                await emit_event(
                    db,
                    event_name=LLM_CALL_FAILED,
                    payload={
                        "caller_id": request.caller_id,
                        "provider": adapter.provider_name,
                        "failure_type": exc.failure_type,
                    },
                )
                raise LLMCallFailedError(
                    str(exc),
                    failure_type=exc.failure_type,
                    provider=adapter.provider_name,
                ) from exc

            # Success path.
            await emit_event(
                db,
                event_name=LLM_CALL_COMPLETED,
                payload={
                    "caller_id": request.caller_id,
                    "provider": adapter.provider_name,
                    "model": response.model,
                    "tokens_used": response.tokens_used,
                    "latency_ms": response.latency_ms,
                    "request_id": response.request_id,
                },
            )
            return response

        # Retries exhausted.
        assert last_error is not None
        await emit_event(
            db,
            event_name=LLM_CALL_FAILED,
            payload={
                "caller_id": request.caller_id,
                "provider": adapter.provider_name,
                "failure_type": last_error.failure_type,
                "retries_exhausted": True,
            },
        )
        raise LLMCallFailedError(
            str(last_error),
            failure_type=last_error.failure_type,
            provider=adapter.provider_name,
        ) from last_error

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _bucket_for(self, provider_name: str, calls_per_minute: int) -> _TokenBucket:
        """Return (or create) the per-provider rate-limit bucket.

        If the configured rate has changed since the last call, a new bucket
        is allocated; we don't try to migrate timestamps because the practical
        difference is negligible at cluster 1 scale.
        """
        existing = self._buckets.get(provider_name)
        if existing is not None and existing.calls_per_minute == calls_per_minute:
            return existing
        bucket = _TokenBucket(calls_per_minute=calls_per_minute)
        self._buckets[provider_name] = bucket
        return bucket

    def _build_adapter(self, config: LLMProviderConfig) -> ProviderAdapter:
        """Instantiate the matching adapter with a freshly decrypted API key."""
        provider = config.active_provider
        adapter_cls = PROVIDER_REGISTRY.get(provider or "")
        if adapter_cls is None:
            raise LLMCallFailedError(
                f"Unknown provider {provider!r}",
                failure_type="provider_error",
                provider=provider,
            )

        key_ciphertext = (
            config.mistral_api_key_encrypted
            if provider == "mistral"
            else config.claude_api_key_encrypted
        )
        if not key_ciphertext:
            raise LLMCallFailedError(
                f"No API key configured for active provider {provider!r}",
                failure_type="auth_error",
                provider=provider,
            )

        api_key = decrypt_api_key(key_ciphertext)
        default_model = config_default_model(config, provider)
        return adapter_cls(api_key=api_key, default_model=default_model)


def config_default_model(config: LLMProviderConfig, provider: str | None) -> str:
    """Return the configured default model for ``provider``."""
    if provider == "mistral":
        return config.default_mistral_model
    if provider == "claude":
        return config.default_claude_model
    return ""


def _estimate_token_count(request: LLMCallRequest) -> int:
    """Rough token-count estimate for telemetry (4 chars ≈ 1 token)."""
    if request.messages:
        chars = sum(len(m.content) for m in request.messages)
    else:
        chars = len(request.prompt or "")
    return max(1, chars // 4)


# ---------------------------------------------------------------------------
# Process-wide singleton + dependency
# ---------------------------------------------------------------------------


_router_singleton: SmartLLMRouter | None = None


def get_smart_llm_router() -> SmartLLMRouter:
    """FastAPI dependency that hands out the process-wide router instance.

    A separate factory (vs. a top-level module global) lets tests reset the
    singleton via :func:`reset_smart_llm_router`.
    """
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = SmartLLMRouter()
    return _router_singleton


def reset_smart_llm_router() -> None:
    """Test-only helper: drop the cached singleton."""
    global _router_singleton
    _router_singleton = None
