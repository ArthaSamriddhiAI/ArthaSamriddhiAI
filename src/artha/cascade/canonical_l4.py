"""§5.9.3 — L4 Cascade Service.

When the firm's L4 manifest moves to a new version with REMOVE operations,
this service spawns one Mode-1-dominant case per affected client. The
substitution helper from Pass 16 (`compute_substitution_impacts`) provides
the per-removed-instrument breakdown; this service folds those impacts into
per-client `L4CascadeCase` stubs and emits the SHOULD_RESPOND N0 alerts.

Per §5.9.3 the case title follows the §5.13 Test 7 phrasing exactly.

Pure deterministic. No LLM. Output:
  * `L4CascadeRun` envelope with all spawned cases + N0 alert ids.
  * Optional T1 event written via injected repo.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from artha.canonical.cascade import (
    L4CascadeCase,
    L4CascadeCaseStatus,
    L4CascadeRun,
)
from artha.canonical.construction import ClientPortfolioSlice, L4SubstitutionImpact
from artha.canonical.monitoring import (
    AlertTier,
    N0Alert,
    N0AlertCategory,
    N0Originator,
)
from artha.common.clock import get_clock
from artha.common.hashing import payload_hash
from artha.common.standards import T1EventType
from artha.common.types import InputsUsedManifest
from artha.common.ulid import new_ulid
from artha.construction.canonical_substitution import compute_substitution_impacts

logger = logging.getLogger(__name__)


class L4CascadeService:
    """§5.9.3 deterministic L4 cascade service."""

    agent_id = "l4_cascade"

    def __init__(
        self,
        *,
        t1_repository: Any | None = None,
        agent_version: str = "0.1.0",
    ) -> None:
        self._t1 = t1_repository
        self._agent_version = agent_version

    # --------------------- Public API --------------------------------

    async def cascade(
        self,
        *,
        firm_id: str,
        l4_manifest_version: str,
        client_slices: list[ClientPortfolioSlice],
        removed_instrument_ids: list[str],
        replacement_map: dict[str, str],
        advisor_assignments: dict[str, str] | None = None,
    ) -> tuple[L4CascadeRun, list[N0Alert]]:
        """Compute substitution impacts + spawn per-client Mode-1 cases.

        `advisor_assignments` maps client_id → advisor_id (production wires
        from the firm directory; tests can supply directly). Cases without an
        assignment leave `advisor_id=None` for downstream resolution.
        """
        impacts = compute_substitution_impacts(
            client_slices=client_slices,
            removed_instrument_ids=removed_instrument_ids,
            replacement_map=replacement_map,
        )

        spawned_cases: list[L4CascadeCase] = []
        alerts: list[N0Alert] = []
        now = self._now()
        client_aum_per_instrument = self._index_aum_per_client(client_slices)
        assignments = advisor_assignments or {}

        for impact in impacts:
            for client_id in impact.affected_client_ids:
                aum = client_aum_per_instrument.get(client_id, {}).get(
                    impact.removed_instrument_id, 0.0
                )
                alert = self._build_n0_alert(
                    firm_id=firm_id,
                    client_id=client_id,
                    removed_id=impact.removed_instrument_id,
                    replacement_id=impact.replacement_instrument_id,
                    aum=aum,
                    created_at=now,
                )
                alerts.append(alert)
                case = L4CascadeCase(
                    case_id=new_ulid(),
                    client_id=client_id,
                    firm_id=firm_id,
                    advisor_id=assignments.get(client_id),
                    removed_instrument_id=impact.removed_instrument_id,
                    replacement_instrument_id=impact.replacement_instrument_id,
                    affected_aum_inr=aum,
                    title=(
                        f"Fund {impact.removed_instrument_id} [removed] — "
                        f"substitute to {impact.replacement_instrument_id} "
                        "[recommended alternative in L3 cell]."
                    ),
                    body=(
                        f"L4 manifest version {l4_manifest_version} removed "
                        f"{impact.removed_instrument_id}. Client holds "
                        f"₹{aum:,.0f} in this instrument. Recommended "
                        f"substitution: {impact.replacement_instrument_id}."
                    ),
                    n0_alert_id=alert.alert_id,
                    status=L4CascadeCaseStatus.OPEN,
                    created_at=now,
                )
                spawned_cases.append(case)

        signals_input = self._collect_input_for_hash(
            firm_id=firm_id,
            l4_manifest_version=l4_manifest_version,
            removed_instrument_ids=removed_instrument_ids,
            replacement_map=replacement_map,
            spawned_cases=spawned_cases,
        )

        run = L4CascadeRun(
            run_id=new_ulid(),
            firm_id=firm_id,
            l4_manifest_version=l4_manifest_version,
            triggered_at=now,
            impacts=impacts,
            spawned_cases=spawned_cases,
            n0_alert_ids=[a.alert_id for a in alerts],
            inputs_used_manifest=self._build_inputs_used_manifest(signals_input),
            input_hash=payload_hash(signals_input),
            agent_version=self._agent_version,
        )

        if self._t1 is not None:
            run = await self._emit_t1_event(run)

        return run, alerts

    # --------------------- Helpers ----------------------------------

    def _index_aum_per_client(
        self, slices: list[ClientPortfolioSlice]
    ) -> dict[str, dict[str, float]]:
        """client_id → {instrument_id → market_value}."""
        out: dict[str, dict[str, float]] = {}
        for s in slices:
            out[s.client_id] = dict(s.holdings_by_instrument_id)
        return out

    def _build_n0_alert(
        self,
        *,
        firm_id: str,
        client_id: str,
        removed_id: str,
        replacement_id: str,
        aum: float,
        created_at: datetime,
    ) -> N0Alert:
        return N0Alert(
            alert_id=new_ulid(),
            originator=N0Originator.PM1,
            tier=AlertTier.SHOULD_RESPOND,
            category=N0AlertCategory.THRESHOLD_BREACH,
            client_id=client_id,
            firm_id=firm_id,
            created_at=created_at,
            title=f"L4 substitution: {removed_id} → {replacement_id}",
            body=(
                f"Holding ₹{aum:,.0f} in removed instrument {removed_id}. "
                f"Recommended substitution: {replacement_id}."
            ),
            expected_action="Review and execute the substitution per advisor judgement.",
            related_constraint_id=f"l4_substitution:{removed_id}",
        )

    async def _emit_t1_event(self, run: L4CascadeRun) -> L4CascadeRun:
        """Append a T1 L4_MANIFEST_VERSION_PIN event for the cascade."""
        from artha.accountability.t1.models import T1Event

        payload = {
            "run_id": run.run_id,
            "l4_manifest_version": run.l4_manifest_version,
            "impacts": [i.model_dump(mode="json") for i in run.impacts],
            "spawned_case_ids": [c.case_id for c in run.spawned_cases],
            "n0_alert_ids": list(run.n0_alert_ids),
        }
        event = T1Event(
            event_type=T1EventType.L4_MANIFEST_VERSION_PIN,
            timestamp=run.triggered_at,
            firm_id=run.firm_id,
            payload=payload,
            payload_hash=payload_hash(payload),
        )
        appended = await self._t1.append(event)
        return run.model_copy(update={"t1_event_id": appended.event_id})

    def _collect_input_for_hash(
        self,
        *,
        firm_id: str,
        l4_manifest_version: str,
        removed_instrument_ids: list[str],
        replacement_map: dict[str, str],
        spawned_cases: list[L4CascadeCase],
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "firm_id": firm_id,
            "l4_manifest_version": l4_manifest_version,
            "removed_instrument_ids": sorted(removed_instrument_ids),
            "replacement_map": dict(sorted(replacement_map.items())),
            "spawned_case_client_ids": sorted(c.client_id for c in spawned_cases),
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = ["L4CascadeService", "L4SubstitutionImpact"]
