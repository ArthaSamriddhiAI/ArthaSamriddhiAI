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
from artha.api_v2.c0 import llm_client, state_machine
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

    current_state = ConversationState(convo.state)

    if current_state is ConversationState.INTENT_PENDING:
        await _handle_intent_turn(
            db, convo=convo, user_message=user_message, router=router
        )
    elif current_state is ConversationState.AWAITING_CONFIRMATION:
        # The user typed something while we were waiting on the confirm
        # button. Treat keywords like "cancel" / "no" as an explicit
        # cancel; treat "yes" / "confirm" as a confirm. Otherwise rerender
        # the summary so the conversation isn't stuck.
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
        # only intent cluster 1 implements) so the FSM can proceed in
        # template-fallback mode (FR 14.0 §5.1).
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

    if result.intent != "investor_onboarding":
        # FR 14.0 §2.1: other intents return placeholder responses in cluster 1.
        await _transition(db, convo=convo, to=ConversationState.COMPLETED)
        convo.status = "completed"
        convo.completed_at = datetime.now(timezone.utc)
        await _append_system_message(
            db,
            convo=convo,
            content=(
                f"That intent ({result.intent.replace('_', ' ')}) isn't "
                "implemented yet — cluster 1 only handles new client "
                "onboarding. Try saying 'I want to onboard a new client'."
            ),
            metadata={"intent": result.intent, "placeholder": True},
        )
        return

    # Apply pre-filled slots from turn-1 extraction.
    if result.extracted_fields:
        await _apply_extracted_fields(
            db,
            convo=convo,
            fields=result.extracted_fields,
            confidence="medium",  # turn-1 extractions don't carry confidence
            llm_provider=result.llm_provider,
            llm_latency_ms=result.llm_latency_ms,
        )

    # Move into the first collection state and prompt for the first
    # missing fields.
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
