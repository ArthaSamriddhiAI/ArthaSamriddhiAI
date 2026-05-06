"""M0 portfolio_state — assembles the canonical portfolio-state object.

Per FR Entry 20.2 §3.2, the portfolio_state sub-agent reads a Snapshot
bundle and reduces it to a flat per-case payload that evidence agents
consume. The shape is deterministic, sortable, and small enough to
embed in a prompt.

Cluster 5.2 ships the *pure-function* layer: callers pass holding rows
(usually pulled from a snapshot bundle by the case opening flow in
chunk 5.3) and receive a :class:`PortfolioState`. The snapshot →
holding-rows extraction lives in cluster 5.3's case opening service.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

# Asset class buckets aligned with cluster-3 instrument schema.
_KNOWN_ASSET_CLASSES: frozenset[str] = frozenset({
    "equity",
    "debt",
    "alternatives",
    "cash",
    "gold",
    "real_estate",
})


@dataclass(frozen=True)
class HoldingInput:
    """Single position passed in from the case opening flow.

    ``allocation_pct`` is the position's share of the total portfolio,
    pre-computed by the snapshot pinner. ``market_value_inr`` is in
    rupees; we accept :class:`Decimal` for accounting precision.
    """

    instrument_id: str
    asset_class: str
    sector: str | None
    market_value_inr: Decimal
    allocation_pct: Decimal


@dataclass(frozen=True)
class AssetClassSlice:
    asset_class: str
    market_value_inr: Decimal
    allocation_pct: Decimal


@dataclass(frozen=True)
class SectorSlice:
    sector: str
    market_value_inr: Decimal
    allocation_pct: Decimal


@dataclass(frozen=True)
class TopPosition:
    instrument_id: str
    asset_class: str
    allocation_pct: Decimal


@dataclass(frozen=True)
class PortfolioState:
    """Reduced view consumed by evidence + synthesis layers."""

    total_value_inr: Decimal
    holding_count: int
    asset_class_slices: tuple[AssetClassSlice, ...]
    sector_slices: tuple[SectorSlice, ...]
    top_positions: tuple[TopPosition, ...]


def assemble_state(
    holdings: Iterable[HoldingInput],
    *,
    top_n: int = 10,
) -> PortfolioState:
    """Reduce holdings into the canonical portfolio-state object.

    - Asset-class slices: sum ``market_value_inr`` + ``allocation_pct``
      per ``asset_class``, sorted by allocation desc.
    - Sector slices: same but for ``sector`` (excluding ``None``).
    - Top positions: top-``top_n`` holdings by ``allocation_pct``.
    """
    holdings_list = list(holdings)
    total_value = sum(
        (h.market_value_inr for h in holdings_list),
        Decimal("0"),
    )

    by_asset: dict[str, list[HoldingInput]] = {}
    for h in holdings_list:
        ac = h.asset_class if h.asset_class in _KNOWN_ASSET_CLASSES else "other"
        by_asset.setdefault(ac, []).append(h)

    asset_slices = tuple(
        sorted(
            (
                AssetClassSlice(
                    asset_class=ac,
                    market_value_inr=sum(
                        (h.market_value_inr for h in items),
                        Decimal("0"),
                    ),
                    allocation_pct=sum(
                        (h.allocation_pct for h in items),
                        Decimal("0"),
                    ),
                )
                for ac, items in by_asset.items()
            ),
            key=lambda s: s.allocation_pct,
            reverse=True,
        ),
    )

    by_sector: dict[str, list[HoldingInput]] = {}
    for h in holdings_list:
        if h.sector is None:
            continue
        by_sector.setdefault(h.sector, []).append(h)

    sector_slices = tuple(
        sorted(
            (
                SectorSlice(
                    sector=sec,
                    market_value_inr=sum(
                        (h.market_value_inr for h in items),
                        Decimal("0"),
                    ),
                    allocation_pct=sum(
                        (h.allocation_pct for h in items),
                        Decimal("0"),
                    ),
                )
                for sec, items in by_sector.items()
            ),
            key=lambda s: s.allocation_pct,
            reverse=True,
        ),
    )

    top_positions = tuple(
        TopPosition(
            instrument_id=h.instrument_id,
            asset_class=h.asset_class,
            allocation_pct=h.allocation_pct,
        )
        for h in sorted(
            holdings_list,
            key=lambda h: h.allocation_pct,
            reverse=True,
        )[:top_n]
    )

    return PortfolioState(
        total_value_inr=total_value,
        holding_count=len(holdings_list),
        asset_class_slices=asset_slices,
        sector_slices=sector_slices,
        top_positions=top_positions,
    )


__all__ = [
    "AssetClassSlice",
    "HoldingInput",
    "PortfolioState",
    "SectorSlice",
    "TopPosition",
    "assemble_state",
]
