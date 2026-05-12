"""E3.NewsScanner → cache-invalidation push mechanism.

Cluster 8 chunk 8.4 §10 + §11.

After the E3.NewsScanner verdict is parsed, any
:class:`~artha.api_v2.agents.e3_news_scanner.schema.CacheInvalidationPush`
entries trigger two actions per push:

1. **Auto-flag upsert** — inserts a :class:`StockLevelManualFlag` row
   with ``advisor_id="auto_e3_news_scanner"`` so the next E1/E2SIS
   cache-key rotation picks up the news event.  The flag id is
   deterministic (``auto_e3_{news_id}_{ticker}``) for idempotency.

2. **Cache invalidation** — drops stale E1 and/or E2SIS cache rows for
   the affected ticker based on the push's
   ``invalidates_e1`` / ``invalidates_e2sis`` flags.

Design invariants:

- **Non-blocking**: push failures are captured in
  :attr:`PushSummary.errors`; they never fail the parent case.
- **Idempotent**: the deterministic flag-id means replaying the same
  push is a safe no-op (upsert skips the duplicate, delete is also
  idempotent).
- **Full-ticker invalidation**: E1/E2SIS invalidation uses
  :func:`invalidate_all_for_ticker` (drops ALL rows for the ticker,
  not just rows matching a specific flag) because the news event
  itself is the reason for the invalidation — the current flag state
  is irrelevant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.agents.cache import repository as e1repo
from artha.api_v2.agents.cache import repository_cluster8 as c8repo
from artha.api_v2.agents.cache.models_cluster8 import StockLevelManualFlag
from artha.api_v2.agents.e3_news_scanner.schema import CacheInvalidationPush

logger = logging.getLogger(__name__)

_AUTO_ADVISOR_ID = "auto_e3_news_scanner"


@dataclass
class PushSummary:
    """Outcome of :func:`process_e3_news_scanner_pushes`."""

    total_pushes: int
    successful_auto_flags: int
    e1_rows_invalidated: int
    e2sis_rows_invalidated: int
    errors: list[str] = field(default_factory=list)

    @property
    def had_errors(self) -> bool:
        return bool(self.errors)


async def process_e3_news_scanner_pushes(
    db: AsyncSession,
    *,
    case_id: str,
    cache_invalidation_pushes: list[CacheInvalidationPush],
    firm_id: str = "default_firm",
    now: datetime | None = None,
) -> PushSummary:
    """Process all cache-invalidation pushes from an E3.NewsScanner verdict.

    Each push in ``cache_invalidation_pushes`` is processed
    independently; a failure on one does not abort the others.
    The returned :class:`PushSummary` records any errors.

    Args:
        db: Async SQLAlchemy session.  The caller owns the transaction.
        case_id: Case that generated the news scan (for lineage logging).
        cache_invalidation_pushes: The ``cache_invalidation_pushes``
            list from the parsed :class:`E3NewsScannerOutput`.
        firm_id: Firm context for the auto-flag rows.
        now: Override UTC now (tests).
    """
    moment = now or datetime.now(timezone.utc)
    total = len(cache_invalidation_pushes)
    successful_flags = 0
    e1_invals = 0
    e2sis_invals = 0
    errors: list[str] = []

    for push in cache_invalidation_pushes:
        try:
            await _upsert_auto_flag(db, push=push, firm_id=firm_id, moment=moment)
            successful_flags += 1

            if push.invalidates_e1:
                n = await e1repo.invalidate_all_for_ticker(db, ticker=push.ticker)
                e1_invals += n
                logger.debug(
                    "E3.NewsScanner push: invalidated %d E1 rows for ticker=%s "
                    "news_id=%s case_id=%s",
                    n, push.ticker, push.news_id, case_id,
                )

            if push.invalidates_e2sis:
                n = await c8repo.invalidate_all_e2sis_for_ticker(
                    db, ticker=push.ticker,
                )
                e2sis_invals += n
                logger.debug(
                    "E3.NewsScanner push: invalidated %d E2SIS rows for "
                    "ticker=%s news_id=%s case_id=%s",
                    n, push.ticker, push.news_id, case_id,
                )

        except Exception as exc:  # noqa: BLE001 — push must not fail the case
            msg = f"{push.ticker}/{push.news_id}: {exc!r}"
            errors.append(msg)
            logger.warning(
                "E3.NewsScanner push failed (non-fatal): %s case_id=%s",
                msg, case_id,
            )

    return PushSummary(
        total_pushes=total,
        successful_auto_flags=successful_flags,
        e1_rows_invalidated=e1_invals,
        e2sis_rows_invalidated=e2sis_invals,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _upsert_auto_flag(
    db: AsyncSession,
    *,
    push: CacheInvalidationPush,
    firm_id: str,
    moment: datetime,
) -> None:
    """Insert (or skip) the deterministic auto-flag for this push.

    Flag id format: ``auto_e3_{news_id}_{ticker}``.
    If a row with that id already exists, we skip (idempotent).
    """
    flag_id = f"auto_e3_{push.news_id}_{push.ticker}"

    existing = (
        await db.execute(
            select(StockLevelManualFlag).where(
                StockLevelManualFlag.manual_flag_id == flag_id,
            ),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return  # idempotent — already inserted by a prior run

    row = StockLevelManualFlag(
        manual_flag_id=flag_id,
        firm_id=firm_id,
        ticker=push.ticker,
        advisor_id=_AUTO_ADVISOR_ID,
        reason=push.reason,
        active_from=moment,
        cleared_at=None,
        cleared_by=None,
        created_at=moment,
        invalidates_e1=push.invalidates_e1,
        invalidates_e2sis=push.invalidates_e2sis,
        is_active=True,
        schema_version=2,
    )
    db.add(row)
    await db.flush()


__all__ = [
    "PushSummary",
    "process_e3_news_scanner_pushes",
]
