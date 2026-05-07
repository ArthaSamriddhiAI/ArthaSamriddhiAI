"""Case opener — orchestrator that owns the case-creation pipeline.

The single source of truth for "spin up a new case" across the three
intake channels (C0 conversational, REST POST, future N0 alert).

Per FR Entry 20.1 §5.2, opening a case is a five-step pipeline:

1. Validate the investor exists + is in the actor's scope.
2. Run the M0 router to compute ``applicable_evidence_agents``.
3. Insert the Case row in ``opening`` status.
4. Pin a Snapshot bundle (cluster 3 SnapshotAssembler) — immutable
   thereafter.
5. Transition opening → gathering_evidence so chunk 5.4's stub layer
   can begin filling stage rows.

Failures at step 4 transition the case to ``failed`` with
``closed_reason='failed'`` and re-raise as :class:`CaseOpeningError` so
the caller surfaces a 5xx (REST) or system message (C0).

The opener is *aware* of M0 boss but doesn't import it as a singleton —
the boss is injected via :class:`OpenCaseDeps` so chunk 5.4's
integration tests can swap in a deterministic stub-boss for orchestrator-
only assertions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.cases import repository, snapshot_pinner
from artha.api_v2.cases.models import Case
from artha.api_v2.cases.snapshot_pinner import SnapshotPinningError
from artha.api_v2.cases.state_machine import (
    CaseClosedReason,
    CaseIntent,
    CaseMode,
    CaseStatus,
    DominantLens,
)
from artha.api_v2.investors.models import Investor

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CaseOpeningError(RuntimeError):
    """Base error for case-opening failures.

    Wraps lower-level errors (snapshot pin failure, mandate-version
    missing) so callers can branch on a single exception type.
    """


class InvestorNotFoundError(CaseOpeningError):
    """The investor_id did not resolve, or it's outside the actor's scope."""


class InvestorScopeError(CaseOpeningError):
    """Actor (advisor) tried to open a case for an investor outside own_book."""


class InvalidCaseModeError(CaseOpeningError):
    """An invalid combination of mode + intent was supplied."""


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenCaseRequest:
    """Normalised input shape consumed by :func:`open_case`.

    Built by the REST router from ``CaseCreateRequest``, by C0 from the
    confirmed conversation slot bag, or by the cluster 5.6 seed loader
    from a fixture row.
    """

    investor_id: str
    case_mode: CaseMode | str
    case_intent: CaseIntent | str | None = None
    dominant_lens: DominantLens | str | None = None
    proposed_action: str | None = None
    proposed_action_amount_inr: Decimal | None = None
    proposed_action_products: tuple[str, ...] = ()
    materiality_manual_flag: bool = False
    supersedes_case_id: str | None = None
    manual_override_evidence_agents: tuple[str, ...] | None = None
    is_seed_data: bool = False
    seed_archetype_id: str | None = None
    #: ``api`` (default REST), ``c0_conversational``, ``seed_loader``,
    #: ``ui_form``, ``n0_alert``, ``m0_scheduled`` per :class:`CaseCreatedVia`.
    #: C0 service / seed loader override before calling the opener.
    created_via: str = "api"
    #: Test-only escape hatch: skip the chunk 5.4 pipeline run and leave
    #: the case in ``gathering_evidence``. Production callers always run
    #: the pipeline; chunk 5.3 unit tests (orchestrator-only assertions)
    #: opt out via this flag.
    skip_pipeline: bool = False
    #: Optional explicit case_id. Production callers leave this ``None``
    #: and let the repository generate a ULID. The cluster-6 seed loader
    #: passes the fixture's stable case_id (e.g. ``case_arch01_a``) so
    #: the dispatcher's case_id-keyed seed-payload lookup finds the
    #: right curated content. Must be unique; collides at INSERT time.
    case_id_override: str | None = None


@dataclass(frozen=True)
class OpenCaseResult:
    """Output of :func:`open_case`. ``case`` is always non-null on success."""

    case: Case
    snapshot_bundle_id: str
    applicable_evidence_agents: tuple[str, ...]


# ---------------------------------------------------------------------------
# Boss protocol — the orchestrator only needs route_evidence_agents
# ---------------------------------------------------------------------------


class _RouterDecisionLike(Protocol):
    applicable_evidence_agents: tuple[str, ...]
    reason: str


class BossProto(Protocol):
    """Minimal subset of :class:`artha.api_v2.m0.boss.M0Boss` that the
    opener depends on. Defined as a Protocol so tests can inject stubs
    without importing the full boss.
    """

    def route_evidence_agents(self, case) -> _RouterDecisionLike:  # noqa: ANN001
        ...


@dataclass(frozen=True)
class OpenCaseDeps:
    """Bag of dependencies for the opener.

    Production usage hands :data:`artha.api_v2.m0.boss.boss` here. Tests
    pass a stub.
    """

    boss: BossProto
    extras: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_investor(
    db: AsyncSession,
    *,
    investor_id: str,
    actor: UserContext,
) -> Investor:
    """Lookup the investor + apply the advisor own-book scope filter.

    CIO / compliance / audit see firm-wide. Advisors only see investors
    they manage. ``InvestorScopeError`` is raised separately from
    ``InvestorNotFoundError`` so the REST router can map them to 403 vs
    404 respectively.
    """
    from sqlalchemy import select

    stmt = select(Investor).where(Investor.investor_id == investor_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise InvestorNotFoundError(
            f"Investor {investor_id!r} not found.",
        )
    if actor.role is Role.ADVISOR and row.advisor_id != actor.user_id:
        raise InvestorScopeError(
            f"Investor {investor_id!r} is outside advisor "
            f"{actor.user_id!r}'s own book.",
        )
    return row


def _coerce_mode(mode: CaseMode | str) -> CaseMode:
    return CaseMode(mode) if isinstance(mode, str) else mode


def _coerce_intent(intent: CaseIntent | str | None) -> CaseIntent | None:
    if intent is None:
        return None
    return CaseIntent(intent) if isinstance(intent, str) else intent


def _coerce_lens(
    lens: DominantLens | str | None,
) -> DominantLens | None:
    if lens is None:
        return None
    return DominantLens(lens) if isinstance(lens, str) else lens


def _validate_mode_intent_pairing(
    mode: CaseMode,
    intent: CaseIntent | None,
) -> None:
    """Enforce FR 20.1 §1.2 mode↔intent legality.

    - ``portfolio_health`` is only valid in diagnostic mode.
    - ``meeting_prep`` is only valid in briefing mode.
    - Other intents are case-mode-only (proposed_action / scenario).
    """
    if intent is None:
        return
    diagnostic_only = {CaseIntent.PORTFOLIO_HEALTH}
    briefing_only = {CaseIntent.MEETING_PREP}
    case_mode_intents = {
        CaseIntent.REBALANCE_PROPOSAL,
        CaseIntent.NEW_INVESTMENT,
        CaseIntent.EXIT_POSITION,
        CaseIntent.PRODUCT_EVALUATION,
        CaseIntent.ASSET_ALLOCATION_CHANGE,
        CaseIntent.TAX_LOSS_HARVESTING,
        CaseIntent.LIQUIDITY_MOBILISATION,
        CaseIntent.MANDATE_REVIEW_RESPONSE,
        CaseIntent.OTHER,
    }
    if intent in diagnostic_only and mode is not CaseMode.DIAGNOSTIC:
        raise InvalidCaseModeError(
            f"intent={intent.value} requires case_mode=diagnostic; got {mode.value}",
        )
    if intent in briefing_only and mode is not CaseMode.BRIEFING:
        raise InvalidCaseModeError(
            f"intent={intent.value} requires case_mode=briefing; got {mode.value}",
        )
    if intent in case_mode_intents and mode not in {
        CaseMode.PROPOSED_ACTION,
        CaseMode.SCENARIO,
    }:
        raise InvalidCaseModeError(
            f"intent={intent.value} requires case_mode in "
            f"{{proposed_action, scenario}}; got {mode.value}",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def open_case(
    db: AsyncSession,
    request: OpenCaseRequest,
    *,
    actor: UserContext,
    deps: OpenCaseDeps,
) -> OpenCaseResult:
    """Run the five-step opening pipeline (FR 20.1 §5.2).

    Caller is responsible for the transaction boundary (the FastAPI
    endpoint wraps the call in ``async with db.begin():``). On any
    exception after step 3, the case row already exists in ``opening``;
    we transition it to ``failed`` so the audit trail captures the
    attempt before re-raising.
    """
    mode = _coerce_mode(request.case_mode)
    intent = _coerce_intent(request.case_intent)
    lens = _coerce_lens(request.dominant_lens)
    _validate_mode_intent_pairing(mode, intent)

    # Step 1 — investor lookup + scope check.
    investor = await _resolve_investor(
        db,
        investor_id=request.investor_id,
        actor=actor,
    )

    # Step 2 — M0 router decision.
    from artha.api_v2.m0.boss import CaseRoutingInput

    routing_input = CaseRoutingInput(
        case_mode=mode,
        case_intent=intent,
        dominant_lens=lens,
        manual_override=request.manual_override_evidence_agents,
    )
    decision = deps.boss.route_evidence_agents(routing_input)
    applicable = tuple(decision.applicable_evidence_agents)

    # Step 3 — insert Case row in opening status.
    case = await repository.create_case(
        db,
        investor_id=investor.investor_id,
        household_id=investor.household_id,
        opened_by=actor.user_id,
        assigned_to=investor.advisor_id or actor.user_id,
        case_mode=mode.value,
        case_intent=intent.value if intent else None,
        dominant_lens=lens.value if lens else None,
        proposed_action=request.proposed_action,
        proposed_action_amount_inr=request.proposed_action_amount_inr,
        proposed_action_products=list(request.proposed_action_products),
        materiality_manual_flag=request.materiality_manual_flag,
        case_id=request.case_id_override,
        created_via=request.created_via,
        applicable_evidence_agents=list(applicable),
        is_seed_data=request.is_seed_data,
        seed_archetype_id=request.seed_archetype_id,
        supersedes_case_id=request.supersedes_case_id,
        firm_id=actor.firm_id,
    )

    # Step 4 — pin snapshot. On failure, transition to failed + re-raise.
    try:
        pin = await snapshot_pinner.pin_snapshot_for_case(
            db,
            case=case,
            actor_user_id=actor.user_id,
            firm_id=actor.firm_id,
        )
    except SnapshotPinningError as exc:
        await repository.transition_status(
            db,
            case=case,
            to_status=CaseStatus.FAILED,
            closed_reason=CaseClosedReason.FAILED,
            firm_id=actor.firm_id,
        )
        raise CaseOpeningError(
            f"Snapshot pinning failed for case {case.case_id!r}: {exc}",
        ) from exc

    # Step 5 — transition to gathering_evidence.
    await repository.transition_status(
        db,
        case=case,
        to_status=CaseStatus.GATHERING_EVIDENCE,
        firm_id=actor.firm_id,
    )

    # Step 6 — run the case through its mode-specific pipeline (chunk 5.4).
    # Stub layer is sub-millisecond per stage so we run inline. Cluster 7
    # swaps in real LLM calls and this hop moves to a background worker.
    if not request.skip_pipeline:
        try:
            from artha.api_v2.cases import pipeline as case_pipeline

            await case_pipeline.run_pipeline(
                db,
                case=case,
                firm_id=actor.firm_id,
            )
        except case_pipeline.PipelineError as exc:
            try:
                await repository.transition_status(
                    db,
                    case=case,
                    to_status=CaseStatus.FAILED,
                    closed_reason=CaseClosedReason.FAILED,
                    firm_id=actor.firm_id,
                )
            except Exception:  # noqa: BLE001 — best-effort failure recording
                pass
            raise CaseOpeningError(
                f"Pipeline failed for case {case.case_id!r}: {exc}",
            ) from exc

    return OpenCaseResult(
        case=case,
        snapshot_bundle_id=pin.snapshot_bundle_id,
        applicable_evidence_agents=applicable,
    )


__all__ = [
    "BossProto",
    "CaseOpeningError",
    "InvalidCaseModeError",
    "InvestorNotFoundError",
    "InvestorScopeError",
    "OpenCaseDeps",
    "OpenCaseRequest",
    "OpenCaseResult",
    "open_case",
]
