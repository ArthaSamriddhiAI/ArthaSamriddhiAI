"""§14.3 — CIO view composer.

Two core views in Pass 18:

  * `CIOConstructionApprovalView` (§14.3.2) — version diff + blast radius
    + rollout mode + approval rationale composed from a
    `BucketConstructionProposal` (Pass 16).
  * `CIOFirmDriftDashboard` (§14.3.4) — firm-level drift aggregation
    across the 9 buckets composed from per-bucket `BucketDriftRow`
    counts.
"""

from __future__ import annotations

from datetime import date

from artha.canonical.construction import BucketConstructionProposal
from artha.canonical.views import (
    BucketDriftRow,
    CellChangeSummary,
    CIOConstructionApprovalView,
    CIOFirmDriftDashboard,
    Role,
    ViewerContext,
)
from artha.views.canonical_permissions import (
    PermissionDeniedError,
    assert_can_read_firm,
)


class CIOViewComposer:
    """§14.3 CIO surface composer."""

    composer_id = "view.cio"

    def __init__(self, *, agent_version: str = "0.1.0") -> None:
        self._agent_version = agent_version

    # --------------------- §14.3.2 --------------------------------

    def construction_approval_view(
        self,
        *,
        viewer: ViewerContext,
        firm_id: str,
        run_id: str,
        proposal: BucketConstructionProposal,
    ) -> CIOConstructionApprovalView:
        if viewer.role is not Role.CIO:
            raise PermissionDeniedError(
                f"construction_approval_view is CIO-scoped; "
                f"got {viewer.role.value!r}"
            )
        assert_can_read_firm(viewer, firm_id=firm_id)

        cell_changes = [
            CellChangeSummary(
                level=c.level,
                cell_key=c.cell_key,
                prior_target=c.prior_target,
                proposed_target=c.proposed_target,
                delta=c.delta,
            )
            for c in proposal.version_diff.cell_changes
        ]

        return CIOConstructionApprovalView(
            viewer_user_id=viewer.user_id,
            firm_id=firm_id,
            run_id=run_id,
            bucket=proposal.bucket,
            proposed_model_id=proposal.proposed_model.model_id,
            proposed_version=proposal.proposed_model.version,
            prior_model_id=proposal.prior_model_id,
            cell_changes=cell_changes,
            blast_radius_share=proposal.blast_radius.blast_radius_share,
            clients_in_bucket_count=proposal.blast_radius.clients_in_bucket_count,
            clients_in_tolerance_who_breach=(
                proposal.blast_radius.clients_in_tolerance_who_breach
            ),
            total_aum_moved_inr=proposal.blast_radius.total_aum_moved_inr,
            estimated_txn_cost_inr=proposal.blast_radius.estimated_txn_cost_inr,
            estimated_tax_cost_inr=proposal.blast_radius.estimated_tax_cost_inr,
            rollout_mode=proposal.rollout_mode.value,
            approval_rationale=proposal.approval_rationale,
            approved_for_rollout=proposal.approved_for_rollout,
        )

    # --------------------- §14.3.4 --------------------------------

    def firm_drift_dashboard(
        self,
        *,
        viewer: ViewerContext,
        firm_id: str,
        as_of_date: date,
        bucket_distribution: list[BucketDriftRow],
    ) -> CIOFirmDriftDashboard:
        if viewer.role is not Role.CIO:
            raise PermissionDeniedError(
                f"firm_drift_dashboard is CIO-scoped; got {viewer.role.value!r}"
            )
        assert_can_read_firm(viewer, firm_id=firm_id)

        total_clients = sum(
            r.clients_in_tolerance + r.clients_amber + r.clients_red
            for r in bucket_distribution
        )
        total_breaches = sum(r.mandate_breach_count for r in bucket_distribution)
        total_red = sum(r.clients_red for r in bucket_distribution)

        return CIOFirmDriftDashboard(
            viewer_user_id=viewer.user_id,
            firm_id=firm_id,
            as_of_date=as_of_date,
            bucket_distribution=list(bucket_distribution),
            total_clients=total_clients,
            total_mandate_breaches=total_breaches,
            total_action_required_drifts=total_red,
        )


__all__ = ["CIOViewComposer"]
