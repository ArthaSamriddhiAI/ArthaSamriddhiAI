"""Section 8.4 — M0.PortfolioState: semantic data layer over canonical holdings.

Downstream agents query PortfolioState rather than the database directly. The
service exposes typed methods (used by Phase C agents) plus a generic `query()`
dispatcher that wraps results in the canonical `M0PortfolioStateResponse`
envelope (Section 15.6.3).

Pass 6 ships an in-memory `InMemoryPortfolioStateRepository`. Pass 19
(persistence) replaces it with an ORM-backed implementation behind the same
protocol; the service is unchanged.

Pass 6 does not yet implement ingestion (Section 8.4.2 write path) — that
requires CAS / broker statement parsers and the L4 reconciliation algorithm.
Acceptance tests 2 and 3 (ingestion latency and reconciliation surfacing) are
deferred. Tests 1, 4, 5, 6, 7 are covered.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

from artha.canonical.holding import (
    CascadeEvent,
    ConflictReport,
    Holding,
    LookThroughEntry,
    LookThroughResponse,
    SliceResponse,
)
from artha.canonical.m0_portfolio_state import (
    M0PortfolioStateQuery,
    M0PortfolioStateQueryCategory,
    M0PortfolioStateResponse,
)
from artha.canonical.mandate import MandateObject
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.common.errors import ArthaError
from artha.common.types import (
    AssetClass,
    InputsUsedManifest,
    RunMode,
    VehicleType,
    WealthTier,
)
from artha.model_portfolio.conflict import detect_mandate_vs_model_conflicts
from artha.model_portfolio.service import vehicle_accessible

# ---------------------------------------------------------------------------
# Repository protocol + in-memory implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class PortfolioStateRepository(Protocol):
    """Protocol for the data backend behind PortfolioState.

    Pass 19 (persistence) provides a DB-backed implementation; Pass 6 uses
    `InMemoryPortfolioStateRepository`. Both honor this contract.
    """

    def get_holdings(
        self, client_id: str, *, as_of_date: date | None = None
    ) -> list[Holding]: ...

    def get_look_through(self, parent_instrument_id: str) -> list[LookThroughEntry]: ...

    def get_cascade_events(
        self, client_id: str, *, as_of_date: date | None = None
    ) -> list[CascadeEvent]: ...


class InMemoryPortfolioStateRepository:
    """Pass 6 in-memory backend. Tests construct one with pre-populated data."""

    def __init__(
        self,
        *,
        holdings_by_client: dict[str, list[Holding]] | None = None,
        look_through_by_parent: dict[str, list[LookThroughEntry]] | None = None,
        cascade_by_client: dict[str, list[CascadeEvent]] | None = None,
    ) -> None:
        self._holdings = holdings_by_client or {}
        self._look_through = look_through_by_parent or {}
        self._cascade = cascade_by_client or {}

    def get_holdings(
        self, client_id: str, *, as_of_date: date | None = None
    ) -> list[Holding]:
        # Pass 6 is point-in-time-naive; future persistence layer filters by as_of_date.
        return list(self._holdings.get(client_id, []))

    def get_look_through(self, parent_instrument_id: str) -> list[LookThroughEntry]:
        return list(self._look_through.get(parent_instrument_id, []))

    def get_cascade_events(
        self, client_id: str, *, as_of_date: date | None = None
    ) -> list[CascadeEvent]:
        events = list(self._cascade.get(client_id, []))
        if as_of_date is not None:
            events = [e for e in events if e.expected_date >= as_of_date]
        return events


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class IngestionNotImplementedError(ArthaError):
    """Pass 6 does not implement the ingestion (write) path. Phase C / E will."""


class M0PortfolioState:
    """Section 8.4 — semantic data layer service.

    Typed methods (`get_holdings`, `get_slice`, `get_look_through`, `get_cascade`,
    `detect_conflicts`) are the natural API for downstream agents. The
    `query()` dispatcher wraps these in the canonical Section 15.6.3 envelope
    for callers that consume the structured query interface.

    Construction-mode queries (`run_mode=RunMode.CONSTRUCTION`) are stubbed
    until Phase F's construction pipeline lands.
    """

    def __init__(self, repository: PortfolioStateRepository) -> None:
        self._repo = repository

    # -----------------------------------------------------------------------
    # Typed methods
    # -----------------------------------------------------------------------

    def get_holdings(
        self, client_id: str, *, as_of_date: date | None = None
    ) -> list[Holding]:
        return self._repo.get_holdings(client_id, as_of_date=as_of_date)

    def get_slice(
        self,
        client_id: str,
        *,
        as_of_date: date | None = None,
        asset_class: AssetClass | None = None,
        vehicle_type: VehicleType | None = None,
        amc_or_issuer: str | None = None,
        sub_asset_class: str | None = None,
    ) -> SliceResponse:
        """Return a filtered slice of holdings with aggregate fields.

        Filters compose with AND semantics. Empty filters return the full slice.
        """
        holdings = self.get_holdings(client_id, as_of_date=as_of_date)
        filtered = [
            h
            for h in holdings
            if (asset_class is None or h.asset_class == asset_class)
            and (vehicle_type is None or h.vehicle_type == vehicle_type)
            and (amc_or_issuer is None or h.amc_or_issuer == amc_or_issuer)
            and (sub_asset_class is None or h.sub_asset_class == sub_asset_class)
        ]
        total_value = sum(h.market_value for h in filtered)
        units_by_amc: dict[str, float] = {}
        for h in filtered:
            units_by_amc[h.amc_or_issuer] = units_by_amc.get(h.amc_or_issuer, 0.0) + h.units
        return SliceResponse(
            holdings=filtered,
            total_value_inr=total_value,
            total_units_by_amc=units_by_amc,
        )

    def get_look_through(self, parent_instrument_id: str) -> LookThroughResponse:
        """Return the look-through view for a fund/PMS/AIF holding (Section 8.4.2)."""
        entries = self._repo.get_look_through(parent_instrument_id)
        return LookThroughResponse(
            parent_instrument_id=parent_instrument_id,
            entries=entries,
        )

    def get_cascade(
        self, client_id: str, *, as_of_date: date | None = None
    ) -> list[CascadeEvent]:
        """Return forecast cash-flow events for a client (Section 8.4.2)."""
        return self._repo.get_cascade_events(client_id, as_of_date=as_of_date)

    def detect_conflicts(
        self,
        client_id: str,
        mandate: MandateObject,
        model_portfolio: ModelPortfolioObject,
        *,
        investor_tier: WealthTier | None = None,
    ) -> list[ConflictReport]:
        """Run the Section 5.10 mandate-vs-model conflict check, plus the
        Section 5.3.2 AUM-eligibility check when an investor tier is given.

        Note: returning conflicts here lets downstream code surface the three
        Section 5.10 resolution paths consistently. The actual resolution
        (amend / clip / out-of-bucket) is the advisor's call.
        """
        conflicts = list(detect_mandate_vs_model_conflicts(mandate, model_portfolio))

        if investor_tier is not None:
            for asset_class, vehicle_targets in model_portfolio.l2_targets.items():
                for vehicle, target_band in vehicle_targets.items():
                    if target_band.target <= 0:
                        continue
                    if not vehicle_accessible(vehicle, investor_tier):
                        conflicts.append(
                            ConflictReport(
                                conflict_type=_aum_conflict_type(),
                                dimension=f"vehicle.{asset_class.value}.{vehicle.value}",
                                mandate_value={"investor_tier": investor_tier.value},
                                model_value={"target": target_band.target},
                                resolution_paths=["aum_filter_redistribute"],
                            )
                        )
        return conflicts

    # -----------------------------------------------------------------------
    # Generic query dispatcher (Section 15.6.3 envelope)
    # -----------------------------------------------------------------------

    def query(
        self,
        query: M0PortfolioStateQuery,
        *,
        mandate: MandateObject | None = None,
        model_portfolio: ModelPortfolioObject | None = None,
        investor_tier: WealthTier | None = None,
    ) -> M0PortfolioStateResponse:
        """Dispatch a structured query and wrap the result in the canonical envelope."""
        if query.run_mode is RunMode.CONSTRUCTION:
            # Phase F adds construction-pipeline support; until then we surface
            # the gap explicitly rather than silently misroute.
            raise NotImplementedError(
                "RunMode.CONSTRUCTION queries are deferred to Phase F (construction pipeline)"
            )

        params = query.query_parameters or {}
        manifest_inputs: dict[str, dict[str, str]] = {
            "client_id": {"value": query.client_id},
            "query_category": {"value": query.query_category.value},
        }

        match query.query_category:
            case M0PortfolioStateQueryCategory.HOLDINGS:
                holdings = self.get_holdings(query.client_id, as_of_date=query.as_of_date)
                manifest_inputs["holdings"] = {"count": str(len(holdings))}
                return M0PortfolioStateResponse(
                    query_category=query.query_category,
                    client_id=query.client_id,
                    as_of_date=query.as_of_date,
                    holdings=holdings,
                    inputs_used_manifest=InputsUsedManifest(inputs=manifest_inputs),
                )

            case M0PortfolioStateQueryCategory.SLICE:
                slice_result = self.get_slice(
                    query.client_id,
                    as_of_date=query.as_of_date,
                    asset_class=_coerce_asset_class(params.get("asset_class")),
                    vehicle_type=_coerce_vehicle_type(params.get("vehicle_type")),
                    amc_or_issuer=params.get("amc_or_issuer"),
                    sub_asset_class=params.get("sub_asset_class"),
                )
                manifest_inputs["slice_count"] = {"value": str(len(slice_result.holdings))}
                return M0PortfolioStateResponse(
                    query_category=query.query_category,
                    client_id=query.client_id,
                    as_of_date=query.as_of_date,
                    slice_result=slice_result,
                    inputs_used_manifest=InputsUsedManifest(inputs=manifest_inputs),
                )

            case M0PortfolioStateQueryCategory.LOOK_THROUGH:
                parent_id = params.get("parent_instrument_id")
                if not isinstance(parent_id, str):
                    raise ValueError(
                        "look_through query requires `parent_instrument_id` in query_parameters"
                    )
                lt = self.get_look_through(parent_id)
                manifest_inputs["look_through"] = {
                    "parent": parent_id,
                    "count": str(len(lt.entries)),
                }
                return M0PortfolioStateResponse(
                    query_category=query.query_category,
                    client_id=query.client_id,
                    as_of_date=query.as_of_date,
                    look_through=lt,
                    inputs_used_manifest=InputsUsedManifest(inputs=manifest_inputs),
                )

            case M0PortfolioStateQueryCategory.CASCADE:
                events = self.get_cascade(query.client_id, as_of_date=query.as_of_date)
                manifest_inputs["cascade"] = {"count": str(len(events))}
                return M0PortfolioStateResponse(
                    query_category=query.query_category,
                    client_id=query.client_id,
                    as_of_date=query.as_of_date,
                    cascade_events=events,
                    inputs_used_manifest=InputsUsedManifest(inputs=manifest_inputs),
                )

            case M0PortfolioStateQueryCategory.CONFLICT_DETECTION:
                if mandate is None or model_portfolio is None:
                    raise ValueError(
                        "conflict_detection query requires `mandate` and `model_portfolio`"
                    )
                conflicts = self.detect_conflicts(
                    query.client_id,
                    mandate,
                    model_portfolio,
                    investor_tier=investor_tier,
                )
                manifest_inputs["mandate_version"] = {"value": str(mandate.version)}
                manifest_inputs["model_portfolio_version"] = {"value": model_portfolio.version}
                manifest_inputs["conflicts"] = {"count": str(len(conflicts))}
                return M0PortfolioStateResponse(
                    query_category=query.query_category,
                    client_id=query.client_id,
                    as_of_date=query.as_of_date,
                    conflicts=conflicts,
                    inputs_used_manifest=InputsUsedManifest(inputs=manifest_inputs),
                )

            case M0PortfolioStateQueryCategory.INGESTION:
                raise IngestionNotImplementedError(
                    "Section 8.4.2 ingestion path is deferred (Pass 6 read-only)"
                )

        # Defensive — exhaustive match above; included for type-checker clarity.
        raise ValueError(f"unknown query_category: {query.query_category!r}")


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _coerce_asset_class(v: Any) -> AssetClass | None:
    if v is None:
        return None
    return AssetClass(v) if not isinstance(v, AssetClass) else v


def _coerce_vehicle_type(v: Any) -> VehicleType | None:
    if v is None:
        return None
    return VehicleType(v) if not isinstance(v, VehicleType) else v


def _aum_conflict_type():
    """Avoid circular import at module top by importing lazily."""
    from artha.canonical.holding import ConflictType
    return ConflictType.WEALTH_TIER_ELIGIBILITY
