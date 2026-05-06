"""Demo seed framework — load + reset (FR Entry 19.0, chunk 5.6).

The seed loader inserts a fixed cohort of investors + households +
mandates + cases tagged ``is_seed_data=True`` so demos run against a
realistic-looking firm without leaving real-customer data sloshing
around dev databases. Cluster 5.4's stub layer reads canned per-case
stage outputs from ``data/fixtures/case_seed_data.json`` (loaded via
:mod:`.dispatch.load_seed_fixture`) so seeded cases produce
narratively-aligned evidence + synthesis instead of generic
placeholders.

Key design decisions:

- **Direct ORM writes for foundational entities** (households,
  investors, mandates). The high-level services (``investor_service.
  create_investor`` / ``m1_service.create_mandate``) don't accept an
  ``is_seed_data`` flag and forcing one in would muddy their public
  surface; the seed loader is privileged + narrow, so it constructs
  rows directly.
- **Cases via ``case_opener.open_case``** so the chunk 5.4 pipeline
  runs on every seed case. The pipeline tags every stage row
  ``produced_via='lookup_stub_seed'`` because each case has
  ``is_seed_data=True``.
- **Idempotent load**: refuses to re-load if any seed row exists.
  Caller resets first, then re-loads.
- **Reset cascade order** (FR 19.0 §4): cases → mandates → mandate
  versions → snapshots → investors → households. Each table's
  ``is_seed_data=True`` rows are deleted; nothing else is touched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.cases import case_opener, dispatch, event_names
from artha.api_v2.cases.case_opener import OpenCaseDeps, OpenCaseRequest
from artha.api_v2.cases.models import (
    A1Challenge,
    BriefingNote,
    Case,
    DecisionArtifact,
    EvidenceVerdict,
    GovernanceResult,
    HealthReport,
    IC1Deliberation,
    PortfolioRiskAnalyticsOutput,
    SynthesisOutput,
)
from artha.api_v2.d0.models import Snapshot
from artha.api_v2.i0.active_layer import enrich_investor
from artha.api_v2.investors.models import Household, Investor
from artha.api_v2.m0.boss import boss as default_boss
from artha.api_v2.m1.models import Mandate, MandateVersion, MandateVersionStatus
from artha.api_v2.observability.t1 import emit_event

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SeedFrameworkError(RuntimeError):
    """Base class for seed-loader errors."""


class SeedFixtureMissingError(SeedFrameworkError):
    """The on-disk fixture wasn't found / unreadable."""


class SeedAlreadyLoadedError(SeedFrameworkError):
    """The DB already contains seed-tagged rows; reset before reloading."""


class SeedNotAuthorisedError(SeedFrameworkError):
    """Caller isn't a CIO with seed:admin permission."""


# ---------------------------------------------------------------------------
# Fixture file path (overridable for tests)
# ---------------------------------------------------------------------------


_DEFAULT_SEED_FIXTURE = (
    Path(__file__).resolve().parents[4] / "data" / "fixtures" / "demo_seed.json"
)

_FIXTURE_OVERRIDE: Path | None = None


def get_demo_fixture_path() -> Path:
    return _FIXTURE_OVERRIDE if _FIXTURE_OVERRIDE is not None else _DEFAULT_SEED_FIXTURE


def set_demo_fixture_path(path: Path | None) -> None:
    """Test-only override of the demo-seed fixture path."""
    global _FIXTURE_OVERRIDE
    _FIXTURE_OVERRIDE = path


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedLoadResult:
    households: int
    investors: int
    mandates: int
    cases: int


@dataclass(frozen=True)
class SeedResetResult:
    cases_deleted: int
    mandates_deleted: int
    mandate_versions_deleted: int
    investors_deleted: int
    households_deleted: int
    snapshots_deleted: int
    stage_rows_deleted: int


@dataclass(frozen=True)
class SeedStatus:
    is_loaded: bool
    counts: dict[str, int]


# ---------------------------------------------------------------------------
# Permission gate
# ---------------------------------------------------------------------------


def _ensure_seed_admin(actor: UserContext) -> None:
    if actor.role is not Role.CIO:
        raise SeedNotAuthorisedError(
            "Seed admin operations are CIO-only (FR 19.0 §3.2).",
        )


# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------


def _read_fixture() -> dict[str, Any]:
    path = get_demo_fixture_path()
    if not path.exists():
        raise SeedFixtureMissingError(
            f"Demo seed fixture not found at {path}. Cluster 5.6 ships "
            f"data/fixtures/demo_seed.json; check the file is on disk.",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedFixtureMissingError(
            f"Demo seed fixture {path} is malformed JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise SeedFixtureMissingError(
            f"Demo seed fixture {path} root must be an object.",
        )
    return raw


# ---------------------------------------------------------------------------
# Status / count helpers
# ---------------------------------------------------------------------------


async def get_status(db: AsyncSession) -> SeedStatus:
    """Return the current seed-row counts across the cluster-5 universe."""
    investors = await db.execute(
        select(func.count()).select_from(Investor).where(Investor.is_seed_data.is_(True)),
    )
    households = await db.execute(
        select(func.count()).select_from(Household).where(Household.is_seed_data.is_(True)),
    )
    mandates = await db.execute(
        select(func.count()).select_from(Mandate).where(Mandate.is_seed_data.is_(True)),
    )
    cases = await db.execute(
        select(func.count()).select_from(Case).where(Case.is_seed_data.is_(True)),
    )
    counts = {
        "investors": int(investors.scalar_one() or 0),
        "households": int(households.scalar_one() or 0),
        "mandates": int(mandates.scalar_one() or 0),
        "cases": int(cases.scalar_one() or 0),
    }
    is_loaded = any(v > 0 for v in counts.values())
    return SeedStatus(is_loaded=is_loaded, counts=counts)


async def _has_any_seed_rows(db: AsyncSession) -> bool:
    status = await get_status(db)
    return status.is_loaded


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


async def load_demo_seed(
    db: AsyncSession,
    *,
    actor: UserContext,
) -> SeedLoadResult:
    """Load the on-disk demo-seed fixture into the DB.

    Refuses to re-load if any seed-tagged rows already exist (caller
    must reset first). Caller wraps in ``async with db.begin()``.
    """
    _ensure_seed_admin(actor)
    if await _has_any_seed_rows(db):
        raise SeedAlreadyLoadedError(
            "Seed data already loaded; call reset before reloading.",
        )

    fixture = _read_fixture()
    await emit_event(
        db,
        event_name=event_names.SEED_LOAD_STARTED,
        payload={"fixture_version": fixture.get("version", "unknown")},
        firm_id=actor.firm_id,
    )

    households_inserted = await _load_households(db, fixture, actor=actor)
    investors_inserted = await _load_investors(db, fixture, actor=actor)
    mandates_inserted = await _load_mandates(db, fixture, actor=actor)

    await emit_event(
        db,
        event_name=event_names.SEED_LOAD_PROGRESS,
        payload={
            "stage": "foundational_entities_loaded",
            "households": households_inserted,
            "investors": investors_inserted,
            "mandates": mandates_inserted,
        },
        firm_id=actor.firm_id,
    )

    cases_inserted = await _load_cases(db, fixture, actor=actor)

    result = SeedLoadResult(
        households=households_inserted,
        investors=investors_inserted,
        mandates=mandates_inserted,
        cases=cases_inserted,
    )
    await emit_event(
        db,
        event_name=event_names.SEED_LOAD_COMPLETED,
        payload={
            "households": result.households,
            "investors": result.investors,
            "mandates": result.mandates,
            "cases": result.cases,
        },
        firm_id=actor.firm_id,
    )
    return result


async def _load_households(
    db: AsyncSession, fixture: dict[str, Any], *, actor: UserContext,
) -> int:
    rows = fixture.get("households", [])
    for hh in rows:
        db.add(
            Household(
                household_id=hh["household_id"],
                name=hh["name"],
                created_by=hh.get("created_by", actor.user_id),
                created_at=_iso(hh.get("created_at")),
                is_seed_data=True,
            ),
        )
    await db.flush()
    return len(rows)


async def _load_investors(
    db: AsyncSession, fixture: dict[str, Any], *, actor: UserContext,
) -> int:
    rows = fixture.get("investors", [])
    for inv in rows:
        enrichment = enrich_investor(
            age=inv["age"],
            risk_appetite=inv["risk_appetite"],
            time_horizon=inv["time_horizon"],
        )
        db.add(
            Investor(
                investor_id=inv["investor_id"],
                household_id=inv["household_id"],
                name=inv["name"],
                email=inv["email"],
                phone=inv["phone"],
                pan=inv["pan"],
                age=inv["age"],
                advisor_id=inv["advisor_id"],
                risk_appetite=inv["risk_appetite"],
                time_horizon=inv["time_horizon"],
                kyc_status=inv.get("kyc_status", "pending"),
                life_stage=enrichment.life_stage,
                life_stage_confidence=enrichment.life_stage_confidence,
                liquidity_tier=enrichment.liquidity_tier,
                liquidity_tier_range=enrichment.liquidity_tier_range,
                enriched_at=_iso(inv.get("created_at")),
                enrichment_version=enrichment.enrichment_version,
                created_at=_iso(inv.get("created_at")),
                created_by=inv.get("created_by", actor.user_id),
                created_via=inv.get("created_via", "seed_loader"),
                last_modified_at=_iso(inv.get("created_at")),
                last_modified_by=inv.get("created_by", actor.user_id),
                is_seed_data=True,
                seed_archetype_id=inv.get("archetype_id"),
                schema_version=2,
            ),
        )
    await db.flush()
    return len(rows)


async def _load_mandates(
    db: AsyncSession, fixture: dict[str, Any], *, actor: UserContext,
) -> int:
    rows = fixture.get("mandates", [])
    for m in rows:
        version_id = m.get("version_id") or str(ULID())
        mandate = Mandate(
            mandate_id=m["mandate_id"],
            investor_id=m["investor_id"],
            active_version_id=version_id,
            created_at=_iso(m.get("created_at")),
            created_by=m.get("created_by", actor.user_id),
            is_seed_data=True,
            schema_version=2,
        )
        db.add(mandate)

        version = MandateVersion(
            version_id=version_id,
            mandate_id=m["mandate_id"],
            version_number=1,
            status=MandateVersionStatus.ACTIVE.value,
            equity_min_pct=int(m["equity_min_pct"]),
            equity_max_pct=int(m["equity_max_pct"]),
            debt_min_pct=int(m["debt_min_pct"]),
            debt_max_pct=int(m["debt_max_pct"]),
            cash_min_pct=int(m.get("cash_min_pct", 0)),
            cash_max_pct=int(m.get("cash_max_pct", 100)),
            alternatives_min_pct=int(m["alternatives_min_pct"]),
            alternatives_max_pct=int(m["alternatives_max_pct"]),
            single_position_max_pct=int(m["single_position_max_pct"]),
            liquidity_floor_pct=int(m["liquidity_floor_pct"]),
            sector_max_pct=int(m["sector_max_pct"]),
            prohibited_instruments=list(m.get("prohibited_instruments", [])),
            created_at=_iso(m.get("created_at")),
            created_by=m.get("created_by", actor.user_id),
            created_via=m.get("created_via", "seed_loader"),
            parent_version_id=None,
            activated_at=_iso(m.get("created_at")),
            is_seed_data=True,
        )
        db.add(version)
    await db.flush()
    return len(rows)


async def _load_cases(
    db: AsyncSession, fixture: dict[str, Any], *, actor: UserContext,
) -> int:
    """Open each fixture case via the chunk 5.3 case_opener.

    The case_opener pins a snapshot bundle and runs the chunk 5.4
    pipeline; each stage row will be tagged ``is_seed_data=True`` and
    ``produced_via='lookup_stub_seed'`` because the case carries
    ``is_seed_data=True`` + a ``seed_archetype_id`` matching an entry
    in ``data/fixtures/case_seed_data.json``.
    """
    rows = fixture.get("cases", [])
    deps = OpenCaseDeps(boss=default_boss)
    for c in rows:
        # Build a synthetic actor whose role + identity are taken from the
        # fixture so opened_by / assigned_to look natural.
        case_actor = UserContext(
            user_id=c.get("opened_by", actor.user_id),
            firm_id=actor.firm_id,
            role=Role.CIO,  # CIO writes seed cases firm-wide.
            email=actor.email,
            name=actor.name,
            session_id=actor.session_id,
        )

        request = OpenCaseRequest(
            investor_id=c["investor_id"],
            case_mode=c["case_mode"],
            case_intent=c.get("case_intent"),
            dominant_lens=c.get("dominant_lens"),
            proposed_action=c.get("proposed_action"),
            proposed_action_amount_inr=(
                Decimal(str(c["proposed_action_amount_inr"]))
                if c.get("proposed_action_amount_inr") is not None
                else None
            ),
            proposed_action_products=tuple(c.get("proposed_action_products", [])),
            materiality_manual_flag=bool(c.get("materiality_manual_flag", False)),
            is_seed_data=True,
            seed_archetype_id=c.get("seed_archetype_id"),
            created_via="seed_loader",
        )
        await case_opener.open_case(
            db, request, actor=case_actor, deps=deps,
        )
    return len(rows)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


async def reset_demo_seed(
    db: AsyncSession,
    *,
    actor: UserContext,
) -> SeedResetResult:
    """Delete every is_seed_data=True row across the cluster-5 universe.

    Order matters because of FK constraints — children first.
    """
    _ensure_seed_admin(actor)

    await emit_event(
        db,
        event_name=event_names.SEED_RESET_STARTED,
        payload={},
        firm_id=actor.firm_id,
    )

    # 1. Stage rows + decision artifacts (children of cases).
    stage_rows_deleted = 0
    for table in (
        EvidenceVerdict,
        SynthesisOutput,
        PortfolioRiskAnalyticsOutput,
        IC1Deliberation,
        GovernanceResult,
        A1Challenge,
        DecisionArtifact,
        BriefingNote,
        HealthReport,
    ):
        result = await db.execute(
            delete(table).where(table.is_seed_data.is_(True)),
        )
        stage_rows_deleted += int(result.rowcount or 0)

    # 2. Cases.
    cases_result = await db.execute(
        delete(Case).where(Case.is_seed_data.is_(True)),
    )
    cases_deleted = int(cases_result.rowcount or 0)

    # 3. Mandate versions + mandates.
    mv_result = await db.execute(
        delete(MandateVersion).where(MandateVersion.is_seed_data.is_(True)),
    )
    mv_deleted = int(mv_result.rowcount or 0)
    m_result = await db.execute(
        delete(Mandate).where(Mandate.is_seed_data.is_(True)),
    )
    m_deleted = int(m_result.rowcount or 0)

    # 4. Snapshots tagged seed.
    snap_result = await db.execute(
        delete(Snapshot).where(Snapshot.is_seed_data.is_(True)),
    )
    snap_deleted = int(snap_result.rowcount or 0)

    # 5. Investors then households.
    inv_result = await db.execute(
        delete(Investor).where(Investor.is_seed_data.is_(True)),
    )
    inv_deleted = int(inv_result.rowcount or 0)
    hh_result = await db.execute(
        delete(Household).where(Household.is_seed_data.is_(True)),
    )
    hh_deleted = int(hh_result.rowcount or 0)

    await db.flush()

    result = SeedResetResult(
        cases_deleted=cases_deleted,
        mandates_deleted=m_deleted,
        mandate_versions_deleted=mv_deleted,
        investors_deleted=inv_deleted,
        households_deleted=hh_deleted,
        snapshots_deleted=snap_deleted,
        stage_rows_deleted=stage_rows_deleted,
    )

    await emit_event(
        db,
        event_name=event_names.SEED_RESET_COMPLETED,
        payload={
            "cases": result.cases_deleted,
            "mandates": result.mandates_deleted,
            "investors": result.investors_deleted,
            "households": result.households_deleted,
            "snapshots": result.snapshots_deleted,
            "stage_rows": result.stage_rows_deleted,
        },
        firm_id=actor.firm_id,
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(value: str | None) -> Any:
    """Parse ISO-8601 strings; pass datetime/None through.

    Fixture timestamps are strings; SQLAlchemy gladly accepts datetimes
    or timezone-aware ISO strings either way, but normalising via
    ``datetime.fromisoformat`` keeps SQLite happy across versions.
    """
    if value is None:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)
    if not isinstance(value, str):
        return value
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# Hot-reload helper for the case_seed_data fixture (chunk 5.4).
# Cluster 5.6 uses the same fixture mechanism; reset clears the cache so
# the next dispatch picks up any out-of-band edits.
def reset_case_seed_cache() -> None:
    dispatch.reset_seed_cache()


__all__ = [
    "SeedAlreadyLoadedError",
    "SeedFixtureMissingError",
    "SeedFrameworkError",
    "SeedLoadResult",
    "SeedNotAuthorisedError",
    "SeedResetResult",
    "SeedStatus",
    "get_demo_fixture_path",
    "get_status",
    "load_demo_seed",
    "reset_case_seed_cache",
    "reset_demo_seed",
    "set_demo_fixture_path",
]
