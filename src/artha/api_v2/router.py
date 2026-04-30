"""Doc 2 — `/api/v2/` root router.

Sub-routers (auth, investors, mandates, cases, ...) attach themselves to
the v2 root router as they are built in subsequent passes. Pass 1 ships
the root router only with a stub `/api/v2/system/health` so the
deployment can verify v2 is mounted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from artha.api_v2.auth import UserContext, get_current_user

V2_PREFIX = "/api/v2"


def create_v2_router() -> APIRouter:
    """Build the `/api/v2/` root router. Subsequent passes mount sub-routers."""
    router = APIRouter(prefix=V2_PREFIX, tags=["api_v2"])

    @router.get(
        "/system/health",
        summary="API v2 liveness check",
        responses={200: {"description": "API v2 is mounted and responding."}},
    )
    async def health() -> dict[str, str]:
        """Pass 1 stub — replaced by the full System family in Pass 12."""
        return {"status": "ok", "service": "samriddhi-api-v2", "phase": "foundation"}

    @router.get(
        "/auth/whoami",
        summary="Smoke endpoint that echoes the authenticated UserContext",
    )
    async def whoami(user: UserContext = Depends(get_current_user)) -> dict[str, object]:
        """Pass 1 stub for end-to-end auth + permission verification.

        Subsequent passes replace this with the full `/auth/session` endpoint
        (Pass 2). Until then it gives integration tests a concrete authed
        endpoint to hit.
        """
        return {
            "user_id": user.user_id,
            "firm_id": user.firm_id,
            "role": user.role.value,
            "permissions": sorted(p.value for p in user.permissions),
            "token_expires_at": (
                user.token_expires_at.isoformat() if user.token_expires_at else None
            ),
        }

    return router


__all__ = ["V2_PREFIX", "create_v2_router"]
