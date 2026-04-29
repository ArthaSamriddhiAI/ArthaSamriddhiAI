"""§14.2 — Advisor view composer.

Three core views in Pass 18:

  * `AdvisorPerClientView` (§14.2.1) — single-client operational dashboard
    with risk/horizon header, AUM summary, drift status traffic light,
    active N0 alerts, recent cases.
  * Advisor N0 inbox composition (the alert list as `N0InboxItem`s).
  * `AdvisorCaseDetailView` (§14.2.3) — full case rendering with evidence
    drill-downs + governance verdicts + decision options.

Pure deterministic. Composer reads canonical objects + applies role-based
access control via `canonical_permissions`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from artha.canonical.case import CaseObject
from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.governance import G3Evaluation
from artha.canonical.holding import Holding
from artha.canonical.investor import InvestorContextProfile
from artha.canonical.mandate import MandateObject
from artha.canonical.monitoring import N0Alert
from artha.canonical.synthesis import IC1Deliberation, S1Synthesis
from artha.canonical.views import (
    AdvisorCaseDetailView,
    AdvisorPerClientView,
    CaseRecentRow,
    DriftStatusLight,
    EvidenceVerdictSummary,
    HoldingSummaryRow,
    N0InboxItem,
    Role,
    ViewerContext,
)
from artha.common.types import Permission
from artha.model_portfolio.tolerance import (
    DriftEvent,
    DriftSeverity,
)
from artha.views.canonical_permissions import (
    PermissionDeniedError,
    assert_can_read_client,
)

_BODY_PREVIEW_CHARS = 200
_REASONING_PREVIEW_CHARS = 400
_TOP_HOLDINGS_LIMIT = 5
_RECENT_CASES_LIMIT = 10


class AdvisorViewComposer:
    """§14.2 advisor surface composer.

    Construction:
      * No external collaborators required for Pass 18; the composer is a
        pure transformation. Production wires repositories.
    """

    composer_id = "view.advisor"

    def __init__(self, *, agent_version: str = "0.1.0") -> None:
        self._agent_version = agent_version

    # --------------------- §14.2.1 --------------------------------

    def per_client_view(
        self,
        *,
        viewer: ViewerContext,
        profile: InvestorContextProfile,
        mandate: MandateObject | None,
        holdings: list[Holding],
        active_alerts: list[N0Alert],
        recent_cases: list[CaseObject],
        drift_events: list[DriftEvent] | None = None,
        cash_buffer_inr: float = 0.0,
    ) -> AdvisorPerClientView:
        if viewer.role is not Role.ADVISOR:
            raise PermissionDeniedError(
                f"per_client_view is advisor-scoped; got {viewer.role.value!r}"
            )
        assert_can_read_client(
            viewer, client_id=profile.client_id, client_firm_id=profile.firm_id
        )

        total_aum = sum(h.market_value for h in holdings)
        deployed = total_aum - cash_buffer_inr

        # Top holdings
        sorted_holdings = sorted(holdings, key=lambda h: h.market_value, reverse=True)
        top_rows = [
            HoldingSummaryRow(
                instrument_id=h.instrument_id,
                instrument_name=h.instrument_name,
                market_value_inr=h.market_value,
                share_of_aum=(h.market_value / total_aum) if total_aum > 0 else 0.0,
            )
            for h in sorted_holdings[:_TOP_HOLDINGS_LIMIT]
        ]

        drift_status, breach_count = self._derive_drift_status(drift_events or [])

        # N0 inbox (filter to client's alerts only)
        inbox = [
            self._inbox_item(a)
            for a in active_alerts
            if a.client_id == profile.client_id
        ]

        # Recent cases (filter same client)
        case_rows = [
            CaseRecentRow(
                case_id=c.case_id,
                intent=c.intent.value,
                dominant_lens=c.dominant_lens.value,
                current_status=c.current_status.value,
                created_at=c.created_at,
            )
            for c in sorted(
                [c for c in recent_cases if c.client_id == profile.client_id],
                key=lambda c: c.created_at,
                reverse=True,
            )[:_RECENT_CASES_LIMIT]
        ]

        mandate_summary = self._mandate_summary(mandate)

        return AdvisorPerClientView(
            viewer_user_id=viewer.user_id,
            firm_id=profile.firm_id,
            client_id=profile.client_id,
            risk_profile=profile.risk_profile.value,
            time_horizon=profile.time_horizon.value,
            assigned_bucket=profile.assigned_bucket,
            total_aum_inr=total_aum,
            deployed_inr=deployed,
            cash_buffer_inr=cash_buffer_inr,
            drift_status=drift_status,
            drift_breaches_count=breach_count,
            top_holdings=top_rows,
            active_alerts=inbox,
            recent_cases=case_rows,
            mandate_summary=mandate_summary,
        )

    # --------------------- §14.2.3 --------------------------------

    def case_detail_view(
        self,
        *,
        viewer: ViewerContext,
        case: CaseObject,
        rendered_artifact_text: str,
        evidence_verdicts: list[StandardEvidenceVerdict],
        s1_synthesis: S1Synthesis | None = None,
        ic1_deliberation: IC1Deliberation | None = None,
        g3_evaluation: G3Evaluation | None = None,
        decision_options: list[str] | None = None,
        t1_replay_link: str | None = None,
    ) -> AdvisorCaseDetailView:
        if viewer.role is not Role.ADVISOR:
            raise PermissionDeniedError(
                f"case_detail_view is advisor-scoped; got {viewer.role.value!r}"
            )
        assert_can_read_client(
            viewer, client_id=case.client_id, client_firm_id=case.firm_id
        )

        evidence_summaries = [
            EvidenceVerdictSummary(
                agent_id=v.agent_id,
                risk_level=v.risk_level.value,
                confidence=v.confidence,
                flags=list(v.flags),
                reasoning_excerpt=v.reasoning_trace[:_REASONING_PREVIEW_CHARS],
            )
            for v in evidence_verdicts
        ]

        ic1_minutes_excerpt: str | None = None
        ic1_recommendation: str | None = None
        if ic1_deliberation is not None:
            ic1_recommendation = ic1_deliberation.recommendation.value
            # Per §14.2.3 the case detail surfaces the IC1 minutes as a
            # compact excerpt; we use the chair's narrative as the
            # advisor-facing rollup.
            chair = ic1_deliberation.chair_synthesis
            ic1_minutes_excerpt = (
                chair[:_REASONING_PREVIEW_CHARS] if chair else None
            )

        g3_permission_value: str | None = None
        g3_blocking: list[str] = []
        if g3_evaluation is not None:
            g3_permission_value = g3_evaluation.permission.value
            if g3_evaluation.permission is Permission.BLOCKED:
                g3_blocking = list(g3_evaluation.blocking_reasons)

        s1_recommendation: str | None = None
        if s1_synthesis is not None:
            s1_recommendation = s1_synthesis.recommendation.value

        return AdvisorCaseDetailView(
            viewer_user_id=viewer.user_id,
            firm_id=case.firm_id,
            case_id=case.case_id,
            client_id=case.client_id,
            case_intent=case.intent.value,
            dominant_lens=case.dominant_lens.value,
            rendered_artifact_text=rendered_artifact_text,
            evidence_summaries=evidence_summaries,
            s1_synthesis_recommendation=s1_recommendation,
            ic1_recommendation=ic1_recommendation,
            ic1_minutes_excerpt=ic1_minutes_excerpt,
            g3_permission=g3_permission_value,
            g3_blocking_reasons=g3_blocking,
            decision_options=list(decision_options or []),
            t1_replay_link=t1_replay_link,
        )

    # --------------------- N0 inbox helper ----------------------

    def n0_inbox_for_advisor(
        self,
        *,
        viewer: ViewerContext,
        alerts: list[N0Alert],
    ) -> list[N0InboxItem]:
        """Compose the advisor's N0 inbox from raw alerts.

        Filters to alerts on the advisor's assigned clients within the
        same firm. Out-of-firm alerts raise; out-of-scope-clients are
        silently filtered (they should not have been delivered to this
        advisor in production).
        """
        if viewer.role is not Role.ADVISOR:
            raise PermissionDeniedError(
                f"n0_inbox is advisor-scoped; got {viewer.role.value!r}"
            )
        out: list[N0InboxItem] = []
        for a in alerts:
            if a.firm_id != viewer.firm_id:
                raise PermissionDeniedError(
                    f"alert {a.alert_id} firm_id={a.firm_id!r} mismatches "
                    f"viewer firm {viewer.firm_id!r}"
                )
            if a.client_id not in viewer.assigned_client_ids:
                continue
            out.append(self._inbox_item(a))
        # Stable ordering: most recent first.
        out.sort(key=lambda i: i.created_at, reverse=True)
        return out

    # --------------------- Helpers ----------------------------------

    def _inbox_item(self, alert: N0Alert) -> N0InboxItem:
        return N0InboxItem(
            alert_id=alert.alert_id,
            tier=alert.tier,
            title=alert.title,
            body_preview=alert.body[:_BODY_PREVIEW_CHARS],
            related_case_id=alert.case_id,
            created_at=alert.created_at,
        )

    def _derive_drift_status(
        self, events: list[DriftEvent]
    ) -> tuple[DriftStatusLight, int]:
        if not events:
            return DriftStatusLight.GREEN, 0
        if any(e.severity is DriftSeverity.ACTION_REQUIRED for e in events):
            return DriftStatusLight.RED, len(events)
        return DriftStatusLight.AMBER, len(events)

    def _mandate_summary(self, mandate: MandateObject | None) -> dict[str, Any]:
        if mandate is None:
            return {}
        return {
            "mandate_id": mandate.mandate_id,
            "version": mandate.version,
            "mandate_type": mandate.mandate_type.value,
            "asset_class_caps": {
                ac.value: limits.max_pct
                for ac, limits in mandate.asset_class_limits.items()
            },
            "liquidity_floor": mandate.liquidity_floor,
            "sector_exclusions_count": len(mandate.sector_exclusions),
        }

    def _now(self) -> datetime:
        from artha.common.clock import get_clock

        return get_clock().now()


__all__ = ["AdvisorViewComposer"]
