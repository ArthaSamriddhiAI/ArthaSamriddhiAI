"""C0 conversational REST router — chunk plan §1.2 surface.

Endpoints:

- ``POST /api/v2/conversations``                      — start a conversation
- ``GET  /api/v2/conversations``                      — list visible conversations
- ``GET  /api/v2/conversations/{conversation_id}``    — fetch full thread
- ``POST /api/v2/conversations/{id}/messages``        — send one user turn
- ``POST /api/v2/conversations/{id}/confirm``         — confirm summary card
- ``POST /api/v2/conversations/{id}/cancel``          — cancel mid-flight

Permission gates:

- Reads: any of ``conversations:read:own_book`` / ``...:firm_scope`` (the
  service layer applies the actual scope filter per role).
- Writes: ``conversations:write:own_book`` (advisor only in cluster 1; CIO
  / compliance / audit have no write surface here).

Errors map to RFC 7807 problem details where structured (404, 409, 422
state errors). Pydantic validation returns FastAPI's default 422 envelope.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.c0 import service as c0_service
from artha.api_v2.c0.schemas import (
    CancelConversationRequest,
    ConfirmActionRequest,
    ConversationRead,
    ConversationsListResponse,
    CreateConversationRequest,
    PostMessageRequest,
)
from artha.api_v2.investors.service import DuplicatePanError
from artha.api_v2.llm.router_runtime import SmartLLMRouter, get_smart_llm_router
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/conversations", tags=["c0"])


def _read_perms_any():
    return Depends(
        require_permission(
            Permission.CONVERSATIONS_READ_OWN_BOOK,
            Permission.CONVERSATIONS_READ_FIRM_SCOPE,
            mode="any",
        )
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@router.get("", response_model=ConversationsListResponse)
async def list_conversations(
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    rows = await c0_service.list_conversations(db, actor=actor)
    return ConversationsListResponse(conversations=rows)


@router.get("/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        return await c0_service.get_conversation(
            db, conversation_id=conversation_id, actor=actor
        )
    except c0_service.ConversationNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Conversation not found",
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    body: CreateConversationRequest,  # noqa: ARG001 — empty by design
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.CONVERSATIONS_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,  # noqa: ARG001 — reserved for future per-request headers
):
    async with db.begin():
        convo = await c0_service.start_conversation(db, actor=actor)
    # Re-fetch with messages (empty so far) so the UI can render straight away.
    return await c0_service.get_conversation(
        db, conversation_id=convo.conversation_id, actor=actor
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationRead,
)
async def post_message(
    conversation_id: str,
    body: PostMessageRequest,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.CONVERSATIONS_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    smart_router: Annotated[SmartLLMRouter, Depends(get_smart_llm_router)],
):
    try:
        async with db.begin():
            await c0_service.post_message(
                db,
                conversation_id=conversation_id,
                user_message=body.content,
                actor=actor,
                router=smart_router,
            )
    except c0_service.ConversationNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Conversation not found",
            detail=str(exc),
        )
    except c0_service.ConversationStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Conversation state invalid",
            detail=str(exc),
        )
    return await c0_service.get_conversation(
        db, conversation_id=conversation_id, actor=actor
    )


@router.post(
    "/{conversation_id}/confirm",
    response_model=ConversationRead,
)
async def confirm_action(
    conversation_id: str,
    body: ConfirmActionRequest,  # noqa: ARG001 — empty by design
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.CONVERSATIONS_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        async with db.begin():
            await c0_service.confirm_action(
                db, conversation_id=conversation_id, actor=actor
            )
    except c0_service.ConversationNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Conversation not found",
            detail=str(exc),
        )
    except c0_service.ConversationStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Conversation state invalid",
            detail=str(exc),
        )
    except DuplicatePanError as exc:
        # Surface the duplicate-PAN warning so the chat UI can prompt the
        # user. The conversation has already been moved back to
        # AWAITING_CONFIRMATION inside the service.
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Duplicate PAN",
            detail=(
                f"PAN {exc.warning.pan!r} already exists for "
                f"{exc.warning.duplicate_of_name!r}."
            ),
            extras={"duplicate": exc.warning.model_dump(mode="json")},
        )
    return await c0_service.get_conversation(
        db, conversation_id=conversation_id, actor=actor
    )


@router.post(
    "/{conversation_id}/cancel",
    response_model=ConversationRead,
)
async def cancel_conversation(
    conversation_id: str,
    body: CancelConversationRequest,  # noqa: ARG001 — empty by design
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.CONVERSATIONS_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        async with db.begin():
            await c0_service.cancel_conversation(
                db, conversation_id=conversation_id, actor=actor
            )
    except c0_service.ConversationNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Conversation not found",
            detail=str(exc),
        )
    except c0_service.ConversationStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Conversation state invalid",
            detail=str(exc),
        )
    return await c0_service.get_conversation(
        db, conversation_id=conversation_id, actor=actor
    )
