"""Mutual fund NAV pipeline — downloads NAV history via MFAPI."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.data.models import MFNavRow, PipelineRunRow
from artha.data.universe import get_active_mf_schemes

log = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in"
REQUEST_DELAY_SEC = 0.5
BACKFILL_YEARS = 10


def _parse_nav_date(date_str: str) -> date | None:
    """Parse date from MFAPI format (DD-MM-YYYY)."""
    try:
        parts = date_str.strip().split("-")
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except (ValueError, IndexError):
        return None


async def run_mf_pipeline(session: AsyncSession, initial: bool = False) -> str:
    """Download mutual fund NAVs. Returns pipeline run ID."""
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = PipelineRunRow(
        id=run_id, pipeline="mf_navs", status="running",
        records_added=0, started_at=started,
    )
    session.add(run)
    await session.flush()

    total_added = 0
    try:
        schemes = await get_active_mf_schemes(session)
        if not schemes:
            log.warning("No active MF schemes in universe. Seed schemes first.")
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            await session.flush()
            return run_id

        log.info(f"MF pipeline: {len(schemes)} schemes, initial={initial}")

        # Get latest dates per scheme
        latest_dates: dict[str, date] = {}
        if not initial:
            result = await session.execute(
                select(MFNavRow.scheme_code, func.max(MFNavRow.date))
                .group_by(MFNavRow.scheme_code)
            )
            latest_dates = {row[0]: row[1] for row in result.all()}

        cutoff = date.today() - timedelta(days=365 * BACKFILL_YEARS)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for idx, scheme in enumerate(schemes):
                code = scheme.scheme_code
                log.info(f"  [{idx + 1}/{len(schemes)}] {code}: {scheme.scheme_name}")

                if not initial:
                    last = latest_dates.get(code)
                    if last and last >= date.today() - timedelta(days=1):
                        log.info(f"    Up to date (last: {last})")
                        continue

                try:
                    resp = await client.get(f"{MFAPI_BASE}/mf/{code}")
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    log.warning(f"    MFAPI error for {code}: {e}")
                    time.sleep(REQUEST_DELAY_SEC)
                    continue

                nav_entries = data.get("data", [])
                if not nav_entries:
                    log.warning(f"    No NAV data for {code}")
                    time.sleep(REQUEST_DELAY_SEC)
                    continue

                scheme_added = 0
                last_existing = latest_dates.get(code)

                for entry in nav_entries:
                    nav_date = _parse_nav_date(entry.get("date", ""))
                    if nav_date is None:
                        continue

                    # Skip old data if not initial
                    if initial and nav_date < cutoff:
                        continue
                    if not initial and last_existing and nav_date <= last_existing:
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
                log.info(f"    +{scheme_added} NAV records")
                await session.flush()

                time.sleep(REQUEST_DELAY_SEC)

        run.status = "completed"
        run.records_added = total_added
        run.completed_at = datetime.now(UTC)
        log.info(f"MF pipeline complete: {total_added} records added")

    except Exception as e:
        log.error(f"MF pipeline failed: {e}")
        run.status = "failed"
        run.error = str(e)[:2000]
        run.completed_at = datetime.now(UTC)

    await session.flush()
    return run_id
