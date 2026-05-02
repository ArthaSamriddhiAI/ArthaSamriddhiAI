"""SSE channel endpoint: ``GET /api/v2/events/stream``.

Per FR Entry 18.0 §2.1.

Auth: requires a valid Bearer JWT in the ``Authorization`` header. The
:func:`get_current_user` dependency from :mod:`artha.api_v2.auth.dependencies`
handles the validation and constructs the :class:`UserContext`.

Reconnect: clients that present the standard SSE ``Last-Event-ID`` header
get any buffered events with id > Last-Event-ID replayed before normal
event delivery resumes. The buffer is shared across reconnects within the
same auth session per FR 18.0 §2.7's "connection_session_token persists
across reconnects within the same session."
"""

from __future__ import annotations

from typing import Annotated

import jwt as pyjwt
from fastapi import APIRouter, Depends, Header, Request
from sse_starlette.sse import EventSourceResponse

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.events.stream import sse_event_stream

router = APIRouter(prefix="/api/v2/events", tags=["events"])


@router.get("/stream")
async def stream(
    request: Request,
    user: Annotated[
        UserContext,
        # Per FR 17.2 §6: advisor has events:subscribe:own_scope; cio /
        # compliance / audit have events:subscribe:firm_scope. Either is
        # sufficient to open the stream.
        Depends(
            require_permission(
                Permission.EVENTS_SUBSCRIBE_OWN_SCOPE,
                Permission.EVENTS_SUBSCRIBE_FIRM_SCOPE,
                mode="any",
            )
        ),
    ],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    """Open a long-lived SSE channel for the authenticated user."""
    # Pull the JWT exp out of the Authorization header so the stream can
    # schedule token_refresh_required at exp − lead.
    jwt_exp = _extract_jwt_exp(request)

    # Headers per FR 18.0 §2.1 — defeat intermediate proxy buffering.
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    }

    return EventSourceResponse(
        sse_event_stream(user, last_event_id=last_event_id, jwt_exp=jwt_exp),
        headers=headers,
    )


def _extract_jwt_exp(request: Request) -> int | None:
    """Pull ``exp`` from the bearer JWT without re-verifying signature.

    Signature was already validated by the upstream :func:`get_current_user`
    dependency — we just need the timestamp. Decoding without verification
    is safe here for that reason.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(None, 1)[1]
    try:
        claims = pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.PyJWTError:
        return None
    exp = claims.get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None
