"""C0 service layer — turn-level entrypoints (FR Entry 14.0 §2 + §3).

The service exposes four primary calls:

- :func:`start_conversation` — allocate a new conversation row.
- :func:`post_message` — handle one user message: detect intent (turn 1)
  or extract slots (later turns), advance the FSM, append the system
  reply, persist.
- :func:`confirm_action` — user confirmed the summary → run the
  investor-creation service inside the same transaction → emit T1.
- :func:`cancel_conversation` — abandon explicitly.

Plus listing + read + abandon-stale (background-job) helpers.

All persistence happens through :class:`AsyncSession` with the caller's
``async with db.begin():`` boundary, so a turn's writes (message + slot
update + T1 events) commit atomically (or roll back atomically if
anything fails).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.c0 import (
    case_opening_state_machine,
    investor_lookup,
    llm_client,
    mandate_state_machine,
    state_machine,
)
from artha.api_v2.c0.case_opening_state_machine import CaseOpeningState
from artha.api_v2.c0.event_names import (
    C0_CONVERSATION_ABANDONED,
    C0_CONVERSATION_COMPLETED,
    C0_CONVERSATION_STARTED,
    C0_INTENT_DETECTED,
    C0_LLM_FAILURE,
    C0_SLOT_EXTRACTED,
    C0_STATE_TRANSITIONED,
)
from artha.api_v2.c0.llm_client import LLMFallback
from artha.api_v2.c0.mandate_state_machine import MandateConversationState
from artha.api_v2.c0.models import Conversation, Message
from artha.api_v2.c0.schemas import (
    ConversationRead,
    ConversationSummary,
    MessageRead,
)
from artha.api_v2.c0.state_machine import ConversationState
from artha.api_v2.investors import service as investor_service
from artha.api_v2.investors.schemas import InvestorCreateRequest, InvestorRead
from artha.api_v2.llm.router_runtime import SmartLLMRouter
from artha.api_v2.m1 import service as m1_service
from artha.api_v2.m1.schemas import MandateCreateRequest
from artha.api_v2.m1.validation import MandateValidationError
from artha.api_v2.observability.t1 import emit_event

logger = logging.getLogger(__name__)


#: Inactivity threshold for the background abandonment scan (FR 14.0 §3.3).
ABANDONMENT_THRESHOLD = timedelta(hours=4)

#: User-visible degraded-mode notice when the LLM is unavailable
#: (FR 14.0 §5.1).
LLM_FALLBACK_NOTICE = (
    "Conversational understanding is temporarily unavailable; please respond "
    "with a single value to each question."
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConversationNotFoundError(Exception):
    """No conversation matches the id (or it isn't visible to the actor)."""


class ConversationStateError(Exception):
    """Operation invalid for the conversation's current state.

    e.g., posting another user message after STATE_COMPLETED, confirming
    while still in STATE_COLLECTING_BASICS, or cancelling a conversation
    that's already abandoned.
    """


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


async def start_conversation(
    db: AsyncSession, *, actor: UserContext
) -> Conversation:
    """Allocate a fresh conversation row in STATE_INTENT_PENDING."""
    now = datetime.now(timezone.utc)
    row = Conversation(
        conversation_id=str(ULID()),
        user_id=actor.user_id,
        firm_id=actor.firm_id,
        intent=None,
        state=state_machine.initial_state().value,
        collected_slots={},
        status="active",
        started_at=now,
        last_message_at=now,
        completed_at=None,
        investor_id=None,
    )
    db.add(row)
    await db.flush()

    await emit_event(
        db,
        event_name=C0_CONVERSATION_STARTED,
        payload={"conversation_id": row.conversation_id, "user_id": actor.user_id},
        firm_id=actor.firm_id,
    )
    return row


# ---------------------------------------------------------------------------
# Post message
# ---------------------------------------------------------------------------


async def post_message(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_message: str,
    actor: UserContext,
    router: SmartLLMRouter,
) -> Conversation:
    """Handle one user-typed turn end-to-end.

    The flow:

    1. Lookup + scope-check + persist the user message.
    2. If the conversation is in INTENT_PENDING, run intent detection;
       otherwise run slot extraction against the current state's expected
       fields.
    3. Apply extracted slots, advance the FSM, append the system message.
    4. Emit T1 events for each lifecycle step.
    """
    convo = await _load_for_actor(db, conversation_id=conversation_id, actor=actor)
    _ensure_writable(convo)

    now = datetime.now(timezone.utc)
    user_msg = Message(
        message_id=str(ULID()),
        conversation_id=convo.conversation_id,
        sender="user",
        content=user_message,
        metadata_json={},
        timestamp=now,
    )
    db.add(user_msg)

    # Dispatch by (intent, current_state). Cluster 1 ships only
    # investor_onboarding states; cluster 2 chunk 2.2 adds mandate_creation
    # states using the same persistence/conversation infrastructure.
    if convo.intent is None:
        await _handle_intent_turn(
            db, convo=convo, user_message=user_message, router=router
        )
    elif convo.intent == "mandate_creation":
        await _handle_mandate_turn(
            db, convo=convo, user_message=user_message, actor=actor, router=router
        )
    elif convo.intent == "case_opening":
        await _handle_case_opening_turn(
            db, convo=convo, user_message=user_message, actor=actor, router=router
        )
    else:
        # Cluster 1 investor_onboarding flow (unchanged from chunk 1.2).
        current_state = ConversationState(convo.state)
        if current_state is ConversationState.AWAITING_CONFIRMATION:
            await _handle_confirmation_text_turn(
                db, convo=convo, user_message=user_message
            )
        else:
            await _handle_slot_turn(
                db, convo=convo, user_message=user_message, router=router
            )

    convo.last_message_at = datetime.now(timezone.utc)
    await db.flush()
    return convo


async def _handle_intent_turn(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    router: SmartLLMRouter,
) -> None:
    """First turn: classify intent, optionally pre-fill slots."""
    result = await llm_client.detect_intent(
        db=db, router=router, user_message=user_message
    )

    if isinstance(result, LLMFallback):
        await _emit_llm_failure(db, convo=convo, fallback=result, stage="intent")
        # Without an intent we still optimistically assume onboarding (the
        # safer default for fallback mode — mandate_creation depends on an
        # existing investor that we can't disambiguate without LLM).
        convo.intent = "investor_onboarding"
        await _transition(
            db, convo=convo, to=ConversationState.COLLECTING_BASICS
        )
        await _append_system_message(
            db,
            convo=convo,
            content=(
                LLM_FALLBACK_NOTICE
                + "\n\n"
                + state_machine.system_prompt_for(
                    ConversationState.COLLECTING_BASICS, convo.collected_slots
                )
            ),
            metadata={"fallback_mode": True},
        )
        return

    # Successful intent detection.
    convo.intent = result.intent
    await emit_event(
        db,
        event_name=C0_INTENT_DETECTED,
        payload={
            "conversation_id": convo.conversation_id,
            "intent": result.intent,
            "llm_provider": result.llm_provider,
            "llm_latency_ms": result.llm_latency_ms,
            "skill_version": result.skill_version,
        },
        firm_id=convo.firm_id,
    )

    if result.intent == "investor_onboarding":
        await _handle_investor_onboarding_intent_extraction(
            db, convo=convo, result=result
        )
        return

    if result.intent == "mandate_creation":
        await _handle_mandate_intent_extraction(
            db, convo=convo, result=result
        )
        return

    if result.intent == "case_opening":
        await _handle_case_opening_intent_extraction(
            db, convo=convo, result=result
        )
        return

    # Other intents (alert_response, briefing_request, general_question)
    # return placeholder responses per FR 14.0 §2.1.
    await _transition(db, convo=convo, to=ConversationState.COMPLETED)
    convo.status = "completed"
    convo.completed_at = datetime.now(timezone.utc)
    await _append_system_message(
        db,
        convo=convo,
        content=(
            f"That intent ({result.intent.replace('_', ' ')}) isn't "
            "implemented yet. Cluster 2 supports new-client onboarding "
            "and mandate creation. Try 'onboard a new client called X' "
            "or 'set up the mandate for X'."
        ),
        metadata={"intent": result.intent, "placeholder": True},
    )


async def _handle_investor_onboarding_intent_extraction(
    db: AsyncSession,
    *,
    convo: Conversation,
    result: llm_client.IntentDetectionResult,
) -> None:
    """Carry-forward of cluster 1 chunk 1.2 behaviour (unchanged)."""
    if result.extracted_fields:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields=result.extracted_fields,
            confidence="medium",
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )
    next_state = state_machine.next_state_after(
        ConversationState.INTENT_PENDING, convo.collected_slots
    )
    await _transition(db, convo=convo, to=next_state)
    await _append_system_message(
        db,
        convo=convo,
        content=state_machine.system_prompt_for(next_state, convo.collected_slots),
        metadata={"expected_fields": list(state_machine.expected_fields_for(next_state))},
    )


# ---------------------------------------------------------------------------
# Mandate-creation intent (chunk 2.2 — FR Entry 14.0 Cluster 2 Revision)
# ---------------------------------------------------------------------------


async def _handle_mandate_intent_extraction(
    db: AsyncSession,
    *,
    convo: Conversation,
    result: llm_client.IntentDetectionResult,
) -> None:
    """Turn-1 handler when the LLM classifies as mandate_creation.

    Stamps any extracted ``investor_name`` / ``investor_pan`` references
    into the slot bag, transitions to the disambiguation state, and runs
    the structured lookup (no LLM fuzzy matching) to surface candidates.
    """
    fields_to_apply = {
        k: v
        for k, v in result.extracted_fields.items()
        if k in ("investor_name", "investor_pan")
    }
    if fields_to_apply:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields=fields_to_apply,
            confidence="medium",
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )

    await _transition_mandate(
        db, convo=convo, to=MandateConversationState.INVESTOR_DISAMBIGUATION
    )
    await _run_investor_disambiguation(db, convo=convo)


async def _handle_mandate_turn(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    actor: UserContext,
    router: SmartLLMRouter,
) -> None:
    """Subsequent-turn dispatcher for the mandate_creation intent."""
    state = MandateConversationState(convo.state)

    if state is MandateConversationState.AWAITING_CONFIRMATION:
        await _handle_mandate_confirmation_text(
            db, convo=convo, user_message=user_message, actor=actor
        )
        return

    if state is MandateConversationState.INVESTOR_DISAMBIGUATION:
        await _handle_mandate_disambiguation_turn(
            db, convo=convo, user_message=user_message, router=router
        )
        return

    # Slot-collection states (asset_allocation, concentration, liquidity,
    # sector, prohibited).
    await _handle_mandate_slot_turn(
        db, convo=convo, user_message=user_message, router=router
    )


async def _handle_mandate_disambiguation_turn(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    router: SmartLLMRouter,
) -> None:
    """Resolve which investor the advisor wants the mandate for.

    Either:
    - The advisor's reply names an investor (LLM extracts name/PAN), so
      we re-run the structured lookup; OR
    - The advisor's reply is a confirmation ("yes", "the first one") of
      a candidate already proposed in the previous turn.
    """
    state = MandateConversationState.INVESTOR_DISAMBIGUATION
    expected = list(mandate_state_machine.expected_fields_for(state))
    current_prompt = mandate_state_machine.system_prompt_for(
        state, convo.collected_slots
    )

    # Fast path: explicit "yes" / index selection on a candidate list.
    candidates = convo.collected_slots.get("_disambiguation_candidates") or []
    selection = _parse_candidate_selection(user_message, candidates)
    if selection is not None:
        await _lock_in_investor(db, convo=convo, candidate=selection)
        return

    # Otherwise: extract any name/PAN hint and retry the lookup.
    result = await llm_client.extract_slots(
        db=db,
        router=router,
        user_response=user_message,
        current_prompt=current_prompt,
        expected_fields=expected,
    )
    if isinstance(result, LLMFallback):
        await _emit_llm_failure(db, convo=convo, fallback=result, stage="slot")
        await _append_system_message(
            db,
            convo=convo,
            content=(
                LLM_FALLBACK_NOTICE
                + "\n\nReply with the investor's full name or PAN."
            ),
            metadata={"fallback_mode": True},
        )
        return

    if result.extracted_fields:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields={
                k: v
                for k, v in result.extracted_fields.items()
                if k in ("investor_name", "investor_pan")
            },
            confidence=result.extraction_confidence,
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )

    await _run_investor_disambiguation(db, convo=convo)


async def _run_investor_disambiguation(
    db: AsyncSession, *, convo: Conversation
) -> None:
    """Run the structured lookup + emit the next system message based on
    cardinality."""
    actor = UserContext(
        user_id=convo.user_id,
        firm_id=convo.firm_id,
        role=Role.ADVISOR,
        email="",
        name="",
        session_id="",
    )
    matches = await investor_lookup.find_matching_investors(
        db,
        name_query=convo.collected_slots.get("investor_name"),
        pan_query=convo.collected_slots.get("investor_pan"),
        actor=actor,
    )

    if len(matches) == 1:
        candidate = matches[0]
        # Stash candidates so a follow-up "yes" confirms; service moves
        # forward when the user confirms.
        await _stash_candidates(db, convo=convo, candidates=matches)
        await _append_system_message(
            db,
            convo=convo,
            content=(
                f"I found {candidate.name} (PAN {candidate.pan}). "
                "Is this the right investor? Reply 'yes' to proceed."
            ),
            metadata={
                "disambiguation_candidates": [
                    _candidate_dict(c) for c in matches
                ],
            },
        )
        return

    if len(matches) > 1:
        await _stash_candidates(db, convo=convo, candidates=matches)
        lines = ["I found multiple investors. Which one?"]
        for i, c in enumerate(matches, start=1):
            lines.append(
                f"  {i}. {c.name} · PAN {c.pan} · age {c.age}"
            )
        lines.append("")
        lines.append("Reply with the number or the name to select.")
        await _append_system_message(
            db,
            convo=convo,
            content="\n".join(lines),
            metadata={
                "disambiguation_candidates": [
                    _candidate_dict(c) for c in matches
                ],
            },
        )
        return

    # Zero matches.
    await _append_system_message(
        db,
        convo=convo,
        content=(
            "I couldn't find an investor matching that name or PAN. "
            "Can you provide the full name or PAN? If this client isn't "
            "in your book yet, I can help you onboard them first — say "
            "'onboard new client'."
        ),
        metadata={"disambiguation_candidates": []},
    )


async def _lock_in_investor(
    db: AsyncSession,
    *,
    convo: Conversation,
    candidate: investor_lookup.InvestorMatch,
) -> None:
    """Confirm an investor selection + advance to constraint collection."""
    new_slots = {**convo.collected_slots}
    new_slots["investor_id"] = candidate.investor_id
    new_slots["investor_name"] = candidate.name
    new_slots["investor_pan"] = candidate.pan
    new_slots.pop("_disambiguation_candidates", None)
    convo.collected_slots = new_slots

    # Block forward progress if the investor already has a mandate.
    existing = await m1_service.get_active_mandate(
        db,
        investor_id=candidate.investor_id,
        actor=UserContext(
            user_id=convo.user_id,
            firm_id=convo.firm_id,
            role=Role.ADVISOR,
            email="",
            name="",
            session_id="",
        ),
    )
    if existing is not None:
        await _transition_mandate(
            db, convo=convo, to=MandateConversationState.COMPLETED
        )
        convo.status = "completed"
        convo.completed_at = datetime.now(timezone.utc)
        await _append_system_message(
            db,
            convo=convo,
            content=(
                f"{candidate.name} already has an active mandate. To change "
                "constraints, propose an amendment from the investor's "
                "profile."
            ),
            metadata={
                "investor_id": candidate.investor_id,
                "existing_mandate_id": existing.mandate_id,
            },
        )
        return

    next_state = MandateConversationState.COLLECTING_ASSET_ALLOCATION
    await _transition_mandate(db, convo=convo, to=next_state)
    await _append_system_message(
        db,
        convo=convo,
        content=mandate_state_machine.system_prompt_for(
            next_state, convo.collected_slots
        ),
        metadata={
            "expected_fields": list(
                mandate_state_machine.expected_fields_for(next_state)
            ),
        },
    )


async def _handle_mandate_slot_turn(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    router: SmartLLMRouter,
) -> None:
    """Slot-collection turn for one of the five constraint families."""
    state = MandateConversationState(convo.state)
    current_prompt = mandate_state_machine.system_prompt_for(
        state, convo.collected_slots
    )
    expected = list(mandate_state_machine.expected_fields_for(state))

    result = await llm_client.extract_slots(
        db=db,
        router=router,
        user_response=user_message,
        current_prompt=current_prompt,
        expected_fields=expected,
    )

    if isinstance(result, LLMFallback):
        await _emit_llm_failure(db, convo=convo, fallback=result, stage="slot")
        await _append_system_message(
            db,
            convo=convo,
            content=LLM_FALLBACK_NOTICE + "\n\n" + current_prompt,
            metadata={"fallback_mode": True},
        )
        return

    extracted = dict(result.extracted_fields)

    # Skip-to-defaults affordance.
    if extracted.pop("use_defaults", False):
        defaults_struct = await _compute_mandate_defaults_for_slot_bag(
            db, convo=convo
        )
        skip = mandate_state_machine.apply_skip_to_defaults(
            current=state,
            defaults=defaults_struct,
            existing_slots=convo.collected_slots,
        )
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields=skip.slot_updates,
            confidence=result.extraction_confidence,
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )
        await _transition_mandate(db, convo=convo, to=skip.next_state)
        await _append_system_message(
            db,
            convo=convo,
            content=mandate_state_machine.system_prompt_for(
                skip.next_state, convo.collected_slots
            ),
            metadata={"used_defaults": True},
        )
        return

    # Normalise prohibited list responses.
    if state is MandateConversationState.COLLECTING_PROHIBITED:
        prohibited = extracted.get("prohibited_instruments")
        normalised = _normalise_prohibited(user_message, prohibited)
        extracted["prohibited_instruments"] = normalised
        extracted["prohibited_instruments_collected"] = True

    if extracted:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields=extracted,
            confidence=result.extraction_confidence,
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )

    next_state = mandate_state_machine.next_state_after(
        state, convo.collected_slots
    )
    if next_state is not state:
        await _transition_mandate(db, convo=convo, to=next_state)
    await _append_system_message(
        db,
        convo=convo,
        content=mandate_state_machine.system_prompt_for(
            next_state, convo.collected_slots
        ),
        metadata={
            "expected_fields": list(
                mandate_state_machine.expected_fields_for(next_state)
            ),
            "extraction_confidence": result.extraction_confidence,
        },
    )


async def _handle_mandate_confirmation_text(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    actor: UserContext,
) -> None:
    """Free-text yes/no/cancel handler in the mandate confirmation state."""
    norm = user_message.strip().lower()
    if norm in {"cancel", "no", "stop", "abort"}:
        await _abandon_inline(db, convo=convo, reason="user_cancelled")
        return
    if norm in {"yes", "confirm", "go ahead", "create it", "create"}:
        await _execute_mandate_creation(db, convo=convo, actor=actor)
        return
    # Otherwise re-render the summary.
    await _append_system_message(
        db,
        convo=convo,
        content=mandate_state_machine.system_prompt_for(
            MandateConversationState.AWAITING_CONFIRMATION, convo.collected_slots
        ),
        metadata={"hint": "type 'yes' to confirm or 'cancel' to abort"},
    )


async def _execute_mandate_creation(
    db: AsyncSession, *, convo: Conversation, actor: UserContext
) -> None:
    """Call the M1 mandate creation service with the conversation's slots."""
    await _transition_mandate(
        db, convo=convo, to=MandateConversationState.EXECUTING
    )

    payload = _slots_to_mandate_payload(convo.collected_slots)
    investor_id = convo.collected_slots["investor_id"]

    # Reuse the C0-acting actor (advisor role) the conversation owner has.
    creator = UserContext(
        user_id=convo.user_id,
        firm_id=convo.firm_id,
        role=Role.ADVISOR,
        email=actor.email,
        name=actor.name,
        session_id=actor.session_id,
    )

    try:
        response = await m1_service.create_mandate(
            db,
            investor_id=investor_id,
            payload=payload,
            actor=creator,
            via="conversational",
        )
    except m1_service.MandateAlreadyExistsError as exc:
        await _transition_mandate(
            db, convo=convo, to=MandateConversationState.COMPLETED
        )
        convo.status = "completed"
        convo.completed_at = datetime.now(timezone.utc)
        await _append_system_message(
            db,
            convo=convo,
            content=(
                "That investor already has an active mandate. To change "
                "constraints, propose an amendment from the investor's "
                "profile."
            ),
            metadata={"existing_mandate_id": exc.mandate_id, "error": "duplicate_mandate"},
        )
        return
    except MandateValidationError as exc:
        await _transition_mandate(
            db, convo=convo, to=MandateConversationState.COLLECTING_ASSET_ALLOCATION
        )
        await _append_system_message(
            db,
            convo=convo,
            content=(
                "The constraints didn't pass validation:\n  • "
                + "\n  • ".join(f["message"] for f in exc.failures)
                + "\n\nLet's revisit the asset allocation."
            ),
            metadata={"error": "validation", "failures": exc.failures},
        )
        return

    mandate = response.mandate
    convo.investor_id = investor_id
    await _transition_mandate(
        db, convo=convo, to=MandateConversationState.COMPLETED
    )
    convo.status = "completed"
    convo.completed_at = datetime.now(timezone.utc)

    await emit_event(
        db,
        event_name=C0_CONVERSATION_COMPLETED,
        payload={
            "conversation_id": convo.conversation_id,
            "action_taken": "mandate_created",
            "mandate_id": mandate.mandate_id,
            "investor_id": investor_id,
            "final_state": MandateConversationState.COMPLETED.value,
        },
        firm_id=convo.firm_id,
    )

    summary_lines = ["Done — the mandate is created and active."]
    if response.warnings:
        summary_lines.append("Soft warnings:")
        for w in response.warnings:
            summary_lines.append(f"  • {w.message}")
    await _append_system_message(
        db,
        convo=convo,
        content="\n".join(summary_lines),
        metadata={
            "mandate_id": mandate.mandate_id,
            "card": "mandate_success",
            "warnings": [w.model_dump(mode="json") for w in response.warnings],
        },
    )


async def _compute_mandate_defaults_for_slot_bag(
    db: AsyncSession, *, convo: Conversation
) -> dict[str, Any]:
    """Return the I0 defaults for the conversation's locked-in investor."""
    investor_id = convo.collected_slots.get("investor_id")
    if not investor_id:
        return {}
    actor = UserContext(
        user_id=convo.user_id,
        firm_id=convo.firm_id,
        role=Role.ADVISOR,
        email="",
        name="",
        session_id="",
    )
    try:
        defaults = await m1_service.get_mandate_defaults(
            db, investor_id=investor_id, actor=actor
        )
    except m1_service.InvestorNotVisibleError:
        return {}
    return defaults.model_dump()


async def _transition_mandate(
    db: AsyncSession, *, convo: Conversation, to: MandateConversationState
) -> None:
    """Wraps :func:`_transition` for mandate-FSM states (separate enum)."""
    from_state = convo.state
    convo.state = to.value
    await emit_event(
        db,
        event_name=C0_STATE_TRANSITIONED,
        payload={
            "conversation_id": convo.conversation_id,
            "from_state": from_state,
            "to_state": to.value,
        },
        firm_id=convo.firm_id,
    )


async def _stash_candidates(
    db: AsyncSession,
    *,
    convo: Conversation,
    candidates: list[investor_lookup.InvestorMatch],
) -> None:
    """Persist the disambiguation candidate list in the slot bag so a
    follow-up "yes" / index selection can resolve without re-running the
    LLM.
    """
    new_slots = {**convo.collected_slots}
    new_slots["_disambiguation_candidates"] = [
        _candidate_dict(c) for c in candidates
    ]
    convo.collected_slots = new_slots
    await db.flush()


def _candidate_dict(c: investor_lookup.InvestorMatch) -> dict[str, Any]:
    return {
        "investor_id": c.investor_id,
        "name": c.name,
        "pan": c.pan,
        "age": c.age,
        "last_activity_at": c.last_activity_at,
    }


def _parse_candidate_selection(
    user_message: str, candidates: list[dict[str, Any]]
) -> investor_lookup.InvestorMatch | None:
    """Map a free-text reply to a candidate from the previously-stashed list.

    Recognises:
    - "yes" / "confirm" → first candidate when there's exactly one.
    - "1" / "2" / ... / "the first one" / "the second one" → indexed pick.
    - exact name match (case-insensitive) → that candidate.
    """
    if not candidates:
        return None
    norm = user_message.strip().lower()

    if len(candidates) == 1 and norm in {"yes", "confirm", "that's right", "correct"}:
        return _dict_to_match(candidates[0])

    # Index-based picks ("1", "the first one", etc.).
    word_to_index = {
        "first": 0, "1": 0,
        "second": 1, "2": 1,
        "third": 2, "3": 2,
        "fourth": 3, "4": 3,
        "fifth": 4, "5": 4,
    }
    for word, idx in word_to_index.items():
        if word in norm and idx < len(candidates):
            return _dict_to_match(candidates[idx])

    # Exact name (case-insensitive).
    for c in candidates:
        if c["name"].lower() == norm:
            return _dict_to_match(c)

    return None


def _dict_to_match(d: dict[str, Any]) -> investor_lookup.InvestorMatch:
    return investor_lookup.InvestorMatch(
        investor_id=d["investor_id"],
        name=d["name"],
        pan=d["pan"],
        age=d["age"],
        last_activity_at=d["last_activity_at"],
    )


def _normalise_prohibited(
    user_message: str, llm_value: Any
) -> list[str]:
    """Convert "none"-shaped replies to an empty list; otherwise prefer
    the LLM's structured value."""
    if llm_value is None:
        # LLM didn't extract a list; check the raw message.
        none_shaped = {
            "none", "no", "nothing", "no exclusions", "none to add",
        }
        if user_message.strip().lower() in none_shaped:
            return []
        # Otherwise treat the message as a single comma-separated input.
        items = [
            chunk.strip()
            for chunk in user_message.split(",")
            if chunk.strip()
        ]
        return items[:50]
    if isinstance(llm_value, list):
        return [str(item).strip() for item in llm_value if str(item).strip()][:50]
    if isinstance(llm_value, str):
        if llm_value.strip().lower() in {"none", "no", "nothing", "[]"}:
            return []
        return [
            chunk.strip()
            for chunk in llm_value.split(",")
            if chunk.strip()
        ][:50]
    return []


def _slots_to_mandate_payload(slots: dict[str, Any]) -> MandateCreateRequest:
    return MandateCreateRequest(
        equity_min_pct=int(slots["equity_min_pct"]),
        equity_max_pct=int(slots["equity_max_pct"]),
        debt_min_pct=int(slots["debt_min_pct"]),
        debt_max_pct=int(slots["debt_max_pct"]),
        alternatives_min_pct=int(slots["alternatives_min_pct"]),
        alternatives_max_pct=int(slots["alternatives_max_pct"]),
        single_position_max_pct=int(slots["single_position_max_pct"]),
        liquidity_floor_pct=int(slots["liquidity_floor_pct"]),
        sector_max_pct=int(slots["sector_max_pct"]),
        prohibited_instruments=list(slots.get("prohibited_instruments") or []),
    )


# ---------------------------------------------------------------------------
# Cluster 1 investor-onboarding slot turn (kept for back-compat)
# ---------------------------------------------------------------------------


async def _handle_slot_turn(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    router: SmartLLMRouter,
) -> None:
    """Subsequent turns: extract slots, advance FSM, prompt for next gap."""
    state = ConversationState(convo.state)
    current_prompt = state_machine.system_prompt_for(state, convo.collected_slots)
    expected = list(state_machine.expected_fields_for(state))

    result = await llm_client.extract_slots(
        db=db,
        router=router,
        user_response=user_message,
        current_prompt=current_prompt,
        expected_fields=expected,
    )

    if isinstance(result, LLMFallback):
        await _emit_llm_failure(db, convo=convo, fallback=result, stage="slot")
        # Single-field fallback: re-prompt for the first missing field
        # using the templated single-field nudge, no slot updates.
        missing = state_machine.missing_fields(state, convo.collected_slots)
        next_prompt = (
            LLM_FALLBACK_NOTICE
            + "\n\n"
            + (state_machine._single_field_prompt(missing[0]) if missing else current_prompt)
        )
        await _append_system_message(
            db,
            convo=convo,
            content=next_prompt,
            metadata={"fallback_mode": True},
        )
        return

    if result.extracted_fields:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields=result.extracted_fields,
            confidence=result.extraction_confidence,
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )

    next_state = state_machine.next_state_after(state, convo.collected_slots)
    if next_state is not state:
        await _transition(db, convo=convo, to=next_state)
    await _append_system_message(
        db,
        convo=convo,
        content=state_machine.system_prompt_for(next_state, convo.collected_slots),
        metadata={
            "expected_fields": list(state_machine.expected_fields_for(next_state)),
            "extraction_confidence": result.extraction_confidence,
        },
    )


async def _handle_confirmation_text_turn(
    db: AsyncSession, *, convo: Conversation, user_message: str
) -> None:
    """Free-text replies during STATE_AWAITING_CONFIRMATION map to confirm /
    cancel keywords; anything else just re-renders the summary."""
    norm = user_message.strip().lower()
    if norm in {"cancel", "no", "stop", "abort"}:
        await _abandon_inline(db, convo=convo, reason="user_cancelled")
        return

    # Anything resembling confirmation gets routed through confirm_action
    # so the same execution path runs whether the user clicked the button
    # or typed "yes".
    if norm in {"yes", "confirm", "go ahead", "create it", "create"}:
        await _execute_action(db, convo=convo)
        return

    # Otherwise, re-display the summary so the UI doesn't go blank.
    await _append_system_message(
        db,
        convo=convo,
        content=state_machine.system_prompt_for(
            ConversationState.AWAITING_CONFIRMATION, convo.collected_slots
        ),
        metadata={"hint": "type 'yes' to confirm or 'cancel' to abort"},
    )


# ---------------------------------------------------------------------------
# Confirm action — invoked by the explicit confirm endpoint
# ---------------------------------------------------------------------------


async def confirm_action(
    db: AsyncSession,
    *,
    conversation_id: str,
    actor: UserContext,
) -> Conversation:
    convo = await _load_for_actor(db, conversation_id=conversation_id, actor=actor)
    _ensure_writable(convo)
    if convo.state != ConversationState.AWAITING_CONFIRMATION.value:
        raise ConversationStateError(
            "confirm is only valid when the conversation is awaiting confirmation"
        )
    # Dispatch by intent — investor_onboarding hits the cluster 1 path,
    # mandate_creation hits chunk 2.2's path, case_opening hits chunk 5.3.
    if convo.intent == "mandate_creation":
        await _execute_mandate_creation(db, convo=convo, actor=actor)
    elif convo.intent == "case_opening":
        await _execute_case_opening(db, convo=convo, actor=actor)
    else:
        await _execute_action(db, convo=convo)
    convo.last_message_at = datetime.now(timezone.utc)
    await db.flush()
    return convo


async def _execute_action(db: AsyncSession, *, convo: Conversation) -> None:
    """Move into STATE_EXECUTING, call the investor service, settle final state."""
    await _transition(db, convo=convo, to=ConversationState.EXECUTING)

    actor = UserContext(
        user_id=convo.user_id,
        firm_id=convo.firm_id,
        # The advisor created the conversation; reuse their role for the
        # investor-creation call. Cluster 1 only the advisor reaches this
        # path (CIO/compliance/audit don't have CONVERSATIONS_WRITE_OWN_BOOK).
        role=Role.ADVISOR,
        email="",  # not used by investor_service.create_investor
        name="",
        session_id="",
    )

    payload = _slots_to_investor_payload(convo.collected_slots)
    try:
        investor: InvestorRead = await investor_service.create_investor(
            db, payload=payload, actor=actor, via="conversational"
        )
    except investor_service.DuplicatePanError as exc:
        await _append_system_message(
            db,
            convo=convo,
            content=(
                f"PAN {exc.warning.pan} already exists for "
                f"{exc.warning.duplicate_of_name}. Reply with 'yes proceed' "
                "to create a separate record anyway, or 'cancel' to abort."
            ),
            metadata={"error": "duplicate_pan", "duplicate": exc.warning.model_dump(mode="json")},
        )
        # Stash the acknowledgement intent so a follow-up "yes" re-runs
        # the create with the flag set.
        convo.collected_slots = {
            **convo.collected_slots,
            "_duplicate_pan_pending": True,
        }
        # Move back to confirmation so the FSM accepts a fresh confirm.
        await _transition(db, convo=convo, to=ConversationState.AWAITING_CONFIRMATION)
        return
    except investor_service.HouseholdResolutionError as exc:
        await _append_system_message(
            db,
            convo=convo,
            content=f"I couldn't resolve the household: {exc}. Let's pick a household.",
            metadata={"error": "household_resolution"},
        )
        # Drop back to household collection so the FSM can re-prompt.
        await _transition(db, convo=convo, to=ConversationState.COLLECTING_HOUSEHOLD)
        return

    convo.investor_id = investor.investor_id
    await _transition(db, convo=convo, to=ConversationState.COMPLETED)
    convo.status = "completed"
    convo.completed_at = datetime.now(timezone.utc)
    await emit_event(
        db,
        event_name=C0_CONVERSATION_COMPLETED,
        payload={
            "conversation_id": convo.conversation_id,
            "action_taken": "investor_created",
            "investor_id": investor.investor_id,
            "final_state": ConversationState.COMPLETED.value,
        },
        firm_id=convo.firm_id,
    )
    await _append_system_message(
        db,
        convo=convo,
        content=(
            f"Done — {investor.name} is onboarded "
            f"(life stage: {investor.life_stage}, "
            f"liquidity tier: {investor.liquidity_tier})."
        ),
        metadata={"investor_id": investor.investor_id, "card": "success"},
    )


# ---------------------------------------------------------------------------
# Cancel + abandonment
# ---------------------------------------------------------------------------


async def cancel_conversation(
    db: AsyncSession, *, conversation_id: str, actor: UserContext
) -> Conversation:
    convo = await _load_for_actor(db, conversation_id=conversation_id, actor=actor)
    _ensure_writable(convo)
    await _abandon_inline(db, convo=convo, reason="user_cancelled")
    await db.flush()
    return convo


async def abandon_stale_conversations(
    db: AsyncSession, *, now: datetime | None = None
) -> int:
    """Background-job helper: mark every active conversation older than the
    threshold as ``abandoned``. Returns the count abandoned this run.

    The application calls this on a schedule; cluster 1 hooks it into the
    FastAPI lifespan or an external cron — see chunk plan §implementation_notes.
    """
    cutoff = (now or datetime.now(timezone.utc)) - ABANDONMENT_THRESHOLD
    result = await db.execute(
        select(Conversation).where(
            Conversation.status == "active",
            Conversation.last_message_at < cutoff,
        )
    )
    rows = list(result.scalars())
    for convo in rows:
        await _abandon_inline(db, convo=convo, reason="inactivity_threshold_4h")
    if rows:
        await db.flush()
    return len(rows)


async def _abandon_inline(
    db: AsyncSession, *, convo: Conversation, reason: str
) -> None:
    convo.status = "abandoned"
    convo.completed_at = datetime.now(timezone.utc)
    await _transition(db, convo=convo, to=ConversationState.ABANDONED)
    await emit_event(
        db,
        event_name=C0_CONVERSATION_ABANDONED,
        payload={
            "conversation_id": convo.conversation_id,
            "abandonment_reason": reason,
        },
        firm_id=convo.firm_id,
    )
    await _append_system_message(
        db,
        convo=convo,
        content=state_machine.system_prompt_for(
            ConversationState.ABANDONED, convo.collected_slots
        ),
        metadata={"abandonment_reason": reason},
    )


# ---------------------------------------------------------------------------
# Read paths
# ---------------------------------------------------------------------------


async def get_conversation(
    db: AsyncSession, *, conversation_id: str, actor: UserContext
) -> ConversationRead:
    convo = await _load_for_actor(db, conversation_id=conversation_id, actor=actor)
    msgs = await _load_messages(db, conversation_id=convo.conversation_id)

    investor_read: InvestorRead | None = None
    if convo.investor_id:
        investor_read = await investor_service.get_investor(
            db, investor_id=convo.investor_id, actor=actor
        )

    return ConversationRead(
        conversation_id=convo.conversation_id,
        user_id=convo.user_id,
        intent=convo.intent,
        state=convo.state,
        collected_slots=convo.collected_slots,
        status=convo.status,  # type: ignore[arg-type]
        started_at=convo.started_at,
        last_message_at=convo.last_message_at,
        completed_at=convo.completed_at,
        investor_id=convo.investor_id,
        investor=investor_read,
        messages=[_message_read(m) for m in msgs],
    )


async def list_conversations(
    db: AsyncSession, *, actor: UserContext
) -> list[ConversationSummary]:
    """List conversations visible to the actor.

    Per FR 17.2: advisor sees own_book; cio/compliance/audit see firm-wide.
    Excludes abandoned conversations from the active sidebar listing
    (FR 14.0 §3.3 — "Abandoned conversations are preserved in the database
    for audit but do not appear in the user's active conversation list").
    """
    stmt = select(Conversation).order_by(Conversation.last_message_at.desc())
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Conversation.user_id == actor.user_id)
    else:
        stmt = stmt.where(Conversation.firm_id == actor.firm_id)
    stmt = stmt.where(Conversation.status != "abandoned")

    result = await db.execute(stmt)
    rows = list(result.scalars())

    # First user message preview (if any) for each row.
    out: list[ConversationSummary] = []
    for row in rows:
        preview = await _first_user_message_preview(
            db, conversation_id=row.conversation_id
        )
        out.append(
            ConversationSummary(
                conversation_id=row.conversation_id,
                intent=row.intent,
                state=row.state,
                status=row.status,  # type: ignore[arg-type]
                started_at=row.started_at,
                last_message_at=row.last_message_at,
                preview=preview,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_for_actor(
    db: AsyncSession, *, conversation_id: str, actor: UserContext
) -> Conversation:
    """Lookup + scope-check; raises if the actor can't see this conversation."""
    stmt = select(Conversation).where(Conversation.conversation_id == conversation_id)
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Conversation.user_id == actor.user_id)
    else:
        stmt = stmt.where(Conversation.firm_id == actor.firm_id)
    result = await db.execute(stmt)
    convo = result.scalar_one_or_none()
    if convo is None:
        raise ConversationNotFoundError(
            f"conversation {conversation_id!r} not found or not visible to actor"
        )
    return convo


def _ensure_writable(convo: Conversation) -> None:
    if convo.status != "active":
        raise ConversationStateError(
            f"conversation {convo.conversation_id!r} is {convo.status}; cannot mutate"
        )


async def _load_messages(
    db: AsyncSession, *, conversation_id: str
) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.timestamp)
    )
    return list(result.scalars())


async def _first_user_message_preview(
    db: AsyncSession, *, conversation_id: str
) -> str:
    result = await db.execute(
        select(Message.content)
        .where(
            Message.conversation_id == conversation_id,
            Message.sender == "user",
        )
        .order_by(Message.timestamp)
        .limit(1)
    )
    text = result.scalar_one_or_none() or ""
    if len(text) > 80:
        return text[:77] + "…"
    return text


async def _transition(
    db: AsyncSession, *, convo: Conversation, to: ConversationState
) -> None:
    from_state = convo.state
    convo.state = to.value
    await emit_event(
        db,
        event_name=C0_STATE_TRANSITIONED,
        payload={
            "conversation_id": convo.conversation_id,
            "from_state": from_state,
            "to_state": to.value,
        },
        firm_id=convo.firm_id,
    )


async def _append_system_message(
    db: AsyncSession,
    *,
    convo: Conversation,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> Message:
    msg = Message(
        message_id=str(ULID()),
        conversation_id=convo.conversation_id,
        sender="system",
        content=content,
        metadata_json=metadata or {},
        timestamp=datetime.now(timezone.utc),
    )
    db.add(msg)
    return msg


async def _apply_extracted_fields(
    db: AsyncSession,
    *,
    convo: Conversation,
    fields: dict[str, Any],
    confidence: str,
    llm_provider: str,
    llm_latency_ms: int,
) -> None:
    """Merge extracted fields into ``collected_slots`` (re-assign the dict
    so SQLAlchemy detects the change) and emit telemetry."""
    new_slots = {**convo.collected_slots}
    new_slots.update(fields)
    convo.collected_slots = new_slots

    await emit_event(
        db,
        event_name=C0_SLOT_EXTRACTED,
        payload={
            "conversation_id": convo.conversation_id,
            "fields_extracted": list(fields.keys()),
            "extraction_confidence": confidence,
            "llm_provider": llm_provider,
            "llm_latency_ms": llm_latency_ms,
        },
        firm_id=convo.firm_id,
    )


async def _emit_llm_failure(
    db: AsyncSession,
    *,
    convo: Conversation,
    fallback: LLMFallback,
    stage: str,
) -> None:
    logger.warning(
        "C0 LLM failure (stage=%s, type=%s, conversation_id=%s)",
        stage,
        fallback.failure_type,
        convo.conversation_id,
    )
    await emit_event(
        db,
        event_name=C0_LLM_FAILURE,
        payload={
            "conversation_id": convo.conversation_id,
            "stage": stage,
            "failure_type": fallback.failure_type,
        },
        firm_id=convo.firm_id,
    )


def _message_read(row: Message):
    return MessageRead(
        message_id=row.message_id,
        sender=row.sender,  # type: ignore[arg-type]
        content=row.content,
        metadata=row.metadata_json or {},
        timestamp=row.timestamp,
    )


def _slots_to_investor_payload(slots: dict[str, Any]) -> InvestorCreateRequest:
    """Build the canonical create payload from the conversation's slot bag.

    The Pydantic schema is the source of truth for validation; passing
    through it here means the conversational path enforces exactly the
    same rules as the form path.
    """
    payload: dict[str, Any] = {
        "name": slots["name"],
        "email": slots["email"],
        "phone": slots["phone"],
        "pan": slots["pan"],
        "age": slots["age"],
        "risk_appetite": slots["risk_appetite"],
        "time_horizon": slots["time_horizon"],
    }
    if slots.get("household_id"):
        payload["household_id"] = slots["household_id"]
    elif slots.get("household_name"):
        payload["household_name"] = slots["household_name"]
    if slots.get("_duplicate_pan_pending"):
        payload["duplicate_pan_acknowledged"] = True
    return InvestorCreateRequest(**payload)


# ---------------------------------------------------------------------------
# Case-opening intent (chunk 5.3 — FR Entry 14.0 cluster-5 revision)
# ---------------------------------------------------------------------------


async def _transition_case_opening(
    db: AsyncSession, *, convo: Conversation, to: CaseOpeningState
) -> None:
    """Mirror of :func:`_transition_mandate` for the case_opening FSM."""
    src = convo.state
    convo.state = to.value
    await db.flush()
    await emit_event(
        db,
        event_name=C0_STATE_TRANSITIONED,
        payload={
            "conversation_id": convo.conversation_id,
            "from": src,
            "to": to.value,
            "intent": "case_opening",
        },
        firm_id=convo.firm_id,
    )


async def _handle_case_opening_intent_extraction(
    db: AsyncSession,
    *,
    convo: Conversation,
    result: llm_client.IntentDetectionResult,
) -> None:
    """Turn-1 handler when the LLM classifies as ``case_opening``.

    Stamps any extracted investor / case_mode hints into the slot bag,
    transitions to disambiguation, runs the structured investor lookup.
    """
    fields_to_apply = {
        k: v
        for k, v in result.extracted_fields.items()
        if k in (
            "investor_name",
            "investor_pan",
            "case_mode",
            "case_intent",
            "proposed_action",
        )
    }
    if fields_to_apply:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields=fields_to_apply,
            confidence="medium",
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )

    await _transition_case_opening(
        db,
        convo=convo,
        to=CaseOpeningState.INVESTOR_DISAMBIGUATION,
    )
    await _run_investor_disambiguation_for_case_opening(db, convo=convo)


async def _handle_case_opening_turn(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    actor: UserContext,
    router: SmartLLMRouter,
) -> None:
    """Subsequent-turn dispatcher for the case_opening intent."""
    state = CaseOpeningState(convo.state)

    if state is CaseOpeningState.AWAITING_CONFIRMATION:
        await _handle_case_opening_confirmation_text(
            db, convo=convo, user_message=user_message, actor=actor
        )
        return

    if state is CaseOpeningState.INVESTOR_DISAMBIGUATION:
        await _handle_case_opening_disambiguation_turn(
            db, convo=convo, user_message=user_message, router=router
        )
        return

    # COLLECTING_DETAILS
    await _handle_case_opening_slot_turn(
        db, convo=convo, user_message=user_message, router=router
    )


async def _handle_case_opening_disambiguation_turn(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    router: SmartLLMRouter,
) -> None:
    state = CaseOpeningState.INVESTOR_DISAMBIGUATION
    expected = list(case_opening_state_machine.expected_fields_for(state))
    current_prompt = case_opening_state_machine.system_prompt_for(
        state, convo.collected_slots
    )

    candidates = convo.collected_slots.get("_disambiguation_candidates") or []
    selection = _parse_candidate_selection(user_message, candidates)
    if selection is not None:
        await _lock_in_investor_for_case_opening(
            db, convo=convo, candidate=selection
        )
        return

    result = await llm_client.extract_slots(
        db=db,
        router=router,
        user_response=user_message,
        current_prompt=current_prompt,
        expected_fields=expected,
    )
    if isinstance(result, LLMFallback):
        await _emit_llm_failure(db, convo=convo, fallback=result, stage="slot")
        await _append_system_message(
            db,
            convo=convo,
            content=(
                LLM_FALLBACK_NOTICE
                + "\n\nReply with the investor's full name or PAN."
            ),
            metadata={"fallback_mode": True},
        )
        return

    if result.extracted_fields:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields={
                k: v
                for k, v in result.extracted_fields.items()
                if k in ("investor_name", "investor_pan")
            },
            confidence=result.extraction_confidence,
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )

    await _run_investor_disambiguation_for_case_opening(db, convo=convo)


async def _run_investor_disambiguation_for_case_opening(
    db: AsyncSession, *, convo: Conversation
) -> None:
    """Like :func:`_run_investor_disambiguation` but uses the case_opening
    state names. Logic identical otherwise: structured lookup, branch on
    cardinality, prompt accordingly."""
    actor = UserContext(
        user_id=convo.user_id,
        firm_id=convo.firm_id,
        role=Role.ADVISOR,
        email="",
        name="",
        session_id="",
    )
    matches = await investor_lookup.find_matching_investors(
        db,
        name_query=convo.collected_slots.get("investor_name"),
        pan_query=convo.collected_slots.get("investor_pan"),
        actor=actor,
    )

    if len(matches) == 1:
        candidate = matches[0]
        await _stash_candidates(db, convo=convo, candidates=matches)
        await _append_system_message(
            db,
            convo=convo,
            content=(
                f"I found {candidate.name} (PAN {candidate.pan}). "
                "Is this the right investor? Reply 'yes' to proceed."
            ),
            metadata={
                "disambiguation_candidates": [
                    _candidate_dict(c) for c in matches
                ],
            },
        )
        return

    if len(matches) > 1:
        await _stash_candidates(db, convo=convo, candidates=matches)
        lines = ["I found multiple investors. Which one?"]
        for i, c in enumerate(matches, start=1):
            lines.append(f"  {i}. {c.name} · PAN {c.pan} · age {c.age}")
        lines.append("")
        lines.append("Reply with the number or the name to select.")
        await _append_system_message(
            db,
            convo=convo,
            content="\n".join(lines),
            metadata={
                "disambiguation_candidates": [
                    _candidate_dict(c) for c in matches
                ],
            },
        )
        return

    await _append_system_message(
        db,
        convo=convo,
        content=(
            "I couldn't find an investor matching that name or PAN. "
            "Can you provide the full name or PAN? If this client isn't "
            "in your book yet, I can help you onboard them first — say "
            "'onboard new client'."
        ),
        metadata={"disambiguation_candidates": []},
    )


async def _lock_in_investor_for_case_opening(
    db: AsyncSession,
    *,
    convo: Conversation,
    candidate: investor_lookup.InvestorMatch,
) -> None:
    """Confirm an investor and advance to detail collection.

    Unlike the mandate variant, we don't gate on existing-mandate state
    — case_opening *requires* an existing mandate (the governance gate
    consumes it), and missing-mandate is surfaced as a soft warning at
    decision-time rather than blocking case creation.
    """
    new_slots = {**convo.collected_slots}
    new_slots["investor_id"] = candidate.investor_id
    new_slots["investor_name"] = candidate.name
    new_slots["investor_pan"] = candidate.pan
    new_slots.pop("_disambiguation_candidates", None)
    convo.collected_slots = new_slots

    next_state = CaseOpeningState.COLLECTING_DETAILS
    await _transition_case_opening(db, convo=convo, to=next_state)
    await _append_system_message(
        db,
        convo=convo,
        content=case_opening_state_machine.system_prompt_for(
            next_state, convo.collected_slots
        ),
        metadata={
            "expected_fields": list(
                case_opening_state_machine.expected_fields_for(next_state)
            ),
        },
    )


async def _handle_case_opening_slot_turn(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    router: SmartLLMRouter,
) -> None:
    state = CaseOpeningState(convo.state)
    expected = list(case_opening_state_machine.expected_fields_for(state))
    current_prompt = case_opening_state_machine.system_prompt_for(
        state, convo.collected_slots
    )

    result = await llm_client.extract_slots(
        db=db,
        router=router,
        user_response=user_message,
        current_prompt=current_prompt,
        expected_fields=expected,
    )

    if isinstance(result, LLMFallback):
        await _emit_llm_failure(db, convo=convo, fallback=result, stage="slot")
        await _append_system_message(
            db,
            convo=convo,
            content=LLM_FALLBACK_NOTICE + "\n\n" + current_prompt,
            metadata={"fallback_mode": True},
        )
        return

    extracted = {
        k: v
        for k, v in result.extracted_fields.items()
        if k in case_opening_state_machine.DETAIL_FIELDS
    }
    if extracted:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields=extracted,
            confidence=result.extraction_confidence,
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )

    next_state = case_opening_state_machine.next_state_after(
        state, convo.collected_slots
    )
    if next_state is not state:
        await _transition_case_opening(db, convo=convo, to=next_state)
    await _append_system_message(
        db,
        convo=convo,
        content=case_opening_state_machine.system_prompt_for(
            next_state, convo.collected_slots
        ),
        metadata={
            "expected_fields": list(
                case_opening_state_machine.expected_fields_for(next_state)
            ),
            "extraction_confidence": result.extraction_confidence,
        },
    )


async def _handle_case_opening_confirmation_text(
    db: AsyncSession,
    *,
    convo: Conversation,
    user_message: str,
    actor: UserContext,
) -> None:
    """Yes/no/cancel handler in the case_opening confirmation state."""
    norm = user_message.strip().lower()
    if norm in {"cancel", "no", "stop", "abort"}:
        await _abandon_inline(db, convo=convo, reason="user_cancelled")
        return
    if norm in {"yes", "confirm", "go ahead", "open it", "open"}:
        await _execute_case_opening(db, convo=convo, actor=actor)
        return
    await _append_system_message(
        db,
        convo=convo,
        content=case_opening_state_machine.system_prompt_for(
            CaseOpeningState.AWAITING_CONFIRMATION, convo.collected_slots
        ),
        metadata={"hint": "type 'yes' to confirm or 'cancel' to abort"},
    )


async def _execute_case_opening(
    db: AsyncSession, *, convo: Conversation, actor: UserContext
) -> None:
    """Call the chunk 5.3 case_opener with the conversation's slot bag."""
    from artha.api_v2.cases import case_opener
    from artha.api_v2.cases.case_opener import (
        CaseOpeningError,
        InvalidCaseModeError,
        InvestorNotFoundError,
        InvestorScopeError,
        OpenCaseDeps,
        OpenCaseRequest,
    )
    from artha.api_v2.m0.boss import boss as m0_boss

    await _transition_case_opening(
        db, convo=convo, to=CaseOpeningState.EXECUTING
    )

    slots = convo.collected_slots
    request = OpenCaseRequest(
        investor_id=slots["investor_id"],
        case_mode=slots["case_mode"],
        case_intent=slots.get("case_intent"),
        proposed_action=slots.get("proposed_action"),
        created_via="c0_conversational",
    )

    creator = UserContext(
        user_id=convo.user_id,
        firm_id=convo.firm_id,
        role=Role.ADVISOR,
        email=actor.email,
        name=actor.name,
        session_id=actor.session_id,
    )

    try:
        result = await case_opener.open_case(
            db,
            request,
            actor=creator,
            deps=OpenCaseDeps(boss=m0_boss),
        )
    except InvestorNotFoundError as exc:
        await _transition_case_opening(
            db, convo=convo, to=CaseOpeningState.INVESTOR_DISAMBIGUATION
        )
        await _append_system_message(
            db,
            convo=convo,
            content=f"Investor lookup failed: {exc}. Try again with a name or PAN.",
            metadata={"error": "investor_not_found"},
        )
        return
    except InvestorScopeError as exc:
        await _transition_case_opening(
            db, convo=convo, to=CaseOpeningState.COMPLETED
        )
        convo.status = "completed"
        convo.completed_at = datetime.now(timezone.utc)
        await _append_system_message(
            db,
            convo=convo,
            content=(
                "That investor isn't in your book. Ask the assigned advisor "
                "or your CIO to open the case."
            ),
            metadata={"error": "scope", "detail": str(exc)},
        )
        return
    except InvalidCaseModeError as exc:
        await _transition_case_opening(
            db, convo=convo, to=CaseOpeningState.COLLECTING_DETAILS
        )
        await _append_system_message(
            db,
            convo=convo,
            content=f"That mode/intent combo doesn't work: {exc}.",
            metadata={"error": "invalid_mode"},
        )
        return
    except CaseOpeningError as exc:
        await _transition_case_opening(
            db, convo=convo, to=CaseOpeningState.COMPLETED
        )
        convo.status = "completed"
        convo.completed_at = datetime.now(timezone.utc)
        await _append_system_message(
            db,
            convo=convo,
            content=f"Case opening failed: {exc}.",
            metadata={"error": "case_opening_failed"},
        )
        return

    convo.investor_id = result.case.investor_id
    await _transition_case_opening(
        db, convo=convo, to=CaseOpeningState.COMPLETED
    )
    convo.status = "completed"
    convo.completed_at = datetime.now(timezone.utc)

    await emit_event(
        db,
        event_name=C0_CONVERSATION_COMPLETED,
        payload={
            "conversation_id": convo.conversation_id,
            "action_taken": "case_opened",
            "case_id": result.case.case_id,
            "investor_id": result.case.investor_id,
            "final_state": CaseOpeningState.COMPLETED.value,
        },
        firm_id=convo.firm_id,
    )

    await _append_system_message(
        db,
        convo=convo,
        content=(
            f"Case {result.case.case_id} is open. It's gathering evidence "
            f"now — you'll see findings appear in the case detail view."
        ),
        metadata={
            "case_id": result.case.case_id,
            "card": "case_success",
            "applicable_evidence_agents": list(result.applicable_evidence_agents),
        },
    )
