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
from artha.api_v2.m1 import diff as diff_lib
from artha.api_v2.m1 import i0_defaults, validation
from artha.api_v2.m1.event_names import (
    MANDATE_AMENDMENT_APPROVED,
    MANDATE_AMENDMENT_CHANGES_REQUESTED,
    MANDATE_AMENDMENT_PROPOSED,
    MANDATE_AMENDMENT_REJECTED,
    MANDATE_CREATED,
    MANDATE_VERSION_ACTIVATED,
    MANDATE_VERSION_ARCHIVED,
    MANDATE_VERSION_CREATED,
)
from artha.api_v2.m1.models import Mandate, MandateVersion, MandateVersionStatus
from artha.api_v2.m1.schemas import (
    AmendmentDiffResponse,
    AmendmentDraftUpdateRequest,
    ImpactAnalysisRead,
    MandateCreateRequest,
    MandateCreateResponse,
    MandateDefaultsRead,
    MandateRead,
    MandateVersionRead,
    NumericFieldChangeRead,
    PendingAmendmentSummary,
    PortfolioImplicationsRead,
    ProhibitedListChangeRead,
    SoftWarningRead,
    StructuralImpactRead,
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


class NoActiveMandateError(Exception):
    """Amendment proposal blocked because the investor has no active
    mandate (FR 12.2 §3.2)."""


class PendingAmendmentExistsError(Exception):
    """Amendment proposal blocked because a pending amendment already
    exists for the same mandate (FR 12.2 §3.2 + §7.1).

    Carries the existing draft/pending version's id so the caller can
    pivot to editing or reviewing it instead.
    """

    def __init__(self, *, version_id: str, mandate_id: str, status: str) -> None:
        super().__init__(
            f"Mandate {mandate_id} already has a {status} amendment "
            f"({version_id})"
        )
        self.version_id = version_id
        self.mandate_id = mandate_id
        self.status = status


class VersionNotFoundError(Exception):
    """Version doesn't exist or isn't visible to the actor."""


class VersionStateError(Exception):
    """The requested action is invalid for the version's current status.

    e.g., approving a draft, editing an active version, submitting a
    pending_approval that's already been submitted.
    """


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
# Amendment proposal (chunk 2.3 — FR Entry 12.2 §3)
# ---------------------------------------------------------------------------


async def propose_amendment(
    db: AsyncSession,
    *,
    investor_id: str,
    actor: UserContext,
    via: CreatedVia = "form",
) -> MandateVersionRead:
    """Create a fresh draft :class:`MandateVersion` for an investor.

    Per FR 12.2 §3.3: copies all constraint values from the active
    version into a new row with status=draft, parent_version_id pointing
    to the active version, version_number=active.version_number + 1.

    Pre-validation (FR 12.2 §3.2):
    - Active mandate must exist (else :class:`NoActiveMandateError`).
    - No pending or draft amendment may already exist (else
      :class:`PendingAmendmentExistsError`). Strict one-at-a-time rule.
    """
    await _load_visible_investor(db, investor_id=investor_id, actor=actor)
    mandate = await _find_mandate_for_investor(db, investor_id=investor_id)
    if mandate is None or mandate.active_version_id is None:
        raise NoActiveMandateError(
            f"Investor {investor_id} has no active mandate to amend"
        )

    active = await _load_version(db, version_id=mandate.active_version_id)
    if active is None:  # pragma: no cover — defensive; FK guarantees presence
        raise NoActiveMandateError(
            f"Active version for mandate {mandate.mandate_id} not found"
        )

    pending = await _find_pending_or_draft(db, mandate_id=mandate.mandate_id)
    if pending is not None:
        raise PendingAmendmentExistsError(
            version_id=pending.version_id,
            mandate_id=mandate.mandate_id,
            status=pending.status,
        )

    # Compute the next version_number as MAX(version_number) + 1 across ALL
    # versions for this mandate (active + archived + rejected), not just the
    # active one. Rejected versions retain their slot, so the simpler
    # active.version_number + 1 trips the unique (mandate_id, version_number)
    # constraint when an earlier amendment was rejected.
    next_version_number = await _next_version_number(
        db, mandate_id=mandate.mandate_id
    )

    now = datetime.now(timezone.utc)
    version_id = str(ULID())
    draft = MandateVersion(
        version_id=version_id,
        mandate_id=mandate.mandate_id,
        version_number=next_version_number,
        status=MandateVersionStatus.DRAFT.value,
        equity_min_pct=active.equity_min_pct,
        equity_max_pct=active.equity_max_pct,
        debt_min_pct=active.debt_min_pct,
        debt_max_pct=active.debt_max_pct,
        alternatives_min_pct=active.alternatives_min_pct,
        alternatives_max_pct=active.alternatives_max_pct,
        single_position_max_pct=active.single_position_max_pct,
        liquidity_floor_pct=active.liquidity_floor_pct,
        sector_max_pct=active.sector_max_pct,
        prohibited_instruments=list(active.prohibited_instruments or []),
        created_at=now,
        created_by=actor.user_id,
        created_via=via,
        parent_version_id=active.version_id,
    )
    db.add(draft)
    await db.flush()

    await emit_event(
        db,
        event_name=MANDATE_VERSION_CREATED,
        payload={
            "mandate_id": mandate.mandate_id,
            "investor_id": investor_id,
            "version_id": version_id,
            "version_number": draft.version_number,
            "status": MandateVersionStatus.DRAFT.value,
            "created_via": via,
            "parent_version_id": active.version_id,
        },
        firm_id=actor.firm_id,
    )
    return _version_read(draft)


async def update_draft(
    db: AsyncSession,
    *,
    version_id: str,
    payload: AmendmentDraftUpdateRequest,
    actor: UserContext,
) -> MandateVersionRead:
    """Update a draft amendment's constraint values.

    Validates hard rules at write time so the draft is never persisted in
    a known-invalid shape. Soft warnings are NOT emitted on every keystroke;
    they fire on submit (when the CIO will see them).
    """
    version, _mandate = await _load_visible_version(
        db, version_id=version_id, actor=actor
    )
    if version.status != MandateVersionStatus.DRAFT.value:
        raise VersionStateError(
            f"Cannot edit version {version_id}: status is {version.status!r} "
            "(draft required)"
        )

    constraints = payload.model_dump()
    validation.validate_hard_rules(constraints)

    # Apply the update. The draft retains its identity + lineage; only
    # the constraint columns mutate.
    version.equity_min_pct = payload.equity_min_pct
    version.equity_max_pct = payload.equity_max_pct
    version.debt_min_pct = payload.debt_min_pct
    version.debt_max_pct = payload.debt_max_pct
    version.alternatives_min_pct = payload.alternatives_min_pct
    version.alternatives_max_pct = payload.alternatives_max_pct
    version.single_position_max_pct = payload.single_position_max_pct
    version.liquidity_floor_pct = payload.liquidity_floor_pct
    version.sector_max_pct = payload.sector_max_pct
    version.prohibited_instruments = list(payload.prohibited_instruments)
    await db.flush()
    return _version_read(version)


async def submit_for_approval(
    db: AsyncSession, *, version_id: str, actor: UserContext
) -> MandateVersionRead:
    """Transition draft → pending_approval (FR 12.2 §3.5)."""
    version, mandate = await _load_visible_version(
        db, version_id=version_id, actor=actor
    )
    if version.status != MandateVersionStatus.DRAFT.value:
        raise VersionStateError(
            f"Cannot submit version {version_id}: status is "
            f"{version.status!r} (draft required)"
        )

    # Re-validate at submit time — the draft might have been edited by an
    # older client that bypassed the per-write validator.
    validation.validate_hard_rules({
        "equity_min_pct": version.equity_min_pct,
        "equity_max_pct": version.equity_max_pct,
        "debt_min_pct": version.debt_min_pct,
        "debt_max_pct": version.debt_max_pct,
        "alternatives_min_pct": version.alternatives_min_pct,
        "alternatives_max_pct": version.alternatives_max_pct,
        "single_position_max_pct": version.single_position_max_pct,
        "liquidity_floor_pct": version.liquidity_floor_pct,
        "sector_max_pct": version.sector_max_pct,
        "prohibited_instruments": list(version.prohibited_instruments or []),
    })

    now = datetime.now(timezone.utc)
    version.status = MandateVersionStatus.PENDING_APPROVAL.value
    version.proposed_at = now
    version.proposed_by = actor.user_id
    await db.flush()

    await emit_event(
        db,
        event_name=MANDATE_AMENDMENT_PROPOSED,
        payload={
            "mandate_id": mandate.mandate_id,
            "investor_id": mandate.investor_id,
            "version_id": version.version_id,
            "version_number": version.version_number,
            "proposed_by": actor.user_id,
            "proposed_at": now.isoformat(),
        },
        firm_id=actor.firm_id,
    )
    return _version_read(version)


# ---------------------------------------------------------------------------
# CIO review (chunk 2.3 — FR Entry 12.2 §4)
# ---------------------------------------------------------------------------


async def list_pending_amendments(
    db: AsyncSession, *, actor: UserContext
) -> list[PendingAmendmentSummary]:
    """Return the CIO's pending-amendment queue (FR 12.2 §4.1).

    Visible to anyone with ``mandates:read:firm_scope`` (CIO + compliance
    + audit). Cluster 2 enforces firm-wide read; the CIO is the sole
    actor that can resolve the rows but compliance/audit can monitor.
    """
    stmt = (
        select(MandateVersion, Mandate, Investor)
        .join(Mandate, Mandate.mandate_id == MandateVersion.mandate_id)
        .join(Investor, Investor.investor_id == Mandate.investor_id)
        .where(
            MandateVersion.status == MandateVersionStatus.PENDING_APPROVAL.value
        )
        .order_by(MandateVersion.proposed_at.desc())
    )
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Investor.advisor_id == actor.user_id)

    result = await db.execute(stmt)
    rows = list(result.all())

    out: list[PendingAmendmentSummary] = []
    for version, mandate, investor in rows:
        active = (
            await _load_version(db, version_id=mandate.active_version_id)
            if mandate.active_version_id
            else None
        )
        if active is None:  # pragma: no cover — defensive
            continue
        diff = diff_lib.compute_diff(
            active=_version_read(active),
            proposed=_version_read(version),
        )
        out.append(
            PendingAmendmentSummary(
                version_id=version.version_id,
                mandate_id=mandate.mandate_id,
                investor_id=investor.investor_id,
                investor_name=investor.name,
                investor_pan=investor.pan,
                advisor_id=investor.advisor_id,
                version_number=version.version_number,
                proposed_at=version.proposed_at,
                proposed_by=version.proposed_by,
                change_summary=diff_lib.summarise_diff(diff),
            )
        )
    return out


async def get_amendment_diff(
    db: AsyncSession, *, version_id: str, actor: UserContext
) -> AmendmentDiffResponse:
    """Build the side-by-side diff + impact-analysis envelope (FR 12.2 §4)."""
    version, mandate = await _load_visible_version(
        db, version_id=version_id, actor=actor
    )
    if mandate.active_version_id is None:
        raise VersionStateError(
            "Mandate has no active version; cannot compute diff"
        )
    active = await _load_version(db, version_id=mandate.active_version_id)
    if active is None:  # pragma: no cover — defensive
        raise VersionStateError("Active version not found")
    if active.version_id == version.version_id:
        # The proposed version IS the active version — diff against itself
        # would be empty. Cluster 2 returns the empty diff explicitly so the
        # CIO can read a (no-op) review surface for completed amendments.
        proposed = _version_read(version)
        active_read = _version_read(active)
    else:
        proposed = _version_read(version)
        active_read = _version_read(active)

    diff = diff_lib.compute_diff(active=active_read, proposed=proposed)
    impact = diff_lib.build_impact_analysis(
        diff=diff, proposed=proposed, active=active_read
    )

    return AmendmentDiffResponse(
        active=active_read,
        proposed=proposed,
        numeric_changes=[
            NumericFieldChangeRead(
                field=c.field,
                label=c.label,
                old_value=c.old_value,
                new_value=c.new_value,
            )
            for c in diff.numeric_changes
        ],
        prohibited_change=ProhibitedListChangeRead(
            added=list(diff.prohibited_change.added),
            removed=list(diff.prohibited_change.removed),
        ),
        summary=diff_lib.summarise_diff(diff),
        impact=ImpactAnalysisRead(
            structural=[
                StructuralImpactRead(label=s.label, explanation=s.explanation)
                for s in impact.structural
            ],
            portfolio_implications=PortfolioImplicationsRead(
                status=impact.portfolio_implications.status,  # type: ignore[arg-type]
                message=impact.portfolio_implications.message,
                rows=[],
            ),
            activation_summary=impact.activation_summary,
        ),
    )


async def approve_amendment(
    db: AsyncSession,
    *,
    version_id: str,
    actor: UserContext,
    comments: str | None,
) -> MandateVersionRead:
    """Atomically activate the proposed version + archive the previously-active.

    Per FR 12.2 §5.1:
    1. proposed.status: pending_approval → active
    2. mandate.active_version_id: → proposed.version_id
    3. previously_active.status: active → archived

    All three writes share the caller's ``async with db.begin():`` boundary
    so the system is never observable in a 0-active or 2-active state.
    """
    proposed, mandate = await _load_visible_version(
        db, version_id=version_id, actor=actor
    )
    if proposed.status != MandateVersionStatus.PENDING_APPROVAL.value:
        raise VersionStateError(
            f"Cannot approve version {version_id}: status is "
            f"{proposed.status!r} (pending_approval required)"
        )

    now = datetime.now(timezone.utc)
    previously_active_id = mandate.active_version_id
    previously_active = (
        await _load_version(db, version_id=previously_active_id)
        if previously_active_id
        else None
    )

    proposed.status = MandateVersionStatus.ACTIVE.value
    proposed.approved_at = now
    proposed.approved_by = actor.user_id
    proposed.approval_comments = comments
    proposed.activated_at = now

    mandate.active_version_id = proposed.version_id

    if previously_active is not None and previously_active.version_id != proposed.version_id:
        previously_active.status = MandateVersionStatus.ARCHIVED.value
        previously_active.archived_at = now

    await db.flush()

    base_payload = {
        "mandate_id": mandate.mandate_id,
        "investor_id": mandate.investor_id,
        "version_id": proposed.version_id,
        "version_number": proposed.version_number,
    }
    await emit_event(
        db,
        event_name=MANDATE_AMENDMENT_APPROVED,
        payload={
            **base_payload,
            "approved_by": actor.user_id,
            "approval_comments": comments,
        },
        firm_id=actor.firm_id,
    )
    await emit_event(
        db,
        event_name=MANDATE_VERSION_ACTIVATED,
        payload={**base_payload, "activated_at": now.isoformat()},
        firm_id=actor.firm_id,
    )
    if previously_active is not None and previously_active.version_id != proposed.version_id:
        await emit_event(
            db,
            event_name=MANDATE_VERSION_ARCHIVED,
            payload={
                "mandate_id": mandate.mandate_id,
                "investor_id": mandate.investor_id,
                "version_id": previously_active.version_id,
                "version_number": previously_active.version_number,
                "archived_at": now.isoformat(),
                "replaced_by_version_id": proposed.version_id,
            },
            firm_id=actor.firm_id,
        )
    return _version_read(proposed)


async def reject_amendment(
    db: AsyncSession,
    *,
    version_id: str,
    actor: UserContext,
    rejection_reason: str,
) -> MandateVersionRead:
    """Transition pending_approval → rejected (FR 12.2 §5.2).

    The previously-active version remains active.
    """
    version, mandate = await _load_visible_version(
        db, version_id=version_id, actor=actor
    )
    if version.status != MandateVersionStatus.PENDING_APPROVAL.value:
        raise VersionStateError(
            f"Cannot reject version {version_id}: status is "
            f"{version.status!r} (pending_approval required)"
        )

    now = datetime.now(timezone.utc)
    version.status = MandateVersionStatus.REJECTED.value
    version.rejected_at = now
    version.rejected_by = actor.user_id
    version.rejection_reason = rejection_reason
    await db.flush()

    await emit_event(
        db,
        event_name=MANDATE_AMENDMENT_REJECTED,
        payload={
            "mandate_id": mandate.mandate_id,
            "investor_id": mandate.investor_id,
            "version_id": version.version_id,
            "version_number": version.version_number,
            "rejected_by": actor.user_id,
            "rejection_reason": rejection_reason,
        },
        firm_id=actor.firm_id,
    )
    return _version_read(version)


async def request_changes(
    db: AsyncSession,
    *,
    version_id: str,
    actor: UserContext,
    comments: str,
) -> MandateVersionRead:
    """Transition pending_approval → draft with CIO comments (FR 12.2 §5.3).

    Per the FR: ``version_number`` does NOT change — the same draft is
    returned to the advisor with the CIO's comments. The advisor can edit
    and resubmit (which transitions back to pending_approval).
    """
    version, mandate = await _load_visible_version(
        db, version_id=version_id, actor=actor
    )
    if version.status != MandateVersionStatus.PENDING_APPROVAL.value:
        raise VersionStateError(
            f"Cannot request changes on version {version_id}: status is "
            f"{version.status!r} (pending_approval required)"
        )

    now = datetime.now(timezone.utc)
    version.status = MandateVersionStatus.DRAFT.value
    version.changes_requested_at = now
    version.changes_requested_by = actor.user_id
    version.changes_requested_comments = comments
    # Reset proposal-side fields so a fresh submit re-stamps them.
    version.proposed_at = None
    version.proposed_by = None
    await db.flush()

    await emit_event(
        db,
        event_name=MANDATE_AMENDMENT_CHANGES_REQUESTED,
        payload={
            "mandate_id": mandate.mandate_id,
            "investor_id": mandate.investor_id,
            "version_id": version.version_id,
            "version_number": version.version_number,
            "changes_requested_by": actor.user_id,
            "changes_requested_comments": comments,
        },
        firm_id=actor.firm_id,
    )
    return _version_read(version)


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


async def _load_visible_version(
    db: AsyncSession, *, version_id: str, actor: UserContext
) -> tuple[MandateVersion, Mandate]:
    """Load a :class:`MandateVersion` + its parent :class:`Mandate`,
    scoped to the actor's visibility.

    Advisor → must own the investor (advisor_id match). CIO/compliance/
    audit → firm-wide. Raises :class:`VersionNotFoundError` when the row
    doesn't exist or the actor can't see it.
    """
    stmt = (
        select(MandateVersion, Mandate, Investor)
        .join(Mandate, Mandate.mandate_id == MandateVersion.mandate_id)
        .join(Investor, Investor.investor_id == Mandate.investor_id)
        .where(MandateVersion.version_id == version_id)
    )
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Investor.advisor_id == actor.user_id)
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        raise VersionNotFoundError(
            f"Mandate version {version_id!r} not found or not visible to actor"
        )
    version, mandate, _investor = row
    return version, mandate


async def _next_version_number(
    db: AsyncSession, *, mandate_id: str
) -> int:
    """Return ``MAX(version_number) + 1`` for the mandate, or 1 if empty.

    Used by :func:`propose_amendment` so rejected versions don't stall the
    counter (the unique (mandate_id, version_number) constraint blocks
    reusing slots).
    """
    from sqlalchemy import func

    result = await db.execute(
        select(func.max(MandateVersion.version_number)).where(
            MandateVersion.mandate_id == mandate_id
        )
    )
    current_max = result.scalar_one_or_none()
    return (current_max or 0) + 1


async def _find_pending_or_draft(
    db: AsyncSession, *, mandate_id: str
) -> MandateVersion | None:
    """Return any draft / pending_approval version for the mandate, if any.

    Strict-one-at-a-time enforcement (FR 12.2 §3.2 + §7.1) gates amendment
    proposals on this returning ``None``.
    """
    result = await db.execute(
        select(MandateVersion).where(
            MandateVersion.mandate_id == mandate_id,
            MandateVersion.status.in_(
                [
                    MandateVersionStatus.DRAFT.value,
                    MandateVersionStatus.PENDING_APPROVAL.value,
                ]
            ),
        )
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
