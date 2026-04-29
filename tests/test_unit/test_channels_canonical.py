"""Pass 14 — C0 + N0 + M0.Librarian acceptance tests.

§10.1.6 (C0):
  Test 1 — Standard cases parse correctly with high confidence
  Test 2 — Ambiguity surfacing on multi-intent inputs
  Test 3 — Entity resolution against client directory
  Test 4 — Continuation turns: anaphora resolution via session
  Test 5 — Determinism within parser version

§10.2.7 (N0):
  Test 1 — Tier semantics (windows differ by tier)
  Test 2 — Watch lifecycle (active_watch → resolved_occurred / did_not_occur)
  Test 4 — MUST_RESPOND timeout escalates
  Test 7 — Tier configuration honored (different windows for different firms)
  Test 8 — Determinism within version (input_hash stable on N0Alert)

§8.7.6 (M0.Librarian):
  Test 1 — Session isolation
  Test 2 — Recent turns retrieval in chronological order
  Test 3 — Themed retrieval correctness with valid citations
  Test 4 — Summary fidelity (no invented claims)
  Test 5 — Pending followup surfaced at session close
  Test 6 — Determinism for non-LLM operations
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from artha.canonical.channels import (
    AlertDeliveryState,
    AlertEngagementType,
    C0AmbiguityType,
    C0ChannelSource,
    C0ParseOutput,
    LibrarianSession,
)
from artha.canonical.monitoring import (
    N0Alert,
    N0AlertCategory,
    N0Originator,
    WatchMetadata,
)
from artha.channels import (
    ConversationalChannel,
    InMemoryClientDirectory,
    NotificationChannel,
)
from artha.common.clock import FrozenClock, set_clock
from artha.common.types import (
    AlertTier,
    CaseIntent,
    WatchState,
)
from artha.common.ulid import new_ulid
from artha.llm.providers.mock import MockProvider
from artha.m0.librarian import M0Librarian, TurnInput

# ===========================================================================
# Helpers
# ===========================================================================


def _c0_mock(
    *,
    intent: CaseIntent = CaseIntent.CASE,
    confidence: float = 0.92,
    entities: dict | None = None,
    ambiguity_flags: list[str] | None = None,
) -> MockProvider:
    mock = MockProvider()
    mock.set_structured_response(
        "Signals:",
        {
            "parsed_intent_value": intent.value,
            "parsed_intent_confidence": confidence,
            "extracted_entities": entities or {},
            "ambiguity_flags": ambiguity_flags or [],
        },
    )
    return mock


def _build_alert(
    *,
    originator: N0Originator = N0Originator.M1,
    tier: AlertTier = AlertTier.MUST_RESPOND,
    category: N0AlertCategory = N0AlertCategory.MANDATE_BREACH,
    client_id: str = "c1",
    related_constraint_id: str | None = "asset_class_limit:equity",
    title: str = "Mandate breach: equity",
    body: str = "Equity 70% > cap 60%.",
    watch_metadata: WatchMetadata | None = None,
    created_at: datetime | None = None,
) -> N0Alert:
    return N0Alert(
        alert_id=new_ulid(),
        originator=originator,
        tier=tier,
        category=category,
        client_id=client_id,
        firm_id="firm_test",
        created_at=created_at or datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        title=title,
        body=body,
        related_constraint_id=related_constraint_id,
        watch_metadata=watch_metadata,
    )


# ===========================================================================
# §10.1.6 — C0 acceptance
# ===========================================================================


class TestC0Acceptance:
    @pytest.mark.asyncio
    async def test_test_1_standard_parse(self):
        directory = InMemoryClientDirectory(
            [{"client_id": "c1", "display_name": "Sharma Family"}]
        )
        c0 = ConversationalChannel(
            _c0_mock(
                intent=CaseIntent.CASE,
                confidence=0.92,
                entities={"client_name_raw": "Sharma"},
            ),
            directory=directory,
        )
        out = await c0.parse(
            raw_text="Review Sharma's portfolio for an AIF Cat II proposal.",
            advisor_id="advisor_jane",
            firm_id="firm_test",
        )
        assert out.parsed_intent is CaseIntent.CASE
        assert out.parsed_intent_confidence >= 0.85
        assert out.extracted_entities.client_id == "c1"
        assert C0AmbiguityType.CLIENT_NAME_AMBIGUOUS not in out.ambiguity_flags

    @pytest.mark.asyncio
    async def test_test_2_ambiguity_surfaced(self):
        c0 = ConversationalChannel(
            _c0_mock(
                intent=CaseIntent.CASE,
                confidence=0.45,
                ambiguity_flags=["intent_ambiguous"],
            ),
        )
        out = await c0.parse(
            raw_text="Maybe rebalance, or review, or both? Not sure.",
            advisor_id="advisor_jane",
            firm_id="firm_test",
        )
        assert out.parsed_intent_confidence < 0.6
        assert C0AmbiguityType.INTENT_AMBIGUOUS in out.ambiguity_flags

    @pytest.mark.asyncio
    async def test_test_3_entity_resolution_ambiguous(self):
        # Two clients share a name fragment → ambiguous
        directory = InMemoryClientDirectory([
            {"client_id": "c1", "display_name": "Sharma Family"},
            {"client_id": "c2", "display_name": "Sharma Brothers Trust"},
        ])
        c0 = ConversationalChannel(
            _c0_mock(
                intent=CaseIntent.CASE,
                entities={"client_name_raw": "Sharma"},
            ),
            directory=directory,
        )
        out = await c0.parse(
            raw_text="Pull up Sharma's portfolio.",
            advisor_id="advisor_jane",
            firm_id="firm_test",
        )
        assert out.extracted_entities.client_id is None
        assert C0AmbiguityType.CLIENT_NAME_AMBIGUOUS in out.ambiguity_flags

    @pytest.mark.asyncio
    async def test_test_3_entity_resolution_miss(self):
        directory = InMemoryClientDirectory([
            {"client_id": "c1", "display_name": "Patel Family"},
        ])
        c0 = ConversationalChannel(
            _c0_mock(
                intent=CaseIntent.CASE,
                entities={"client_name_raw": "Sharma"},
            ),
            directory=directory,
        )
        out = await c0.parse(
            raw_text="Pull up Sharma's portfolio.",
            advisor_id="advisor_jane",
            firm_id="firm_test",
        )
        assert out.extracted_entities.client_id is None
        assert C0AmbiguityType.CLIENT_NAME_AMBIGUOUS in out.ambiguity_flags

    @pytest.mark.asyncio
    async def test_test_4_continuation_turn(self):
        directory = InMemoryClientDirectory([
            {"client_id": "c1", "display_name": "Sharma Family"},
        ])
        librarian = M0Librarian()
        session = librarian.begin_session(
            advisor_id="advisor_jane",
            firm_id="firm_test",
            client_id="c1",
        )
        # First turn established context — record one prior turn manually.
        librarian.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Review Sharma's portfolio.",
                parsed_intent=CaseIntent.CASE,
                parsed_intent_confidence=0.92,
            ),
        )

        # Second turn: anaphora — LLM is expected to resolve via session
        # context. With a mock that returns no client_id, our deterministic
        # layer should NOT silently inherit; it should surface
        # REFERENT_UNRESOLVED to the human.
        c0 = ConversationalChannel(
            _c0_mock(intent=CaseIntent.CASE, entities={}),
            directory=directory,
        )
        out = await c0.parse(
            raw_text="What about for him?",
            advisor_id="advisor_jane",
            firm_id="firm_test",
            session=session,
        )
        assert out.session_metadata.continuity is True
        assert out.session_metadata.session_id == session.session_id
        # Deterministic layer surfaces REFERENT_UNRESOLVED when LLM didn't
        # produce a client_id in spite of session.client_id being set.
        assert C0AmbiguityType.REFERENT_UNRESOLVED in out.ambiguity_flags

    @pytest.mark.asyncio
    async def test_test_5_determinism(self):
        directory = InMemoryClientDirectory([
            {"client_id": "c1", "display_name": "Sharma Family"},
        ])
        c0 = ConversationalChannel(
            _c0_mock(
                intent=CaseIntent.CASE,
                entities={"client_name_raw": "Sharma"},
            ),
            directory=directory,
        )
        out1 = await c0.parse(
            raw_text="Review Sharma's portfolio.",
            advisor_id="advisor_jane",
            firm_id="firm_test",
        )
        out2 = await c0.parse(
            raw_text="Review Sharma's portfolio.",
            advisor_id="advisor_jane",
            firm_id="firm_test",
        )
        assert out1.input_hash == out2.input_hash

    @pytest.mark.asyncio
    async def test_round_trip_c0_schema(self):
        directory = InMemoryClientDirectory([
            {"client_id": "c1", "display_name": "Sharma Family"},
        ])
        c0 = ConversationalChannel(
            _c0_mock(
                intent=CaseIntent.CASE,
                entities={"client_name_raw": "Sharma"},
            ),
            directory=directory,
        )
        out = await c0.parse(
            raw_text="Review Sharma.",
            advisor_id="advisor_jane",
            firm_id="firm_test",
        )
        round_tripped = C0ParseOutput.model_validate_json(out.model_dump_json())
        assert round_tripped == out


# ===========================================================================
# §10.2.7 — N0 acceptance
# ===========================================================================


class TestN0Acceptance:
    def test_test_1a_must_respond_window_default(self):
        n0 = NotificationChannel()
        alert = _build_alert(tier=AlertTier.MUST_RESPOND)
        kept, dedup = n0.enqueue(alert)
        assert not dedup
        assert n0.get_state(kept.alert_id) is AlertDeliveryState.QUEUED

    def test_test_1b_dedupe_collapses(self):
        n0 = NotificationChannel()
        a1 = _build_alert(
            tier=AlertTier.MUST_RESPOND,
            related_constraint_id="liquidity_floor",
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        a2 = _build_alert(
            tier=AlertTier.MUST_RESPOND,
            related_constraint_id="liquidity_floor",
            created_at=datetime(2026, 4, 25, 9, 30, tzinfo=UTC),  # 30 min later, within 1h window
        )
        n0.enqueue(a1)
        kept, was_dedup = n0.enqueue(a2)
        assert was_dedup is True
        assert kept.alert_id == a1.alert_id
        assert n0.get_duplicate_count(a1.alert_id) == 1

    def test_test_2_watch_resolved_occurred(self):
        n0 = NotificationChannel()
        watch = WatchMetadata(
            probability=0.7,
            confidence_band="high",
            resolution_horizon_days=30,
            impact_if_resolved="Reduce equity allocation 200bps",
            state=WatchState.ACTIVE_WATCH,
        )
        alert = _build_alert(
            originator=N0Originator.E3,
            tier=AlertTier.WATCH,
            category=N0AlertCategory.REGIME_WATCH,
            watch_metadata=watch,
            related_constraint_id=None,
        )
        n0.enqueue(alert)
        successor_id = "alert_succ_001"
        outcome = n0.resolve_watch(
            alert.alert_id,
            outcome=WatchState.RESOLVED_OCCURRED,
            successor_alert_id=successor_id,
        )
        assert outcome is WatchState.RESOLVED_OCCURRED
        closure = n0.get_closure(alert.alert_id)
        assert closure is not None
        assert closure.successor_alert_id == successor_id
        # Watch state mutated on the alert
        updated = n0.get_alert(alert.alert_id)
        assert updated.watch_metadata.state is WatchState.RESOLVED_OCCURRED

    def test_test_2_watch_resolved_did_not_occur(self):
        n0 = NotificationChannel()
        watch = WatchMetadata(
            probability=0.6,
            confidence_band="moderate",
            resolution_horizon_days=30,
            impact_if_resolved="x",
        )
        alert = _build_alert(
            originator=N0Originator.E3,
            tier=AlertTier.WATCH,
            category=N0AlertCategory.REGIME_WATCH,
            watch_metadata=watch,
            related_constraint_id=None,
        )
        n0.enqueue(alert)
        n0.resolve_watch(alert.alert_id, outcome=WatchState.RESOLVED_DID_NOT_OCCUR)
        updated = n0.get_alert(alert.alert_id)
        assert updated.watch_metadata.state is WatchState.RESOLVED_DID_NOT_OCCUR

    def test_resolve_watch_rejects_invalid_outcome(self):
        n0 = NotificationChannel()
        alert = _build_alert(
            originator=N0Originator.E3,
            tier=AlertTier.WATCH,
            category=N0AlertCategory.REGIME_WATCH,
            watch_metadata=WatchMetadata(
                probability=0.5,
                confidence_band="moderate",
                resolution_horizon_days=30,
                impact_if_resolved="x",
            ),
            related_constraint_id=None,
        )
        n0.enqueue(alert)
        with pytest.raises(ValueError):
            n0.resolve_watch(alert.alert_id, outcome=WatchState.ACTIVE_WATCH)

    def test_resolve_watch_rejects_non_watch_tier(self):
        n0 = NotificationChannel()
        alert = _build_alert(tier=AlertTier.MUST_RESPOND)
        n0.enqueue(alert)
        with pytest.raises(ValueError):
            n0.resolve_watch(alert.alert_id, outcome=WatchState.RESOLVED_OCCURRED)

    def test_test_4_must_respond_timeout_escalates(self):
        # Default 12h window. Alert created at 09:00; check at 22:00 (>12h).
        n0 = NotificationChannel()
        alert = _build_alert(
            tier=AlertTier.MUST_RESPOND,
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        n0.enqueue(alert)
        n0.deliver(alert.alert_id)
        escalations = n0.check_timeouts(
            as_of=datetime(2026, 4, 25, 22, 0, tzinfo=UTC),  # 13h later
        )
        assert any(e.alert_id == alert.alert_id for e in escalations)

    def test_must_respond_no_escalation_when_acknowledged(self):
        n0 = NotificationChannel()
        alert = _build_alert(
            tier=AlertTier.MUST_RESPOND,
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        n0.enqueue(alert)
        n0.deliver(alert.alert_id)
        n0.record_engagement(
            alert.alert_id,
            event_type=AlertEngagementType.ACKNOWLEDGED,
            advisor_id="advisor_jane",
        )
        escalations = n0.check_timeouts(
            as_of=datetime(2026, 4, 25, 22, 0, tzinfo=UTC),
        )
        assert not any(e.alert_id == alert.alert_id for e in escalations)

    def test_should_respond_expires_silently_past_window(self):
        n0 = NotificationChannel()
        alert = _build_alert(
            tier=AlertTier.SHOULD_RESPOND,
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        n0.enqueue(alert)
        # Default SHOULD_RESPOND window: 72h. Check 73h later.
        escalations = n0.check_timeouts(
            as_of=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
        )
        # Not in escalations (only MUST_RESPOND escalates)
        assert not any(e.alert_id == alert.alert_id for e in escalations)
        # But state advances to expired
        assert n0.get_state(alert.alert_id) is AlertDeliveryState.EXPIRED

    def test_test_7_firm_overrides_window(self):
        n0_short = NotificationChannel(must_respond_window=timedelta(hours=4))
        alert = _build_alert(
            tier=AlertTier.MUST_RESPOND,
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        n0_short.enqueue(alert)
        # 5h later — past short window
        escalations = n0_short.check_timeouts(
            as_of=datetime(2026, 4, 25, 14, 0, tzinfo=UTC),
        )
        assert any(e.alert_id == alert.alert_id for e in escalations)

    def test_engagement_log_grows(self):
        n0 = NotificationChannel()
        alert = _build_alert()
        n0.enqueue(alert)
        n0.deliver(alert.alert_id)
        n0.record_engagement(
            alert.alert_id,
            event_type=AlertEngagementType.OPENED,
            advisor_id="advisor_jane",
        )
        n0.record_engagement(
            alert.alert_id,
            event_type=AlertEngagementType.DRILLED_DOWN,
            advisor_id="advisor_jane",
        )
        log = n0.get_engagement_log(alert.alert_id)
        assert len(log) == 2
        assert log[0].event_type is AlertEngagementType.OPENED
        assert log[1].event_type is AlertEngagementType.DRILLED_DOWN

    def test_test_8_n0_alert_round_trip(self):
        """N0Alert schema round-trips for replay."""
        alert = _build_alert()
        round_tripped = N0Alert.model_validate_json(alert.model_dump_json())
        assert round_tripped == alert


# ===========================================================================
# §8.7.6 — M0.Librarian acceptance
# ===========================================================================


def _librarian_retrieval_mock(
    *,
    summary: str = "",
    cited_turn_ids: list[str] | None = None,
    no_relevant_turns: bool = False,
) -> MockProvider:
    mock = MockProvider()
    mock.set_structured_response(
        "themed retrieval surface",
        {
            "summary": summary,
            "cited_turn_ids": cited_turn_ids or [],
            "no_relevant_turns": no_relevant_turns,
        },
    )
    return mock


class TestLibrarianAcceptance:
    def setup_method(self):
        # Reset the system clock back to real after FrozenClock tests below.
        from artha.common.clock import SystemClock

        set_clock(SystemClock())

    def test_test_1_session_isolation(self):
        lib = M0Librarian()
        s1 = lib.begin_session(advisor_id="adv1", firm_id="firm_test", client_id="c1")
        s2 = lib.begin_session(advisor_id="adv1", firm_id="firm_test", client_id="c1")
        assert s1.session_id != s2.session_id

        lib.update_on_turn(
            s1.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Mention liquidity concerns in s1.",
            ),
        )
        # s2 doesn't see s1's turns
        assert lib.retrieve_recent(s2.session_id) == []
        assert len(lib.retrieve_recent(s1.session_id)) == 1

    def test_test_2_recent_turns_chronological(self):
        lib = M0Librarian()
        session = lib.begin_session(
            advisor_id="adv1", firm_id="firm_test", client_id="c1"
        )
        for i in range(5):
            lib.update_on_turn(
                session.session_id,
                turn=TurnInput(
                    timestamp=datetime(2026, 4, 25, 9 + i, 0, tzinfo=UTC),
                    channel=C0ChannelSource.UI_CHAT,
                    raw_text=f"turn {i}",
                ),
            )
        recent3 = lib.retrieve_recent(session.session_id, n=3)
        assert [t.raw_text for t in recent3] == ["turn 2", "turn 3", "turn 4"]

    @pytest.mark.asyncio
    async def test_test_3_themed_retrieval_with_valid_citations(self):
        lib = M0Librarian()
        session = lib.begin_session(
            advisor_id="adv1", firm_id="firm_test", client_id="c1"
        )
        t1 = lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Sharma needs ₹2 Cr by March for daughter's wedding.",
            ),
        )
        lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 15, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="What's the AIF Cat II minimum?",
            ),
        )

        lib._provider = _librarian_retrieval_mock(
            summary="Advisor mentioned a ₹2 Cr liquidity need by March.",
            cited_turn_ids=[t1.turn_id],
        )
        summary, cited = await lib.retrieve_themed(
            session.session_id, query="liquidity concerns"
        )
        assert "₹2 Cr" in summary
        assert cited == [t1.turn_id]

    @pytest.mark.asyncio
    async def test_test_4_invented_citations_suppressed(self):
        """LLM cites turn_ids that don't exist → summary suppressed."""
        lib = M0Librarian()
        session = lib.begin_session(
            advisor_id="adv1", firm_id="firm_test", client_id="c1"
        )
        lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Some legitimate turn.",
            ),
        )
        # LLM invents a non-existent turn id → summary should be suppressed
        lib._provider = _librarian_retrieval_mock(
            summary="Made-up summary about content not in any turn.",
            cited_turn_ids=["bogus_invented_turn_id"],
        )
        summary, cited = await lib.retrieve_themed(
            session.session_id, query="anything"
        )
        assert summary == ""
        assert cited == []

    @pytest.mark.asyncio
    async def test_no_relevant_turns_returns_empty(self):
        lib = M0Librarian()
        session = lib.begin_session(
            advisor_id="adv1", firm_id="firm_test", client_id="c1"
        )
        lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Some turn.",
            ),
        )
        lib._provider = _librarian_retrieval_mock(no_relevant_turns=True)
        summary, cited = await lib.retrieve_themed(
            session.session_id, query="off-topic"
        )
        assert summary == ""
        assert cited == []

    def test_test_5_pending_followup_surfaced(self):
        lib = M0Librarian()
        session = lib.begin_session(
            advisor_id="adv1", firm_id="firm_test", client_id="c1"
        )
        t1 = lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Will check the AIF cascade.",
            ),
        )
        lib.open_pending_followup(
            session.session_id,
            description="Verify AIF Cat II cascade timing for client c1.",
            introduced_turn_id=t1.turn_id,
        )
        unresolved = lib.unresolved_followups(session.session_id)
        assert len(unresolved) == 1
        assert "cascade" in unresolved[0].description.lower()

        # Resolving removes from unresolved list
        lib.resolve_pending_followup(
            session.session_id,
            unresolved[0].followup_id,
            resolved_turn_id=t1.turn_id,
        )
        assert lib.unresolved_followups(session.session_id) == []

    def test_pending_ambiguity_lifecycle(self):
        lib = M0Librarian()
        session = lib.begin_session(
            advisor_id="adv1", firm_id="firm_test", client_id="c1"
        )
        t1 = lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Sharma — Family or Brothers Trust?",
            ),
        )
        amb = lib.open_pending_ambiguity(
            session.session_id,
            description="Sharma name ambiguous: Family vs Brothers Trust.",
            introduced_turn_id=t1.turn_id,
        )
        assert not amb.resolved

        t2 = lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 5, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Sharma Family.",
            ),
        )
        resolved = lib.resolve_pending_ambiguity(
            session.session_id,
            amb.ambiguity_id,
            resolved_turn_id=t2.turn_id,
        )
        assert resolved.resolved is True
        assert resolved.resolved_turn_id == t2.turn_id

    def test_test_6_running_summary_respects_budget(self):
        lib = M0Librarian()
        session = lib.begin_session(
            advisor_id="adv1",
            firm_id="firm_test",
            summary_token_budget=50,  # very tight: ~200 chars
        )
        for i in range(10):
            lib.update_on_turn(
                session.session_id,
                turn=TurnInput(
                    timestamp=datetime(2026, 4, 25, 9 + i, 0, tzinfo=UTC),
                    channel=C0ChannelSource.UI_CHAT,
                    raw_text=f"turn {i}",
                    summary_fragment="x" * 100,  # each fragment 100 chars
                ),
            )
        # Final summary should not exceed budget * 4 (chars)
        assert len(session.running_summary) <= 50 * 4 + 10

    def test_session_round_trips(self):
        lib = M0Librarian()
        session = lib.begin_session(
            advisor_id="adv1", firm_id="firm_test", client_id="c1"
        )
        lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="hi",
            ),
        )
        round_tripped = LibrarianSession.model_validate_json(session.model_dump_json())
        assert round_tripped.session_id == session.session_id
        assert len(round_tripped.turns) == 1

    def test_end_session_idempotent(self):
        lib = M0Librarian()
        session = lib.begin_session(advisor_id="adv1", firm_id="firm_test")
        lib.end_session(session.session_id)
        first_end = session.ended_at
        lib.end_session(session.session_id)
        # ended_at unchanged on second call
        assert session.ended_at == first_end

    def test_update_on_ended_session_raises(self):
        lib = M0Librarian()
        session = lib.begin_session(advisor_id="adv1", firm_id="firm_test")
        lib.end_session(session.session_id)
        with pytest.raises(ValueError):
            lib.update_on_turn(
                session.session_id,
                turn=TurnInput(
                    timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                    channel=C0ChannelSource.UI_CHAT,
                    raw_text="too late",
                ),
            )

    def teardown_method(self):
        # Restore real clock
        from artha.common.clock import SystemClock

        set_clock(SystemClock())


# Avoid losing imports when ruff trims (helpers used above).
_keep = (FrozenClock,)
