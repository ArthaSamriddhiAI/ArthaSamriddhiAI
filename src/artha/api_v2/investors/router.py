"""Investors + households REST router.

Endpoints (per chunk 1.1 §scope_in):

- ``POST /api/v2/investors`` — create + I0 enrich (form / conversational / api callers)
- ``GET  /api/v2/investors`` — list scoped by actor's role
- ``GET  /api/v2/investors/{investor_id}`` — fetch one (scoped)
- ``GET  /api/v2/households`` — list scoped by actor's role
- ``POST /api/v2/households`` — create standalone household

Permission gates:
- Read endpoints (investors + households): require any of own_book or
  firm_scope (advisor reads own book; cio/compliance/audit read firm-wide;
  the service layer enforces the actual filtering).
- Write endpoints: require ``investors:write:own_book`` /
  ``households:write:own_book`` (advisor only in cluster 1).

Errors map to RFC 7807 problem details where structured (404, 409 duplicate
PAN). Pydantic validation errors return FastAPI's default 422 envelope; the
frontend handles those inline next to fields.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.investors import service as investor_service
from artha.api_v2.investors.schemas import (
    HouseholdCreateRequest,
    HouseholdRead,
    HouseholdsListResponse,
    InvestorCreateRequest,
    InvestorRead,
    InvestorsListResponse,
)
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2", tags=["investors"])


# ---------------------------------------------------------------------------
# Investors
# ---------------------------------------------------------------------------


def _read_perms_any():
    return Depends(
        require_permission(
            Permission.INVESTORS_READ_OWN_BOOK,
            Permission.INVESTORS_READ_FIRM_SCOPE,
            mode="any",
        )
    )


def _household_read_perms_any():
    return Depends(
        require_permission(
            Permission.HOUSEHOLDS_READ_OWN_BOOK,
            Permission.HOUSEHOLDS_READ_FIRM_SCOPE,
            mode="any",
        )
    )


@router.post(
    "/investors",
    response_model=InvestorRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_investor(
    body: InvestorCreateRequest,
    request: Request,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.INVESTORS_WRITE_OWN_BOOK)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Create one investor and run I0 enrichment synchronously.

    Determines ``created_via`` from the request: if the path includes
    ``X-API-Source: c0`` header, marks as ``conversational``; if
    ``X-API-Source: api`` (raw API consumer), marks as ``api``; otherwise
    defaults to ``form`` (the form-path is the demo-friendly default).
    """
    via = _detect_created_via(request)
    try:
        async with db.begin():
            return await investor_service.create_investor(
                db, payload=body, actor=actor, via=via
            )
    except investor_service.DuplicatePanError as exc:
        # 409 with the duplicate-PAN payload so the frontend can show the
        # warn-and-proceed dialog.
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Duplicate PAN",
            detail=(
                f"PAN {exc.warning.pan!r} already exists for "
                f"{exc.warning.duplicate_of_name!r}. Re-submit with "
                "duplicate_pan_acknowledged=true to create a separate record."
            ),
            extras={"duplicate": exc.warning.model_dump(mode="json")},
        )
    except investor_service.HouseholdResolutionError as exc:
        return problem_response(
            status=status.HTTP_400_BAD_REQUEST,
            title="Household resolution failed",
            detail=str(exc),
        )


@router.get("/investors", response_model=InvestorsListResponse)
async def list_investors(
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    investors = await investor_service.list_investors(db, actor=actor)
    return InvestorsListResponse(investors=investors)


@router.get("/investors/{investor_id}", response_model=InvestorRead)
async def get_investor(
    investor_id: str,
    actor: Annotated[UserContext, _read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    investor = await investor_service.get_investor(
        db, investor_id=investor_id, actor=actor
    )
    if investor is None:
        return problem_response(
            status=status.HTTP_404_NOT_FOUND,
            title="Investor not found",
            detail=f"No investor with id={investor_id!r} visible to your role.",
        )
    return investor


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------


@router.get("/households", response_model=HouseholdsListResponse)
async def list_households(
    actor: Annotated[UserContext, _household_read_perms_any()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    households = await investor_service.list_households(db, actor=actor)
    return HouseholdsListResponse(households=households)


@router.post(
    "/households",
    response_model=HouseholdRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_household(
    body: HouseholdCreateRequest,
    actor: Annotated[
        UserContext,
        Depends(require_permission(Permission.HOUSEHOLDS_WRITE_OWN_BOOK)),
    ],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    async with db.begin():
        return await investor_service.create_household(
            db, name=body.name, actor=actor, emit_t1=True
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_created_via(request: Request) -> str:
    """Honour an X-API-Source header for non-form callers (C0, API consumers).

    The frontend form omits the header; defaults to ``form``.
    """
    source = request.headers.get("x-api-source", "").lower()
    if source == "c0":
        return "conversational"
    if source == "api":
        return "api"
    return "form"
