"""M1 mandate REST router — chunk 2.1 + 2.4 surface.

Endpoints (chunk 2.1 — mandate creation + read paths):

- ``GET  /api/v2/investors/{id}/mandate/defaults``  — I0 defaults + sources
- ``POST /api/v2/investors/{id}/mandate``           — create initial mandate
- ``GET  /api/v2/investors/{id}/mandate``           — fetch active mandate
- ``GET  /api/v2/investors/{id}/mandate/versions``  — list all versions
- ``GET  /api/v2/mandates/{mandate_id}``            — fetch by mandate_id

Endpoint (chunk 2.4 — PDF stub):

- ``POST /api/v2/mandates/from-pdf``  — 501 Not Implemented

Permission gates:

- Reads: ``mandates:read:own_book`` OR ``mandates:read:firm_scope``
  (mode="any"; the service applies the actual scope filter).
- Writes: ``mandates:write:own_book`` (advisor only in cluster 2).

Errors map to RFC 7807 problem details where structured (404, 409, 422
state errors).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile, status
from fastapi import File as UploadFileParam
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.m1 import service as m1_service
from artha.api_v2.m1.event_names import (
    MANDATE_CREATION_BLOCKED_EXISTING,
    PDF_ENDPOINT_CALLED,
)
from artha.api_v2.m1.schemas import (
    AmendmentApproveRequest,
    AmendmentDiffResponse,
    AmendmentDraftUpdateRequest,
    AmendmentRejectRequest,
    AmendmentRequestChangesRequest,
    AmendmentSubmitRequest,
    MandateCreateRequest,
    MandateCreateResponse,
    MandateDefaultsRead,
    MandateRead,
    MandateVersionRead,
    MandateVersionsListResponse,
    PendingAmendmentsResponse,
)
from artha.api_v2.m1.validation import MandateValidationError
from artha.api_v2.observability.t1 import emit_event
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2", tags=["mandates"])


def _read_perms_any():
    return Depends(
        require_permission(
            Permission.MANDATES_READ_OWN_BOOK,
            Permission.MANDATES_READ_FIRM_SCOPE,
            mode="any",
        )
    )


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


@router.get(
    "/investors/{investor_id}/mandate/defaults",
    response_model=MandateDefaultsRead,
)
async def get_defaults(
    investor_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Return I0-suggested defaults for the form's pre-population."""
    try:
        return await m1_service.get_mandate_defaults(
            db, investor_id=investor_id, actor=actor
        )
    except m1_service.InvestorNotVisibleError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Investor not found",
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "/investors/{investor_id}/mandate",
    response_model=MandateCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mandate(
    investor_id: str,
    body: MandateCreateRequest,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.MANDATES_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
):
    """Create the initial mandate for an investor.

    ``X-API-Source`` header carries forward from cluster 1 chunk 1.1 — if the
    caller sets ``X-API-Source: c0`` the mandate's ``created_via`` becomes
    ``conversational``; ``X-API-Source: api`` → ``api``; otherwise ``form``.
    """
    via = _detect_created_via(request)
    try:
        async with db.begin():
            return await m1_service.create_mandate(
                db,
                investor_id=investor_id,
                payload=body,
                actor=actor,
                via=via,
            )
    except m1_service.InvestorNotVisibleError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Investor not found",
            detail=str(exc),
        )
    except m1_service.MandateAlreadyExistsError as exc:
        # The create transaction rolled back; emit the audit event in a
        # separate transaction so the audit row survives the failed create.
        async with db.begin():
            await emit_event(
                db,
                event_name=MANDATE_CREATION_BLOCKED_EXISTING,
                payload={
                    "investor_id": exc.investor_id,
                    "existing_mandate_id": exc.mandate_id,
                    "blocked_for": actor.user_id,
                },
                firm_id=actor.firm_id,
            )
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Mandate already exists",
            detail=(
                "Investor already has an active mandate. To change "
                "constraints, propose an amendment instead."
            ),
            extras={
                "mandate_id": exc.mandate_id,
                "investor_id": exc.investor_id,
            },
        )
    except MandateValidationError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Mandate validation failed",
            detail=f"{len(exc.failures)} validation failure(s).",
            extras={"failures": exc.failures},
        )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get(
    "/investors/{investor_id}/mandate", response_model=MandateRead
)
async def get_active_mandate(
    investor_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Return the active mandate for an investor."""
    try:
        mandate = await m1_service.get_active_mandate(
            db, investor_id=investor_id, actor=actor
        )
    except m1_service.InvestorNotVisibleError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Investor not found",
            detail=str(exc),
        )
    if mandate is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="No mandate for investor",
            detail=(
                f"Investor {investor_id!r} does not have a mandate yet. "
                "Use POST /api/v2/investors/{id}/mandate to create one."
            ),
        )
    return mandate


@router.get(
    "/investors/{investor_id}/mandate/versions",
    response_model=MandateVersionsListResponse,
)
async def list_mandate_versions(
    investor_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Return all versions of an investor's mandate, oldest first."""
    try:
        rows = await m1_service.list_versions(
            db, investor_id=investor_id, actor=actor
        )
    except m1_service.InvestorNotVisibleError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Investor not found",
            detail=str(exc),
        )
    return MandateVersionsListResponse(versions=rows)


@router.get("/mandates/{mandate_id}", response_model=MandateRead)
async def get_mandate_by_id(
    mandate_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Fetch by mandate id (visibility scoped via the linked investor)."""
    mandate = await m1_service.get_mandate_by_id(
        db, mandate_id=mandate_id, actor=actor
    )
    if mandate is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Mandate not found",
            detail=f"No mandate with id={mandate_id!r} visible to your role.",
        )
    return mandate


# ---------------------------------------------------------------------------
# Amendment workflow (chunk 2.3 — FR Entry 12.2)
# ---------------------------------------------------------------------------


@router.post(
    "/investors/{investor_id}/mandate/amend",
    response_model=MandateVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def propose_amendment(
    investor_id: str,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.MANDATES_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
):
    """Create a fresh draft amendment (FR 12.2 §3.3)."""
    via = _detect_created_via(request)
    try:
        async with db.begin():
            return await m1_service.propose_amendment(
                db, investor_id=investor_id, actor=actor, via=via
            )
    except m1_service.InvestorNotVisibleError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Investor not found",
            detail=str(exc),
        )
    except m1_service.NoActiveMandateError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="No mandate to amend",
            detail=str(exc),
        )
    except m1_service.PendingAmendmentExistsError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Amendment already in progress",
            detail=(
                f"A {exc.status} amendment already exists for this mandate. "
                "Wait for it to be resolved or edit it instead of starting a "
                "new one."
            ),
            extras={
                "version_id": exc.version_id,
                "mandate_id": exc.mandate_id,
                "status": exc.status,
            },
        )


@router.put(
    "/mandate-versions/{version_id}",
    response_model=MandateVersionRead,
)
async def update_draft(
    version_id: str,
    body: AmendmentDraftUpdateRequest,
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.MANDATES_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Update an in-progress draft amendment (FR 12.2 §3.4)."""
    try:
        async with db.begin():
            return await m1_service.update_draft(
                db, version_id=version_id, payload=body, actor=actor
            )
    except m1_service.VersionNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Mandate version not found",
            detail=str(exc),
        )
    except m1_service.VersionStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Mandate version state invalid",
            detail=str(exc),
        )
    except MandateValidationError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Mandate validation failed",
            detail=f"{len(exc.failures)} validation failure(s).",
            extras={"failures": exc.failures},
        )


@router.post(
    "/mandate-versions/{version_id}/submit",
    response_model=MandateVersionRead,
)
async def submit_amendment(
    version_id: str,
    body: AmendmentSubmitRequest,  # noqa: ARG001 — empty by design
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.MANDATES_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Submit a draft amendment for CIO review (FR 12.2 §3.5)."""
    try:
        async with db.begin():
            return await m1_service.submit_for_approval(
                db, version_id=version_id, actor=actor
            )
    except m1_service.VersionNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Mandate version not found",
            detail=str(exc),
        )
    except m1_service.VersionStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Mandate version state invalid",
            detail=str(exc),
        )
    except MandateValidationError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Mandate validation failed",
            detail=f"{len(exc.failures)} validation failure(s).",
            extras={"failures": exc.failures},
        )


@router.get(
    "/cio/pending-amendments", response_model=PendingAmendmentsResponse
)
async def list_pending_amendments(
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """CIO's pending-amendment queue (FR 12.2 §4.1)."""
    rows = await m1_service.list_pending_amendments(db, actor=actor)
    return PendingAmendmentsResponse(pending=rows)


@router.get(
    "/mandate-versions/{version_id}/diff",
    response_model=AmendmentDiffResponse,
)
async def get_amendment_diff(
    version_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Side-by-side diff + impact analysis (FR 12.2 §4.2 + §4.3)."""
    try:
        return await m1_service.get_amendment_diff(
            db, version_id=version_id, actor=actor
        )
    except m1_service.VersionNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Mandate version not found",
            detail=str(exc),
        )
    except m1_service.VersionStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Mandate version state invalid",
            detail=str(exc),
        )


@router.post(
    "/mandate-versions/{version_id}/approve",
    response_model=MandateVersionRead,
)
async def approve_amendment(
    version_id: str,
    body: AmendmentApproveRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MANDATES_APPROVE_FIRM_SCOPE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """CIO approves a pending amendment (FR 12.2 §5.1)."""
    try:
        async with db.begin():
            return await m1_service.approve_amendment(
                db, version_id=version_id, actor=actor, comments=body.comments
            )
    except m1_service.VersionNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Mandate version not found",
            detail=str(exc),
        )
    except m1_service.VersionStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Mandate version state invalid",
            detail=str(exc),
        )


@router.post(
    "/mandate-versions/{version_id}/reject",
    response_model=MandateVersionRead,
)
async def reject_amendment(
    version_id: str,
    body: AmendmentRejectRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MANDATES_APPROVE_FIRM_SCOPE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """CIO rejects a pending amendment (FR 12.2 §5.2)."""
    try:
        async with db.begin():
            return await m1_service.reject_amendment(
                db,
                version_id=version_id,
                actor=actor,
                rejection_reason=body.rejection_reason,
            )
    except m1_service.VersionNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Mandate version not found",
            detail=str(exc),
        )
    except m1_service.VersionStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Mandate version state invalid",
            detail=str(exc),
        )


@router.post(
    "/mandate-versions/{version_id}/request-changes",
    response_model=MandateVersionRead,
)
async def request_changes(
    version_id: str,
    body: AmendmentRequestChangesRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.MANDATES_APPROVE_FIRM_SCOPE)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """CIO requests changes on a pending amendment (FR 12.2 §5.3)."""
    try:
        async with db.begin():
            return await m1_service.request_changes(
                db,
                version_id=version_id,
                actor=actor,
                comments=body.comments,
            )
    except m1_service.VersionNotFoundError as exc:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Mandate version not found",
            detail=str(exc),
        )
    except m1_service.VersionStateError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Mandate version state invalid",
            detail=str(exc),
        )


# ---------------------------------------------------------------------------
# Chunk 2.4 — PDF stub
# ---------------------------------------------------------------------------


@router.post(
    "/mandates/from-pdf",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses={
        501: {
            "description": (
                "PDF parsing is not yet implemented (cluster 2 demo addendum "
                "§1.1). Production-readiness phase ships the LLM-based "
                "extraction; cluster 2 reserves the endpoint."
            ),
        },
    },
)
async def from_pdf(
    file: Annotated[UploadFile, UploadFileParam(...)],
    actor: Annotated[
        UserContext, Depends(require_permission(Permission.MANDATES_WRITE_OWN_BOOK))
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """501 Not Implemented stub — chunk 2.4 / cluster 2 demo addendum §1.1.

    Reserves the architectural surface so the production-readiness phase can
    flip the implementation in without touching the path or the OpenAPI
    contract. The PDF body is consumed (so multipart parsers don't error)
    but never persisted.
    """
    # Read + discard so the upload completes cleanly.
    _ = await file.read()
    async with db.begin():
        await emit_event(
            db,
            event_name=PDF_ENDPOINT_CALLED,
            payload={
                "filename": file.filename,
                "size_bytes": file.size if hasattr(file, "size") else None,
                "called_by": actor.user_id,
            },
            firm_id=actor.firm_id,
        )
    return problem_response(
        status=status.HTTP_501_NOT_IMPLEMENTED,
        title="PDF parsing not yet implemented",
        detail=(
            "PDF parsing not yet implemented. Use POST "
            "/api/v2/investors/{investor_id}/mandate with structured JSON "
            "instead."
        ),
        extras={"alternative_endpoint": "/api/v2/investors/{investor_id}/mandate"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_created_via(request: Request) -> str:
    """Honour an X-API-Source header (carries forward from chunk 1.1)."""
    source = request.headers.get("x-api-source", "").lower()
    if source == "c0":
        return "conversational"
    if source == "api":
        return "api"
    return "form"
