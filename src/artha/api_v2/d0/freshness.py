"""FreshnessSLA cross-cutting infrastructure (FR Entry 10.5).

Pure-Python computation of freshness status from a ``last_modified_at``
timestamp + a per-entity-table threshold. Threshold lookup hits a static
configuration map seeded at module import time; cluster 3 keeps this in
code (per cluster 3 ideation §3.1 working answer).

The three-tier freshness status (FR 10.5 §2.2):

- ``fresh``: now - last_modified_at < threshold
- ``stale``: threshold <= delta < 2 * threshold
- ``very_stale``: delta >= 2 * threshold
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

FreshnessStatus = Literal["fresh", "stale", "very_stale"]


# ---------------------------------------------------------------------------
# Default thresholds (FR 10.5 §2.1)
# ---------------------------------------------------------------------------

#: Per-canonical-entity-table threshold in seconds. Defaults align with
#: the FR section §2.1 working defaults; deployments can override via
#: :func:`set_freshness_threshold`.
_DEFAULT_THRESHOLDS_SECONDS: dict[str, int] = {
    # Cluster 3 D0 entities
    "instruments": 86_400,         # 24 hours
    "macro_snapshots": 604_800,    # 7 days
    "industry_reports": 7_776_000, # 90 days

    # Cluster 1 entities (carried forward)
    "investors": 2_592_000,        # 30 days
    "households": 2_592_000,       # 30 days

    # Cluster 2 entities (carried forward)
    "mandates": 31_536_000,        # 1 year
    "mandate_versions": 31_536_000, # 1 year
}


_thresholds: dict[str, int] = dict(_DEFAULT_THRESHOLDS_SECONDS)


# ---------------------------------------------------------------------------
# Threshold lookup + override
# ---------------------------------------------------------------------------


def get_threshold_seconds(entity_table: str) -> int:
    """Return the freshness threshold (seconds) for a canonical entity table.

    Falls back to the largest default (1 year) for unknown tables so
    new entity tables can't accidentally trip a stale flag before
    they've been wired into the freshness configuration.
    """
    return _thresholds.get(entity_table, 31_536_000)


def set_freshness_threshold(entity_table: str, seconds: int) -> None:
    """Override the threshold for an entity table (deployment + test use)."""
    _thresholds[entity_table] = seconds


def reset_thresholds() -> None:
    """Test-only helper: restore the default threshold map."""
    _thresholds.clear()
    _thresholds.update(_DEFAULT_THRESHOLDS_SECONDS)


def list_thresholds() -> dict[str, int]:
    """Return a copy of the threshold map (for the admin UI)."""
    return dict(_thresholds)


# ---------------------------------------------------------------------------
# Freshness computation (FR 10.5 §2.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FreshnessResult:
    """One freshness lookup's output."""

    status: FreshnessStatus
    age_seconds: int
    threshold_seconds: int


def compute_freshness(
    *,
    entity_table: str,
    last_modified_at: datetime | None,
    now: datetime | None = None,
) -> FreshnessResult:
    """Compute freshness for an entity given its ``last_modified_at``.

    A ``None`` timestamp is treated as ``very_stale`` — entities with no
    last-modified info are conservatively flagged.
    """
    threshold = get_threshold_seconds(entity_table)
    if last_modified_at is None:
        return FreshnessResult(
            status="very_stale",
            age_seconds=2**31 - 1,  # sentinel "infinity-ish"
            threshold_seconds=threshold,
        )

    current = now or datetime.now(timezone.utc)
    if last_modified_at.tzinfo is None:
        # Naïve timestamp — assume UTC. Cluster 3 stores everything as
        # tz-aware via DateTime(timezone=True), but defensive against
        # legacy seed data.
        last_modified_at = last_modified_at.replace(tzinfo=timezone.utc)
    delta = (current - last_modified_at).total_seconds()
    age_seconds = max(0, int(delta))

    if delta < threshold:
        status: FreshnessStatus = "fresh"
    elif delta < 2 * threshold:
        status = "stale"
    else:
        status = "very_stale"

    return FreshnessResult(
        status=status,
        age_seconds=age_seconds,
        threshold_seconds=threshold,
    )


def threshold_as_human(seconds: int) -> str:
    """Render a threshold seconds value as a human-readable string for the UI."""
    delta = timedelta(seconds=seconds)
    days = delta.days
    if days >= 365:
        return f"{days // 365} year{'s' if days >= 730 else ''}"
    if days >= 30:
        return f"{days // 30} month{'s' if days >= 60 else ''}"
    if days >= 1:
        return f"{days} day{'s' if days >= 2 else ''}"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours} hour{'s' if hours >= 2 else ''}"
    minutes = max(1, delta.seconds // 60)
    return f"{minutes} minute{'s' if minutes >= 2 else ''}"
