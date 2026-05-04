"""SmartLLMRouter service layer — config CRUD + test-connection + kill switch.

Pure functions over :class:`AsyncSession`; the FastAPI router (see
:mod:`artha.api_v2.llm.router`) wraps these in HTTP shapes and permission
gates. The service layer is also reachable from tests + future scripted
flows (e.g., a dev provisioning script that pre-populates a Mistral key).

Per FR Entry 16.0 §4.1: every config write is paired with a T1 event in the
same transaction so audit replay can reconstruct the configuration history.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.llm.encryption import (
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
)
from artha.api_v2.llm.event_names import (
    LLM_KILL_SWITCH_ACTIVATED,
    LLM_KILL_SWITCH_DEACTIVATED,
    LLM_PROVIDER_CONFIGURATION_CHANGED,
)
from artha.api_v2.llm.models import SINGLETON_CONFIG_ID, LLMProviderConfig
from artha.api_v2.llm.providers import (
    PROVIDER_REGISTRY,
    LLMCallRequest,
    ProviderAuthError,
    ProviderError,
)
from artha.api_v2.llm.schemas import (
    KillSwitchResponse,
    LLMConfigRead,
    LLMConfigUpdateRequest,
    TestConnectionRequest,
    TestConnectionResponse,
)
from artha.api_v2.observability.t1 import emit_event
from artha.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions surfaced to the router
# ---------------------------------------------------------------------------


class ConfigValidationError(Exception):
    """Validation failure that translates to a 400 problem-details response.

    Carries a stable ``code`` so the frontend can map specific errors to
    inline form messages (e.g., ``missing_api_key`` next to the key field).
    """

    def __init__(self, detail: str, *, code: str) -> None:
        super().__init__(detail)
        self.code = code


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def load_config(db: AsyncSession) -> LLMProviderConfig | None:
    """Return the singleton config row or ``None`` if it has never been written."""
    result = await db.execute(
        select(LLMProviderConfig).where(
            LLMProviderConfig.config_id == SINGLETON_CONFIG_ID
        )
    )
    return result.scalar_one_or_none()


async def get_config_read(db: AsyncSession) -> LLMConfigRead:
    """Build the settings-UI read shape, masking API keys.

    First-run state (no row yet) returns sensible defaults from
    :data:`artha.config.settings` so the UI can render before any save.
    """
    row = await load_config(db)
    if row is None:
        return LLMConfigRead(
            active_provider=None,
            mistral_api_key_masked=None,
            claude_api_key_masked=None,
            default_mistral_model="mistral-small-latest",
            default_claude_model="claude-sonnet-4-5-20250929",
            rate_limit_calls_per_minute=settings.llm_router_default_rate_limit_per_minute,
            request_timeout_seconds=settings.llm_router_default_timeout_seconds,
            kill_switch_active=False,
            is_configured=False,
            updated_at=None,
            updated_by=None,
        )

    mistral_masked = (
        mask_api_key(decrypt_api_key(row.mistral_api_key_encrypted))
        if row.mistral_api_key_encrypted
        else None
    )
    claude_masked = (
        mask_api_key(decrypt_api_key(row.claude_api_key_encrypted))
        if row.claude_api_key_encrypted
        else None
    )

    is_configured = bool(
        row.active_provider
        and (
            (row.active_provider == "mistral" and row.mistral_api_key_encrypted)
            or (row.active_provider == "claude" and row.claude_api_key_encrypted)
        )
    )

    return LLMConfigRead(
        active_provider=row.active_provider,  # type: ignore[arg-type]
        mistral_api_key_masked=mistral_masked,
        claude_api_key_masked=claude_masked,
        default_mistral_model=row.default_mistral_model,
        default_claude_model=row.default_claude_model,
        rate_limit_calls_per_minute=row.rate_limit_calls_per_minute,
        request_timeout_seconds=row.request_timeout_seconds,
        kill_switch_active=row.kill_switch_active,
        is_configured=is_configured,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


async def get_config_status(db: AsyncSession) -> bool:
    """Return ``True`` if the deployment has a usable LLM provider configured.

    Used by the first-run banner check on the CIO home tree (FR 16.0 §4.3).
    """
    row = await load_config(db)
    if row is None or not row.active_provider:
        return False
    if row.active_provider == "mistral":
        return row.mistral_api_key_encrypted is not None
    if row.active_provider == "claude":
        return row.claude_api_key_encrypted is not None
    return False


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def update_config(
    db: AsyncSession,
    *,
    payload: LLMConfigUpdateRequest,
    actor: UserContext,
) -> LLMConfigRead:
    """Apply a partial config update (validate + persist + T1).

    Validation rules per chunk plan §1.3 acceptance criteria #5: if the
    updated payload sets ``active_provider`` to a provider for which no key
    is currently stored AND no new key is supplied in the same payload, the
    save fails with a validation error.
    """
    row = await load_config(db)
    previous_provider = row.active_provider if row else None
    now = datetime.now(timezone.utc)

    if row is None:
        row = LLMProviderConfig(
            config_id=SINGLETON_CONFIG_ID,
            active_provider=None,
            mistral_api_key_encrypted=None,
            claude_api_key_encrypted=None,
            default_mistral_model="mistral-small-latest",
            default_claude_model="claude-sonnet-4-5-20250929",
            rate_limit_calls_per_minute=settings.llm_router_default_rate_limit_per_minute,
            request_timeout_seconds=settings.llm_router_default_timeout_seconds,
            kill_switch_active=False,
            updated_at=now,
            updated_by=actor.user_id,
        )
        db.add(row)

    # Apply API key updates first so the active-provider check sees the new state.
    if payload.mistral_api_key:
        row.mistral_api_key_encrypted = encrypt_api_key(payload.mistral_api_key)
    if payload.claude_api_key:
        row.claude_api_key_encrypted = encrypt_api_key(payload.claude_api_key)

    if payload.active_provider is not None:
        row.active_provider = payload.active_provider

    if payload.default_mistral_model:
        row.default_mistral_model = payload.default_mistral_model
    if payload.default_claude_model:
        row.default_claude_model = payload.default_claude_model

    # Validate post-update state.
    if row.active_provider == "mistral" and not row.mistral_api_key_encrypted:
        raise ConfigValidationError(
            "Mistral selected as active provider but no Mistral API key is configured.",
            code="missing_mistral_api_key",
        )
    if row.active_provider == "claude" and not row.claude_api_key_encrypted:
        raise ConfigValidationError(
            "Claude selected as active provider but no Claude API key is configured.",
            code="missing_claude_api_key",
        )

    row.updated_at = now
    row.updated_by = actor.user_id

    await db.flush()

    await emit_event(
        db,
        event_name=LLM_PROVIDER_CONFIGURATION_CHANGED,
        payload={
            "previous_provider": previous_provider,
            "new_provider": row.active_provider,
            "changed_by": actor.user_id,
            "mistral_key_updated": bool(payload.mistral_api_key),
            "claude_key_updated": bool(payload.claude_api_key),
        },
        firm_id=actor.firm_id,
    )

    return await get_config_read(db)


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


async def test_connection(
    db: AsyncSession, *, payload: TestConnectionRequest
) -> TestConnectionResponse:
    """Make a one-off provider call to validate the API key.

    The "Test Connection" prompt is intentionally trivial (FR §6 + chunk plan
    implementation notes: "minimal prompt to keep cost negligible"). Errors
    are mapped to a structured response so the UI can show a green check or
    a specific failure reason.
    """
    api_key = payload.api_key
    if not api_key:
        # Use the saved key for the requested provider, if any.
        row = await load_config(db)
        if row is None:
            return TestConnectionResponse(
                success=False,
                provider=payload.provider,
                detail="No saved API key for this provider; enter one and try again.",
                failure_type="not_configured",
            )
        ciphertext = (
            row.mistral_api_key_encrypted
            if payload.provider == "mistral"
            else row.claude_api_key_encrypted
        )
        if not ciphertext:
            return TestConnectionResponse(
                success=False,
                provider=payload.provider,
                detail=f"No saved {payload.provider} API key; enter one and try again.",
                failure_type="not_configured",
            )
        api_key = decrypt_api_key(ciphertext)

    adapter_cls = PROVIDER_REGISTRY[payload.provider]
    default_model = (
        "mistral-small-latest"
        if payload.provider == "mistral"
        else "claude-sonnet-4-5-20250929"
    )
    # Pull saved defaults if a row exists; otherwise the static defaults above.
    row = await load_config(db)
    if row is not None:
        default_model = (
            row.default_mistral_model
            if payload.provider == "mistral"
            else row.default_claude_model
        )

    adapter = adapter_cls(api_key=api_key, default_model=default_model)
    request = LLMCallRequest(
        caller_id="llm_test_connection",
        prompt="Reply with the single word: OK",
        max_tokens=8,
        temperature=0.0,
    )

    try:
        response = await adapter.complete(request, timeout_seconds=15)
    except ProviderAuthError as exc:
        return TestConnectionResponse(
            success=False,
            provider=payload.provider,
            detail="Authentication failed — the API key was rejected by the provider.",
            failure_type=exc.failure_type,
        )
    except ProviderError as exc:
        return TestConnectionResponse(
            success=False,
            provider=payload.provider,
            detail=f"Provider call failed: {exc}",
            failure_type=exc.failure_type,
        )

    return TestConnectionResponse(
        success=True,
        provider=payload.provider,
        detail=f"Connection successful (response: {response.content[:60]!r})",
        failure_type=None,
        latency_ms=response.latency_ms,
    )


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


async def activate_kill_switch(
    db: AsyncSession, *, actor: UserContext
) -> KillSwitchResponse:
    row = await _ensure_config_row(db, actor)
    row.kill_switch_active = True
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = actor.user_id
    await db.flush()
    await emit_event(
        db,
        event_name=LLM_KILL_SWITCH_ACTIVATED,
        payload={"activated_by": actor.user_id},
        firm_id=actor.firm_id,
    )
    return KillSwitchResponse(
        kill_switch_active=True,
        activated_at=row.updated_at,
        activated_by=actor.user_id,
    )


async def deactivate_kill_switch(
    db: AsyncSession, *, actor: UserContext
) -> KillSwitchResponse:
    row = await _ensure_config_row(db, actor)
    row.kill_switch_active = False
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = actor.user_id
    await db.flush()
    await emit_event(
        db,
        event_name=LLM_KILL_SWITCH_DEACTIVATED,
        payload={"deactivated_by": actor.user_id},
        firm_id=actor.firm_id,
    )
    return KillSwitchResponse(
        kill_switch_active=False,
        activated_at=None,
        activated_by=None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _ensure_config_row(
    db: AsyncSession, actor: UserContext
) -> LLMProviderConfig:
    """Get-or-create the singleton row (kill-switch ops can run before any
    config has been saved; we still want them recorded)."""
    row = await load_config(db)
    if row is not None:
        return row
    now = datetime.now(timezone.utc)
    row = LLMProviderConfig(
        config_id=SINGLETON_CONFIG_ID,
        active_provider=None,
        mistral_api_key_encrypted=None,
        claude_api_key_encrypted=None,
        default_mistral_model="mistral-small-latest",
        default_claude_model="claude-sonnet-4-5-20250929",
        rate_limit_calls_per_minute=settings.llm_router_default_rate_limit_per_minute,
        request_timeout_seconds=settings.llm_router_default_timeout_seconds,
        kill_switch_active=False,
        updated_at=now,
        updated_by=actor.user_id,
    )
    db.add(row)
    await db.flush()
    return row
