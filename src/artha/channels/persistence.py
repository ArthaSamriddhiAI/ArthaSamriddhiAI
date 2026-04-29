"""§10.2 / §15.13 — persistent N0 notification channel.

`PersistentNotificationChannel` mirrors `NotificationChannel` (Pass 14)
but persists state to SQLAlchemy. The behavioural contract — lifecycle,
dedupe, watch state machine, timeout escalation — is identical; only
the storage layer differs.

Lifecycle invariants (§10.2.4):
  * Alerts only move forward: queued → delivered → acknowledged | expired.
  * `timeout_at` is set at enqueue time from the tier's window.
  * Watch alerts can additionally transition watch_metadata.state to a
    resolved value via `resolve_watch`.

Dedupe (§10.2.6): fingerprint = `(originator, category, client_id,
related_constraint_id)`. A new alert with the same fingerprint inside
the dedupe window is dropped; the existing alert's `duplicate_count` is
incremented.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from artha.channels.canonical_n0 import (
    DEFAULT_DEDUPE_WINDOW,
    DEFAULT_INFORMATIONAL_WINDOW,
    DEFAULT_MUST_RESPOND_WINDOW,
    DEFAULT_SHOULD_RESPOND_WINDOW,
    TimeoutEscalation,
)
from artha.channels.orm import N0AlertRow, N0EngagementRow
from artha.common.clock import get_clock
from artha.common.hashing import payload_hash
from artha.common.types import WatchState
from artha.common.ulid import new_ulid

logger = logging.getLogger(__name__)


class PersistentNotificationChannel:
    """§10.2 — N0 channel backed by SQLAlchemy."""

    agent_id = "n0_channel.persistent"

    def __init__(
        self,
        session: AsyncSession,
        *,
        must_respond_window: timedelta = DEFAULT_MUST_RESPOND_WINDOW,
        should_respond_window: timedelta = DEFAULT_SHOULD_RESPOND_WINDOW,
        informational_window: timedelta = DEFAULT_INFORMATIONAL_WINDOW,
        dedupe_window: timedelta = DEFAULT_DEDUPE_WINDOW,
    ) -> None:
        self._session = session
        self._must_respond_window = must_respond_window
        self._should_respond_window = should_respond_window
        self._informational_window = informational_window
        self._dedupe_window = dedupe_window

    # --------------------- Public API --------------------------------

    async def enqueue(self, alert: N0Alert) -> tuple[N0Alert, bool]:
        """Enqueue an alert. Returns `(kept_alert, was_dedup)`."""
        fingerprint = self._fingerprint(alert)
        existing = await self._find_recent_dedupe_match(
            fingerprint=fingerprint, created_at=alert.created_at
        )
        if existing is not None:
            existing.duplicate_count += 1
            await self._session.flush()
            existing_alert = self._row_to_alert(existing)
            logger.debug(
                "N0 dedupe collapse: new=%s into existing=%s",
                alert.alert_id, existing.alert_id,
            )
            return existing_alert, True

        timeout_at = alert.created_at + self._window_for_tier(alert.tier)
        alert_json = alert.model_dump_json()
        row = N0AlertRow(
            alert_id=alert.alert_id,
            firm_id=alert.firm_id,
            client_id=alert.client_id,
            case_id=alert.case_id,
            originator=alert.originator.value,
            tier=alert.tier.value,
            category=alert.category.value,
            delivery_state=AlertDeliveryState.QUEUED.value,
            created_at=alert.created_at,
            delivered_at=None,
            timeout_at=timeout_at,
            fingerprint=fingerprint,
            duplicate_count=0,
            payload_hash=payload_hash(alert.model_dump(mode="json")),
            alert_json=alert_json,
        )
        self._session.add(row)
        await self._session.flush()
        return alert, False

    async def deliver(self, alert_id: str) -> AlertDeliveryState:
        row = await self._must_get(alert_id)
        if row.delivery_state == AlertDeliveryState.QUEUED.value:
            row.delivery_state = AlertDeliveryState.DELIVERED.value
            row.delivered_at = self._now()
            await self._session.flush()
        return AlertDeliveryState(row.delivery_state)

    async def record_engagement(
        self,
        alert_id: str,
        *,
        event_type: AlertEngagementType,
        advisor_id: str,
        note: str = "",
    ) -> AlertDeliveryState:
        row = await self._must_get(alert_id)
        engagement_row = N0EngagementRow(
            event_id=new_ulid(),
            alert_id=alert_id,
            event_type=event_type.value,
            advisor_id=advisor_id,
            timestamp=self._now(),
            note=note,
        )
        self._session.add(engagement_row)
        if event_type in (
            AlertEngagementType.ACKNOWLEDGED,
            AlertEngagementType.RESPONDED,
        ):
            row.delivery_state = AlertDeliveryState.ACKNOWLEDGED.value
            row.closure_at = self._now()
            row.closure_reason = f"engagement:{event_type.value}"
        await self._session.flush()
        return AlertDeliveryState(row.delivery_state)

    async def expire(
        self, alert_id: str, *, reason: str = "expired"
    ) -> AlertDeliveryState:
        row = await self._must_get(alert_id)
        if row.delivery_state == AlertDeliveryState.ACKNOWLEDGED.value:
            return AlertDeliveryState.ACKNOWLEDGED
        row.delivery_state = AlertDeliveryState.EXPIRED.value
        row.closure_at = self._now()
        row.closure_reason = reason
        await self._session.flush()
        return AlertDeliveryState.EXPIRED

    async def check_timeouts(
        self, *, as_of: datetime | None = None
    ) -> list[TimeoutEscalation]:
        as_of = as_of or self._now()
        stmt = select(N0AlertRow).where(
            N0AlertRow.delivery_state.in_(
                [
                    AlertDeliveryState.QUEUED.value,
                    AlertDeliveryState.DELIVERED.value,
                ]
            )
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())

        escalations: list[TimeoutEscalation] = []
        for row in rows:
            timeout_at = self._normalise_dt(row.timeout_at)
            if timeout_at is None or as_of < timeout_at:
                continue
            if row.tier == AlertTier.MUST_RESPOND.value:
                # Need to know if any acknowledging engagement happened
                ack_stmt = select(N0EngagementRow).where(
                    N0EngagementRow.alert_id == row.alert_id,
                    N0EngagementRow.event_type.in_(
                        [
                            AlertEngagementType.ACKNOWLEDGED.value,
                            AlertEngagementType.RESPONDED.value,
                        ]
                    ),
                )
                ack_result = await self._session.execute(ack_stmt)
                if ack_result.scalars().first() is None:
                    escalations.append(
                        TimeoutEscalation(
                            alert_id=row.alert_id,
                            advisor_id=None,
                            originator=N0Originator(row.originator),
                            title=self._row_to_alert(row).title,
                            timeout_at=timeout_at,
                        )
                    )
                    continue

            # Non-MUST_RESPOND past window → expire silently.
            row.delivery_state = AlertDeliveryState.EXPIRED.value
            row.closure_at = as_of
            row.closure_reason = "window_expired"

        await self._session.flush()
        return escalations

    async def resolve_watch(
        self,
        alert_id: str,
        *,
        outcome: WatchState,
        successor_alert_id: str | None = None,
    ) -> WatchState:
        row = await self._must_get(alert_id)
        if row.tier != AlertTier.WATCH.value:
            raise ValueError(
                f"resolve_watch called on non-watch alert {alert_id} "
                f"(tier={row.tier})"
            )
        if outcome not in (
            WatchState.RESOLVED_OCCURRED,
            WatchState.RESOLVED_DID_NOT_OCCUR,
        ):
            raise ValueError(
                f"watch outcome must be a resolved state, got {outcome.value}"
            )

        alert = self._row_to_alert(row)
        existing_meta = alert.watch_metadata
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
        new_alert = alert.model_copy(update={"watch_metadata": new_meta})

        row.alert_json = new_alert.model_dump_json()
        row.payload_hash = payload_hash(new_alert.model_dump(mode="json"))
        row.delivery_state = AlertDeliveryState.ACKNOWLEDGED.value
        row.closure_at = self._now()
        row.closure_reason = f"watch:{outcome.value}"
        row.successor_alert_id = successor_alert_id
        await self._session.flush()
        return outcome

    # --------------------- Inspection ----------------------------------

    async def get_state(self, alert_id: str) -> AlertDeliveryState:
        row = await self._must_get(alert_id)
        return AlertDeliveryState(row.delivery_state)

    async def get_alert(self, alert_id: str) -> N0Alert:
        row = await self._must_get(alert_id)
        return self._row_to_alert(row)

    async def get_engagement_log(
        self, alert_id: str
    ) -> list[AlertEngagementEvent]:
        await self._must_get(alert_id)  # raises if missing
        stmt = (
            select(N0EngagementRow)
            .where(N0EngagementRow.alert_id == alert_id)
            .order_by(N0EngagementRow.timestamp, N0EngagementRow.event_id)
        )
        result = await self._session.execute(stmt)
        return [
            AlertEngagementEvent(
                event_type=AlertEngagementType(r.event_type),
                timestamp=self._normalise_dt(r.timestamp) or r.timestamp,
                advisor_id=r.advisor_id,
                note=r.note,
            )
            for r in result.scalars().all()
        ]

    async def get_closure(self, alert_id: str) -> AlertClosureMetadata | None:
        row = await self._must_get(alert_id)
        if row.closure_at is None or row.closure_reason is None:
            return None
        closure_at = self._normalise_dt(row.closure_at) or row.closure_at
        return AlertClosureMetadata(
            closure_at=closure_at,
            closure_reason=row.closure_reason,
            successor_alert_id=row.successor_alert_id,
        )

    async def get_duplicate_count(self, alert_id: str) -> int:
        row = await self._must_get(alert_id)
        return row.duplicate_count

    async def list_active(self) -> list[N0Alert]:
        stmt = select(N0AlertRow).where(
            N0AlertRow.delivery_state.in_(
                [
                    AlertDeliveryState.QUEUED.value,
                    AlertDeliveryState.DELIVERED.value,
                ]
            )
        )
        result = await self._session.execute(stmt)
        return [self._row_to_alert(r) for r in result.scalars().all()]

    # --------------------- Helpers ----------------------------------

    def _window_for_tier(self, tier: AlertTier) -> timedelta:
        if tier is AlertTier.MUST_RESPOND:
            return self._must_respond_window
        if tier is AlertTier.SHOULD_RESPOND:
            return self._should_respond_window
        if tier is AlertTier.WATCH:
            return timedelta(days=365)
        return self._informational_window

    def _fingerprint(self, alert: N0Alert) -> str:
        return "|".join(
            [
                alert.originator.value,
                alert.category.value,
                alert.client_id,
                alert.related_constraint_id or "",
            ]
        )

    async def _find_recent_dedupe_match(
        self,
        *,
        fingerprint: str,
        created_at: datetime,
    ) -> N0AlertRow | None:
        cutoff_low = created_at - self._dedupe_window
        cutoff_high = created_at + self._dedupe_window
        stmt = (
            select(N0AlertRow)
            .where(
                N0AlertRow.fingerprint == fingerprint,
                N0AlertRow.delivery_state.in_(
                    [
                        AlertDeliveryState.QUEUED.value,
                        AlertDeliveryState.DELIVERED.value,
                    ]
                ),
                N0AlertRow.created_at >= cutoff_low,
                N0AlertRow.created_at <= cutoff_high,
            )
            .order_by(desc(N0AlertRow.created_at))
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def _must_get(self, alert_id: str) -> N0AlertRow:
        row = await self._session.get(N0AlertRow, alert_id)
        if row is None:
            raise KeyError(f"unknown alert_id={alert_id}")
        return row

    def _row_to_alert(self, row: N0AlertRow) -> N0Alert:
        return N0Alert.model_validate_json(row.alert_json)

    def _normalise_dt(self, value: datetime | None) -> datetime | None:
        """Reattach UTC tzinfo on SQLite reads (mirrors T1 repo behaviour)."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = ["PersistentNotificationChannel"]
