"""Phase-based dispatcher — cluster 8 chunk 8.5 §1; cluster 9 chunk 9.5.

Four sequential phases with intra-phase parallelism, separated by
synchronisation barriers:

  Phase 1 (sequential): E3.MacroView
  Phase 2 (parallel):   E2.SectorView × unique_sectors
                        E1 × tickers
                        E5.FundView × aif_ids   (cluster 9)
                        E4.Behavioural × investor_id  (cluster 9)
  Phase 3 (parallel):   E2.StockInSector × ticker_sector_pairs
                        E7.MutualFund × fund_ids
                        E5.DealView × deal_ids  (cluster 9)
  Phase 4 (sequential): E3.NewsScanner
  Post-4 (non-blocking): E3.NewsScanner push → auto-flags + cache
                          invalidation

Failure mode: any agent failure inside a phase raises
:class:`PhaseDispatchError` immediately — no silent fallback
(case_arch08_b strict-failure pattern, chunk 8.5 §1.4).

Input wiring convention
-----------------------
Each phase calls :func:`.runtime.dispatch_real_agent` with a fully-
built :class:`AgentInputs` passed as ``agent_inputs_override``.  The
``seed_payload`` dict drives test injection.  Key namespace:

  ``phase_config``                          — PhaseConfig overrides
  ``evidence.e3_macro_view``                — E3.MacroView inputs
  ``evidence.e2_sector_view.{sector_code}`` — E2.SectorView per sector
  ``evidence.e1_listed_fundamental_equity.{ticker}`` — E1 per ticker
  ``evidence.e2_stock_in_sector.{ticker}``  — E2.StockInSector per ticker
  ``evidence.e7_mutual_fund.{fund_id}``     — E7 per fund
  ``evidence.e5_fund_view.{aif_id}``        — E5.FundView per AIF
  ``evidence.e5_deal_view.{deal_id}``       — E5.DealView per deal
  ``evidence.e4_behavioural.{investor_id}`` — E4 per investor
  ``evidence.e3_news_scanner``              — E3.NewsScanner inputs

Phase-result key convention
---------------------------
  phase1: ``{"e3_macro_view": RealDispatchOutput}``
  phase2: ``{"e1.{ticker}": ..., "e2sv.{sector_code}": ...,
             "e5fv.{aif_id}": ..., "e4.{investor_id}": ...}``
  phase3: ``{"e2sis.{ticker}": ..., "e7.{fund_id}": ...,
             "e5dv.{deal_id}": ...}``
  phase4: ``{"e3_news_scanner": ...}``
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from artha.api_v2.agents import runtime as agent_runtime
from artha.api_v2.agents.cache import deal_manual_flag as deal_flag_svc
from artha.api_v2.agents.cache import fund_manual_flag as fund_flag_svc
from artha.api_v2.agents.cache import investor_manual_flag as investor_flag_svc
from artha.api_v2.agents.cache import manual_flag as stock_flag_svc
from artha.api_v2.agents.cache import sector_manual_flag as sector_flag_svc
from artha.api_v2.agents.e3_news_scanner.push import (
    PushSummary,
    process_e3_news_scanner_pushes,
)
from artha.api_v2.agents.e3_news_scanner.schema import E3NewsScannerOutput
from artha.api_v2.agents.e4_behavioural.shim import derive_window_id
from artha.api_v2.agents.runtime import RealDispatchOutput
from artha.api_v2.agents.shim import AgentInputs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from artha.api_v2.agents.cache.backend import CacheBackend
    from artha.api_v2.agents.prompt_loader import PromptTemplate
    from artha.api_v2.cases.models import Case

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PhaseConfig:
    """Controls which agents run in each phase.

    Derived from the case + ``seed_payload["phase_config"]``.
    """

    tickers: list[str]
    """E1 + E2.StockInSector subjects."""

    unique_sectors: list[str]
    """E2.SectorView subjects (one call per sector)."""

    ticker_sector_pairs: list[tuple[str, str]]
    """E2.StockInSector subjects: (ticker, sector_code) pairs."""

    fund_ids: list[str]
    """E7 subjects (one call per fund)."""

    # Cluster 9 additions (chunk 9.5 §1.1).
    aif_ids: list[str] = field(default_factory=list)
    """E5.FundView subjects — one call per AIF registration ID."""

    deal_ids: list[str] = field(default_factory=list)
    """E5.DealView subjects — one call per deal/portfolio company."""

    investor_id: str | None = None
    """E4.Behavioural subject — at most one per case (case.investor_id)."""


@dataclass
class PhaseResult:
    """Collected :class:`RealDispatchOutput` from all four phases."""

    phase1: dict[str, RealDispatchOutput] = field(default_factory=dict)
    phase2: dict[str, RealDispatchOutput] = field(default_factory=dict)
    phase3: dict[str, RealDispatchOutput] = field(default_factory=dict)
    phase4: dict[str, RealDispatchOutput] = field(default_factory=dict)
    push_summary: PushSummary | None = None

    # ── Convenience accessors ──────────────────────────────────────────

    @property
    def e3_macro_view(self) -> RealDispatchOutput | None:
        return self.phase1.get("e3_macro_view")

    def e1(self, ticker: str) -> RealDispatchOutput | None:
        return self.phase2.get(f"e1.{ticker}")

    def e2_sector_view(self, sector_code: str) -> RealDispatchOutput | None:
        return self.phase2.get(f"e2sv.{sector_code}")

    def e2_stock_in_sector(self, ticker: str) -> RealDispatchOutput | None:
        return self.phase3.get(f"e2sis.{ticker}")

    def e7(self, fund_id: str) -> RealDispatchOutput | None:
        return self.phase3.get(f"e7.{fund_id}")

    # Cluster 9 accessors (chunk 9.5 §1.1).

    def e5fv(self, aif_id: str) -> RealDispatchOutput | None:
        """E5.FundView output for ``aif_id`` (phase 2)."""
        return self.phase2.get(f"e5fv.{aif_id}")

    def e5dv(self, deal_id: str) -> RealDispatchOutput | None:
        """E5.DealView output for ``deal_id`` (phase 3)."""
        return self.phase3.get(f"e5dv.{deal_id}")

    def e4(self, investor_id: str) -> RealDispatchOutput | None:
        """E4.Behavioural output for ``investor_id`` (phase 2)."""
        return self.phase2.get(f"e4.{investor_id}")

    @property
    def e3_news_scanner(self) -> RealDispatchOutput | None:
        return self.phase4.get("e3_news_scanner")


class PhaseDispatchError(RuntimeError):
    """Raised when any agent inside a phase fails.

    Carries the original exception and the agent_id that failed.
    """

    def __init__(self, agent_key: str, cause: BaseException) -> None:
        super().__init__(f"Phase dispatch failed for {agent_key!r}: {cause!r}")
        self.agent_key = agent_key
        self.cause = cause


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


async def run_phases(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    db: AsyncSession | None = None,
    cache: CacheBackend | None = None,
    skill_template_override: PromptTemplate | None = None,
    firm_id: str = "default_firm",
) -> PhaseResult:
    """Run all four cluster-8 phases and return the collected outputs.

    Args:
        case: The active :class:`Case` row.
        seed_payload: Test fixture data + phase config (see module doc).
        db: Async session for cache reads/writes + flag lookups.
        cache: E1/E3mv/etc. cache backend.  Defaults to NullCacheBackend
            when ``None`` (no caching — useful in tests without a DB).
        skill_template_override: Injected prompt template for tests.
        firm_id: Firm context for flag lookups and cache writes.

    Returns:
        :class:`PhaseResult` with outputs keyed as documented above.

    Raises:
        :class:`PhaseDispatchError`: if any agent call fails.
    """
    cfg = _build_phase_config(case, seed_payload)
    result = PhaseResult()

    # ------------------------------------------------------------------
    # Phase 1: E3.MacroView (sequential)
    # ------------------------------------------------------------------
    e3mv_inputs = _build_e3mv_inputs(case, seed_payload, firm_id)
    e3mv_out = await _dispatch(
        case=case,
        agent_id="e3_macro_view",
        inputs=e3mv_inputs,
        db=db, cache=cache,
        template=skill_template_override,
        key="e3_macro_view",
    )
    result.phase1["e3_macro_view"] = e3mv_out

    # Carry forward from Phase 1
    macro_regime_id: str = e3mv_inputs.payload.get(
        "macro_regime_id", "no_regime_seeded",
    )
    e3mv_stage = e3mv_out.parsed.stage_payload

    # ------------------------------------------------------------------
    # Phase 2: E2.SectorView + E1 in parallel
    # ------------------------------------------------------------------
    phase2_coros: list[tuple[str, Any]] = []

    for sector_code in cfg.unique_sectors:
        phase2_coros.append((
            f"e2sv.{sector_code}",
            _build_e2sv_inputs(
                case, seed_payload, sector_code=sector_code,
                macro_regime_id=macro_regime_id, e3mv_stage=e3mv_stage,
                firm_id=firm_id, db=db,
            ),
            "e2_sector_view",
        ))

    for ticker in cfg.tickers:
        phase2_coros.append((
            f"e1.{ticker}",
            _build_e1_inputs(
                case, seed_payload, ticker=ticker, db=db,
            ),
            "e1_listed_fundamental_equity",
        ))

    # Cluster 9: E5.FundView per AIF (phase 2).
    for aif_id in cfg.aif_ids:
        phase2_coros.append((
            f"e5fv.{aif_id}",
            _build_e5fv_inputs(
                case, seed_payload, aif_id=aif_id,
                e3mv_stage=e3mv_stage, firm_id=firm_id, db=db,
            ),
            "e5_fund_view",
        ))

    # Cluster 9: E4.Behavioural for the case investor (phase 2).
    if cfg.investor_id:
        phase2_coros.append((
            f"e4.{cfg.investor_id}",
            _build_e4_inputs(
                case, seed_payload,
                investor_id=cfg.investor_id,
                e3mv_stage=e3mv_stage, firm_id=firm_id, db=db,
            ),
            "e4_behavioural",
        ))

    phase2_results = await _run_parallel_phase(
        case=case, phase_specs=phase2_coros,
        db=db, cache=cache, template=skill_template_override, phase_num=2,
    )
    result.phase2.update(phase2_results)

    # ------------------------------------------------------------------
    # Phase 3: E2.StockInSector + E7 in parallel
    # ------------------------------------------------------------------
    phase3_coros: list[tuple[str, Any]] = []

    for ticker, sector_code in cfg.ticker_sector_pairs:
        e2sv_out = result.phase2.get(f"e2sv.{sector_code}")
        e2sv_stage = e2sv_out.parsed.stage_payload if e2sv_out else {}
        phase3_coros.append((
            f"e2sis.{ticker}",
            _build_e2sis_inputs(
                case, seed_payload, ticker=ticker, sector_code=sector_code,
                e2sv_stage=e2sv_stage, e3mv_stage=e3mv_stage,
                firm_id=firm_id, db=db,
            ),
            "e2_stock_in_sector",
        ))

    for fund_id in cfg.fund_ids:
        phase3_coros.append((
            f"e7.{fund_id}",
            _build_e7_inputs(
                case, seed_payload, fund_id=fund_id, e3mv_stage=e3mv_stage,
                firm_id=firm_id, db=db,
            ),
            "e7_mutual_fund",
        ))

    # Cluster 9: E5.DealView per deal (phase 3).
    for deal_id in cfg.deal_ids:
        phase3_coros.append((
            f"e5dv.{deal_id}",
            _build_e5dv_inputs(
                case, seed_payload, deal_id=deal_id,
                e3mv_stage=e3mv_stage, firm_id=firm_id, db=db,
            ),
            "e5_deal_view",
        ))

    phase3_results = await _run_parallel_phase(
        case=case, phase_specs=phase3_coros,
        db=db, cache=cache, template=skill_template_override, phase_num=3,
    )
    result.phase3.update(phase3_results)

    # ------------------------------------------------------------------
    # Phase 4: E3.NewsScanner (sequential)
    # ------------------------------------------------------------------
    ns_inputs = _build_news_scanner_inputs(case, seed_payload, cfg=cfg)
    ns_out = await _dispatch(
        case=case,
        agent_id="e3_news_scanner",
        inputs=ns_inputs,
        db=db, cache=cache,
        template=skill_template_override,
        key="e3_news_scanner",
    )
    result.phase4["e3_news_scanner"] = ns_out

    # ------------------------------------------------------------------
    # Post-Phase 4: push auto-flags + cache invalidation (non-blocking)
    # ------------------------------------------------------------------
    if db is not None:
        try:
            ns_verdict = E3NewsScannerOutput.model_validate(
                ns_out.parsed.structured
            )
            push_sum = await process_e3_news_scanner_pushes(
                db,
                case_id=case.case_id,
                cache_invalidation_pushes=ns_verdict.cache_invalidation_pushes,
                firm_id=firm_id,
            )
            result.push_summary = push_sum
        except Exception as exc:  # noqa: BLE001 — push must not fail the case
            logger.warning(
                "E3.NewsScanner push processing failed (non-fatal): %r "
                "case_id=%s", exc, case.case_id,
            )
            result.push_summary = PushSummary(
                total_pushes=0,
                successful_auto_flags=0,
                e1_rows_invalidated=0,
                e2sis_rows_invalidated=0,
                errors=[repr(exc)],
            )

    return result


# ---------------------------------------------------------------------------
# Phase config
# ---------------------------------------------------------------------------


def _build_phase_config(case: Case, seed_payload: dict[str, Any]) -> PhaseConfig:
    cfg_seed = seed_payload.get("phase_config") or {}
    products = list(getattr(case, "proposed_action_products", None) or [])
    tickers: list[str] = cfg_seed.get("tickers") or products
    unique_sectors: list[str] = cfg_seed.get("unique_sectors") or []
    raw_pairs = cfg_seed.get("ticker_sector_pairs")
    if raw_pairs is not None:
        ticker_sector_pairs: list[tuple[str, str]] = [
            (p[0], p[1]) for p in raw_pairs
        ]
    else:
        # Cartesian product as fallback for simple single-sector cases.
        ticker_sector_pairs = [
            (t, s) for t in tickers for s in unique_sectors
        ]
    fund_ids: list[str] = cfg_seed.get("fund_ids") or []
    # Cluster 9 additions.
    aif_ids: list[str] = cfg_seed.get("aif_ids") or []
    deal_ids: list[str] = cfg_seed.get("deal_ids") or []
    investor_id: str | None = cfg_seed.get("investor_id") or getattr(
        case, "investor_id", None,
    )
    return PhaseConfig(
        tickers=tickers,
        unique_sectors=unique_sectors,
        ticker_sector_pairs=ticker_sector_pairs,
        fund_ids=fund_ids,
        aif_ids=aif_ids,
        deal_ids=deal_ids,
        investor_id=investor_id,
    )


# ---------------------------------------------------------------------------
# Per-agent input builders
# ---------------------------------------------------------------------------


def _build_e3mv_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    firm_id: str,
) -> AgentInputs:
    seed = seed_payload.get("evidence.e3_macro_view") or {}
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "macro_regime_id": (
                seed.get("macro_regime_id") or "no_regime_seeded"
            ),
            "macro_regime_name": (
                seed.get("macro_regime_name") or "Unknown Regime"
            ),
            "regime_category": seed.get("regime_category") or "unknown",
            "latest_material_event_id": seed.get("latest_material_event_id"),
            "macro_snapshot": seed.get("macro_snapshot") or {},
            "firm_id": firm_id,
        },
    )


async def _build_e2sv_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    sector_code: str,
    macro_regime_id: str,
    e3mv_stage: dict[str, Any],
    firm_id: str,
    db: AsyncSession | None,
) -> AgentInputs:
    seed = (
        seed_payload.get(f"evidence.e2_sector_view.{sector_code}")
        or seed_payload.get("evidence.e2_sector_view")
        or {}
    )
    flag_id: str | None = None
    if db is not None:
        flag_id = await sector_flag_svc.get_active_sector_flag_id(
            db, firm_id=firm_id, sector_code=sector_code,
        )
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "sector_code": sector_code,
            "macro_regime_id": macro_regime_id,
            "sector_manual_flag_id": flag_id or "null",
            "e3_macro_view_output": e3mv_stage,
            "sector_background": seed.get("sector_background") or {},
            "firm_id": firm_id,
        },
    )


async def _build_e1_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    ticker: str,
    db: AsyncSession | None,
) -> AgentInputs:
    seed = (
        seed_payload.get(f"evidence.e1_listed_fundamental_equity.{ticker}")
        or seed_payload.get("evidence.e1_listed_fundamental_equity")
        or {}
    )
    flag_snap = None
    if db is not None:
        flag_snap = await stock_flag_svc.get_active_manual_flag_for_ticker(
            db, ticker=ticker,
        )
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "ticker": ticker,
            "snapshot_excerpt": seed.get("snapshot_excerpt") or "",
            "mandate_excerpt": (
                seed.get("mandate_excerpt")
                or f"investor_id={case.investor_id}; "
                   f"case_intent={getattr(case, 'case_intent', 'review') or 'review'}"
            ),
            "latest_earnings_id": (
                seed.get("latest_earnings_id") or "no_earnings_seeded"
            ),
            "manual_flag_id": (
                flag_snap.manual_flag_id if flag_snap else "null"
            ),
        },
    )


async def _build_e2sis_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    ticker: str,
    sector_code: str,
    e2sv_stage: dict[str, Any],
    e3mv_stage: dict[str, Any],
    firm_id: str,
    db: AsyncSession | None,
) -> AgentInputs:
    seed = (
        seed_payload.get(f"evidence.e2_stock_in_sector.{ticker}")
        or seed_payload.get("evidence.e2_stock_in_sector")
        or {}
    )
    flag_snap = None
    if db is not None:
        flag_snap = await stock_flag_svc.get_active_manual_flag_for_ticker(
            db, ticker=ticker,
        )
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "ticker": ticker,
            "sector_code": sector_code,
            "latest_earnings_id": (
                seed.get("latest_earnings_id") or "no_earnings_seeded"
            ),
            "stock_manual_flag_id": (
                flag_snap.manual_flag_id if flag_snap else "null"
            ),
            "sector_view_output": e2sv_stage,
            "e3_macro_view_output": e3mv_stage,
            "firm_id": firm_id,
        },
    )


async def _build_e7_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    fund_id: str,
    e3mv_stage: dict[str, Any],
    firm_id: str,
    db: AsyncSession | None,
) -> AgentInputs:
    seed = (
        seed_payload.get(f"evidence.e7_mutual_fund.{fund_id}")
        or seed_payload.get("evidence.e7_mutual_fund")
        or {}
    )
    flag_id: str | None = None
    if db is not None:
        flag_id = await fund_flag_svc.get_active_fund_flag_id(
            db, firm_id=firm_id, fund_id=fund_id,
        )
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "fund_id": fund_id,
            "fund_name": seed.get("fund_name") or fund_id,
            "fund_category": seed.get("fund_category") or "unknown",
            "current_manager_name": seed.get("current_manager_name"),
            "alpha_5y_bps_input": seed.get("alpha_5y_bps_input"),
            "current_aum_inr_cr": seed.get("current_aum_inr_cr"),
            "ter_pct_current": seed.get("ter_pct_current"),
            "latest_quarterly_disclosure_id": (
                seed.get("latest_quarterly_disclosure_id")
                or "no_disclosure_seeded"
            ),
            "fund_manual_flag_id": flag_id or "null",
            "e3_macro_view_output": e3mv_stage,
            "firm_id": firm_id,
        },
    )


async def _build_e5fv_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    aif_id: str,
    e3mv_stage: dict[str, Any],
    firm_id: str,
    db: AsyncSession | None,
) -> AgentInputs:
    """Build E5.FundView inputs for ``aif_id`` (cluster 9 chunk 9.2)."""
    seed = (
        seed_payload.get(f"evidence.e5_fund_view.{aif_id}")
        or seed_payload.get("evidence.e5_fund_view")
        or {}
    )
    flag_id: str | None = None
    if db is not None:
        flag_id = await fund_flag_svc.get_active_aif_flag_id(
            db, firm_id=firm_id, aif_id=aif_id,
        )
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "aif_id": aif_id,
            "fund_name": seed.get("fund_name") or aif_id,
            "current_manager_name": seed.get("current_manager_name"),
            "latest_aif_disclosure_id": (
                seed.get("latest_aif_disclosure_id") or "no_disclosure_seeded"
            ),
            "fund_manual_flag_id": flag_id or "null",
            "aif_data": seed.get("aif_data") or {},
            "e3_macro_view_output": e3mv_stage,
            "firm_id": firm_id,
        },
    )


async def _build_e5dv_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    deal_id: str,
    e3mv_stage: dict[str, Any],
    firm_id: str,
    db: AsyncSession | None,
) -> AgentInputs:
    """Build E5.DealView inputs for ``deal_id`` (cluster 9 chunk 9.2)."""
    seed = (
        seed_payload.get(f"evidence.e5_deal_view.{deal_id}")
        or seed_payload.get("evidence.e5_deal_view")
        or {}
    )
    flag_id: str | None = None
    if db is not None:
        flag_id = await deal_flag_svc.get_active_deal_flag_id(
            db, firm_id=firm_id, deal_id=deal_id,
        )
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "deal_id": deal_id,
            "fund_or_firm_id": seed.get("fund_or_firm_id") or "unknown",
            "latest_mca_filing_id": (
                seed.get("latest_mca_filing_id") or "no_filing_seeded"
            ),
            "deal_manual_flag_id": flag_id or "null",
            "deal_data": seed.get("deal_data") or {},
            "e3_macro_view_output": e3mv_stage,
            "firm_id": firm_id,
        },
    )


async def _build_e4_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    investor_id: str,
    e3mv_stage: dict[str, Any],
    firm_id: str,
    db: AsyncSession | None,
) -> AgentInputs:
    """Build E4.Behavioural inputs for ``investor_id`` (cluster 9 chunk 9.3).

    The ``window_id`` is derived from the current UTC time unless the seed
    provides an override (useful for deterministic test behaviour).
    """
    seed = (
        seed_payload.get(f"evidence.e4_behavioural.{investor_id}")
        or seed_payload.get("evidence.e4_behavioural")
        or {}
    )
    # Allow seed to override window_id for deterministic tests.
    from datetime import datetime, timezone  # noqa: PLC0415

    window_id: str = seed.get("window_id") or derive_window_id(
        datetime.now(timezone.utc),
    )
    flag_id: str | None = None
    if db is not None:
        flag_id = await investor_flag_svc.get_active_investor_flag_id(
            db, firm_id=firm_id, investor_id=investor_id,
        )
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "investor_id": investor_id,
            "window_id": window_id,
            "behavioural_manual_flag_id": flag_id or "null",
            "behavioural_data": seed.get("behavioural_data") or {},
            "e3_macro_view_output": e3mv_stage,
            "firm_id": firm_id,
        },
    )


def _build_news_scanner_inputs(
    case: Case,
    seed_payload: dict[str, Any],
    *,
    cfg: PhaseConfig,
) -> AgentInputs:
    seed = seed_payload.get("evidence.e3_news_scanner") or {}
    tickers = seed.get("tickers") or list(cfg.tickers)
    recent_events = seed.get("recent_news_events") or []
    avail_ids = seed.get("available_news_ids") or [
        e.get("news_id") for e in recent_events if e.get("news_id")
    ]
    return AgentInputs(
        case_id=case.case_id,
        case_mode=case.case_mode,
        case_intent=getattr(case, "case_intent", None),
        payload={
            "case_id": case.case_id,
            "tickers": tickers,
            "recent_news_events": recent_events,
            "available_news_ids": avail_ids,
        },
    )


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


async def _dispatch(
    *,
    case: Case,
    agent_id: str,
    inputs: AgentInputs,
    db: AsyncSession | None,
    cache: CacheBackend | None,
    template: PromptTemplate | None,
    key: str,
) -> RealDispatchOutput:
    """Single-agent dispatch wrapper; raises :class:`PhaseDispatchError` on failure."""
    # Await coroutine inputs (e.g. from async input builders).
    if asyncio.iscoroutine(inputs):
        inputs = await inputs
    try:
        return await agent_runtime.dispatch_real_agent(
            case=case,
            agent_id=agent_id,
            agent_inputs_override=inputs,
            skill_template_override=template,
            cache=cache,
            db=db,
        )
    except Exception as exc:
        raise PhaseDispatchError(key, exc) from exc


async def _run_parallel_phase(
    *,
    case: Case,
    phase_specs: list[tuple[str, Any, str]],
    db: AsyncSession | None,
    cache: CacheBackend | None,
    template: PromptTemplate | None,
    phase_num: int,
) -> dict[str, RealDispatchOutput]:
    """Run a list of (key, inputs_coro_or_inputs, agent_id) in parallel.

    ``return_exceptions=True`` so one failure doesn't cancel sibling
    tasks.  After gathering, the first exception is re-raised as
    :class:`PhaseDispatchError`.
    """
    if not phase_specs:
        return {}

    async def _one(key: str, inputs_src: Any, agent_id: str) -> RealDispatchOutput:
        inputs = await inputs_src if asyncio.iscoroutine(inputs_src) else inputs_src
        return await _dispatch(
            case=case, agent_id=agent_id, inputs=inputs,
            db=db, cache=cache, template=template, key=key,
        )

    gathered = await asyncio.gather(
        *[_one(k, inp, aid) for k, inp, aid in phase_specs],
        return_exceptions=True,
    )

    results: dict[str, RealDispatchOutput] = {}
    for (key, _, _), outcome in zip(phase_specs, gathered):
        if isinstance(outcome, BaseException):
            raise PhaseDispatchError(key, outcome) from outcome
        results[key] = outcome

    logger.debug("Phase %d complete: %d agents ran", phase_num, len(results))
    return results


__all__ = [
    "PhaseConfig",
    "PhaseDispatchError",
    "PhaseResult",
    "run_phases",
]
