"""Structured investor disambiguation for C0's mandate_creation intent.

Per FR Entry 14.0 Cluster 2 Revision §2.5 + Cluster 2 Ideation §4.2:
**no LLM fuzzy matching**. Cluster 2 ships exact-then-substring matching
on name (case-insensitive) plus partial PAN matches against the
advisor's investor book.

The matcher is a pure function over Investor ORM rows; the C0 service
calls it after the LLM has extracted ``investor_name`` and / or
``investor_pan`` from the user message.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.investors.models import Investor


@dataclass(frozen=True)
class InvestorMatch:
    """One disambiguation candidate."""

    investor_id: str
    name: str
    pan: str
    age: int
    last_activity_at: str  # ISO timestamp of last_modified_at


async def find_matching_investors(
    db: AsyncSession,
    *,
    name_query: str | None,
    pan_query: str | None,
    actor: UserContext,
    limit: int = 10,
) -> list[InvestorMatch]:
    """Return investor matches scoped to the actor's visibility.

    Matching strategy (chosen over LLM fuzzy matching for predictability +
    auditability):

    1. **Exact name match** (case-insensitive) on the full ``name`` field.
    2. **Substring name match** (case-insensitive) — anywhere in the name.
    3. **PAN match** — case-insensitive prefix or exact.

    Results are deduplicated by ``investor_id`` and capped at ``limit``.
    The caller (C0 service) interprets cardinality:

    - 0 matches → ask for clarification
    - 1 match → confirm with the advisor
    - 2+ matches → present the list as a structured disambiguation card
    """
    if not name_query and not pan_query:
        return []

    stmt = select(Investor)
    if actor.role is Role.ADVISOR:
        stmt = stmt.where(Investor.advisor_id == actor.user_id)
    # Order is by last_modified_at DESC so most-recently-active investors
    # surface first in the disambiguation list (FR §2.5: "name, PAN, age,
    # last activity").
    stmt = stmt.order_by(Investor.last_modified_at.desc())

    result = await db.execute(stmt)
    candidates = list(result.scalars())

    matches: dict[str, Investor] = {}

    if name_query:
        name_lc = name_query.strip().lower()
        # Exact (case-insensitive) first.
        for inv in candidates:
            if inv.name.lower() == name_lc:
                matches[inv.investor_id] = inv
        # Substring next.
        for inv in candidates:
            if name_lc in inv.name.lower():
                matches.setdefault(inv.investor_id, inv)

    if pan_query:
        pan_uc = pan_query.strip().upper()
        for inv in candidates:
            if inv.pan.startswith(pan_uc) or inv.pan == pan_uc:
                matches.setdefault(inv.investor_id, inv)

    out: list[InvestorMatch] = []
    for inv in matches.values():
        out.append(
            InvestorMatch(
                investor_id=inv.investor_id,
                name=inv.name,
                pan=inv.pan,
                age=inv.age,
                last_activity_at=inv.last_modified_at.isoformat(),
            )
        )
        if len(out) >= limit:
            break
    return out
