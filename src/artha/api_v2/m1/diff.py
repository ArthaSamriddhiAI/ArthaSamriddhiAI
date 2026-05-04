"""Mandate-version diff + impact analysis (FR Entry 12.2 §4.2 + §4.3).

Pure-Python helpers — no DB access, no I/O. Used by:

- The CIO's amendment review surface to render the side-by-side panel.
- The plain-language change summary that appears at the top of the diff.
- The impact analysis structural diff and activation summary.

All inputs are :class:`MandateVersionRead` Pydantic models so the
helpers stay decoupled from SQLAlchemy ORM rows; the router builds the
read shape once and reuses it for both the diff response and the
underlying detail rendering.
"""

from __future__ import annotations

from dataclasses import dataclass

from artha.api_v2.m1.schemas import MandateVersionRead

# ---------------------------------------------------------------------------
# Field labels (drives the plain-language summary text)
# ---------------------------------------------------------------------------


_NUMERIC_FIELD_LABELS: dict[str, str] = {
    "equity_min_pct": "equity min",
    "equity_max_pct": "equity max",
    "debt_min_pct": "debt min",
    "debt_max_pct": "debt max",
    "alternatives_min_pct": "alternatives min",
    "alternatives_max_pct": "alternatives max",
    "single_position_max_pct": "single-position limit",
    "liquidity_floor_pct": "liquidity floor",
    "sector_max_pct": "sector cap",
}

_NUMERIC_FIELDS: tuple[str, ...] = tuple(_NUMERIC_FIELD_LABELS.keys())


# ---------------------------------------------------------------------------
# Diff shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NumericFieldChange:
    """One numerical-constraint change between two versions."""

    field: str
    label: str
    old_value: int
    new_value: int


@dataclass(frozen=True)
class ProhibitedListChange:
    """Add/remove deltas on the prohibited_instruments list."""

    added: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed


@dataclass(frozen=True)
class MandateDiff:
    """Structured diff between two :class:`MandateVersionRead` records.

    ``numeric_changes`` lists each field that changed with old/new values;
    ``prohibited_change`` is always present (with possibly-empty add/remove
    tuples). The :attr:`is_empty` flag short-circuits "nothing changed"
    rendering.
    """

    numeric_changes: tuple[NumericFieldChange, ...]
    prohibited_change: ProhibitedListChange

    @property
    def is_empty(self) -> bool:
        return not self.numeric_changes and self.prohibited_change.is_empty


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


def compute_diff(
    *, active: MandateVersionRead, proposed: MandateVersionRead
) -> MandateDiff:
    """Diff ``proposed`` against ``active``.

    Field order matches the form's section order: asset allocation
    (equity/debt/alternatives min/max), single-position, liquidity floor,
    sector cap, prohibited list. The frontend renders rows in this order
    so the diff visual mirrors the create form layout (chunk plan §2.1
    implementation_notes).
    """
    numeric: list[NumericFieldChange] = []
    for field in _NUMERIC_FIELDS:
        old = getattr(active, field)
        new = getattr(proposed, field)
        if old != new:
            numeric.append(
                NumericFieldChange(
                    field=field,
                    label=_NUMERIC_FIELD_LABELS[field],
                    old_value=old,
                    new_value=new,
                )
            )

    active_set = set(active.prohibited_instruments)
    proposed_set = set(proposed.prohibited_instruments)
    added = tuple(sorted(proposed_set - active_set))
    removed = tuple(sorted(active_set - proposed_set))

    return MandateDiff(
        numeric_changes=tuple(numeric),
        prohibited_change=ProhibitedListChange(added=added, removed=removed),
    )


# ---------------------------------------------------------------------------
# Plain-language summary (FR 12.2 §4.2)
# ---------------------------------------------------------------------------


def summarise_diff(diff: MandateDiff) -> list[str]:
    """Produce a list of plain-language change strings.

    Each line is one human-readable change. The frontend joins them into
    a bullet list at the top of the side-by-side diff.

    Examples:
    - "Equity max changing from 70 to 75"
    - "Single-position limit unchanged"
    - "Adding 'tobacco stocks' to prohibited list"
    - "Removing 'XYZ Corp' from prohibited list"
    """
    if diff.is_empty:
        return ["No changes"]

    out: list[str] = []
    for change in diff.numeric_changes:
        # Capitalise first letter of label for nicer copy.
        label = change.label[0].upper() + change.label[1:]
        out.append(
            f"{label} changing from {change.old_value} to {change.new_value}"
        )
    for added in diff.prohibited_change.added:
        out.append(f"Adding {added!r} to prohibited list")
    for removed in diff.prohibited_change.removed:
        out.append(f"Removing {removed!r} from prohibited list")
    return out


# ---------------------------------------------------------------------------
# Impact analysis (FR 12.2 §4.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuralImpact:
    """One structural-diff entry expanded with brief explanation."""

    label: str
    explanation: str


@dataclass(frozen=True)
class PortfolioImplicationsPlaceholder:
    """The cluster 2 placeholder panel — lights up in cluster 4 when
    holdings exist for the investor.

    The frontend reads ``status="cluster_4_placeholder"`` to render the
    reserved panel; future clusters that integrate holdings flip
    ``status="populated"`` and fill in ``rows``.
    """

    status: str = "cluster_4_placeholder"
    message: str = (
        "Portfolio analysis will be available when holdings data is loaded "
        "for this investor (cluster 4 onwards). For now, structural changes "
        "are visible above. Approving this amendment will not affect the "
        "portfolio until holdings data is integrated."
    )


@dataclass(frozen=True)
class ImpactAnalysis:
    """The three-subsection impact-analysis panel below the diff."""

    structural: tuple[StructuralImpact, ...]
    portfolio_implications: PortfolioImplicationsPlaceholder
    activation_summary: str


def build_impact_analysis(
    *,
    diff: MandateDiff,
    proposed: MandateVersionRead,
    active: MandateVersionRead,
) -> ImpactAnalysis:
    """Build the three-subsection impact analysis envelope.

    Cluster 2 ships:
    - Structural diff with brief explanations per change.
    - Portfolio implications: cluster 4 placeholder (always).
    - Activation summary: one-line "what approval will do".
    """
    structural = tuple(
        StructuralImpact(
            label=_explain_label(change),
            explanation=_explain_change(change),
        )
        for change in diff.numeric_changes
    ) + tuple(
        StructuralImpact(
            label=f"Add {item!r} to prohibited list",
            explanation=(
                f"The governance gate will block any holding matching "
                f"{item!r} once approved."
            ),
        )
        for item in diff.prohibited_change.added
    ) + tuple(
        StructuralImpact(
            label=f"Remove {item!r} from prohibited list",
            explanation=(
                f"Holdings matching {item!r} will no longer be blocked by "
                "the prohibited-instruments rule."
            ),
        )
        for item in diff.prohibited_change.removed
    )

    activation_summary = (
        f"Approving will activate version {proposed.version_number} of the "
        f"mandate. The current active version {active.version_number} will "
        "be archived but retained for audit. No automatic rebalancing is "
        "triggered."
    )

    return ImpactAnalysis(
        structural=structural,
        portfolio_implications=PortfolioImplicationsPlaceholder(),
        activation_summary=activation_summary,
    )


def _explain_label(change: NumericFieldChange) -> str:
    label = change.label[0].upper() + change.label[1:]
    return f"{label}: {change.old_value}% → {change.new_value}%"


def _explain_change(change: NumericFieldChange) -> str:
    delta = change.new_value - change.old_value
    direction = "increasing" if delta > 0 else "decreasing"
    return (
        f"{change.label.capitalize()} {direction} by {abs(delta)} "
        f"percentage point{'s' if abs(delta) != 1 else ''}; "
        f"previously {change.old_value}%, now {change.new_value}%."
    )
