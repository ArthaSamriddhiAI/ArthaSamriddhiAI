"""3x3 client-profile-matrix cell vocabulary (FR Entry 13.0 §3).

The model portfolio matrix has 9 cells, identified by ``(risk_profile,
horizon)`` pairs. Cell identifiers are flat snake-case strings used as
tag values on instruments and as discriminators on PreferredPortfolioEntry
rows.

Investor-side cluster 1 fields use slightly different naming
(``time_horizon`` ∈ ``{over_5_years, 3_to_5_years, under_3_years}``); the
mapping to model-portfolio horizons is ``over_5_years → long_term``,
``3_to_5_years → medium_term``, ``under_3_years → short_term``.
:func:`investor_to_cell` performs the lookup.
"""

from __future__ import annotations

from typing import Literal

RiskProfile = Literal["aggressive", "moderate", "conservative"]
Horizon = Literal["long_term", "medium_term", "short_term"]

RISK_PROFILES: tuple[RiskProfile, ...] = ("aggressive", "moderate", "conservative")
HORIZONS: tuple[Horizon, ...] = ("long_term", "medium_term", "short_term")

#: All 9 valid cell identifiers, sorted in matrix-row order
#: (aggressive_long, aggressive_medium, aggressive_short, moderate_long, ...).
ALL_CELLS: tuple[str, ...] = tuple(
    f"{rp}_{h}" for rp in RISK_PROFILES for h in HORIZONS
)


def cell_id(risk_profile: str, horizon: str) -> str:
    """Build a canonical cell identifier from ``(risk_profile, horizon)``.

    Validates both components against the enum and raises
    :class:`ValueError` on mismatch.
    """
    if risk_profile not in RISK_PROFILES:
        raise ValueError(
            f"Unknown risk_profile {risk_profile!r}; expected one of {RISK_PROFILES}"
        )
    if horizon not in HORIZONS:
        raise ValueError(
            f"Unknown horizon {horizon!r}; expected one of {HORIZONS}"
        )
    return f"{risk_profile}_{horizon}"


def split_cell(identifier: str) -> tuple[str, str]:
    """Reverse of :func:`cell_id`: split ``"moderate_long_term"`` →
    ``("moderate", "long_term")``."""
    if identifier not in ALL_CELLS:
        raise ValueError(f"Unknown cell identifier {identifier!r}")
    if identifier.startswith("aggressive_"):
        return "aggressive", identifier[len("aggressive_") :]
    if identifier.startswith("moderate_"):
        return "moderate", identifier[len("moderate_") :]
    return "conservative", identifier[len("conservative_") :]


def is_valid_cell(identifier: str) -> bool:
    """Cheap predicate — true iff the identifier is in :data:`ALL_CELLS`."""
    return identifier in ALL_CELLS


# ---------------------------------------------------------------------------
# Investor-side mapping (cluster 1 → cluster 4)
# ---------------------------------------------------------------------------


_INVESTOR_HORIZON_MAP: dict[str, Horizon] = {
    "over_5_years": "long_term",
    "3_to_5_years": "medium_term",
    "under_3_years": "short_term",
}


def investor_to_cell(
    *, risk_appetite: str | None, time_horizon: str | None
) -> str | None:
    """Compute the model-portfolio cell for an investor's profile.

    Returns ``None`` when either field is missing, so the investor profile
    UI can render the "incomplete profile" fallback.
    """
    if not risk_appetite or not time_horizon:
        return None
    if risk_appetite not in RISK_PROFILES:
        return None
    horizon = _INVESTOR_HORIZON_MAP.get(time_horizon)
    if horizon is None:
        return None
    return cell_id(risk_appetite, horizon)
