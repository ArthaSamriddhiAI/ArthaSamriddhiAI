"""Case status state machine (FR Entry 20.1 §1.5).

Pure-Python validator. Given a current status and a desired next status,
``validate_transition`` returns the new status (canonicalised) or raises
:class:`InvalidStateTransitionError`.

The machine is enforced at the application layer per FR 20.1 §4.2:
"Case status transitions follow §1.5 table; rejected → RFC 7807."
Database-level constraint would be too restrictive; transition logic
includes mode-aware rules that don't compile cleanly into CHECK
constraints.

Mode-specific pipeline shapes (FR 20.1 §1.4):

- ``proposed_action`` / ``scenario`` (full pipeline): opening →
  gathering_evidence → synthesizing → [awaiting_committee if material]
  → awaiting_governance → awaiting_challenge → awaiting_decision →
  decided.
- ``diagnostic``: opening → gathering_evidence → synthesizing →
  awaiting_governance → decided. (Skips committee + challenge +
  explicit decision form.)
- ``briefing``: opening → gathering_evidence → synthesizing → decided.
  (Skips governance entirely.)

Universal escapes (FR 20.1 §3.5): any state can transition to
``failed`` (unrecoverable error) or ``archived`` (explicit archive).
``decided`` / ``archived`` / ``failed`` are terminal — no outbound
edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CaseStatus(str, Enum):
    """The 10-value status enum (FR 20.1 §1.5)."""

    OPENING = "opening"
    GATHERING_EVIDENCE = "gathering_evidence"
    SYNTHESIZING = "synthesizing"
    AWAITING_COMMITTEE = "awaiting_committee"
    AWAITING_GOVERNANCE = "awaiting_governance"
    AWAITING_CHALLENGE = "awaiting_challenge"
    AWAITING_DECISION = "awaiting_decision"
    DECIDED = "decided"
    ARCHIVED = "archived"
    FAILED = "failed"


class CaseMode(str, Enum):
    """The 4 case modes (FR 20.1 §1.4)."""

    PROPOSED_ACTION = "proposed_action"
    SCENARIO = "scenario"
    DIAGNOSTIC = "diagnostic"
    BRIEFING = "briefing"


# ---------------------------------------------------------------------------
# Transition table — FR 20.1 §1.5
# ---------------------------------------------------------------------------

#: Allowed transitions per source state. ``failed`` and ``archived`` are
#: included as universal escapes; mode-specific transitions are checked
#: in :func:`validate_transition` because they depend on case mode.
_ALLOWED_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPENING: frozenset({
        CaseStatus.GATHERING_EVIDENCE,
        CaseStatus.FAILED,
        CaseStatus.ARCHIVED,
    }),
    CaseStatus.GATHERING_EVIDENCE: frozenset({
        CaseStatus.SYNTHESIZING,
        CaseStatus.FAILED,
        CaseStatus.ARCHIVED,
    }),
    CaseStatus.SYNTHESIZING: frozenset({
        # Material proposed_action / scenario → awaiting_committee
        CaseStatus.AWAITING_COMMITTEE,
        # Non-material proposed_action / scenario, or diagnostic →
        # awaiting_governance
        CaseStatus.AWAITING_GOVERNANCE,
        # briefing mode skips governance + decision; goes straight to
        # decided
        CaseStatus.DECIDED,
        CaseStatus.FAILED,
        CaseStatus.ARCHIVED,
    }),
    CaseStatus.AWAITING_COMMITTEE: frozenset({
        CaseStatus.AWAITING_GOVERNANCE,
        CaseStatus.FAILED,
        CaseStatus.ARCHIVED,
    }),
    CaseStatus.AWAITING_GOVERNANCE: frozenset({
        # proposed_action / scenario → awaiting_challenge
        CaseStatus.AWAITING_CHALLENGE,
        # diagnostic skips challenge + decision; goes straight to decided
        CaseStatus.DECIDED,
        CaseStatus.FAILED,
        CaseStatus.ARCHIVED,
    }),
    CaseStatus.AWAITING_CHALLENGE: frozenset({
        CaseStatus.AWAITING_DECISION,
        CaseStatus.FAILED,
        CaseStatus.ARCHIVED,
    }),
    CaseStatus.AWAITING_DECISION: frozenset({
        CaseStatus.DECIDED,
        CaseStatus.ARCHIVED,
        # Universal escape — pre-decision failures (e.g. snapshot bundle
        # corruption discovered during decision review) need a path out.
        CaseStatus.FAILED,
    }),
    # Terminal states — no outbound transitions
    CaseStatus.DECIDED: frozenset(),
    CaseStatus.ARCHIVED: frozenset(),
    CaseStatus.FAILED: frozenset(),
}


# ---------------------------------------------------------------------------
# Mode-specific guards
# ---------------------------------------------------------------------------

#: For the synthesizing → decided transition to be valid, the case mode
#: must be ``briefing`` (per FR 20.1 §1.4 — briefing skips
#: governance + decision form).
_SYNTHESIZING_TO_DECIDED_MODES: frozenset[CaseMode] = frozenset({
    CaseMode.BRIEFING,
})

#: For awaiting_governance → decided, mode must be ``diagnostic``.
_GOVERNANCE_TO_DECIDED_MODES: frozenset[CaseMode] = frozenset({
    CaseMode.DIAGNOSTIC,
})

#: For synthesizing → awaiting_committee, mode must be a "case mode"
#: (proposed_action or scenario). Diagnostic + briefing never reach the
#: committee — materiality gate is mode-excluded for them.
_AWAITING_COMMITTEE_MODES: frozenset[CaseMode] = frozenset({
    CaseMode.PROPOSED_ACTION,
    CaseMode.SCENARIO,
})

#: For awaiting_governance → awaiting_challenge, same — only case modes.
_AWAITING_CHALLENGE_MODES: frozenset[CaseMode] = frozenset({
    CaseMode.PROPOSED_ACTION,
    CaseMode.SCENARIO,
})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass
class InvalidStateTransitionError(Exception):
    """Raised when ``validate_transition`` rejects a status change.

    Carries the from + to state strings + an optional reason, suitable
    for embedding in an RFC 7807 problem document with
    ``type=case_invalid_state_transition`` (FR 20.1 §1.5).

    Non-frozen because Python's exception machinery sets
    ``__traceback__`` on the instance.
    """

    from_state: str
    to_state: str
    case_mode: str | None
    reason: str

    def __str__(self) -> str:
        return self.reason


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_transition(
    *,
    from_state: CaseStatus | str,
    to_state: CaseStatus | str,
    case_mode: CaseMode | str | None = None,
) -> CaseStatus:
    """Validate a status transition and return the new status.

    ``case_mode`` is required for transitions where mode determines
    legality (synthesizing → decided is briefing-only,
    awaiting_governance → decided is diagnostic-only,
    synthesizing → awaiting_committee is case-modes-only,
    awaiting_governance → awaiting_challenge is case-modes-only).

    Raises :class:`InvalidStateTransitionError` on any failure.
    """
    src = CaseStatus(from_state) if isinstance(from_state, str) else from_state
    dst = CaseStatus(to_state) if isinstance(to_state, str) else to_state
    mode: CaseMode | None
    if case_mode is None:
        mode = None
    elif isinstance(case_mode, str):
        mode = CaseMode(case_mode)
    else:
        mode = case_mode

    if dst == src:
        raise InvalidStateTransitionError(
            from_state=src.value,
            to_state=dst.value,
            case_mode=mode.value if mode else None,
            reason="No-op transition: from == to.",
        )

    allowed = _ALLOWED_TRANSITIONS.get(src, frozenset())
    if dst not in allowed:
        raise InvalidStateTransitionError(
            from_state=src.value,
            to_state=dst.value,
            case_mode=mode.value if mode else None,
            reason=(
                f"Transition {src.value!r} → {dst.value!r} is not in the "
                f"FR 20.1 §1.5 transition table."
            ),
        )

    # Mode-aware guards.
    if src == CaseStatus.SYNTHESIZING and dst == CaseStatus.DECIDED:
        if mode not in _SYNTHESIZING_TO_DECIDED_MODES:
            raise InvalidStateTransitionError(
                from_state=src.value,
                to_state=dst.value,
                case_mode=mode.value if mode else None,
                reason=(
                    "synthesizing → decided is only valid for briefing "
                    "mode (FR 20.1 §1.4); other modes must transit "
                    "awaiting_governance."
                ),
            )
    if src == CaseStatus.AWAITING_GOVERNANCE and dst == CaseStatus.DECIDED:
        if mode not in _GOVERNANCE_TO_DECIDED_MODES:
            raise InvalidStateTransitionError(
                from_state=src.value,
                to_state=dst.value,
                case_mode=mode.value if mode else None,
                reason=(
                    "awaiting_governance → decided is only valid for "
                    "diagnostic mode (FR 20.1 §1.4); proposed_action / "
                    "scenario must transit awaiting_challenge first."
                ),
            )
    if src == CaseStatus.SYNTHESIZING and dst == CaseStatus.AWAITING_COMMITTEE:
        if mode not in _AWAITING_COMMITTEE_MODES:
            raise InvalidStateTransitionError(
                from_state=src.value,
                to_state=dst.value,
                case_mode=mode.value if mode else None,
                reason=(
                    "awaiting_committee is only valid for proposed_action "
                    "or scenario modes (FR 20.1 §6); diagnostic + "
                    "briefing are mode-excluded from materiality."
                ),
            )
    if src == CaseStatus.AWAITING_GOVERNANCE and dst == CaseStatus.AWAITING_CHALLENGE:
        if mode not in _AWAITING_CHALLENGE_MODES:
            raise InvalidStateTransitionError(
                from_state=src.value,
                to_state=dst.value,
                case_mode=mode.value if mode else None,
                reason=(
                    "awaiting_challenge is only valid for proposed_action "
                    "or scenario modes (FR 20.1 §1.4); diagnostic + "
                    "briefing skip the challenge step."
                ),
            )

    return dst


def is_terminal(state: CaseStatus | str) -> bool:
    """Return True for terminal states (decided / archived / failed)."""
    s = CaseStatus(state) if isinstance(state, str) else state
    return s in {CaseStatus.DECIDED, CaseStatus.ARCHIVED, CaseStatus.FAILED}


def expected_pipeline_for_mode(mode: CaseMode | str) -> tuple[CaseStatus, ...]:
    """Return the canonical happy-path status sequence for a mode.

    Used by tests and the case detail UI's pipeline-stages renderer to
    show "where we are" relative to the mode-specific shape. Materiality
    is excluded from the canonical sequence — for material cases the
    UI inserts ``awaiting_committee`` between synthesizing and
    awaiting_governance based on the case row's ``is_material`` flag.
    """
    m = CaseMode(mode) if isinstance(mode, str) else mode
    if m in {CaseMode.PROPOSED_ACTION, CaseMode.SCENARIO}:
        return (
            CaseStatus.OPENING,
            CaseStatus.GATHERING_EVIDENCE,
            CaseStatus.SYNTHESIZING,
            CaseStatus.AWAITING_GOVERNANCE,
            CaseStatus.AWAITING_CHALLENGE,
            CaseStatus.AWAITING_DECISION,
            CaseStatus.DECIDED,
        )
    if m == CaseMode.DIAGNOSTIC:
        return (
            CaseStatus.OPENING,
            CaseStatus.GATHERING_EVIDENCE,
            CaseStatus.SYNTHESIZING,
            CaseStatus.AWAITING_GOVERNANCE,
            CaseStatus.DECIDED,
        )
    # briefing
    return (
        CaseStatus.OPENING,
        CaseStatus.GATHERING_EVIDENCE,
        CaseStatus.SYNTHESIZING,
        CaseStatus.DECIDED,
    )


# ---------------------------------------------------------------------------
# Closed reasons (FR 20.1 §1.1)
# ---------------------------------------------------------------------------


class CaseClosedReason(str, Enum):
    DECIDED = "decided"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Other case-level enums
# ---------------------------------------------------------------------------


class CaseCreatedVia(str, Enum):
    C0_CONVERSATIONAL = "c0_conversational"
    UI_FORM = "ui_form"
    N0_ALERT = "n0_alert"
    M0_SCHEDULED = "m0_scheduled"
    API = "api"
    SEED_LOADER = "seed_loader"


class DominantLens(str, Enum):
    PORTFOLIO_SHIFT = "portfolio_shift"
    PROPOSAL_EVALUATION = "proposal_evaluation"


# ---------------------------------------------------------------------------
# Case intent enumeration (FR 20.1 §1.2)
# ---------------------------------------------------------------------------


class CaseIntent(str, Enum):
    """All allowed values for ``cases.case_intent``.

    For proposed_action / scenario modes:
    """

    REBALANCE_PROPOSAL = "rebalance_proposal"
    NEW_INVESTMENT = "new_investment"
    EXIT_POSITION = "exit_position"
    PRODUCT_EVALUATION = "product_evaluation"
    ASSET_ALLOCATION_CHANGE = "asset_allocation_change"
    TAX_LOSS_HARVESTING = "tax_loss_harvesting"
    LIQUIDITY_MOBILISATION = "liquidity_mobilisation"
    MANDATE_REVIEW_RESPONSE = "mandate_review_response"
    OTHER = "other"
    # diagnostic / briefing modes:
    PORTFOLIO_HEALTH = "portfolio_health"
    MEETING_PREP = "meeting_prep"


# ---------------------------------------------------------------------------
# Outcome enums on stage tables
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GovernanceGate(str, Enum):
    G1_MANDATE = "g1_mandate"
    G2_SEBI_REGULATORY = "g2_sebi_regulatory"
    G3_ACTION_FILTER = "g3_action_filter"


class GovernanceOutcome(str, Enum):
    APPROVED = "approved"
    BLOCKED = "blocked"
    ESCALATION_REQUIRED = "escalation_required"


class IC1Recommendation(str, Enum):
    PROCEED = "proceed"
    SUPPORT_WITH_CONDITIONS = "support_with_conditions"
    OPPOSE = "oppose"
    DEFER = "defer"


class DecisionVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    DEFERRED = "deferred"


class HealthOverall(str, Enum):
    HEALTHY = "healthy"
    ATTENTION_NEEDED = "attention_needed"
    URGENT = "urgent"


class ProducedVia(str, Enum):
    """Universal `produced_via` enum across stage tables.

    ``lookup_stub_placeholder`` — cluster 5 default for non-seeded cases.
    ``lookup_stub_seed``        — cluster 6 enrichment for seeded cases.
    ``real_agent``              — cluster 7+ when LLM agents replace stubs.

    Stage-specific aliases (real_s1 / real_ic1 / real_gate / real_a1 /
    real_briefing / real_health_report) are accepted at the application
    layer; the DB column is a single string. We list ``real_agent`` here
    as the canonical generic value; specialised enums per stage are
    enforced at validation time only.
    """

    LOOKUP_STUB_PLACEHOLDER = "lookup_stub_placeholder"
    LOOKUP_STUB_SEED = "lookup_stub_seed"
    REAL_AGENT = "real_agent"
    REAL_S1 = "real_s1"
    REAL_IC1 = "real_ic1"
    REAL_GATE = "real_gate"
    REAL_A1 = "real_a1"
    REAL_BRIEFING = "real_briefing"
    REAL_HEALTH_REPORT = "real_health_report"


Status = CaseStatus  # convenient alias

__all__ = [
    "CaseClosedReason",
    "CaseCreatedVia",
    "CaseIntent",
    "CaseMode",
    "CaseStatus",
    "DecisionVerdict",
    "DominantLens",
    "GovernanceGate",
    "GovernanceOutcome",
    "HealthOverall",
    "IC1Recommendation",
    "InvalidStateTransitionError",
    "ProducedVia",
    "RiskLevel",
    "Status",
    "expected_pipeline_for_mode",
    "is_terminal",
    "validate_transition",
]
