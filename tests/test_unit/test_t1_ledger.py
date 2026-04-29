"""Pass 1 T1 ledger tests — canonical T1Event, repository, TraceNode adapter.

Covers:
  * T1Event construction via build() with auto-computed payload_hash
  * T1Event field validators (ULID shape, hash shape)
  * T1Event frozen / append-only at the model level
  * T1Repository.append + get + list_for_case + list_for_client
  * T1AppendError on event_id collision
  * Correction chain via correction_of
  * TraceNode → T1Event adapter (information-preserving projection)
  * Replay invariant: persist + reload yields identical T1Event
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

# Importing the package registers T1EventRow with Base.metadata so that
# conftest's db_session fixture can create the table on the in-memory SQLite.
from artha.accountability.t1 import (
    T1AppendError,
    T1Event,
    T1Repository,
    t1_event_from_trace_node,
)
from artha.accountability.trace.models import TraceNode, TraceNodeType
from artha.common.hashing import payload_hash
from artha.common.standards import T1EventType
from artha.common.types import VersionPins
from artha.common.ulid import new_ulid

# ===========================================================================
# T1Event model
# ===========================================================================


class TestT1EventModel:
    def test_build_computes_payload_hash(self):
        ts = datetime(2026, 4, 25, 14, 30, tzinfo=UTC)
        event = T1Event.build(
            event_type=T1EventType.E1_VERDICT,
            firm_id="firm_01",
            timestamp=ts,
            payload={"risk_level": "MEDIUM", "confidence": 0.78},
            case_id="case_abc",
            client_id="client_xyz",
        )
        assert event.payload_hash == payload_hash({"risk_level": "MEDIUM", "confidence": 0.78})
        assert event.verify_payload_integrity() is True

    def test_build_generates_ulid(self):
        event = T1Event.build(
            event_type=T1EventType.ROUTER_CLASSIFICATION,
            firm_id="firm_01",
            timestamp=datetime.now(UTC),
        )
        assert len(event.event_id) == 26

    def test_rejects_invalid_event_id(self):
        with pytest.raises(ValidationError, match="ULID"):
            T1Event(
                event_id="not-a-ulid",
                event_type=T1EventType.E1_VERDICT,
                timestamp=datetime.now(UTC),
                firm_id="firm_01",
                payload={},
                payload_hash="0" * 64,
            )

    def test_rejects_invalid_payload_hash(self):
        with pytest.raises(ValidationError, match="payload_hash"):
            T1Event(
                event_id=new_ulid(),
                event_type=T1EventType.E1_VERDICT,
                timestamp=datetime.now(UTC),
                firm_id="firm_01",
                payload={},
                payload_hash="too-short",
            )

    def test_rejects_invalid_correction_of(self):
        with pytest.raises(ValidationError, match="correction_of"):
            T1Event(
                event_id=new_ulid(),
                event_type=T1EventType.E1_VERDICT,
                timestamp=datetime.now(UTC),
                firm_id="firm_01",
                payload={},
                payload_hash="0" * 64,
                correction_of="bad",
            )

    def test_frozen_model(self):
        event = T1Event.build(
            event_type=T1EventType.E1_VERDICT,
            firm_id="firm_01",
            timestamp=datetime.now(UTC),
        )
        with pytest.raises(ValidationError):
            event.payload = {"hacked": True}  # type: ignore[misc]

    def test_extra_fields_rejected(self):
        # Section 15.13 / extra="forbid" — schema discipline
        with pytest.raises(ValidationError):
            T1Event(
                event_id=new_ulid(),
                event_type=T1EventType.E1_VERDICT,
                timestamp=datetime.now(UTC),
                firm_id="firm_01",
                payload={},
                payload_hash="0" * 64,
                made_up_field="x",  # type: ignore[call-arg]
            )

    def test_tamper_detection_via_payload_hash(self):
        event = T1Event.build(
            event_type=T1EventType.G1_EVALUATION,
            firm_id="firm_01",
            timestamp=datetime.now(UTC),
            payload={"status": "APPROVED"},
        )
        # If we craft an event with a mismatched hash, integrity check fails.
        tampered = T1Event(
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            firm_id=event.firm_id,
            payload={"status": "BLOCKED"},  # changed
            payload_hash=event.payload_hash,  # but hash from old payload
            version_pins=event.version_pins,
        )
        assert tampered.verify_payload_integrity() is False


# ===========================================================================
# T1Repository — append / read
# ===========================================================================


@pytest.mark.asyncio
async def test_append_and_get(db_session):
    repo = T1Repository(db_session)
    event = T1Event.build(
        event_type=T1EventType.S1_SYNTHESIS,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 25, 14, 30, tzinfo=UTC),
        payload={"recommendation": "modify", "consensus_risk": "MEDIUM"},
        case_id="case_001",
        client_id="client_42",
    )
    await repo.append(event)
    fetched = await repo.get(event.event_id)
    assert fetched == event


@pytest.mark.asyncio
async def test_append_collision_raises(db_session):
    repo = T1Repository(db_session)
    fixed_id = new_ulid()
    event_a = T1Event.build(
        event_type=T1EventType.E1_VERDICT,
        firm_id="firm_01",
        timestamp=datetime.now(UTC),
        payload={"a": 1},
        event_id=fixed_id,
    )
    await repo.append(event_a)

    event_b = T1Event.build(
        event_type=T1EventType.E2_VERDICT,
        firm_id="firm_01",
        timestamp=datetime.now(UTC),
        payload={"b": 2},
        event_id=fixed_id,  # same event_id — must fail
    )
    with pytest.raises(T1AppendError, match="collision"):
        await repo.append(event_b)


@pytest.mark.asyncio
async def test_list_for_case_chronological(db_session):
    repo = T1Repository(db_session)
    case = "case_xyz"

    e1 = T1Event.build(
        event_type=T1EventType.ROUTER_CLASSIFICATION,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 25, 14, 30, tzinfo=UTC),
        case_id=case,
    )
    e2 = T1Event.build(
        event_type=T1EventType.E1_VERDICT,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 25, 14, 31, tzinfo=UTC),
        case_id=case,
    )
    e3 = T1Event.build(
        event_type=T1EventType.S1_SYNTHESIS,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 25, 14, 32, tzinfo=UTC),
        case_id=case,
    )

    # Append out of order — repository must return in timestamp order.
    await repo.append(e2)
    await repo.append(e3)
    await repo.append(e1)

    events = await repo.list_for_case(case)
    assert [e.event_type for e in events] == [
        T1EventType.ROUTER_CLASSIFICATION,
        T1EventType.E1_VERDICT,
        T1EventType.S1_SYNTHESIS,
    ]


@pytest.mark.asyncio
async def test_list_for_client_isolation(db_session):
    repo = T1Repository(db_session)
    e_a = T1Event.build(
        event_type=T1EventType.E1_VERDICT,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        client_id="client_a",
    )
    e_b = T1Event.build(
        event_type=T1EventType.E1_VERDICT,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        client_id="client_b",
    )
    await repo.append(e_a)
    await repo.append(e_b)

    list_a = await repo.list_for_client("client_a")
    assert len(list_a) == 1
    assert list_a[0].client_id == "client_a"


@pytest.mark.asyncio
async def test_correction_chain(db_session):
    repo = T1Repository(db_session)
    original = T1Event.build(
        event_type=T1EventType.G1_EVALUATION,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 25, tzinfo=UTC),
        payload={"status": "APPROVED"},
        case_id="case_a",
    )
    await repo.append(original)

    # Correction: same case, references original
    correction = T1Event.build(
        event_type=T1EventType.G1_EVALUATION,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 26, tzinfo=UTC),
        payload={"status": "BLOCKED", "reason": "later finding overrode"},
        case_id="case_a",
        correction_of=original.event_id,
    )
    await repo.append(correction)

    corrections = await repo.list_corrections_of(original.event_id)
    assert len(corrections) == 1
    assert corrections[0].correction_of == original.event_id


@pytest.mark.asyncio
async def test_replay_invariant_round_trip(db_session):
    """Persist a T1Event and reload it; the result must be byte-identical (replay invariant)."""
    repo = T1Repository(db_session)
    event = T1Event.build(
        event_type=T1EventType.E6_GATE,
        firm_id="firm_01",
        timestamp=datetime(2026, 4, 25, 14, 30, tzinfo=UTC),
        payload={
            "gate_result": "SOFT_BLOCK",
            "reasons": ["capacity_trajectory_declining_moderate"],
        },
        case_id="case_xyz",
        client_id="client_42",
        version_pins=VersionPins(
            model_portfolio_version="3.4.0",
            mandate_version="2026.04.1",
            agent_version="0.1.0",
        ),
    )
    await repo.append(event)
    reloaded = await repo.get(event.event_id)
    assert reloaded == event
    assert reloaded is not None
    assert reloaded.verify_payload_integrity() is True


# ===========================================================================
# TraceNode adapter
# ===========================================================================


class TestTraceNodeAdapter:
    def test_intent_received_maps_to_router_classification(self):
        node = TraceNode(
            id="node_1",
            decision_id="case_a",
            node_type=TraceNodeType.INTENT_RECEIVED,
            data={"intent": "rebalance"},
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
        )
        event = t1_event_from_trace_node(node, firm_id="firm_01")
        assert event.event_type is T1EventType.ROUTER_CLASSIFICATION
        assert event.case_id == "case_a"

    def test_agent_output_uses_agent_name(self):
        node = TraceNode(
            id="node_1",
            decision_id="case_a",
            node_type=TraceNodeType.AGENT_OUTPUT,
            data={"agent_name": "financial_risk", "risk_level": "MEDIUM"},
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
        )
        event = t1_event_from_trace_node(node, firm_id="firm_01")
        assert event.event_type is T1EventType.E1_VERDICT

    def test_agent_output_unknown_agent_falls_back(self):
        node = TraceNode(
            id="node_1",
            decision_id="case_a",
            node_type=TraceNodeType.AGENT_OUTPUT,
            data={"agent_name": "unknown_agent_42"},
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
        )
        event = t1_event_from_trace_node(node, firm_id="firm_01")
        # Falls back to S1_SYNTHESIS as the safest non-evidence-specific bucket.
        assert event.event_type is T1EventType.S1_SYNTHESIS

    def test_error_maps_to_ex1(self):
        node = TraceNode(
            id="node_1",
            decision_id="case_a",
            node_type=TraceNodeType.ERROR,
            data={"error": "agent timeout"},
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
        )
        event = t1_event_from_trace_node(node, firm_id="firm_01")
        assert event.event_type is T1EventType.EX1_EVENT

    def test_information_preserving_projection(self):
        node = TraceNode(
            id="node_42",
            decision_id="case_a",
            node_type=TraceNodeType.RULE_EVALUATED,
            parent_node_ids=["parent_1", "parent_2"],
            data={"rule_id": "g1_max_equity", "passed": False, "actual": 0.72, "limit": 0.65},
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
        )
        event = t1_event_from_trace_node(node, firm_id="firm_01")
        # Original id, parent_ids, full data, and node_type all preserved in payload
        assert event.payload["legacy_node_id"] == "node_42"
        assert event.payload["legacy_node_type"] == "rule_evaluated"
        assert event.payload["legacy_parent_node_ids"] == ["parent_1", "parent_2"]
        assert event.payload["data"] == {
            "rule_id": "g1_max_equity",
            "passed": False,
            "actual": 0.72,
            "limit": 0.65,
        }

    def test_adapter_assigns_fresh_ulid(self):
        # The new T1Event must have its own ULID, not the legacy id
        node = TraceNode(
            id="legacy_id_not_a_ulid",
            decision_id="case_a",
            node_type=TraceNodeType.INTENT_RECEIVED,
            data={},
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
        )
        event = t1_event_from_trace_node(node, firm_id="firm_01")
        assert len(event.event_id) == 26
        assert event.event_id != "legacy_id_not_a_ulid"

    def test_adapter_carries_optional_scope(self):
        node = TraceNode(
            id="n",
            decision_id="case_a",
            node_type=TraceNodeType.INTENT_RECEIVED,
            data={},
            created_at=datetime(2026, 4, 25, tzinfo=UTC),
        )
        event = t1_event_from_trace_node(
            node,
            firm_id="firm_01",
            client_id="client_42",
            advisor_id="advisor_jane",
            version_pins=VersionPins(agent_version="0.2.1"),
        )
        assert event.client_id == "client_42"
        assert event.advisor_id == "advisor_jane"
        assert event.version_pins.agent_version == "0.2.1"
