"""Investor + household service layer.

Used by:
- The form-based POST /api/v2/investors endpoint (chunk 1.1).
- The conversational onboarding flow (chunk 1.2; reuses :func:`create_investor`).
- The API stub path (also via POST /api/v2/investors with `created_via='api'`).

Per FR 10.7 §7 (write patterns), all three onboarding paths converge on the
same service so the canonical schema is reachable through structured input
regardless of channel.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.i0.active_layer import enrich_investor
from artha.api_v2.investors.event_names import (
    HOUSEHOLD_CREATED,
    INVESTOR_CREATED,
    INVESTOR_ENRICHMENT_COMPLETED,
)
from artha.api_v2.investors.models import Household, Investor
from artha.api_v2.investors.schemas import (
    DuplicatePanWarningResponse,
    HouseholdRead,
    InvestorCreateRequest,
    InvestorRead,
)
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DuplicatePanError(Exception):
    """Raised when create_investor finds an existing investor with the same
    PAN and the request didn't set ``duplicate_pan_acknowledged=true``.
    Carries the existing investor's identity so the router can surface the
    warn-and-proceed dialog payload.
    """

    def __init__(self, warning: DuplicatePanWarningResponse) -> None:
        super().__init__(f"PAN {warning.pan!r} already exists")
        self.warning = warning


class HouseholdResolutionError(Exception):
    """Raised when neither ``household_id`` nor ``household_name`` was
    provided on the request, or when ``household_id`` references a
    household that doesn't exist."""


# ---------------------------------------------------------------------------
# Investor service
# ---------------------------------------------------------------------------


async def create_investor(
    db: AsyncSession,
    *,
    payload: InvestorCreateRequest,
    actor: UserContext,
    via: str,
) -> InvestorRead:
    """Create one investor + run I0 enrichment in the same transaction.

    Caller wraps in ``async with db.begin():`` so persistence + T1 emission
    + enrichment all roll back together if anything fails.

    Per FR 11.1 §6 (integration with creation flow): the investor row is
    written first, then the active layer is invoked, then enrichment fields
    are populated on the same row, and T1 emits ``investor_created`` plus
    ``investor_enrichment_completed``.
    """
    # 1. Duplicate-PAN check (warn-and-proceed per Cluster 1 Ideation Log §2.2).
    duplicate = await _find_existing_by_pan(db, payload.pan)
    if duplicate is not None and not payload.duplicate_pan_acknowledged:
        raise DuplicatePanError(
            warning=DuplicatePanWarningResponse(
                duplicate_of_investor_id=duplicate.investor_id,
                duplicate_of_name=duplicate.name,
                duplicate_of_created_at=duplicate.created_at,
                pan=payload.pan,
            )
        )

    # 2. Resolve household (existing id or fresh creation).
    household = await _resolve_household(db, payload, actor)

    # 3. Mint investor + run I0.
    now = datetime.now(timezone.utc)
    investor_id = str(ULID())
    advisor_id = payload.advisor_id or actor.user_id

    enrichment = enrich_investor(
        age=payload.age,
        risk_appetite=payload.risk_appetite,
        time_horizon=payload.time_horizon,
    )

    row = Investor(
        investor_id=investor_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        pan=payload.pan,
        age=payload.age,
        household_id=household.household_id,
        advisor_id=advisor_id,
        risk_appetite=payload.risk_appetite,
        time_horizon=payload.time_horizon,
        kyc_status="pending",
        life_stage=enrichment.life_stage,
        life_stage_confidence=enrichment.life_stage_confidence,
        liquidity_tier=enrichment.liquidity_tier,
        liquidity_tier_range=enrichment.liquidity_tier_range,
        enriched_at=now,
        enrichment_version=enrichment.enrichment_version,
        created_at=now,
        created_by=actor.user_id,
        created_via=via,
        duplicate_pan_acknowledged=payload.duplicate_pan_acknowledged,
        last_modified_at=now,
        last_modified_by=actor.user_id,
        schema_version=1,
    )
    db.add(row)
    await db.flush()

    # 4. T1 emissions — investor_created + investor_enrichment_completed.
    await emit_event(
        db,
        event_name=INVESTOR_CREATED,
        payload={
            "investor_id": investor_id,
            "advisor_id": advisor_id,
            "household_id": household.household_id,
            "created_via": via,
            "duplicate_pan_acknowledged": payload.duplicate_pan_acknowledged,
        },
        firm_id=actor.firm_id,
    )
    await emit_event(
        db,
        event_name=INVESTOR_ENRICHMENT_COMPLETED,
        payload={
            "investor_id": investor_id,
            "enrichment_version": enrichment.enrichment_version,
            "life_stage": enrichment.life_stage,
            "life_stage_confidence": enrichment.life_stage_confidence,
            "liquidity_tier": enrichment.liquidity_tier,
        },
        firm_id=actor.firm_id,
    )

    return _investor_read(row)


async def list_investors(
    db: AsyncSession, *, actor: UserContext
) -> list[InvestorRead]:
    """List investors visible to the actor.

    Per cluster 1 chunk 1.1 §scope_in + FR 17.2 §6:
    - Advisor: own book (advisor_id == actor.user_id)
    - CIO / Compliance / Audit: firm-wide (no advisor filter)
    """
    stmt = select(Investor).order_by(Investor.created_at.desc())
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Investor.advisor_id == actor.user_id)
    result = await db.execute(stmt)
    return [_investor_read(row) for row in result.scalars()]


async def get_investor(
    db: AsyncSession, *, investor_id: str, actor: UserContext
) -> InvestorRead | None:
    """Fetch one investor with the same scope rules as :func:`list_investors`."""
    stmt = select(Investor).where(Investor.investor_id == investor_id)
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Investor.advisor_id == actor.user_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return _investor_read(row) if row else None


# ---------------------------------------------------------------------------
# Household service
# ---------------------------------------------------------------------------


async def list_households(
    db: AsyncSession, *, actor: UserContext
) -> list[HouseholdRead]:
    """List households visible to the actor.

    Per cluster 1 chunk 1.1 §scope_in:
    - Advisor: households they created (the form's selector shows "your" households)
    - CIO / Compliance / Audit: firm-wide
    """
    stmt = select(Household).order_by(Household.created_at.desc())
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Household.created_by == actor.user_id)
    result = await db.execute(stmt)
    return [_household_read(row) for row in result.scalars()]


async def create_household(
    db: AsyncSession,
    *,
    name: str,
    actor: UserContext,
    emit_t1: bool = True,
) -> HouseholdRead:
    """Create a household, optionally emitting the T1 event.

    The inline-during-investor-creation path (via :func:`_resolve_household`)
    sets ``emit_t1=False`` because the wrapping investor T1 events already
    capture the household_id; the standalone POST /api/v2/households path
    sets ``emit_t1=True``.
    """
    row = Household(
        household_id=str(ULID()),
        name=name.strip().title(),
        created_by=actor.user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    if emit_t1:
        await emit_event(
            db,
            event_name=HOUSEHOLD_CREATED,
            payload={
                "household_id": row.household_id,
                "name": row.name,
                "created_by": actor.user_id,
            },
            firm_id=actor.firm_id,
        )
    return _household_read(row)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _find_existing_by_pan(
    db: AsyncSession, pan: str
) -> Investor | None:
    result = await db.execute(select(Investor).where(Investor.pan == pan))
    return result.scalar_one_or_none()


async def _resolve_household(
    db: AsyncSession, payload: InvestorCreateRequest, actor: UserContext
) -> Household:
    """Either look up an existing household_id or create a new one inline."""
    if payload.household_id:
        result = await db.execute(
            select(Household).where(Household.household_id == payload.household_id)
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise HouseholdResolutionError(
                f"household_id={payload.household_id!r} does not exist"
            )
        return existing

    if payload.household_name:
        # Inline household creation: emit the household_created T1 event
        # so the audit trail captures the household even when the wrapping
        # investor flow is the originator.
        row = Household(
            household_id=str(ULID()),
            name=payload.household_name,
            created_by=actor.user_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        await db.flush()
        await emit_event(
            db,
            event_name=HOUSEHOLD_CREATED,
            payload={
                "household_id": row.household_id,
                "name": row.name,
                "created_by": actor.user_id,
                "created_inline_for_investor": True,
            },
            firm_id=actor.firm_id,
        )
        return row

    raise HouseholdResolutionError(
        "Either household_id (existing) or household_name (new) is required"
    )


def _investor_read(row: Investor) -> InvestorRead:
    return InvestorRead(
        investor_id=row.investor_id,
        name=row.name,
        email=row.email,
        phone=row.phone,
        pan=row.pan,
        age=row.age,
        household_id=row.household_id,
        advisor_id=row.advisor_id,
        risk_appetite=row.risk_appetite,
        time_horizon=row.time_horizon,
        kyc_status=row.kyc_status,
        kyc_verified_at=row.kyc_verified_at,
        kyc_provider=row.kyc_provider,
        life_stage=row.life_stage,
        life_stage_confidence=row.life_stage_confidence,
        liquidity_tier=row.liquidity_tier,
        liquidity_tier_range=row.liquidity_tier_range,
        enriched_at=row.enriched_at,
        enrichment_version=row.enrichment_version,
        created_at=row.created_at,
        created_by=row.created_by,
        created_via=row.created_via,
        duplicate_pan_acknowledged=row.duplicate_pan_acknowledged,
        last_modified_at=row.last_modified_at,
        last_modified_by=row.last_modified_by,
        schema_version=row.schema_version,
    )


def _household_read(row: Household) -> HouseholdRead:
    return HouseholdRead(
        household_id=row.household_id,
        name=row.name,
        created_by=row.created_by,
        created_at=row.created_at,
    )
