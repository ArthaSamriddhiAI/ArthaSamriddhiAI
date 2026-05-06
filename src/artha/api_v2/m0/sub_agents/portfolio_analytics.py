"""M0 portfolio_analytics — deterministic concentration computations.

Per FR Entry 20.2 §3.5, the portfolio_analytics sub-agent computes
deterministic concentration metrics from a portfolio state. These feed
the materiality gate (chunk 5.4) + governance gates + the case-mode
synthesizer.

All functions are pure: given the same input they emit the same output
to the cent. Decimal arithmetic throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from artha.api_v2.m0.sub_agents.portfolio_state import PortfolioState


@dataclass(frozen=True)
class ConcentrationMetrics:
    """Output of :func:`compute_concentration`.

    - ``hhi`` is the Herfindahl-Hirschman Index over instrument-level
      shares (0..10000, higher = more concentrated).
    - ``top_n_share_pct`` is the cumulative allocation of the top N
      positions (typically N=5).
    - ``max_single_position_pct`` is the largest single instrument's
      share.
    - ``max_sector_share_pct`` is the largest sector's share.
    """

    hhi: Decimal
    top_n_share_pct: Decimal
    top_n: int
    max_single_position_pct: Decimal
    max_sector_share_pct: Decimal


def compute_concentration(
    state: PortfolioState,
    *,
    top_n: int = 5,
) -> ConcentrationMetrics:
    """Compute the deterministic concentration metrics for ``state``.

    Empty state returns zero across the board (HHI=0, top-N share=0)
    rather than raising — callers may pass a freshly-pinned empty
    snapshot during tests.
    """
    positions = state.top_positions
    if not positions:
        return ConcentrationMetrics(
            hhi=Decimal("0"),
            top_n_share_pct=Decimal("0"),
            top_n=top_n,
            max_single_position_pct=Decimal("0"),
            max_sector_share_pct=Decimal("0"),
        )

    # HHI is computed over *all* holdings, not only the top-N. We rely
    # on the caller passing a state whose top_positions covers every
    # holding for HHI to be exact; in chunk 5.5 the case opening flow
    # uses top_n large enough to capture every holding.
    hhi = sum(
        (p.allocation_pct * p.allocation_pct for p in positions),
        Decimal("0"),
    )

    top_share = sum(
        (p.allocation_pct for p in positions[:top_n]),
        Decimal("0"),
    )
    max_single = max((p.allocation_pct for p in positions), default=Decimal("0"))
    max_sector = max(
        (s.allocation_pct for s in state.sector_slices),
        default=Decimal("0"),
    )

    return ConcentrationMetrics(
        hhi=hhi,
        top_n_share_pct=top_share,
        top_n=top_n,
        max_single_position_pct=max_single,
        max_sector_share_pct=max_sector,
    )


@dataclass(frozen=True)
class AssetClassDeviation:
    """Per asset-class deviation from a target allocation."""

    asset_class: str
    actual_pct: Decimal
    target_pct: Decimal
    deviation_pct: Decimal  # actual - target; negative = under, positive = over


def compute_drift_vs_target(
    state: PortfolioState,
    targets: dict[str, Decimal],
) -> tuple[AssetClassDeviation, ...]:
    """Return per-asset-class deviation from a target dict.

    ``targets`` maps asset_class → target percentage. Asset classes
    present in either ``state`` or ``targets`` appear in the output;
    the missing side reads as 0.
    """
    actuals: dict[str, Decimal] = {
        s.asset_class: s.allocation_pct for s in state.asset_class_slices
    }
    keys = sorted(set(actuals) | set(targets))
    return tuple(
        AssetClassDeviation(
            asset_class=k,
            actual_pct=actuals.get(k, Decimal("0")),
            target_pct=targets.get(k, Decimal("0")),
            deviation_pct=actuals.get(k, Decimal("0")) - targets.get(k, Decimal("0")),
        )
        for k in keys
    )


def cumulative_share(values: Iterable[Decimal]) -> tuple[Decimal, ...]:
    """Running-sum helper used by the synthesis layer for concentration plots."""
    out: list[Decimal] = []
    running = Decimal("0")
    for v in values:
        running += v
        out.append(running)
    return tuple(out)


__all__ = [
    "AssetClassDeviation",
    "ConcentrationMetrics",
    "compute_concentration",
    "compute_drift_vs_target",
    "cumulative_share",
]
