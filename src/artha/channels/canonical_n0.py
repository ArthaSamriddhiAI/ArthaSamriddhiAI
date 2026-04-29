"""§10.2 — N0 Notification Channel (deterministic mechanics).

N0 carries alerts from originators (PM1, M1, M0, E3, IC1, EX1) to advisors.
Per §10.2.6 N0 generates no content — originators do. N0 owns:

  * Lifecycle: queued → delivered → acknowledged | expired (§10.2.4).
  * Watch state machine: ACTIVE_WATCH → RESOLVED_OCCURRED | RESOLVED_DID_NOT_OCCUR (§10.2.3).
  * Dedupe: collapse alerts with the same `(originator, related_constraint_id, client_id)`
    fingerprint within a configurable window.
  * Engagement tracking: opened / dismissed / drilled_down / responded.
  * Timeout escalation: when a MUST_RESPOND alert ages past its window without
    engagement, surface a follow-up event (the orchestrator wires this to EX1).

All operations are deterministic. The channel mutates an in-memory store
exposed via `NotificationChannelState`; production wires this to a durable
queue (Redis / Postgres). Pass 14 ships the in-memory implementation that
tests + the orchestrator both consume.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from artha.canonical.channels import (
    AlertClosureMetadata,
    AlertDeliveryState,
    AlertEngagementEvent,
    AlertEngagementType,
)
from artha.canonical.monitoring import (
    AlertTier,
    N0Alert,
    N0Originator,
    WatchMetadata,
)
from artha.common.clock import get_clock
from artha.common.types import WatchState

logger = logging.getLogger(__name__)


# Default windows per §10.2.4. Firm-overridable.
DEFAULT_MUST_RESPOND_WINDOW = timedelta(hours=12)
DEFAULT_SHOULD_RESPOND_WINDOW = timedelta(hours=72)
DEFAULT_INFORMATIONAL_WINDOW = timedelta(days=30)
DEFAULT_DEDUPE_WINDOW = timedelta(hours=1)


@dataclass
class _AlertRecord:
    """Internal per-alert state."""

    alert: N0Alert
    delivery_state: AlertDeliveryState = AlertDeliveryState.QUEUED
    engagement_log: list[AlertEngagementEvent] = field(default_factory=list)
    closure_metadata: AlertClosureMetadata | None = None
    delivered_at: datetime | None = None
    timeout_at: datetime | None = None
    duplicate_count: int = 0


@dataclass
class TimeoutEscalation:
    """Returned by `check_timeouts` for the orchestrator to feed into EX1."""

    alert_id: str
    advisor_id: str | None
    originator: N0Originator
    title: str
    timeout_at: datetime


class NotificationChannel:
    """§10.2 deterministic notification channel.

    Construction:
      * `must_respond_window` / `should_respond_window` — firm-overridable.
      * `dedupe_window` — alerts with same fingerprint within this window collapse.
    """

    agent_id = "n0_channel"

    def __init__(
        self,
        *,
        must_respond_window: timedelta = DEFAULT_MUST_RESPOND_WINDOW,
        should_respond_window: timedelta = DEFAULT_SHOULD_RESPOND_WINDOW,
        informational_window: timedelta = DEFAULT_INFORMATIONAL_WINDOW,
        dedupe_window: timedelta = DEFAULT_DEDUPE_WINDOW,
    ) -> None:
        self._must_respond_window = must_respond_window
        self._should_respond_window = should_respond_window
        self._informational_window = informational_window
        self._dedupe_window = dedupe_window
        self._records: dict[str, _AlertRecord] = {}
        # Index for dedupe fingerprint → list of recent alert_ids
        self._fingerprint_index: dict[str, list[str]] = {}

    # --------------------- Public API --------------------------------

    def enqueue(self, alert: N0Alert) -> tuple[N0Alert, bool]:
        """Enqueue a new alert. Returns the (kept_alert, was_dedup) pair.

        When a dedupe match is found, the new alert is dropped and the
        existing alert's `duplicate_count` is incremented. The returned
        alert is the existing one in that case.
        """
        # ----- Dedupe -----
        fingerprint = self._fingerprint(alert)
        existing_id = self._find_recent_dedupe_match(fingerprint, alert.created_at)
        if existing_id is not None:
            self._records[existing_id].duplicate_count += 1
            logger.debug(
                "N0 dedupe collapse: new=%s into existing=%s",
                alert.alert_id, existing_id,
            )
            return self._records[existing_id].alert, True

        # ----- Compute timeout -----
        timeout_at = alert.created_at + self._window_for_tier(alert.tier)

        record = _AlertRecord(
            alert=alert,
            delivery_state=AlertDeliveryState.QUEUED,
            timeout_at=timeout_at,
        )
        self._records[alert.alert_id] = record
        self._fingerprint_index.setdefault(fingerprint, []).append(alert.alert_id)
        return alert, False

    def deliver(self, alert_id: str) -> AlertDeliveryState:
        """Mark an alert delivered. Returns the new state."""
        record = self._must_get(alert_id)
        if record.delivery_state is AlertDeliveryState.QUEUED:
            record.delivery_state = AlertDeliveryState.DELIVERED
            record.delivered_at = get_clock().now()
        return record.delivery_state

    def record_engagement(
        self,
        alert_id: str,
        *,
        event_type: AlertEngagementType,
        advisor_id: str,
        note: str = "",
    ) -> AlertDeliveryState:
        """Append an engagement event. Acknowledged → state advances."""
        record = self._must_get(alert_id)
        record.engagement_log.append(
            AlertEngagementEvent(
                event_type=event_type,
                timestamp=get_clock().now(),
                advisor_id=advisor_id,
                note=note,
            )
        )
        if event_type in (
            AlertEngagementType.ACKNOWLEDGED,
            AlertEngagementType.RESPONDED,
        ):
            record.delivery_state = AlertDeliveryState.ACKNOWLEDGED
            record.closure_metadata = AlertClosureMetadata(
                closure_at=get_clock().now(),
                closure_reason=f"engagement:{event_type.value}",
            )
        return record.delivery_state

    def expire(self, alert_id: str, *, reason: str = "expired") -> AlertDeliveryState:
        """Mark an alert expired (called by `check_timeouts` or manually)."""
        record = self._must_get(alert_id)
        if record.delivery_state is AlertDeliveryState.ACKNOWLEDGED:
            return record.delivery_state  # already closed
        record.delivery_state = AlertDeliveryState.EXPIRED
        record.closure_metadata = AlertClosureMetadata(
            closure_at=get_clock().now(),
            closure_reason=reason,
        )
        return record.delivery_state

    def check_timeouts(
        self, *, as_of: datetime | None = None
    ) -> list[TimeoutEscalation]:
        """Return MUST_RESPOND alerts that have aged past their window without ACK.

        The caller (orchestrator) feeds the returned list into EX1 to escalate.
        Alerts that pass their window for non-MUST_RESPOND tiers are simply
        marked `EXPIRED` here and not returned.
        """
        as_of = as_of or get_clock().now()
        escalations: list[TimeoutEscalation] = []
        for record in list(self._records.values()):
            if record.delivery_state in (
                AlertDeliveryState.ACKNOWLEDGED,
                AlertDeliveryState.EXPIRED,
            ):
                continue
            if record.timeout_at is None:
                continue
            if as_of < record.timeout_at:
                continue

            if record.alert.tier is AlertTier.MUST_RESPOND:
                # No engagement within window → escalation candidate.
                if not any(
                    e.event_type
                    in (
                        AlertEngagementType.ACKNOWLEDGED,
                        AlertEngagementType.RESPONDED,
                    )
                    for e in record.engagement_log
                ):
                    escalations.append(
                        TimeoutEscalation(
                            alert_id=record.alert.alert_id,
                            advisor_id=self._advisor_for_alert(record.alert),
                            originator=record.alert.originator,
                            title=record.alert.title,
                            timeout_at=record.timeout_at,
                        )
                    )
                    continue  # leave delivery_state in place; caller decides next state

            # Non-MUST_RESPOND past window → expire silently.
            record.delivery_state = AlertDeliveryState.EXPIRED
            record.closure_metadata = AlertClosureMetadata(
                closure_at=as_of,
                closure_reason="window_expired",
            )
        return escalations

    def resolve_watch(
        self,
        alert_id: str,
        *,
        outcome: WatchState,
        successor_alert_id: str | None = None,
    ) -> WatchState:
        """Transition a WATCH alert to its terminal state.

        `outcome` must be `RESOLVED_OCCURRED` or `RESOLVED_DID_NOT_OCCUR`.
        Pass 14 records the resolution; the originator emits any successor
        alert (which is enqueued separately).
        """
        record = self._must_get(alert_id)
        if record.alert.tier is not AlertTier.WATCH:
            raise ValueError(
                f"resolve_watch called on non-watch alert "
                f"{alert_id} (tier={record.alert.tier.value})"
            )
        if outcome not in (
            WatchState.RESOLVED_OCCURRED,
            WatchState.RESOLVED_DID_NOT_OCCUR,
        ):
            raise ValueError(
                f"watch outcome must be a resolved state, got {outcome.value}"
            )

        # Update watch_metadata.state by reconstructing the alert (frozen Pydantic).
        existing_meta = record.alert.watch_metadata
        if existing_meta is not None:
            new_meta = existing_meta.model_copy(update={"state": outcome})
        else:
            new_meta = WatchMetadata(
                probability=0.0,
                confidence_band="unspecified",
                resolution_horizon_days=0,
                impact_if_resolved="",
                state=outcome,
            )
        record.alert = record.alert.model_copy(update={"watch_metadata": new_meta})
        record.delivery_state = AlertDeliveryState.ACKNOWLEDGED
        record.closure_metadata = AlertClosureMetadata(
            closure_at=get_clock().now(),
            closure_reason=f"watch:{outcome.value}",
            successor_alert_id=successor_alert_id,
        )
        return outcome

    # --------------------- Inspection ----------------------------------

    def get_state(self, alert_id: str) -> AlertDeliveryState:
        return self._must_get(alert_id).delivery_state

    def get_alert(self, alert_id: str) -> N0Alert:
        return self._must_get(alert_id).alert

    def get_engagement_log(self, alert_id: str) -> list[AlertEngagementEvent]:
        return list(self._must_get(alert_id).engagement_log)

    def get_closure(self, alert_id: str) -> AlertClosureMetadata | None:
        return self._must_get(alert_id).closure_metadata

    def get_duplicate_count(self, alert_id: str) -> int:
        return self._must_get(alert_id).duplicate_count

    def list_active(self) -> list[N0Alert]:
        return [
            r.alert
            for r in self._records.values()
            if r.delivery_state
            not in (AlertDeliveryState.ACKNOWLEDGED, AlertDeliveryState.EXPIRED)
        ]

    # --------------------- Helpers ----------------------------------

    def _window_for_tier(self, tier: AlertTier) -> timedelta:
        if tier is AlertTier.MUST_RESPOND:
            return self._must_respond_window
        if tier is AlertTier.SHOULD_RESPOND:
            return self._should_respond_window
        if tier is AlertTier.WATCH:
            # Watch-tier window is governed by `resolution_horizon_days` on the
            # watch_metadata; default a long window so the watch is open until
            # the originator resolves it.
            return timedelta(days=365)
        return self._informational_window

    def _fingerprint(self, alert: N0Alert) -> str:
        """Dedupe key: (originator, category, client_id, related_constraint_id)."""
        return "|".join(
            [
                alert.originator.value,
                alert.category.value,
                alert.client_id,
                alert.related_constraint_id or "",
            ]
        )

    def _find_recent_dedupe_match(
        self, fingerprint: str, created_at: datetime
    ) -> str | None:
        for existing_id in reversed(self._fingerprint_index.get(fingerprint, [])):
            existing_record = self._records.get(existing_id)
            if existing_record is None:
                continue
            if existing_record.delivery_state in (
                AlertDeliveryState.ACKNOWLEDGED,
                AlertDeliveryState.EXPIRED,
            ):
                continue
            if abs(
                (created_at - existing_record.alert.created_at).total_seconds()
            ) <= self._dedupe_window.total_seconds():
                return existing_id
        return None

    def _advisor_for_alert(self, alert: N0Alert) -> str | None:
        """Best-effort: route MUST_RESPOND escalations to the advisor on the alert.

        Pass 14 carries no advisor_id on N0Alert; production wires this via a
        firm directory. We surface None so the orchestrator can resolve.
        """
        return None

    def _must_get(self, alert_id: str) -> _AlertRecord:
        if alert_id not in self._records:
            raise KeyError(f"unknown alert_id={alert_id}")
        return self._records[alert_id]

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "DEFAULT_DEDUPE_WINDOW",
    "DEFAULT_INFORMATIONAL_WINDOW",
    "DEFAULT_MUST_RESPOND_WINDOW",
    "DEFAULT_SHOULD_RESPOND_WINDOW",
    "NotificationChannel",
    "TimeoutEscalation",
]
