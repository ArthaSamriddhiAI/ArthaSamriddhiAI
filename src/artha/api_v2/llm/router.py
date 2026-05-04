"""SmartLLMRouter REST router — chunk plan §1.3 surface.

Endpoints (all CIO-only):

- ``GET    /api/v2/llm/config``                — read masked config
- ``PUT    /api/v2/llm/config``                — update active provider + keys
- ``POST   /api/v2/llm/test-connection``       — validate an API key
- ``POST   /api/v2/llm/kill-switch/activate``  — halt all LLM calls
- ``POST   /api/v2/llm/kill-switch/deactivate``— resume LLM calls
- ``GET    /api/v2/llm/status``                — first-run banner check

Permission gate:

- Read endpoints require ``system:llm_config:read``.
- Write endpoints require ``system:llm_config:write``.

Cluster 1 only the CIO role holds those permissions, so non-CIO callers
hit 403 (FR 17.2 §5).

Errors translate to RFC 7807 problem details where the failure shape is
structured (validation errors, missing API keys); FastAPI's default 422
envelope handles Pydantic-level type errors (the frontend reads it
inline).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.llm import service as llm_service
from artha.api_v2.llm.schemas import (
    KillSwitchResponse,
    LLMConfigRead,
    LLMConfigUpdateRequest,
    TestConnectionRequest,
    TestConnectionResponse,
)
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/llm", tags=["llm"])


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/config", response_model=LLMConfigRead)
async def get_llm_config(
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.SYSTEM_LLM_CONFIG_READ)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Return the masked LLM config + status flags for the settings UI."""
    _ = actor
    return await llm_service.get_config_read(db)


@router.get("/status")
async def get_llm_status(
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.SYSTEM_LLM_CONFIG_READ)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """First-run banner check — ``{ "is_configured": bool }``.

    The CIO home tree polls this on mount; until it returns ``true``, the
    banner stays visible. Cheap response shape so the home tree can re-fetch
    after the CIO saves the config.
    """
    _ = actor
    is_configured = await llm_service.get_config_status(db)
    return {"is_configured": is_configured}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


@router.put("/config", response_model=LLMConfigRead)
async def put_llm_config(
    body: LLMConfigUpdateRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.SYSTEM_LLM_CONFIG_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Apply a partial config update (validate + persist + T1)."""
    try:
        async with db.begin():
            return await llm_service.update_config(db, payload=body, actor=actor)
    except llm_service.ConfigValidationError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="LLM configuration invalid",
            detail=str(exc),
            extras={"code": exc.code},
        )


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


@router.post("/test-connection", response_model=TestConnectionResponse)
async def post_test_connection(
    body: TestConnectionRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.SYSTEM_LLM_CONFIG_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Make a one-off provider call to validate the API key."""
    _ = actor
    return await llm_service.test_connection(db, payload=body)


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


@router.post("/kill-switch/activate", response_model=KillSwitchResponse)
async def post_kill_switch_activate(
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.SYSTEM_LLM_CONFIG_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Halt all LLM calls firm-wide (FR 16.0 §7)."""
    async with db.begin():
        return await llm_service.activate_kill_switch(db, actor=actor)


@router.post("/kill-switch/deactivate", response_model=KillSwitchResponse)
async def post_kill_switch_deactivate(
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.SYSTEM_LLM_CONFIG_WRITE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Resume LLM calls after a kill-switch activation."""
    async with db.begin():
        return await llm_service.deactivate_kill_switch(db, actor=actor)
