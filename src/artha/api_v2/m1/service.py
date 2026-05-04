"""M1 service layer — mandate lifecycle entrypoints (FR Entry 12.0 §3).

Cluster 2 chunk 2.1 / 2.4 surface (this commit):

- :func:`get_mandate_defaults` — read I0 enrichment for an investor and
  return suggested constraint values.
- :func:`create_mandate` — write Mandate + initial MandateVersion
  atomically, status=active, T1 events fire.
- :func:`get_active_mandate` — read by ``investor_id``.
- :func:`get_mandate_by_id` — read by ``mandate_id``.
- :func:`list_versions` — read all versions for a mandate, ordered by
  ``version_number``.

Amendment-lifecycle entrypoints (chunk 2.3) live in this module too once
that chunk lands; cluster 2's commit boundaries keep them out of this
file for now so chunk 2.1 stays self-contained.

All persistence calls participate in the caller's transaction
(``async with db.begin():`` boundary set by the router); cross-table
writes (Mandate + MandateVersion + Mandate.active_version_id update) commit
or roll back atomically.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.investors.models import Investor
from artha.api_v2.m1 import i0_defaults, validation
from artha.api_v2.m1.event_names import (
    MANDATE_CREATED,
    MANDATE_VERSION_ACTIVATED,
    MANDATE_VERSION_CREATED,
)
from artha.api_v2.m1.models import Mandate, MandateVersion, MandateVersionStatus
from artha.api_v2.m1.schemas import (
    MandateCreateRequest,
    MandateCreateResponse,
    MandateDefaultsRead,
    MandateRead,
    MandateVersionRead,
    SoftWarningRead,
)
from artha.api_v2.observability.t1 import emit_event

CreatedVia = str  # form | conversational | api | pdf


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvestorNotVisibleError(Exception):
    """The investor doesn't exist, or isn't visible to the actor's scope.

    Cluster 2 maps this to HTTP 404 from the router; the message is
    intentionally generic so unauthorised actors can't probe for
    investor existence by ID.
    """


class MandateAlreadyExistsError(Exception):
    """Hit when an advisor tries to create a second mandate for an investor.

    Per FR 12.0 §7.1 the API returns 409 with a pointer to the existing
    mandate so the caller can pivot to ``amend`` instead.
    """

    def __init__(self, *, mandate_id: str, investor_id: str) -> None:
        super().__init__(
            f"Investor {investor_id} already has mandate {mandate_id}"
        )
        self.mandate_id = mandate_id
        self.investor_id = investor_id


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


async def get_mandate_defaults(
    db: AsyncSession, *, investor_id: str, actor: UserContext
) -> MandateDefaultsRead:
    """Return the I0-suggested defaults for the given investor."""
    investor = await _load_visible_investor(
        db, investor_id=investor_id, actor=actor
    )
    defaults = i0_defaults.compute_defaults(
        risk_appetite=investor.risk_appetite,
        liquidity_tier=investor.liquidity_tier,
    )
    return MandateDefaultsRead.from_defaults(
        defaults,
        risk_appetite=investor.risk_appetite,
        liquidity_tier=investor.liquidity_tier,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_mandate(
    db: AsyncSession,
    *,
    investor_id: str,
    payload: MandateCreateRequest,
    actor: UserContext,
    via: CreatedVia,
) -> MandateCreateResponse:
    """Create the initial mandate + version=1 (active) for an investor.

    Per FR 12.0 §3.1 the initial version goes straight from creation to
    ``active`` (no CIO approval); subsequent amendments take the full
    draft → pending_approval → active path (chunk 2.3).
    """
    investor = await _load_visible_investor(
        db, investor_id=investor_id, actor=actor
    )

    # 1. Reject if a mandate already exists for this investor. The
    #    `mandate_creation_blocked_existing` audit event is emitted by the
    #    router AFTER the create transaction rolls back (so the audit row
    #    is durable even though the create failed).
    existing = await _find_mandate_for_investor(db, investor_id=investor_id)
    if existing is not None:
        raise MandateAlreadyExistsError(
            mandate_id=existing.mandate_id, investor_id=investor_id
        )

    # 2. Validate hard rules (Pydantic handles per-field range; this catches
    #    cross-constraint).
    constraints = payload.model_dump()
    validation.validate_hard_rules(constraints)

    # 3. Generate soft warnings (informational — not blocking).
    soft_warnings = validation.generate_soft_warnings(
        constraints,
        risk_appetite=investor.risk_appetite,
        liquidity_tier=investor.liquidity_tier,
    )

    # 4. Mint mandate + version=1 in one transaction.
    now = datetime.now(timezone.utc)
    mandate_id = str(ULID())
    version_id = str(ULID())

    mandate = Mandate(
        mandate_id=mandate_id,
        investor_id=investor_id,
        active_version_id=None,  # set below after version is flushed
        created_at=now,
        created_by=actor.user_id,
        schema_version=1,
    )
    db.add(mandate)

    version = MandateVersion(
        version_id=version_id,
        mandate_id=mandate_id,
        version_number=1,
        status=MandateVersionStatus.ACTIVE.value,
        equity_min_pct=payload.equity_min_pct,
        equity_max_pct=payload.equity_max_pct,
        debt_min_pct=payload.debt_min_pct,
        debt_max_pct=payload.debt_max_pct,
        alternatives_min_pct=payload.alternatives_min_pct,
        alternatives_max_pct=payload.alternatives_max_pct,
        single_position_max_pct=payload.single_position_max_pct,
        liquidity_floor_pct=payload.liquidity_floor_pct,
        sector_max_pct=payload.sector_max_pct,
        prohibited_instruments=list(payload.prohibited_instruments),
        created_at=now,
        created_by=actor.user_id,
        created_via=via,
        parent_version_id=None,
        activated_at=now,
    )
    db.add(version)
    await db.flush()

    mandate.active_version_id = version_id
    await db.flush()

    # 5. T1 — three events for the create-and-activate flow.
    base_payload = {
        "mandate_id": mandate_id,
        "investor_id": investor_id,
        "version_id": version_id,
    }
    await emit_event(
        db,
        event_name=MANDATE_CREATED,
        payload={**base_payload, "created_via": via},
        firm_id=actor.firm_id,
    )
    await emit_event(
        db,
        event_name=MANDATE_VERSION_CREATED,
        payload={
            **base_payload,
            "version_number": 1,
            "status": MandateVersionStatus.ACTIVE.value,
            "created_via": via,
        },
        firm_id=actor.firm_id,
    )
    await emit_event(
        db,
        event_name=MANDATE_VERSION_ACTIVATED,
        payload={
            **base_payload,
            "version_number": 1,
            "activated_at": now.isoformat(),
        },
        firm_id=actor.firm_id,
    )

    return MandateCreateResponse(
        mandate=_mandate_read(mandate, version),
        warnings=[
            SoftWarningRead(field=w.field, code=w.code, message=w.message)
            for w in soft_warnings
        ],
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_active_mandate(
    db: AsyncSession, *, investor_id: str, actor: UserContext
) -> MandateRead | None:
    """Return the active mandate for an investor (or ``None`` if none exists)."""
    await _load_visible_investor(db, investor_id=investor_id, actor=actor)
    mandate = await _find_mandate_for_investor(db, investor_id=investor_id)
    if mandate is None:
        return None
    active_version = (
        await _load_version(db, version_id=mandate.active_version_id)
        if mandate.active_version_id
        else None
    )
    return _mandate_read(mandate, active_version)


async def get_mandate_by_id(
    db: AsyncSession, *, mandate_id: str, actor: UserContext
) -> MandateRead | None:
    """Return the mandate by its id (scoped via the investor's visibility)."""
    result = await db.execute(
        select(Mandate).where(Mandate.mandate_id == mandate_id)
    )
    mandate = result.scalar_one_or_none()
    if mandate is None:
        return None
    # Re-validate visibility via the investor scope (advisor: own_book; CIO+:
    # firm_scope).
    try:
        await _load_visible_investor(
            db, investor_id=mandate.investor_id, actor=actor
        )
    except InvestorNotVisibleError:
        return None
    active_version = (
        await _load_version(db, version_id=mandate.active_version_id)
        if mandate.active_version_id
        else None
    )
    return _mandate_read(mandate, active_version)


async def list_versions(
    db: AsyncSession, *, investor_id: str, actor: UserContext
) -> list[MandateVersionRead]:
    """Return all versions of an investor's mandate, oldest first."""
    await _load_visible_investor(db, investor_id=investor_id, actor=actor)
    mandate = await _find_mandate_for_investor(db, investor_id=investor_id)
    if mandate is None:
        return []
    result = await db.execute(
        select(MandateVersion)
        .where(MandateVersion.mandate_id == mandate.mandate_id)
        .order_by(MandateVersion.version_number)
    )
    rows = list(result.scalars())
    return [_version_read(v) for v in rows]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_visible_investor(
    db: AsyncSession, *, investor_id: str, actor: UserContext
) -> Investor:
    """Return the investor row, scoped to the actor's visibility.

    Advisor → own_book (advisor_id == actor.user_id). CIO/compliance/audit →
    firm-wide (no advisor filter). Raises :class:`InvestorNotVisibleError`
    when the row doesn't exist or the actor can't see it.
    """
    stmt = select(Investor).where(Investor.investor_id == investor_id)
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Investor.advisor_id == actor.user_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise InvestorNotVisibleError(
            f"Investor {investor_id!r} not found or not visible to actor"
        )
    return row


async def _find_mandate_for_investor(
    db: AsyncSession, *, investor_id: str
) -> Mandate | None:
    result = await db.execute(
        select(Mandate).where(Mandate.investor_id == investor_id)
    )
    return result.scalar_one_or_none()


async def _load_version(
    db: AsyncSession, *, version_id: str
) -> MandateVersion | None:
    result = await db.execute(
        select(MandateVersion).where(MandateVersion.version_id == version_id)
    )
    return result.scalar_one_or_none()


def _mandate_read(
    mandate: Mandate, active_version: MandateVersion | None
) -> MandateRead:
    return MandateRead(
        mandate_id=mandate.mandate_id,
        investor_id=mandate.investor_id,
        active_version_id=mandate.active_version_id,
        active_version=(
            _version_read(active_version) if active_version is not None else None
        ),
        created_at=mandate.created_at,
        created_by=mandate.created_by,
        schema_version=mandate.schema_version,
    )


def _version_read(row: MandateVersion) -> MandateVersionRead:
    return MandateVersionRead(
        version_id=row.version_id,
        mandate_id=row.mandate_id,
        version_number=row.version_number,
        status=row.status,  # type: ignore[arg-type]
        equity_min_pct=row.equity_min_pct,
        equity_max_pct=row.equity_max_pct,
        debt_min_pct=row.debt_min_pct,
        debt_max_pct=row.debt_max_pct,
        alternatives_min_pct=row.alternatives_min_pct,
        alternatives_max_pct=row.alternatives_max_pct,
        single_position_max_pct=row.single_position_max_pct,
        liquidity_floor_pct=row.liquidity_floor_pct,
        sector_max_pct=row.sector_max_pct,
        prohibited_instruments=list(row.prohibited_instruments or []),
        created_at=row.created_at,
        created_by=row.created_by,
        created_via=row.created_via,  # type: ignore[arg-type]
        parent_version_id=row.parent_version_id,
        proposed_at=row.proposed_at,
        proposed_by=row.proposed_by,
        approved_at=row.approved_at,
        approved_by=row.approved_by,
        rejected_at=row.rejected_at,
        rejected_by=row.rejected_by,
        rejection_reason=row.rejection_reason,
        approval_comments=row.approval_comments,
        changes_requested_at=row.changes_requested_at,
        changes_requested_by=row.changes_requested_by,
        changes_requested_comments=row.changes_requested_comments,
        activated_at=row.activated_at,
        archived_at=row.archived_at,
    )
