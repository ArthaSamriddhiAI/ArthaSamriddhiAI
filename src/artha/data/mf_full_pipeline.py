"""Full Mutual Fund NAV pipeline — ALL AMFI Regular plan schemes, 15 years.

Fetches the complete scheme list from AMFI India, filters for Regular
(non-Direct) plans, and downloads historical NAV via MFAPI.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from artha.data.models import MFNavRow, MFUniverseRow, PipelineRunRow

log = logging.getLogger(__name__)

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
MFAPI_BASE = "https://api.mfapi.in"
REQUEST_DELAY_SEC = 0.3
BACKFILL_YEARS = 15


def _parse_nav_date(date_str: str) -> date | None:
    try:
        parts = date_str.strip().split("-")
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        return None


async def fetch_all_regular_schemes() -> list[dict]:
    """Fetch all Regular plan MF schemes from AMFI master list."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(AMFI_NAV_URL)
        resp.raise_for_status()

    lines = resp.text.strip().split("\n")
    schemes = []

    for line in lines:
        if ";" not in line or not line[0].isdigit():
            continue
        parts = line.split(";")
        if len(parts) < 5:
            continue

        code = parts[0].strip()
        name = parts[3].strip()
        name_lower = name.lower()

        # Skip Direct plans
        if "direct" in name_lower:
            continue

        schemes.append({"scheme_code": code, "scheme_name": name})

    log.info(f"AMFI: {len(schemes)} Regular (non-Direct) schemes found")
    return schemes


async def sync_mf_universe(session: AsyncSession, schemes: list[dict]) -> int:
    """Upsert all Regular schemes into mf_universe table."""
    now = datetime.now(UTC)
    added = 0

    for scheme in schemes:
        code = scheme["scheme_code"]
        existing = await session.execute(
            select(MFUniverseRow).where(MFUniverseRow.scheme_code == code)
        )
        if existing.scalar_one_or_none() is None:
            session.add(MFUniverseRow(
                scheme_code=code,
                scheme_name=scheme["scheme_name"],
                added_at=now,
                active=True,
            ))
            added += 1

    await session.flush()
    total = (await session.execute(
        select(func.count()).select_from(MFUniverseRow).where(MFUniverseRow.active == True)
    )).scalar()
    log.info(f"MF universe synced: {total} active schemes ({added} new)")
    return added


async def run_mf_full_pipeline(session: AsyncSession, initial: bool = False) -> str:
    """Download NAVs for ALL Regular plan MF schemes."""
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = PipelineRunRow(
        id=run_id, pipeline="mf_navs_full", status="running",
        records_added=0, started_at=started,
    )
    session.add(run)
    await session.flush()

    total_added = 0
    total_schemes = 0
    failed_schemes = 0

    try:
        # Step 1: Fetch and sync all Regular schemes
        log.info("Step 1: Fetching AMFI scheme list...")
        schemes = await fetch_all_regular_schemes()
        added = await sync_mf_universe(session, schemes)
        await session.commit()

        # Step 2: Get all active schemes from DB
        all_schemes = (await session.execute(
            select(MFUniverseRow).where(MFUniverseRow.active == True)
        )).scalars().all()
        total_schemes = len(all_schemes)

        # Step 3: Get latest NAV dates per scheme (batch query)
        log.info("Step 2: Checking existing NAV data...")
        latest_dates: dict[str, date] = {}
        result = await session.execute(
            select(MFNavRow.scheme_code, func.max(MFNavRow.date))
            .group_by(MFNavRow.scheme_code)
        )
        latest_dates = {row[0]: row[1] for row in result.all()}

        cutoff = date.today() - timedelta(days=365 * BACKFILL_YEARS)
        today = date.today()

        # Step 4: Download NAVs
        schemes_to_fetch = []
        for scheme in all_schemes:
            last = latest_dates.get(scheme.scheme_code)
            if not initial and last and last >= today - timedelta(days=2):
                continue  # Already up to date
            schemes_to_fetch.append(scheme)

        log.info(f"Step 3: Downloading NAVs for {len(schemes_to_fetch)} schemes (of {total_schemes} total)...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            for idx, scheme in enumerate(schemes_to_fetch):
                code = scheme.scheme_code
                last_existing = latest_dates.get(code)

                if idx % 100 == 0 and idx > 0:
                    log.info(f"  Progress: {idx}/{len(schemes_to_fetch)} schemes, +{total_added} records")
                    await session.commit()  # Periodic commit to avoid huge transactions

                try:
                    resp = await client.get(f"{MFAPI_BASE}/mf/{code}")
                    if resp.status_code != 200:
                        failed_schemes += 1
                        time.sleep(REQUEST_DELAY_SEC)
                        continue
                    data = resp.json()
                except Exception:
                    failed_schemes += 1
                    time.sleep(REQUEST_DELAY_SEC)
                    continue

                nav_entries = data.get("data", [])
                if not nav_entries:
                    time.sleep(REQUEST_DELAY_SEC)
                    continue

                scheme_added = 0
                for entry in nav_entries:
                    nav_date = _parse_nav_date(entry.get("date", ""))
                    if nav_date is None:
                        continue
                    if nav_date < cutoff:
                        continue
                    # Always skip dates we already have (prevents UNIQUE constraint violations)
                    if last_existing and nav_date <= last_existing:
                        continue

                    nav_str = entry.get("nav", "")
                    try:
                        nav_val = float(nav_str)
                    except (ValueError, TypeError):
                        continue

                    session.add(MFNavRow(
                        scheme_code=code, date=nav_date, nav=nav_val,
                    ))
                    scheme_added += 1

                total_added += scheme_added
                try:
                    await session.flush()
                except Exception:
                    await session.rollback()
                    failed_schemes += 1
                time.sleep(REQUEST_DELAY_SEC)

        await session.commit()
        run.status = "completed"
        run.records_added = total_added
        run.completed_at = datetime.now(UTC)
        log.info(f"MF full pipeline complete: {total_added} records from {total_schemes} schemes ({failed_schemes} failed)")

    except Exception as e:
        log.error(f"MF full pipeline failed: {e}")
        run.status = "failed"
        run.error = str(e)[:2000]
        run.completed_at = datetime.now(UTC)

    await session.flush()
    return run_id
