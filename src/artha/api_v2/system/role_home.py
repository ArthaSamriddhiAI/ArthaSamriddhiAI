"""``POST /api/v2/system/role-home-visited`` — chunk 0.2 telemetry endpoint.

Per chunk 0.2 acceptance criterion 11:
    "Each role's home page emits a T1 telemetry event for the role tree
     visit (`role_home_visited` with payload `{role, user_id}`); useful
     for understanding role-tree usage patterns."

The React app fires a one-shot POST to this endpoint when the user
lands on a role-tree home page. The endpoint emits the T1 event from
the user's JWT-resolved identity (so the event source can't be spoofed
client-side).

Returns 204 No Content on success.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.dependencies import get_current_user
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.observability.t1 import emit_event
from artha.api_v2.system.event_names import ROLE_HOME_VISITED
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/system", tags=["system"])


@router.post(
    "/role-home-visited",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Telemetry: user landed on their role-tree home page (chunk 0.2)",
)
async def role_home_visited(
    user: Annotated[UserContext, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    async with db.begin():
        await emit_event(
            db,
            event_name=ROLE_HOME_VISITED,
            payload={
                "role": user.role.value,
                "user_id": user.user_id,
            },
            firm_id=user.firm_id,
        )
