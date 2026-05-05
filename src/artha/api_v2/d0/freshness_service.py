"""Freshness admin-surface service (FR Entry 10.5 §4.1).

Builds the data-freshness table by querying record counts + latest
``last_modified_at`` from each canonical entity table, then computing
the freshness status via the pure :mod:`artha.api_v2.d0.freshness`
helpers.

Cluster 3 chunk 3.1 ships the service + endpoint; chunk 3.4 adds the
audit-role UI surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.c0.models import Conversation as _C0Conversation  # noqa: F401
from artha.api_v2.d0 import freshness as freshness_lib
from artha.api_v2.d0.industry.models import IndustryReport
from artha.api_v2.d0.instruments.models import Instrument
from artha.api_v2.d0.macro.models import MacroSnapshot
from artha.api_v2.d0.schemas import FreshnessRow
from artha.api_v2.investors.models import Household, Investor
from artha.api_v2.m1.models import Mandate, MandateVersion

# Cluster 3 chunks 3.2 + 3.3 wired Instrument, MacroSnapshot, and
# IndustryReport. The ``Any`` typing keeps the call site flexible.
_TABLE_TO_MODEL: dict[str, Any] = {
    "instruments": Instrument,
    "macro_snapshots": MacroSnapshot,
    "industry_reports": IndustryReport,
    "investors": Investor,
    "households": Household,
    "mandates": Mandate,
    "mandate_versions": MandateVersion,
}


def _last_modified_column(model: Any) -> Any:
    """Pick the entity's last-modified column.

    Clusters 1-2 use ``last_modified_at``; cluster 2's mandate_versions
    uses ``activated_at``/``archived_at`` lifecycle fields and doesn't
    carry a single last_modified field — fall back to ``created_at`` for
    those models.
    """
    for name in ("last_modified_at", "created_at"):
        col = getattr(model, name, None)
        if col is not None:
            return col
    raise AttributeError(f"Model {model!r} has no last_modified or created_at column")


async def build_freshness_rows(
    db: AsyncSession, *, now: datetime | None = None
) -> list[FreshnessRow]:
    """Return one :class:`FreshnessRow` per registered canonical entity."""
    out: list[FreshnessRow] = []
    for table, model in _TABLE_TO_MODEL.items():
        last_col = _last_modified_column(model)
        count_stmt = select(func.count()).select_from(model)
        latest_stmt = select(func.max(last_col))
        record_count = (await db.execute(count_stmt)).scalar_one() or 0
        latest = (await db.execute(latest_stmt)).scalar_one_or_none()

        result = freshness_lib.compute_freshness(
            entity_table=table, last_modified_at=latest, now=now
        )
        out.append(
            FreshnessRow(
                entity_table=table,
                record_count=int(record_count),
                latest_last_modified_at=latest,
                threshold_seconds=result.threshold_seconds,
                threshold_human=freshness_lib.threshold_as_human(
                    result.threshold_seconds
                ),
                freshness_status=result.status,
                age_seconds=result.age_seconds,
            )
        )
    return out


def register_entity_table(table_name: str, model: Any) -> None:
    """Add a canonical entity table to the freshness report.

    Chunks 3.2 + 3.3 call this for ``instruments``, ``macro_snapshots``,
    and ``industry_reports`` once their ORM models exist.
    """
    _TABLE_TO_MODEL[table_name] = model
