"""Default loaders for the model portfolio (FR Entry 13.3 §3 + §5).

Two loaders run at chunk 4.1 startup:

- :func:`apply_default_tags` — iterates instruments with empty tag arrays
  and applies the rules from :mod:`default_tags`. Idempotent: only writes
  when tags are currently empty (so CIO customisations are preserved).
- :func:`load_default_preferred_portfolio` — reads
  ``data/fixtures/default_model_portfolio.json``, looks up instruments by
  external identifier (AMFI code, ISIN, SEBI registration, internal
  lookup) and inserts PreferredPortfolioEntry rows. Idempotent: skips
  entries that already exist for the (cell, instrument) pair.

Both loaders emit T1 telemetry per entity processed so the audit-role
admin UI can see exactly what defaulting did at startup.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.m2 import cells, default_tags
from artha.api_v2.m2.event_names import (
    DEFAULT_PREFERRED_ENTRY_LOADED,
    DEFAULT_PREFERRED_ENTRY_SKIPPED_MISSING_INSTRUMENT,
    INSTRUMENT_DEFAULT_TAGGING_FAILED,
    INSTRUMENT_TAGS_DEFAULTED,
)
from artha.api_v2.m2.models import PreferredPortfolioEntry
from artha.api_v2.observability.t1 import emit_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default tagging
# ---------------------------------------------------------------------------


async def apply_default_tags(
    db: AsyncSession,
    *,
    actor_user_id: str = "system_default_loader",
    firm_id: str | None = None,
) -> dict[str, int]:
    """Apply default tags to every instrument with an empty tag array.

    Returns a count summary: ``{"tagged": N, "skipped_already_tagged": N,
    "failed_classification": N}``.

    Idempotent — re-running with the same DB state produces identical
    output. CIO customisations on instruments with non-empty tags are
    preserved (the loader only writes when ``model_portfolio_tags`` is
    currently empty).
    """
    tagged = 0
    skipped = 0
    failed = 0

    rows = list(
        (await db.execute(select(Instrument))).scalars()
    )
    for inst in rows:
        if inst.model_portfolio_tags:
            skipped += 1
            continue

        tags = default_tags.default_tags_for_instrument(
            vehicle_type=inst.vehicle_type,
            sebi_category=inst.sebi_category,
            name=inst.name,
            amc_name=inst.amc_name,
            # Cluster 4 doesn't yet store market_cap_rank on Instrument; cluster
            # 17 will. For chunk 4.1 stocks fall through to the rank=None
            # branch which yields the mid-cap default — a deliberate
            # conservative choice (FR 13.3 §3.3).
            market_cap_rank=None,
        )

        if not tags:
            await emit_event(
                db,
                event_name=INSTRUMENT_DEFAULT_TAGGING_FAILED,
                payload={
                    "instrument_id": inst.instrument_id,
                    "name": inst.name,
                    "vehicle_type": inst.vehicle_type,
                    "sebi_category": inst.sebi_category,
                    "reason": "no rule matched",
                },
                firm_id=firm_id,
            )
            failed += 1
            continue

        # Sort tags in matrix-row order for deterministic JSON encoding.
        ordered = [t for t in cells.ALL_CELLS if t in tags]
        inst.model_portfolio_tags = ordered
        # Note: leave model_portfolio_tags_modified_at NULL — defaults are
        # NOT considered "edited by a human" (FR 10.7 §4.4).
        tagged += 1
        await emit_event(
            db,
            event_name=INSTRUMENT_TAGS_DEFAULTED,
            payload={
                "instrument_id": inst.instrument_id,
                "vehicle_type": inst.vehicle_type,
                "sebi_category": inst.sebi_category,
                "applied_tags": ordered,
                "actor": actor_user_id,
            },
            firm_id=firm_id,
        )

    if rows:
        await db.flush()

    return {
        "tagged": tagged,
        "skipped_already_tagged": skipped,
        "failed_classification": failed,
    }


# ---------------------------------------------------------------------------
# Default preferred portfolio
# ---------------------------------------------------------------------------


_VALID_LOOKUP_TYPES: frozenset[str] = frozenset(
    {"amfi_code", "isin", "sebi_registration", "internal_lookup"}
)


async def _resolve_instrument(
    db: AsyncSession,
    *,
    lookup_type: str,
    lookup_value: str,
) -> Instrument | None:
    """Translate an external identifier from the fixture to the local
    ``instrument_id``. Returns None when not found.

    The fixture ships portable identifiers (AMFI code, ISIN,
    sebi_registration, internal_lookup-by-name) so the same JSON works
    across deployments where ULIDs differ. The cluster 3 Instrument model
    stores ``amfi_scheme_code``, ``isin``, and ``exchange_ticker`` — we
    map external identifiers to those columns.
    """
    if lookup_type == "amfi_code":
        return (
            await db.execute(
                select(Instrument).where(
                    Instrument.amfi_scheme_code == str(lookup_value)
                )
            )
        ).scalar_one_or_none()
    if lookup_type == "isin":
        return (
            await db.execute(
                select(Instrument).where(Instrument.isin == str(lookup_value))
            )
        ).scalar_one_or_none()
    if lookup_type == "sebi_registration":
        # PMS / AIF stored their SEBI registration in the synthetic
        # exchange_ticker by the cluster 3 multi-source loader (chunk 3.2
        # addendum); fall through to ticker match.
        return (
            await db.execute(
                select(Instrument).where(
                    Instrument.exchange_ticker == str(lookup_value)
                )
            )
        ).scalar_one_or_none()
    if lookup_type == "internal_lookup":
        # Best-effort case-insensitive name match for unlisted equities.
        return (
            await db.execute(
                select(Instrument).where(
                    Instrument.name.ilike(str(lookup_value))
                )
            )
        ).scalar_one_or_none()
    return None


async def load_default_preferred_portfolio(
    db: AsyncSession,
    *,
    fixture_path: Path,
    actor_user_id: str = "system_default_loader",
    firm_id: str | None = None,
) -> dict[str, int]:
    """Read the JSON fixture + insert PreferredPortfolioEntry rows.

    Idempotent: skips entries whose ``(risk_profile, horizon, instrument)``
    triple already exists.

    Returns a count summary: ``{"loaded": N, "already_present": N,
    "skipped_missing_instrument": N, "skipped_invalid": N}``.
    """
    if not fixture_path.exists():
        logger.warning(
            "Default model portfolio fixture not found at %s; skipping load.",
            fixture_path,
        )
        return {
            "loaded": 0,
            "already_present": 0,
            "skipped_missing_instrument": 0,
            "skipped_invalid": 0,
        }

    with fixture_path.open("r", encoding="utf-8") as fh:
        fixture = json.load(fh)

    entries = fixture.get("preferred_portfolio_entries") or []
    loaded = 0
    already = 0
    missing = 0
    invalid = 0

    for raw in entries:
        try:
            risk_profile = raw["risk_profile"]
            horizon = raw["horizon"]
            position_role = raw["position_role"]
            rank = int(raw.get("rank_within_role", 0))
            lookup = raw["instrument_lookup"]
            lookup_type = lookup["external_identifier_type"]
            lookup_value = lookup["external_identifier_value"]
            notes = raw.get("notes")
        except (KeyError, ValueError, TypeError):
            invalid += 1
            continue

        if (
            risk_profile not in cells.RISK_PROFILES
            or horizon not in cells.HORIZONS
            or position_role not in ("core", "satellite", "optional")
            or lookup_type not in _VALID_LOOKUP_TYPES
        ):
            invalid += 1
            continue

        inst = await _resolve_instrument(
            db, lookup_type=lookup_type, lookup_value=str(lookup_value)
        )
        if inst is None:
            await emit_event(
                db,
                event_name=DEFAULT_PREFERRED_ENTRY_SKIPPED_MISSING_INSTRUMENT,
                payload={
                    "lookup_type": lookup_type,
                    "lookup_value": lookup_value,
                    "risk_profile": risk_profile,
                    "horizon": horizon,
                    "position_role": position_role,
                },
                firm_id=firm_id,
            )
            missing += 1
            continue

        # Idempotency check: skip if entry already exists.
        existing = (
            await db.execute(
                select(PreferredPortfolioEntry).where(
                    PreferredPortfolioEntry.risk_profile == risk_profile,
                    PreferredPortfolioEntry.horizon == horizon,
                    PreferredPortfolioEntry.instrument_id == inst.instrument_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            already += 1
            continue

        now = datetime.now(timezone.utc)
        entry = PreferredPortfolioEntry(
            entry_id=str(ULID()),
            risk_profile=risk_profile,
            horizon=horizon,
            instrument_id=inst.instrument_id,
            position_role=position_role,
            rank_within_role=max(0, rank),
            notes=notes,
            created_at=now,
            created_by=actor_user_id,
            created_via="default_loader",
            last_modified_at=now,
            last_modified_by=actor_user_id,
            schema_version=1,
        )
        db.add(entry)
        loaded += 1

        await emit_event(
            db,
            event_name=DEFAULT_PREFERRED_ENTRY_LOADED,
            payload={
                "entry_id": entry.entry_id,
                "risk_profile": risk_profile,
                "horizon": horizon,
                "instrument_id": inst.instrument_id,
                "position_role": position_role,
                "rank_within_role": entry.rank_within_role,
                "lookup_type": lookup_type,
                "lookup_value": lookup_value,
            },
            firm_id=firm_id,
        )

    if loaded:
        await db.flush()

    return {
        "loaded": loaded,
        "already_present": already,
        "skipped_missing_instrument": missing,
        "skipped_invalid": invalid,
    }
