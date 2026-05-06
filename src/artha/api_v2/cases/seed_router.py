"""Demo seed admin REST surface — chunk 5.6.

Three CIO-only endpoints under ``/api/v2/admin/seed/``:

- ``GET    /status`` — current seed-row counts.
- ``POST   /load``   — load the demo fixture into the DB.
- ``POST   /reset``  — wipe every ``is_seed_data=True`` row (cascade).

Permission gate: :data:`Permission.SEED_ADMIN` (CIO-only per
FR 19.0 §3.2). The service itself double-checks ``actor.role``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.permissions import Permission, require_permission
from artha.api_v2.auth.user_context import UserContext
from artha.api_v2.cases import seed_loader
from artha.api_v2.cases.seed_loader import (
    SeedAlreadyLoadedError,
    SeedFixtureMissingError,
    SeedFrameworkError,
    SeedNotAuthorisedError,
)
from artha.api_v2.problem_details import problem_response
from artha.common.db.session import get_session

router = APIRouter(prefix="/api/v2/admin/seed", tags=["seed"])


def _seed_perm():
    return Depends(require_permission(Permission.SEED_ADMIN))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SeedStatusResponse(BaseModel):
    is_loaded: bool
    counts: dict[str, int]


class SeedLoadResponse(BaseModel):
    households: int
    investors: int
    mandates: int
    cases: int


class SeedResetResponse(BaseModel):
    cases_deleted: int
    mandates_deleted: int
    mandate_versions_deleted: int
    investors_deleted: int
    households_deleted: int
    snapshots_deleted: int
    stage_rows_deleted: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=SeedStatusResponse)
async def get_seed_status(
    actor: Annotated[UserContext, _seed_perm()],  # noqa: ARG001 — permission gate only
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Return current seed-row counts across the cluster-5 universe."""
    s = await seed_loader.get_status(db)
    return SeedStatusResponse(is_loaded=s.is_loaded, counts=s.counts)


@router.post(
    "/load",
    response_model=SeedLoadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def load_seed(
    actor: Annotated[UserContext, _seed_perm()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Load the demo fixture into the DB. CIO-only."""
    try:
        async with db.begin():
            result = await seed_loader.load_demo_seed(db, actor=actor)
    except SeedAlreadyLoadedError as exc:
        return problem_response(
            status=status.HTTP_409_CONFLICT,
            title="Seed already loaded",
            detail=str(exc),
        )
    except SeedFixtureMissingError as exc:
        return problem_response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Seed fixture missing",
            detail=str(exc),
        )
    except SeedNotAuthorisedError as exc:
        return problem_response(
            status=status.HTTP_403_FORBIDDEN,
            title="Seed admin is CIO-only",
            detail=str(exc),
        )
    except SeedFrameworkError as exc:
        return problem_response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Seed load failed",
            detail=str(exc),
        )

    return SeedLoadResponse(
        households=result.households,
        investors=result.investors,
        mandates=result.mandates,
        cases=result.cases,
    )


@router.post("/reset", response_model=SeedResetResponse)
async def reset_seed(
    actor: Annotated[UserContext, _seed_perm()],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Wipe every is_seed_data=True row across the cluster-5 universe.

    Caller must have ``seed:admin`` permission (CIO-only).
    """
    try:
        async with db.begin():
            result = await seed_loader.reset_demo_seed(db, actor=actor)
    except SeedNotAuthorisedError as exc:
        return problem_response(
            status=status.HTTP_403_FORBIDDEN,
            title="Seed admin is CIO-only",
            detail=str(exc),
        )
    except SeedFrameworkError as exc:
        return problem_response(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Seed reset failed",
            detail=str(exc),
        )

    return SeedResetResponse(
        cases_deleted=result.cases_deleted,
        mandates_deleted=result.mandates_deleted,
        mandate_versions_deleted=result.mandate_versions_deleted,
        investors_deleted=result.investors_deleted,
        households_deleted=result.households_deleted,
        snapshots_deleted=result.snapshots_deleted,
        stage_rows_deleted=result.stage_rows_deleted,
    )
