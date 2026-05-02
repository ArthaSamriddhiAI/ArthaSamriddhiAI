"""Minimal RFC 7807 Problem Details envelope.

Cluster 0 uses this for the few error cases we surface from the auth router
(401 invalid token, 404 unknown demo user, 409 refresh race, 501 unimplemented
production OIDC endpoints). A richer ProblemDetails infrastructure (with
exception handlers, type registry, per-error-class category fields) lands in
step 4 alongside the cross-cutting observability work.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict


class ProblemDetails(BaseModel):
    """RFC 7807 Problem Details object."""

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


def problem_response(
    *,
    status: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
    instance: str | None = None,
    headers: dict[str, str] | None = None,
    extras: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a JSONResponse carrying a Problem Details body.

    The response Content-Type follows RFC 7807: ``application/problem+json``.
    """
    body = ProblemDetails(
        type=type_, title=title, status=status, detail=detail, instance=instance
    ).model_dump(exclude_none=True)
    if extras:
        body.update(extras)
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
        headers=headers,
    )
