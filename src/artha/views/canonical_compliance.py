"""§14.4 — Compliance view composer.

Two core views in Pass 18:

  * `ComplianceCaseReasoningTrail` (§14.4.1) — chronological T1 events
    for a single case with one summary line per event + payload-hash
    pointers (audit can replay deeper via the T1 event_id).
  * `ComplianceOverrideHistoryView` (§14.4.2) — firm-wide override events
    over a window, with rationale excerpt + structured category +
    compliance-review queue flag.

Pure deterministic. Reads `T1Event` + override metadata. Compliance is
read-only (write attempts denied at `assert_can_write`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from artha.canonical.views import (
    ComplianceCaseReasoningTrail,
    ComplianceOverrideHistoryView,
    OverrideHistoryRow,
    ReasoningTrailEntry,
    Role,
    ViewerContext,
)
from artha.common.standards import T1EventType
from artha.views.canonical_permissions import (
    PermissionDeniedError,
    assert_can_read_client,
    assert_can_read_firm,
)

_EVENT_SUMMARY_CHARS = 300
_RATIONALE_PREVIEW_CHARS = 400


class ComplianceViewComposer:
    """§14.4 compliance surface composer."""

    composer_id = "view.compliance"

    def __init__(self, *, agent_version: str = "0.1.0") -> None:
        self._agent_version = agent_version

    # --------------------- §14.4.1 --------------------------------

    def case_reasoning_trail(
        self,
        *,
        viewer: ViewerContext,
        case_id: str,
        client_id: str,
        firm_id: str,
        events: list[Any],  # T1Event
    ) -> ComplianceCaseReasoningTrail:
        if viewer.role is not Role.COMPLIANCE:
            raise PermissionDeniedError(
                f"case_reasoning_trail is compliance-scoped; "
                f"got {viewer.role.value!r}"
            )
        assert_can_read_client(viewer, client_id=client_id, client_firm_id=firm_id)

        scoped_events = [e for e in events if getattr(e, "case_id", None) == case_id]
        scoped_events.sort(key=lambda e: e.timestamp)

        entries: list[ReasoningTrailEntry] = []
        decision_event_id: str | None = None
        override_event_ids: list[str] = []
        for evt in scoped_events:
            entry = ReasoningTrailEntry(
                timestamp=evt.timestamp,
                event_type=evt.event_type.value,
                agent_id=self._extract_agent_id(evt),
                summary=self._event_summary(evt),
                payload_hash=evt.payload_hash,
                event_id=evt.event_id,
            )
            entries.append(entry)
            if evt.event_type is T1EventType.DECISION:
                decision_event_id = evt.event_id
            if evt.event_type is T1EventType.OVERRIDE:
                override_event_ids.append(evt.event_id)

        return ComplianceCaseReasoningTrail(
            viewer_user_id=viewer.user_id,
            firm_id=firm_id,
            case_id=case_id,
            client_id=client_id,
            entries=entries,
            decision_event_id=decision_event_id,
            override_event_ids=override_event_ids,
            replay_available=True,
        )

    # --------------------- §14.4.2 --------------------------------

    def override_history(
        self,
        *,
        viewer: ViewerContext,
        firm_id: str,
        period_start: datetime,
        period_end: datetime,
        override_events: list[Any],  # T1Event with event_type=OVERRIDE
    ) -> ComplianceOverrideHistoryView:
        if viewer.role is not Role.COMPLIANCE:
            raise PermissionDeniedError(
                f"override_history is compliance-scoped; "
                f"got {viewer.role.value!r}"
            )
        assert_can_read_firm(viewer, firm_id=firm_id)

        rows: list[OverrideHistoryRow] = []
        review_queue = 0
        for evt in override_events:
            if evt.event_type is not T1EventType.OVERRIDE:
                continue
            if not (period_start <= evt.timestamp <= period_end):
                continue
            if getattr(evt, "firm_id", None) != firm_id:
                continue
            payload = evt.payload or {}
            rationale = str(payload.get("rationale_text", ""))[:_RATIONALE_PREVIEW_CHARS]
            category = payload.get("structured_category")
            requires_review = bool(payload.get("requires_compliance_review", False))
            if requires_review:
                review_queue += 1
            rows.append(
                OverrideHistoryRow(
                    case_id=evt.case_id or "",
                    client_id=evt.client_id or "",
                    advisor_id=evt.advisor_id or "",
                    timestamp=evt.timestamp,
                    rationale_excerpt=rationale,
                    structured_category=str(category) if category else None,
                    requires_compliance_review=requires_review,
                )
            )

        rows.sort(key=lambda r: r.timestamp)

        return ComplianceOverrideHistoryView(
            viewer_user_id=viewer.user_id,
            firm_id=firm_id,
            period_start=period_start,
            period_end=period_end,
            rows=rows,
            total_overrides=len(rows),
            compliance_review_queue_count=review_queue,
        )

    # --------------------- Helpers ----------------------------------

    def _extract_agent_id(self, evt: Any) -> str | None:
        payload = getattr(evt, "payload", {}) or {}
        return payload.get("agent_id")

    def _event_summary(self, evt: Any) -> str:
        payload = getattr(evt, "payload", {}) or {}
        # Prefer an explicit summary field; fall back to event-type-specific
        # excerpts; else canned per-type text.
        for key in ("summary", "reasoning_trace", "rationale_text"):
            v = payload.get(key)
            if isinstance(v, str) and v:
                return v[:_EVENT_SUMMARY_CHARS]
        return f"{evt.event_type.value} event {evt.event_id}"


__all__ = ["ComplianceViewComposer"]
