"""Pass 19 — persistence + schema registry acceptance tests.

§15.13 (schema registry):
  * Register / lookup (strict + compatible)
  * Validate payload against historical schema
  * Default registry populated on demand
  * Collision protection (replace=False raises)

§10.2 (persistent N0):
  * Round-trip: enqueue → deliver → engagement → state advances
  * Dedupe within window collapses duplicate alerts
  * Watch lifecycle (active_watch → resolved_occurred / did_not_occur)
  * MUST_RESPOND timeout escalates; SHOULD_RESPOND expires silently
  * Engagement log persists chronologically

§8.7 (persistent Librarian):
  * Begin / end session lifecycle
  * Turn log append-only + chronological
  * Running summary built incrementally with budget
  * Pending ambiguities + followups state-machined
  * Reload after end_session preserves state
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ConfigDict

# Import ORM modules so SQLAlchemy registers them on Base.metadata before
# the conftest fixture creates tables.
import artha.channels.orm  # noqa: F401
import artha.m0.librarian_orm  # noqa: F401
from artha.canonical.channels import (
    AlertDeliveryState,
    AlertEngagementType,
    C0ChannelSource,
)
from artha.canonical.monitoring import (
    AlertTier,
    N0Alert,
    N0AlertCategory,
    N0Originator,
    WatchMetadata,
)
from artha.channels.persistence import PersistentNotificationChannel
from artha.common.types import (
    CaseIntent,
    WatchState,
)
from artha.common.ulid import new_ulid
from artha.m0.librarian import TurnInput
from artha.m0.librarian_persistence import PersistentM0Librarian
from artha.registry import (
    DEFAULT_REGISTRY,
    DEFAULT_SCHEMA_VERSION,
    SchemaNotRegisteredError,
    SchemaRegistry,
    SchemaValidationError,
    SchemaVersionFormatError,
    populate_default_registry,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _alert(
    *,
    alert_id: str | None = None,
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
        alert_id=alert_id or new_ulid(),
        originator=N0Originator.M1,
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
# §15.13 — Schema registry
# ===========================================================================


class _ToyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: int


class _ToyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: int
    optional_extra: str | None = None


class TestSchemaRegistry:
    def test_register_and_lookup(self):
        reg = SchemaRegistry()
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)
        assert reg.lookup(name="Toy", version="1.0.0") is _ToyV1

    def test_register_collision_raises(self):
        reg = SchemaRegistry()
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)
        with pytest.raises(SchemaNotRegisteredError):
            reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)

    def test_register_replace_overrides(self):
        reg = SchemaRegistry()
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV2, replace=True)
        assert reg.lookup(name="Toy", version="1.0.0") is _ToyV2

    def test_lookup_missing_raises(self):
        reg = SchemaRegistry()
        with pytest.raises(SchemaNotRegisteredError):
            reg.lookup(name="Toy", version="1.0.0")

    def test_lookup_compatible_falls_back_within_major(self):
        reg = SchemaRegistry()
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)
        reg.register(name="Toy", version="1.2.0", model_cls=_ToyV2)
        # Strict lookup of 1.1.0 misses; compatible returns newest (1.2.0)
        with pytest.raises(SchemaNotRegisteredError):
            reg.lookup(name="Toy", version="1.1.0")
        assert reg.lookup_compatible(name="Toy", version="1.1.0") is _ToyV2

    def test_lookup_compatible_no_major_match_raises(self):
        reg = SchemaRegistry()
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)
        # No registration with major=2 → raises
        with pytest.raises(SchemaNotRegisteredError):
            reg.lookup_compatible(name="Toy", version="2.0.0")

    def test_invalid_semver_raises(self):
        reg = SchemaRegistry()
        with pytest.raises(SchemaVersionFormatError):
            reg.register(name="Toy", version="latest", model_cls=_ToyV1)

    def test_validate_payload_returns_pydantic(self):
        reg = SchemaRegistry()
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)
        instance = reg.validate(
            name="Toy", version="1.0.0", payload={"name": "x", "value": 1}
        )
        assert isinstance(instance, _ToyV1)
        assert instance.value == 1

    def test_validate_payload_invalid_raises(self):
        reg = SchemaRegistry()
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)
        with pytest.raises(SchemaValidationError):
            reg.validate(
                name="Toy", version="1.0.0", payload={"name": "x"}
            )  # missing value

    def test_versions_for_returns_registered_versions(self):
        reg = SchemaRegistry()
        reg.register(name="Toy", version="1.0.0", model_cls=_ToyV1)
        reg.register(name="Toy", version="1.1.0", model_cls=_ToyV2)
        versions = sorted(reg.versions_for("Toy"))
        assert versions == ["1.0.0", "1.1.0"]

    def test_default_registry_populates_canonical_schemas(self):
        reg = SchemaRegistry()
        reg.register_default()
        names = reg.names()
        # Spot-check: T1Event + key canonical objects registered
        for expected in (
            "T1Event",
            "InvestorContextProfile",
            "MandateObject",
            "ModelPortfolioObject",
            "N0Alert",
            "PM1Event",
            "OnboardingResult",
            "ConstructionRun",
            "L4CascadeRun",
            "MandateAmendmentResult",
            "AdvisorPerClientView",
        ):
            assert expected in names
            assert reg.is_registered(name=expected, version=DEFAULT_SCHEMA_VERSION)

    def test_populate_default_registry_idempotent(self):
        # Snapshot original entries (the function is idempotent on subsequent calls)
        from artha.registry.schema_registry import DEFAULT_REGISTRY

        first_count = len(DEFAULT_REGISTRY._entries)
        populate_default_registry()
        second_count = len(DEFAULT_REGISTRY._entries)
        # Either it had been populated already (no-op) or first call populated it
        assert second_count >= first_count
        # Calling again doesn't increase further
        populate_default_registry()
        assert len(DEFAULT_REGISTRY._entries) == second_count

    def test_round_trip_t1_event_via_registry(self):
        from artha.accountability.t1.models import T1Event
        from artha.common.hashing import payload_hash
        from artha.common.standards import T1EventType

        reg = SchemaRegistry()
        reg.register_default()

        payload = {"foo": "bar", "x": 1}
        original = T1Event(
            event_id=new_ulid(),
            event_type=T1EventType.E1_VERDICT,
            timestamp=datetime(2026, 4, 25, tzinfo=UTC),
            firm_id="firm_test",
            payload=payload,
            payload_hash=payload_hash(payload),
        )
        # Round-trip via the registry (simulating replay path)
        cls = reg.lookup(name="T1Event", version=DEFAULT_SCHEMA_VERSION)
        rebuilt = cls.model_validate_json(original.model_dump_json())
        assert rebuilt == original


# ===========================================================================
# §10.2 — Persistent N0 channel
# ===========================================================================


class TestPersistentN0:
    @pytest.mark.asyncio
    async def test_enqueue_and_get_state(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        alert = _alert()
        kept, was_dedup = await n0.enqueue(alert)
        assert not was_dedup
        assert kept.alert_id == alert.alert_id
        assert (await n0.get_state(alert.alert_id)) is AlertDeliveryState.QUEUED

    @pytest.mark.asyncio
    async def test_deliver_advances_state(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        alert = _alert()
        await n0.enqueue(alert)
        new_state = await n0.deliver(alert.alert_id)
        assert new_state is AlertDeliveryState.DELIVERED

    @pytest.mark.asyncio
    async def test_dedupe_within_window(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        first = _alert(
            related_constraint_id="liquidity_floor",
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        second = _alert(
            related_constraint_id="liquidity_floor",
            created_at=datetime(2026, 4, 25, 9, 30, tzinfo=UTC),
        )
        await n0.enqueue(first)
        kept, was_dedup = await n0.enqueue(second)
        assert was_dedup is True
        assert kept.alert_id == first.alert_id
        assert (await n0.get_duplicate_count(first.alert_id)) == 1

    @pytest.mark.asyncio
    async def test_engagement_log_persists_chronologically(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        alert = _alert()
        await n0.enqueue(alert)
        await n0.deliver(alert.alert_id)
        await n0.record_engagement(
            alert.alert_id,
            event_type=AlertEngagementType.OPENED,
            advisor_id="advisor_jane",
        )
        await n0.record_engagement(
            alert.alert_id,
            event_type=AlertEngagementType.DRILLED_DOWN,
            advisor_id="advisor_jane",
        )
        log = await n0.get_engagement_log(alert.alert_id)
        assert len(log) == 2
        assert log[0].event_type is AlertEngagementType.OPENED
        assert log[1].event_type is AlertEngagementType.DRILLED_DOWN

    @pytest.mark.asyncio
    async def test_acknowledged_advances_to_terminal(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        alert = _alert()
        await n0.enqueue(alert)
        await n0.deliver(alert.alert_id)
        new_state = await n0.record_engagement(
            alert.alert_id,
            event_type=AlertEngagementType.ACKNOWLEDGED,
            advisor_id="advisor_jane",
        )
        assert new_state is AlertDeliveryState.ACKNOWLEDGED
        closure = await n0.get_closure(alert.alert_id)
        assert closure is not None
        assert "engagement" in closure.closure_reason

    @pytest.mark.asyncio
    async def test_must_respond_timeout_escalates(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        alert = _alert(
            tier=AlertTier.MUST_RESPOND,
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        await n0.enqueue(alert)
        await n0.deliver(alert.alert_id)
        escalations = await n0.check_timeouts(
            as_of=datetime(2026, 4, 25, 22, 0, tzinfo=UTC)  # 13h later
        )
        assert any(e.alert_id == alert.alert_id for e in escalations)

    @pytest.mark.asyncio
    async def test_should_respond_expires_silently(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        alert = _alert(
            tier=AlertTier.SHOULD_RESPOND,
            related_constraint_id="should_respond_a",
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        await n0.enqueue(alert)
        # Default SHOULD_RESPOND window is 72h; check 73h later
        escalations = await n0.check_timeouts(
            as_of=datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
        )
        assert not any(e.alert_id == alert.alert_id for e in escalations)
        assert (await n0.get_state(alert.alert_id)) is AlertDeliveryState.EXPIRED

    @pytest.mark.asyncio
    async def test_resolve_watch_lifecycle(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        watch = WatchMetadata(
            probability=0.7,
            confidence_band="high",
            resolution_horizon_days=30,
            impact_if_resolved="Reduce equity",
            state=WatchState.ACTIVE_WATCH,
        )
        alert = _alert(
            tier=AlertTier.WATCH,
            category=N0AlertCategory.REGIME_WATCH,
            watch_metadata=watch,
            related_constraint_id=None,
        )
        await n0.enqueue(alert)
        outcome = await n0.resolve_watch(
            alert.alert_id,
            outcome=WatchState.RESOLVED_OCCURRED,
            successor_alert_id="alert_succ_001",
        )
        assert outcome is WatchState.RESOLVED_OCCURRED
        updated = await n0.get_alert(alert.alert_id)
        assert updated.watch_metadata.state is WatchState.RESOLVED_OCCURRED
        closure = await n0.get_closure(alert.alert_id)
        assert closure.successor_alert_id == "alert_succ_001"

    @pytest.mark.asyncio
    async def test_resolve_watch_rejects_non_watch(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        alert = _alert(tier=AlertTier.MUST_RESPOND)
        await n0.enqueue(alert)
        with pytest.raises(ValueError):
            await n0.resolve_watch(
                alert.alert_id, outcome=WatchState.RESOLVED_OCCURRED
            )

    @pytest.mark.asyncio
    async def test_list_active_excludes_terminals(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        a1 = _alert(related_constraint_id="active_1")
        a2 = _alert(related_constraint_id="active_2")
        await n0.enqueue(a1)
        await n0.enqueue(a2)
        await n0.expire(a2.alert_id, reason="manual")
        active = await n0.list_active()
        active_ids = {a.alert_id for a in active}
        assert a1.alert_id in active_ids
        assert a2.alert_id not in active_ids

    @pytest.mark.asyncio
    async def test_round_trip_alert_payload(self, db_session):
        n0 = PersistentNotificationChannel(db_session)
        alert = _alert()
        await n0.enqueue(alert)
        loaded = await n0.get_alert(alert.alert_id)
        assert loaded.alert_id == alert.alert_id
        assert loaded.title == alert.title
        assert loaded.body == alert.body
        assert loaded.tier is AlertTier.MUST_RESPOND

    @pytest.mark.asyncio
    async def test_firm_window_override(self, db_session):
        n0 = PersistentNotificationChannel(
            db_session, must_respond_window=timedelta(hours=4)
        )
        alert = _alert(
            tier=AlertTier.MUST_RESPOND,
            created_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        await n0.enqueue(alert)
        # 5h later — past short window
        escalations = await n0.check_timeouts(
            as_of=datetime(2026, 4, 25, 14, 0, tzinfo=UTC)
        )
        assert any(e.alert_id == alert.alert_id for e in escalations)


# ===========================================================================
# §8.7 — Persistent M0.Librarian
# ===========================================================================


class TestPersistentLibrarian:
    @pytest.mark.asyncio
    async def test_begin_and_get_session(self, db_session):
        lib = PersistentM0Librarian(db_session)
        session = await lib.begin_session(
            advisor_id="advisor_jane",
            firm_id="firm_test",
            client_id="c1",
        )
        loaded = await lib.get_session(session.session_id)
        assert loaded.session_id == session.session_id
        assert loaded.advisor_id == "advisor_jane"
        assert loaded.client_id == "c1"
        assert loaded.ended_at is None

    @pytest.mark.asyncio
    async def test_turn_log_chronological(self, db_session):
        lib = PersistentM0Librarian(db_session)
        session = await lib.begin_session(
            advisor_id="advisor_jane", firm_id="firm_test"
        )
        for i in range(5):
            await lib.update_on_turn(
                session.session_id,
                turn=TurnInput(
                    timestamp=datetime(2026, 4, 25, 9 + i, 0, tzinfo=UTC),
                    channel=C0ChannelSource.UI_CHAT,
                    raw_text=f"turn {i}",
                ),
            )
        recent = await lib.retrieve_recent(session.session_id, n=3)
        assert [t.raw_text for t in recent] == ["turn 2", "turn 3", "turn 4"]

    @pytest.mark.asyncio
    async def test_session_isolation(self, db_session):
        lib = PersistentM0Librarian(db_session)
        s1 = await lib.begin_session(advisor_id="adv1", firm_id="firm_test")
        s2 = await lib.begin_session(advisor_id="adv1", firm_id="firm_test")
        await lib.update_on_turn(
            s1.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="in s1 only",
            ),
        )
        s2_recent = await lib.retrieve_recent(s2.session_id)
        assert s2_recent == []
        s1_recent = await lib.retrieve_recent(s1.session_id)
        assert len(s1_recent) == 1

    @pytest.mark.asyncio
    async def test_running_summary_within_budget(self, db_session):
        lib = PersistentM0Librarian(db_session)
        session = await lib.begin_session(
            advisor_id="adv1",
            firm_id="firm_test",
            summary_token_budget=50,
        )
        for i in range(10):
            await lib.update_on_turn(
                session.session_id,
                turn=TurnInput(
                    timestamp=datetime(2026, 4, 25, 9 + i, 0, tzinfo=UTC),
                    channel=C0ChannelSource.UI_CHAT,
                    raw_text=f"turn {i}",
                    summary_fragment="x" * 100,
                ),
            )
        loaded = await lib.get_session(session.session_id)
        assert len(loaded.running_summary) <= 50 * 4 + 10

    @pytest.mark.asyncio
    async def test_pending_ambiguity_lifecycle(self, db_session):
        lib = PersistentM0Librarian(db_session)
        session = await lib.begin_session(
            advisor_id="adv1", firm_id="firm_test"
        )
        turn = await lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Sharma — Family or Brothers?",
            ),
        )
        amb = await lib.open_pending_ambiguity(
            session.session_id,
            description="Sharma name ambiguous",
            introduced_turn_id=turn.turn_id,
        )
        loaded = await lib.get_session(session.session_id)
        assert len(loaded.pending_ambiguities) == 1
        assert not loaded.pending_ambiguities[0].resolved
        # Resolve
        resolve_turn = await lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 5, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Family.",
            ),
        )
        await lib.resolve_pending_ambiguity(
            session.session_id,
            amb.ambiguity_id,
            resolved_turn_id=resolve_turn.turn_id,
        )
        reloaded = await lib.get_session(session.session_id)
        assert reloaded.pending_ambiguities[0].resolved is True

    @pytest.mark.asyncio
    async def test_pending_followup_unresolved_filter(self, db_session):
        lib = PersistentM0Librarian(db_session)
        session = await lib.begin_session(
            advisor_id="adv1", firm_id="firm_test"
        )
        turn = await lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="Will check AIF cascade",
            ),
        )
        await lib.open_pending_followup(
            session.session_id,
            description="Verify AIF Cat II cascade",
            introduced_turn_id=turn.turn_id,
        )
        unresolved = await lib.unresolved_followups(session.session_id)
        assert len(unresolved) == 1

    @pytest.mark.asyncio
    async def test_end_session_idempotent(self, db_session):
        lib = PersistentM0Librarian(db_session)
        session = await lib.begin_session(
            advisor_id="adv1", firm_id="firm_test"
        )
        first = await lib.end_session(session.session_id)
        first_ended = first.ended_at
        second = await lib.end_session(session.session_id)
        assert second.ended_at == first_ended

    @pytest.mark.asyncio
    async def test_update_on_ended_session_raises(self, db_session):
        lib = PersistentM0Librarian(db_session)
        session = await lib.begin_session(
            advisor_id="adv1", firm_id="firm_test"
        )
        await lib.end_session(session.session_id)
        with pytest.raises(ValueError):
            await lib.update_on_turn(
                session.session_id,
                turn=TurnInput(
                    timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                    channel=C0ChannelSource.UI_CHAT,
                    raw_text="too late",
                ),
            )

    @pytest.mark.asyncio
    async def test_turn_carries_intent_and_confidence(self, db_session):
        lib = PersistentM0Librarian(db_session)
        session = await lib.begin_session(
            advisor_id="adv1", firm_id="firm_test"
        )
        await lib.update_on_turn(
            session.session_id,
            turn=TurnInput(
                timestamp=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
                channel=C0ChannelSource.UI_CHAT,
                raw_text="review",
                parsed_intent=CaseIntent.CASE,
                parsed_intent_confidence=0.92,
                downstream_event_ids=["evt_1"],
            ),
        )
        recent = await lib.retrieve_recent(session.session_id)
        assert recent[0].parsed_intent is CaseIntent.CASE
        assert recent[0].parsed_intent_confidence == pytest.approx(0.92)
        assert recent[0].downstream_event_ids == ["evt_1"]

    @pytest.mark.asyncio
    async def test_unknown_session_raises(self, db_session):
        lib = PersistentM0Librarian(db_session)
        with pytest.raises(KeyError):
            await lib.get_session("not_a_session")


# Sanity reference to silence ruff F401 on the schema_registry import path.
_ = (DEFAULT_REGISTRY,)
