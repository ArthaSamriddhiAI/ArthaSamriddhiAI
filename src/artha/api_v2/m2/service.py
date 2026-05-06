"""M2 service helpers — query + write across the model portfolio surfaces.

Cluster 4 reads dominate writes; this module exposes:

- Instrument-with-tags listing + filtering (chunks 4.1, 4.2)
- Per-cell preferred portfolio reads (chunks 4.1, 4.3)
- Health summary aggregation (chunk 4.1 §implementation_notes)
- Tag write helpers (chunk 4.2)
- Preferred portfolio entry write helpers (chunk 4.3)

The router stays thin — one helper per endpoint or operation; the SQL
lives here so tests can pin both layers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.m2 import cells
from artha.api_v2.m2.event_names import (
    INSTRUMENT_TAGS_CHANGED,
    MODEL_PORTFOLIO_TAGS_BULK_RESET,
    PREFERRED_PORTFOLIO_ENTRY_CREATED,
    PREFERRED_PORTFOLIO_ENTRY_DELETED,
    PREFERRED_PORTFOLIO_ENTRY_MODIFIED,
    PREFERRED_PORTFOLIO_ENTRY_WITHOUT_MATCHING_TAG,
)
from artha.api_v2.m2.models import PreferredPortfolioEntry
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Instrument tag-based queries
# ---------------------------------------------------------------------------


async def list_instruments_with_tags(
    db: AsyncSession,
    *,
    asset_class: str | None = None,
    vehicle_type: str | None = None,
    sebi_category: str | None = None,
    tag_includes: list[str] | None = None,
    tag_excludes: list[str] | None = None,
    untagged_only: bool = False,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Instrument], int]:
    """Filtered + paginated instrument-with-tags query.

    Tag filtering uses SQLite's ``json_each`` / Postgres' JSON contains
    semantics depending on the engine. Cluster 4 keeps the SQLite-compatible
    string-substring fallback for simplicity (cluster 4 ideation §3.1
    working answer); production-grade Postgres-specific GIN-backed filters
    are deferred to cluster 17.

    Substring matching on a JSON-encoded tag list is safe because cell
    identifiers are unambiguous tokens (``"aggressive_long_term"`` doesn't
    appear as a substring inside any other valid tag), so we can use
    ``model_portfolio_tags::text LIKE '%tag%'`` patterns without false
    positives.
    """
    base = select(Instrument)
    count_base = select(func.count()).select_from(Instrument)

    filters: list = []
    if asset_class is not None:
        filters.append(Instrument.asset_class == asset_class)
    if vehicle_type is not None:
        filters.append(Instrument.vehicle_type == vehicle_type)
    if sebi_category is not None:
        filters.append(Instrument.sebi_category == sebi_category)
    if search is not None and search.strip():
        like = f"%{search.strip()}%"
        filters.append(
            or_(
                Instrument.name.ilike(like),
                Instrument.isin.ilike(like),
                Instrument.amfi_scheme_code.ilike(like),
                Instrument.exchange_ticker.ilike(like),
            )
        )

    # Tag inclusion: each tag must appear in the JSON-encoded array.
    if tag_includes:
        for tag in tag_includes:
            filters.append(Instrument.model_portfolio_tags.cast(String).like(f'%"{tag}"%'))

    # Tag exclusion: tag must NOT appear.
    if tag_excludes:
        for tag in tag_excludes:
            filters.append(
                ~Instrument.model_portfolio_tags.cast(String).like(f'%"{tag}"%')
            )

    if untagged_only:
        # Empty JSON array == "[]" string after cast.
        filters.append(Instrument.model_portfolio_tags.cast(String) == "[]")

    if filters:
        base = base.where(and_(*filters))
        count_base = count_base.where(and_(*filters))

    base = base.order_by(Instrument.name.asc()).limit(limit).offset(offset)

    rows = list((await db.execute(base)).scalars())
    total = (await db.execute(count_base)).scalar_one() or 0
    return rows, int(total)


async def list_instruments_tagged_for_cell(
    db: AsyncSession,
    *,
    cell_id: str,
    exclude_already_preferred: bool = False,
    limit: int = 200,
) -> list[Instrument]:
    """All instruments tagged for the cell. Used by the chunk 4.3 add-entry
    picker (with ``exclude_already_preferred=True``) and by the chunk 4.2
    "tagged but not preferred" filter.
    """
    if cell_id not in cells.ALL_CELLS:
        raise ValueError(f"Unknown cell_id {cell_id!r}")

    risk_profile, horizon = cells.split_cell(cell_id)

    stmt = (
        select(Instrument)
        .where(Instrument.model_portfolio_tags.cast(String).like(f'%"{cell_id}"%'))
        .order_by(Instrument.name.asc())
        .limit(limit)
    )

    if exclude_already_preferred:
        already_preferred = (
            select(PreferredPortfolioEntry.instrument_id).where(
                PreferredPortfolioEntry.risk_profile == risk_profile,
                PreferredPortfolioEntry.horizon == horizon,
            )
        ).scalar_subquery()
        stmt = stmt.where(Instrument.instrument_id.notin_(already_preferred))

    return list((await db.execute(stmt)).scalars())


async def get_instrument(
    db: AsyncSession, *, instrument_id: str
) -> Instrument | None:
    return (
        await db.execute(
            select(Instrument).where(Instrument.instrument_id == instrument_id)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Preferred portfolio cell operations
# ---------------------------------------------------------------------------


async def list_cell_entries(
    db: AsyncSession,
    *,
    risk_profile: str,
    horizon: str,
) -> list[PreferredPortfolioEntry]:
    """All entries in one cell, ordered by ``(position_role, rank)``."""
    role_order_case = {"core": 1, "satellite": 2, "optional": 3}
    stmt = select(PreferredPortfolioEntry).where(
        PreferredPortfolioEntry.risk_profile == risk_profile,
        PreferredPortfolioEntry.horizon == horizon,
    )
    rows = list((await db.execute(stmt)).scalars())
    rows.sort(
        key=lambda r: (role_order_case.get(r.position_role, 99), r.rank_within_role)
    )
    return rows


async def find_entry_by_natural_key(
    db: AsyncSession,
    *,
    risk_profile: str,
    horizon: str,
    instrument_id: str,
) -> PreferredPortfolioEntry | None:
    return (
        await db.execute(
            select(PreferredPortfolioEntry).where(
                PreferredPortfolioEntry.risk_profile == risk_profile,
                PreferredPortfolioEntry.horizon == horizon,
                PreferredPortfolioEntry.instrument_id == instrument_id,
            )
        )
    ).scalar_one_or_none()


async def get_entry(
    db: AsyncSession, *, entry_id: str
) -> PreferredPortfolioEntry | None:
    return (
        await db.execute(
            select(PreferredPortfolioEntry).where(
                PreferredPortfolioEntry.entry_id == entry_id
            )
        )
    ).scalar_one_or_none()


async def list_entries_for_instrument(
    db: AsyncSession, *, instrument_id: str
) -> list[PreferredPortfolioEntry]:
    """All cells where the instrument appears (reverse lookup)."""
    return list(
        (
            await db.execute(
                select(PreferredPortfolioEntry)
                .where(PreferredPortfolioEntry.instrument_id == instrument_id)
                .order_by(
                    PreferredPortfolioEntry.risk_profile,
                    PreferredPortfolioEntry.horizon,
                )
            )
        ).scalars()
    )


async def matrix_overview(
    db: AsyncSession,
) -> tuple[
    dict[tuple[str, str], dict[str, int]],
    dict[tuple[str, str], datetime],
    dict[tuple[str, str], list[str]],
]:
    """Aggregate counts + last_modified + top-3 core names per cell.

    Returns three dicts keyed by ``(risk_profile, horizon)``:

    - role-count dict mapping each cell to ``{core, satellite, optional}``
      counts (zero-filled for cells with no entries)
    - last-modified-at dict (only for cells with ≥1 entry)
    - top-3 core names dict (lowest rank wins)
    """
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for rp in cells.RISK_PROFILES:
        for h in cells.HORIZONS:
            counts[(rp, h)] = {"core": 0, "satellite": 0, "optional": 0}

    role_count_rows = (
        await db.execute(
            select(
                PreferredPortfolioEntry.risk_profile,
                PreferredPortfolioEntry.horizon,
                PreferredPortfolioEntry.position_role,
                func.count().label("c"),
            ).group_by(
                PreferredPortfolioEntry.risk_profile,
                PreferredPortfolioEntry.horizon,
                PreferredPortfolioEntry.position_role,
            )
        )
    ).all()
    for risk_profile, horizon, role, count in role_count_rows:
        counts[(risk_profile, horizon)][role] = int(count)

    last_modified_rows = (
        await db.execute(
            select(
                PreferredPortfolioEntry.risk_profile,
                PreferredPortfolioEntry.horizon,
                func.max(PreferredPortfolioEntry.last_modified_at).label("lm"),
            ).group_by(
                PreferredPortfolioEntry.risk_profile,
                PreferredPortfolioEntry.horizon,
            )
        )
    ).all()
    last_modified: dict[tuple[str, str], datetime] = {}
    for risk_profile, horizon, lm in last_modified_rows:
        if lm is not None:
            last_modified[(risk_profile, horizon)] = lm

    # Top-3 core names per cell, joining instruments for the name.
    top_cores_rows = list(
        (
            await db.execute(
                select(
                    PreferredPortfolioEntry.risk_profile,
                    PreferredPortfolioEntry.horizon,
                    PreferredPortfolioEntry.rank_within_role,
                    Instrument.name,
                )
                .join(
                    Instrument,
                    Instrument.instrument_id
                    == PreferredPortfolioEntry.instrument_id,
                )
                .where(PreferredPortfolioEntry.position_role == "core")
                .order_by(
                    PreferredPortfolioEntry.risk_profile,
                    PreferredPortfolioEntry.horizon,
                    PreferredPortfolioEntry.rank_within_role.asc(),
                )
            )
        )
    )
    top_cores: dict[tuple[str, str], list[str]] = {}
    for risk_profile, horizon, _, name in top_cores_rows:
        bucket = top_cores.setdefault((risk_profile, horizon), [])
        if len(bucket) < 3:
            bucket.append(name)

    return counts, last_modified, top_cores


# ---------------------------------------------------------------------------
# Tag write helpers (chunk 4.2)
# ---------------------------------------------------------------------------


async def update_instrument_tags(
    db: AsyncSession,
    *,
    instrument: Instrument,
    new_tags: list[str],
    actor_user_id: str,
    change_type: str = "single",
    firm_id: str | None = None,
) -> Instrument:
    """Replace an instrument's tag set. Caller validates against
    :data:`cells.ALL_CELLS` first.
    """
    old_tags = list(instrument.model_portfolio_tags or [])
    now = datetime.now(timezone.utc)
    # Dedupe + preserve matrix-row order so JSON encoding is deterministic.
    canonical = [t for t in cells.ALL_CELLS if t in set(new_tags)]
    instrument.model_portfolio_tags = canonical
    instrument.model_portfolio_tags_modified_at = now
    instrument.model_portfolio_tags_modified_by = actor_user_id
    instrument.last_modified_at = now
    await db.flush()
    await emit_event(
        db,
        event_name=INSTRUMENT_TAGS_CHANGED,
        payload={
            "instrument_id": instrument.instrument_id,
            "old_tags": old_tags,
            "new_tags": list(instrument.model_portfolio_tags),
            "actor": actor_user_id,
            "change_type": change_type,
        },
        firm_id=firm_id,
    )
    return instrument


def validate_tag_set(tags: list[str]) -> list[str]:
    """Validate + canonicalise a tag list. Raises :class:`ValueError` on
    unknown tags. Duplicates are silently deduped; the result is in
    matrix-row order regardless of input order.
    """
    seen: set[str] = set()
    for t in tags:
        if t not in cells.ALL_CELLS:
            raise ValueError(f"Unknown cell tag: {t!r}")
        seen.add(t)
    return [t for t in cells.ALL_CELLS if t in seen]


async def fetch_instruments_by_ids(
    db: AsyncSession, *, instrument_ids: list[str]
) -> list[Instrument]:
    """Bulk fetch instruments by ID, preserving caller's order."""
    if not instrument_ids:
        return []
    rows = list(
        (
            await db.execute(
                select(Instrument).where(
                    Instrument.instrument_id.in_(instrument_ids)
                )
            )
        ).scalars()
    )
    by_id = {r.instrument_id: r for r in rows}
    return [by_id[i] for i in instrument_ids if i in by_id]


async def bulk_add_tag(
    db: AsyncSession,
    *,
    tag: str,
    instrument_ids: list[str],
    actor_user_id: str,
    firm_id: str | None = None,
) -> dict[str, int]:
    """Add ``tag`` to each instrument that doesn't already carry it.

    Returns ``{"affected": N, "skipped": N}``: ``skipped`` covers
    instruments that already had the tag (no write needed). All writes
    happen in the caller's transaction; emits one bulk T1 event with the
    full affected list.
    """
    if tag not in cells.ALL_CELLS:
        raise ValueError(f"Unknown cell tag: {tag!r}")
    instruments = await fetch_instruments_by_ids(db, instrument_ids=instrument_ids)
    affected: list[str] = []
    skipped: list[str] = []
    now = datetime.now(timezone.utc)
    for inst in instruments:
        current = set(inst.model_portfolio_tags or [])
        if tag in current:
            skipped.append(inst.instrument_id)
            continue
        current.add(tag)
        inst.model_portfolio_tags = [t for t in cells.ALL_CELLS if t in current]
        inst.model_portfolio_tags_modified_at = now
        inst.model_portfolio_tags_modified_by = actor_user_id
        inst.last_modified_at = now
        affected.append(inst.instrument_id)
    if affected:
        await db.flush()
        await emit_event(
            db,
            event_name=INSTRUMENT_TAGS_CHANGED,
            payload={
                "operation": "bulk_add",
                "tag": tag,
                "affected_instrument_ids": affected,
                "skipped_instrument_ids": skipped,
                "actor": actor_user_id,
                "change_type": "bulk",
            },
            firm_id=firm_id,
        )
    return {
        "affected": len(affected),
        "skipped": len(skipped),
        "failed": len(instrument_ids) - len(affected) - len(skipped),
    }


async def bulk_remove_tag(
    db: AsyncSession,
    *,
    tag: str,
    instrument_ids: list[str],
    actor_user_id: str,
    firm_id: str | None = None,
) -> dict[str, int]:
    """Remove ``tag`` from each instrument that carries it.

    Returns ``{"affected": N, "skipped": N, "failed": N}``: ``skipped``
    covers instruments that didn't have the tag.
    """
    if tag not in cells.ALL_CELLS:
        raise ValueError(f"Unknown cell tag: {tag!r}")
    instruments = await fetch_instruments_by_ids(db, instrument_ids=instrument_ids)
    affected: list[str] = []
    skipped: list[str] = []
    now = datetime.now(timezone.utc)
    for inst in instruments:
        current = set(inst.model_portfolio_tags or [])
        if tag not in current:
            skipped.append(inst.instrument_id)
            continue
        current.discard(tag)
        inst.model_portfolio_tags = [t for t in cells.ALL_CELLS if t in current]
        inst.model_portfolio_tags_modified_at = now
        inst.model_portfolio_tags_modified_by = actor_user_id
        inst.last_modified_at = now
        affected.append(inst.instrument_id)
    if affected:
        await db.flush()
        await emit_event(
            db,
            event_name=INSTRUMENT_TAGS_CHANGED,
            payload={
                "operation": "bulk_remove",
                "tag": tag,
                "affected_instrument_ids": affected,
                "skipped_instrument_ids": skipped,
                "actor": actor_user_id,
                "change_type": "bulk",
            },
            firm_id=firm_id,
        )
    return {
        "affected": len(affected),
        "skipped": len(skipped),
        "failed": len(instrument_ids) - len(affected) - len(skipped),
    }


async def bulk_replace_tags(
    db: AsyncSession,
    *,
    tags: list[str],
    instrument_ids: list[str],
    actor_user_id: str,
    firm_id: str | None = None,
) -> dict[str, int]:
    """Replace each selected instrument's tag set with the given ``tags``."""
    canonical = validate_tag_set(tags)
    instruments = await fetch_instruments_by_ids(db, instrument_ids=instrument_ids)
    affected: list[str] = []
    now = datetime.now(timezone.utc)
    for inst in instruments:
        old = list(inst.model_portfolio_tags or [])
        if old == canonical:
            continue  # skip — no change needed
        inst.model_portfolio_tags = canonical
        inst.model_portfolio_tags_modified_at = now
        inst.model_portfolio_tags_modified_by = actor_user_id
        inst.last_modified_at = now
        affected.append(inst.instrument_id)
    if affected:
        await db.flush()
        await emit_event(
            db,
            event_name=INSTRUMENT_TAGS_CHANGED,
            payload={
                "operation": "bulk_replace",
                "new_tags": canonical,
                "affected_instrument_ids": affected,
                "actor": actor_user_id,
                "change_type": "bulk",
            },
            firm_id=firm_id,
        )
    return {
        "affected": len(affected),
        "skipped": len(instruments) - len(affected),
        "failed": len(instrument_ids) - len(instruments),
    }


async def reset_tags_to_default(
    db: AsyncSession,
    *,
    instrument_ids: list[str] | None,
    actor_user_id: str,
    firm_id: str | None = None,
) -> dict[str, int]:
    """Reset instruments to their default tag set (FR 13.3 §2 rules).

    ``instrument_ids=None`` resets the whole universe; a list resets only
    the named subset. Unlike :func:`apply_default_tags`, this OVERWRITES
    existing tag sets — used by the chunk 4.2 admin "reset to default"
    affordance with explicit confirmation.
    """
    from artha.api_v2.m2 import default_tags

    if instrument_ids is None:
        rows = list((await db.execute(select(Instrument))).scalars())
    else:
        rows = await fetch_instruments_by_ids(db, instrument_ids=instrument_ids)

    affected: list[str] = []
    failed: list[str] = []
    now = datetime.now(timezone.utc)
    for inst in rows:
        new_tags = default_tags.default_tags_for_instrument(
            vehicle_type=inst.vehicle_type,
            sebi_category=inst.sebi_category,
            name=inst.name,
            amc_name=inst.amc_name,
            market_cap_rank=None,
        )
        if not new_tags:
            failed.append(inst.instrument_id)
            continue
        canonical = [t for t in cells.ALL_CELLS if t in new_tags]
        inst.model_portfolio_tags = canonical
        inst.model_portfolio_tags_modified_at = now
        inst.model_portfolio_tags_modified_by = actor_user_id
        inst.last_modified_at = now
        affected.append(inst.instrument_id)
    if affected:
        await db.flush()
        await emit_event(
            db,
            event_name=MODEL_PORTFOLIO_TAGS_BULK_RESET,
            payload={
                "scope": "all" if instrument_ids is None else "filtered",
                "affected_instrument_ids": affected,
                "failed_instrument_ids": failed,
                "actor": actor_user_id,
            },
            firm_id=firm_id,
        )
    return {
        "affected": len(affected),
        "skipped": 0,
        "failed": len(failed),
    }


# ---------------------------------------------------------------------------
# Preferred portfolio write helpers (chunk 4.3)
# ---------------------------------------------------------------------------


async def create_preferred_entry(
    db: AsyncSession,
    *,
    risk_profile: str,
    horizon: str,
    instrument_id: str,
    position_role: str,
    rank_within_role: int,
    notes: str | None,
    actor_user_id: str,
    created_via: str = "admin_ui",
    firm_id: str | None = None,
) -> PreferredPortfolioEntry:
    """Insert a PreferredPortfolioEntry; emits T1 + soft-validation warning
    when the instrument lacks the matching tag.
    """
    now = datetime.now(timezone.utc)
    entry = PreferredPortfolioEntry(
        entry_id=str(ULID()),
        risk_profile=risk_profile,
        horizon=horizon,
        instrument_id=instrument_id,
        position_role=position_role,
        rank_within_role=max(0, int(rank_within_role)),
        notes=notes,
        created_at=now,
        created_by=actor_user_id,
        created_via=created_via,
        last_modified_at=now,
        last_modified_by=actor_user_id,
        schema_version=1,
    )
    db.add(entry)
    await db.flush()

    await emit_event(
        db,
        event_name=PREFERRED_PORTFOLIO_ENTRY_CREATED,
        payload={
            "entry_id": entry.entry_id,
            "risk_profile": risk_profile,
            "horizon": horizon,
            "instrument_id": instrument_id,
            "position_role": position_role,
            "rank_within_role": entry.rank_within_role,
            "actor": actor_user_id,
            "created_via": created_via,
        },
        firm_id=firm_id,
    )

    # Soft validation: warn if instrument isn't tagged for this cell.
    inst = await get_instrument(db, instrument_id=instrument_id)
    target_cell = cells.cell_id(risk_profile, horizon)
    if inst is not None and target_cell not in (inst.model_portfolio_tags or []):
        await emit_event(
            db,
            event_name=PREFERRED_PORTFOLIO_ENTRY_WITHOUT_MATCHING_TAG,
            payload={
                "entry_id": entry.entry_id,
                "instrument_id": instrument_id,
                "cell_id": target_cell,
                "current_tags": list(inst.model_portfolio_tags or []),
            },
            firm_id=firm_id,
        )

    return entry


async def modify_preferred_entry(
    db: AsyncSession,
    *,
    entry: PreferredPortfolioEntry,
    position_role: str | None = None,
    rank_within_role: int | None = None,
    notes: str | None = None,
    actor_user_id: str,
    firm_id: str | None = None,
) -> PreferredPortfolioEntry:
    """Update an entry's role / rank / notes (any combination)."""
    before = {
        "position_role": entry.position_role,
        "rank_within_role": entry.rank_within_role,
        "notes": entry.notes,
    }
    now = datetime.now(timezone.utc)
    if position_role is not None:
        entry.position_role = position_role
    if rank_within_role is not None:
        entry.rank_within_role = max(0, int(rank_within_role))
    if notes is not None:
        entry.notes = notes
    entry.last_modified_at = now
    entry.last_modified_by = actor_user_id
    await db.flush()
    await emit_event(
        db,
        event_name=PREFERRED_PORTFOLIO_ENTRY_MODIFIED,
        payload={
            "entry_id": entry.entry_id,
            "before": before,
            "after": {
                "position_role": entry.position_role,
                "rank_within_role": entry.rank_within_role,
                "notes": entry.notes,
            },
            "actor": actor_user_id,
        },
        firm_id=firm_id,
    )
    return entry


async def delete_preferred_entry(
    db: AsyncSession,
    *,
    entry: PreferredPortfolioEntry,
    actor_user_id: str,
    firm_id: str | None = None,
) -> None:
    payload = {
        "entry_id": entry.entry_id,
        "risk_profile": entry.risk_profile,
        "horizon": entry.horizon,
        "instrument_id": entry.instrument_id,
        "position_role": entry.position_role,
        "rank_within_role": entry.rank_within_role,
        "actor": actor_user_id,
    }
    await db.delete(entry)
    await db.flush()
    await emit_event(
        db,
        event_name=PREFERRED_PORTFOLIO_ENTRY_DELETED,
        payload=payload,
        firm_id=firm_id,
    )


# ---------------------------------------------------------------------------
# Health summary aggregation
# ---------------------------------------------------------------------------


async def health_summary(
    db: AsyncSession,
) -> dict[str, Any]:
    """Aggregate health summary used by the chunk 4.1 health endpoint."""
    total = (
        await db.execute(select(func.count()).select_from(Instrument))
    ).scalar_one() or 0
    untagged = (
        await db.execute(
            select(func.count())
            .select_from(Instrument)
            .where(Instrument.model_portfolio_tags.cast(String) == "[]")
        )
    ).scalar_one() or 0
    tagged = total - untagged

    total_preferred = (
        await db.execute(
            select(func.count()).select_from(PreferredPortfolioEntry)
        )
    ).scalar_one() or 0

    counts, last_modified, _ = await matrix_overview(db)

    last_tag = (
        await db.execute(
            select(func.max(Instrument.model_portfolio_tags_modified_at))
        )
    ).scalar_one_or_none()
    last_pref = (
        await db.execute(
            select(func.max(PreferredPortfolioEntry.last_modified_at))
        )
    ).scalar_one_or_none()

    by_cell: dict[str, dict[str, int]] = {}
    for (rp, h), role_counts in counts.items():
        by_cell[cells.cell_id(rp, h)] = role_counts

    return {
        "tagged_instruments_count": int(tagged),
        "untagged_instruments_count": int(untagged),
        "total_instruments": int(total),
        "total_preferred_entries": int(total_preferred),
        "preferred_entries_by_cell": by_cell,
        "last_tag_modification_at": last_tag,
        "last_preferred_modification_at": last_pref,
    }
