"""Cluster 7 chunk 7.4 — end-to-end integration test on the 23 cluster-6
seed cohort cases.

Pins:

- Loading the on-disk demo seed (15 households + 15 investors + 15
  mandates + 23 cases) under cluster-7 routing reaches the same
  terminal states as cluster 5/6 (stub mode default — no regression
  from adding the real-vs-stub router).
- Flipping E1 to real with a smart MockLLMClient: cases that have
  ``proposed_action_products`` route E1 through the real shim
  (``produced_via='real_agent'``) + populate the cache. Cases without
  products fall back to stub via the input-validation safety net.
- Cache hit on a second run for the same ticker (no incremental LLM
  call).
- :func:`agents.eval.harness.run_structural_eval` reports all cases
  passed (smoke test for the harness).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Register every model the test fixtures pull through Base.metadata.
import artha.api_v2.agents.cache.models  # noqa: F401
import artha.api_v2.auth.models  # noqa: F401
import artha.api_v2.c0.models  # noqa: F401
import artha.api_v2.cases.models  # noqa: F401
import artha.api_v2.d0.industry.models  # noqa: F401
import artha.api_v2.d0.instruments.models  # noqa: F401
import artha.api_v2.d0.macro.models  # noqa: F401
import artha.api_v2.d0.models  # noqa: F401
import artha.api_v2.investors.models  # noqa: F401
import artha.api_v2.llm.models  # noqa: F401
import artha.api_v2.m1.models  # noqa: F401
import artha.api_v2.m2.models  # noqa: F401
import artha.api_v2.observability.models  # noqa: F401
from artha.api_v2.agents import config as agents_config
from artha.api_v2.agents import runtime as agents_runtime
from artha.api_v2.agents.cache import repository as cache_repo
from artha.api_v2.agents.eval.harness import run_structural_eval
from artha.api_v2.agents.eval.rubric import RUBRIC_CASES, render_rubric_markdown
from artha.api_v2.agents.llm_client import LLMResponse
from artha.api_v2.agents.prompt_loader import PromptPayload, PromptTemplate
from artha.api_v2.auth.user_context import Role, UserContext
from artha.api_v2.cases import dispatch, seed_loader
from artha.api_v2.cases.models import Case, EvidenceVerdict
from artha.common.db.base import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _cio() -> UserContext:
    return UserContext(
        user_id="cio_anjali_mehta",
        firm_id="firm-1",
        role=Role.CIO,
        email="cio@example.com",
        name="CIO",
        session_id="s",
    )


# ---------------------------------------------------------------------------
# Smart mock LLM that routes by detected agent
# ---------------------------------------------------------------------------


def _e1_canned_payload(ticker: str) -> dict[str, Any]:
    """Canonical E1 verdict the smart mock returns for any E1 call.

    Slight ticker echo so the verdict round-trips through Pydantic +
    rule 5 without warnings.
    """
    reasoning = (
        f"{ticker} fundamentals: cashflow stability evident across "
        f"recent quarters; ROCE in the high-teens, leverage low, "
        f"valuation broadly fair, growth moderate, margins stable. "
        f"Reasoning supports a positive verdict at moderate confidence "
        f"given the constructive picture across all six metric "
        f"families. " * 5
    )
    return {
        "ticker": ticker,
        "verdict": "positive",
        "confidence": 0.7,
        "metric_evaluations": {
            "roce": {"reading": "in-range"},
            "leverage": {"reading": "low"},
            "earnings_quality": {"reading": "high"},
            "valuation": {"reading": "fair"},
            "growth": {"reading": "moderate"},
            "margins": {"reading": "stable"},
        },
        "per_stock_framework": {
            "framework_axis": "quality_maturity_best_in_class",
            "axis_value": "core large-cap value-quality blend",
        },
        "risk_signals": [],
        "reasoning_summary": reasoning,
        "key_drivers": [
            {"driver": "cashflow_stability", "weight": "high"},
            {"driver": "leverage_in_range", "weight": "medium"},
        ],
    }


class SmartMockLLMClient:
    """Mock LLM that returns the right canned payload per agent.

    Detection is based on a distinctive phrase in the rendered user
    prompt (each shim's user template carries unique wording). The
    client also extracts the ticker from the E1 prompt so the verdict
    is internally consistent.
    """

    def __init__(self) -> None:
        self.call_log: list[PromptPayload] = []

    def complete(self, prompt: PromptPayload) -> LLMResponse:
        self.call_log.append(prompt)
        text: str
        if "per-stock fundamental analysis" in prompt.user:
            ticker = self._extract_ticker(prompt.user)
            text = json.dumps(_e1_canned_payload(ticker))
        else:
            # No mock for M0.PRA in the e2e test — that agent stays on
            # the stub path (cluster 7.4 dependency).
            from artha.api_v2.agents.llm_client import LLMCallError

            raise LLMCallError(
                f"SmartMockLLMClient: unexpected agent prompt "
                f"(prefix={prompt.user[:80]!r})",
            )
        return LLMResponse(
            text=text,
            input_tokens=120,
            output_tokens=420,
            model=prompt.llm_model,
            stop_reason="end_turn",
        )

    @staticmethod
    def _extract_ticker(user_prompt: str) -> str:
        # The E1 user template renders ``Ticker: {ticker}\n``; pluck it
        # back out so the verdict mirrors what the dispatcher fed in.
        for line in user_prompt.splitlines():
            stripped = line.strip()
            if stripped.startswith("Ticker:"):
                return stripped.split(":", 1)[1].strip()
        return "UNKNOWN"


def _e1_skill_template() -> PromptTemplate:
    return PromptTemplate(
        agent_id="e1_listed_fundamental_equity",
        skill_md_version="1.1",
        system_body="E1 system body",
        llm_model="claude-sonnet-4-5",
        max_tokens=4096,
        temperature=0.2,
        output_schema_ref="../schemas/e1.json",
    )


def _patch_prompt_loader(monkeypatch) -> None:
    """Override ``load_prompt_template`` so the test doesn't need the
    on-disk skill.md file (the cluster 7 enriched skill.md ships in
    cluster 7.4)."""
    from artha.api_v2.agents import prompt_loader

    def _fake_loader(agent_id: str) -> PromptTemplate:
        return PromptTemplate(
            agent_id=agent_id,
            skill_md_version="1.1",
            system_body=f"{agent_id} system body",
            llm_model="claude-sonnet-4-5",
            max_tokens=4096,
            temperature=0.2,
            output_schema_ref=f"../schemas/{agent_id}.json",
        )

    monkeypatch.setattr(
        prompt_loader, "load_prompt_template", _fake_loader,
    )
    monkeypatch.setattr(
        agents_runtime, "load_prompt_template", _fake_loader,
    )


# ---------------------------------------------------------------------------
# Stub-mode regression: 23 cases reach the same terminal states.
# ---------------------------------------------------------------------------


class TestStubModeNoRegression:
    @pytest.mark.asyncio
    async def test_full_seed_loads_under_cluster7_routing(self, db) -> None:
        seed_loader.set_demo_fixture_path(None)
        dispatch.set_seed_fixture_path(None)
        dispatch.reset_seed_cache()
        agents_config.set_agent_impl_overrides(None)
        try:
            result = await seed_loader.load_demo_seed(db, actor=_cio())
            await db.commit()
            assert result.cases == 23
            cases = list(
                (
                    await db.execute(
                        select(Case).where(Case.is_seed_data.is_(True)),
                    )
                ).scalars()
            )
            assert len(cases) == 23
            # Every case stage row should still tag lookup_stub_seed
            # because no agent is flipped to real.
            verdicts = list(
                (
                    await db.execute(select(EvidenceVerdict))
                ).scalars()
            )
            assert verdicts
            assert all(
                v.produced_via == "lookup_stub_seed" for v in verdicts
            )
        finally:
            dispatch.reset_seed_cache()


# ---------------------------------------------------------------------------
# Real-mode E1 + smart mock against the 23-case cohort.
#
# The cluster-6 demo seed leaves ``proposed_action_products`` empty on
# every case (cluster 6 didn't author per-case ticker lists; cluster 8+
# fan-out wires those). With E1 flipped to real, the input-validation
# safety fallback in ``cases.dispatch._dispatch_real_path`` catches the
# missing-ticker ``AgentDispatchError`` and silently routes those calls
# back through the stub layer — proving the rollout-safety guard.
# ---------------------------------------------------------------------------


class TestRealModeE1OnSeedCohort:
    @pytest_asyncio.fixture(autouse=True)
    async def _setup(self, db, monkeypatch):
        seed_loader.set_demo_fixture_path(None)
        dispatch.set_seed_fixture_path(None)
        dispatch.reset_seed_cache()
        _patch_prompt_loader(monkeypatch)
        self.client = SmartMockLLMClient()
        agents_runtime.set_llm_client(self.client)
        agents_config.set_agent_impl_overrides(
            {"e1_listed_fundamental_equity": "real"},
        )
        yield
        agents_runtime.reset_runtime()
        agents_config.set_agent_impl_overrides(None)
        dispatch.reset_seed_cache()

    @pytest.mark.asyncio
    async def test_seed_loads_cleanly_with_safety_fallback(self, db) -> None:
        """All 23 cases must load even with E1 flipped to real, because
        the input-validation safety net falls back to stub for every
        case lacking ``proposed_action_products``."""
        result = await seed_loader.load_demo_seed(db, actor=_cio())
        await db.commit()
        assert result.cases == 23

        verdicts = list(
            (
                await db.execute(
                    select(EvidenceVerdict).where(
                        EvidenceVerdict.agent_id
                        == "e1_listed_fundamental_equity",
                    ),
                )
            ).scalars()
        )
        # Every E1 verdict in the cluster-6 fixture lacks a ticker, so
        # every dispatch falls back to stub — and the SmartMock should
        # never have been called.
        assert all(
            v.produced_via == "lookup_stub_seed" for v in verdicts
        )
        assert self.client.call_log == []


# ---------------------------------------------------------------------------
# Real-mode E1 with a synthetic case carrying proposed_action_products.
# ---------------------------------------------------------------------------


class _SyntheticCase:
    """Duck-typed Case for direct runtime dispatches.

    Mirrors the ORM ``Case`` surface (case_id, case_mode, etc.) and
    matches what the input-builder reads. We don't go through
    ``case_opener`` here because we're testing the runtime path, not
    the case lifecycle.
    """

    def __init__(
        self,
        *,
        ticker: str = "RELIANCE",
        case_id: str = "01HQZTEST00000000000000001",
        case_mode: str = "proposed_action",
    ) -> None:
        self.case_id = case_id
        self.case_mode = case_mode
        self.case_intent = "invest_top_up"
        self.proposed_action_products = [ticker]
        self.proposed_action = "top up the holding"
        self.dominant_lens = "growth"
        self.investor_id = "01HQZINV0000000000000000001"
        self.is_seed_data = False
        self.seed_archetype_id = None
        self.applicable_evidence_agents = []


class TestRealModeE1WithSyntheticCase:
    @pytest_asyncio.fixture(autouse=True)
    async def _setup(self, db, monkeypatch):
        _patch_prompt_loader(monkeypatch)
        self.client = SmartMockLLMClient()
        agents_runtime.set_llm_client(self.client)
        agents_config.set_agent_impl_overrides(
            {"e1_listed_fundamental_equity": "real"},
        )
        yield
        agents_runtime.reset_runtime()
        agents_config.set_agent_impl_overrides(None)

    @pytest.mark.asyncio
    async def test_synthetic_case_routes_through_real(self, db) -> None:
        from artha.api_v2.agents.cache.backend import DBCacheBackend

        backend = DBCacheBackend(db)
        out = await agents_runtime.dispatch_real_agent(
            case=_SyntheticCase(ticker="RELIANCE"),
            agent_id="e1_listed_fundamental_equity",
            cache=backend,
            db=db,
        )
        assert out.cache_hit is False
        assert out.parsed.structured["ticker"] == "RELIANCE"
        # Telemetry mirrors the SmartMockLLMClient.
        assert out.input_tokens == 120
        assert out.output_tokens == 420

    @pytest.mark.asyncio
    async def test_second_call_hits_cache(self, db) -> None:
        from artha.api_v2.agents.cache.backend import DBCacheBackend

        backend = DBCacheBackend(db)
        case = _SyntheticCase(ticker="HDFCBANK")
        await agents_runtime.dispatch_real_agent(
            case=case,
            agent_id="e1_listed_fundamental_equity",
            cache=backend,
            db=db,
        )
        before_calls = len(self.client.call_log)
        out2 = await agents_runtime.dispatch_real_agent(
            case=case,
            agent_id="e1_listed_fundamental_equity",
            cache=backend,
            db=db,
        )
        assert out2.cache_hit is True
        assert len(self.client.call_log) == before_calls

    @pytest.mark.asyncio
    async def test_manual_flag_invalidates_cached_verdict(self, db) -> None:
        from artha.api_v2.agents.cache import manual_flag as flag_service
        from artha.api_v2.agents.cache.backend import DBCacheBackend
        from artha.api_v2.agents.cache.models import E1VerdictCache

        backend = DBCacheBackend(db)
        case = _SyntheticCase(ticker="INFY")
        # Warm cache.
        await agents_runtime.dispatch_real_agent(
            case=case,
            agent_id="e1_listed_fundamental_equity",
            cache=backend,
            db=db,
        )
        rows_before = list(
            (
                await db.execute(
                    select(E1VerdictCache).where(
                        E1VerdictCache.ticker == "INFY",
                    ),
                )
            ).scalars()
        )
        assert len(rows_before) == 1
        assert rows_before[0].manual_flag_id is None

        # Analyst flips a flag → invalidates the no-flag row.
        out = await flag_service.create_manual_flag(
            db,
            ticker="INFY",
            flagged_by="alice@firm",
            reason="audit qualification surfaced",
        )
        assert out.cache_rows_invalidated == 1

        # Next call misses (different cache key) and produces a fresh
        # verdict + a new cache row keyed by the new manual_flag_id.
        before_calls = len(self.client.call_log)
        out2 = await agents_runtime.dispatch_real_agent(
            case=case,
            agent_id="e1_listed_fundamental_equity",
            cache=backend,
            db=db,
        )
        assert out2.cache_hit is False
        assert len(self.client.call_log) == before_calls + 1
        rows_after = list(
            (
                await db.execute(
                    select(E1VerdictCache).where(
                        E1VerdictCache.ticker == "INFY",
                    ),
                )
            ).scalars()
        )
        assert len(rows_after) == 1
        assert rows_after[0].manual_flag_id == out.new_flag.manual_flag_id

    @pytest.mark.asyncio
    async def test_telemetry_attributed_to_correct_case_id(self, db) -> None:
        from artha.api_v2.agents.cache.backend import DBCacheBackend
        from artha.api_v2.agents.cache.models import E1VerdictCache

        backend = DBCacheBackend(db)
        await agents_runtime.dispatch_real_agent(
            case=_SyntheticCase(
                ticker="TCS",
                case_id="01HQZSPECIFIC000000000001",
            ),
            agent_id="e1_listed_fundamental_equity",
            cache=backend,
            db=db,
        )
        row = (
            await db.execute(
                select(E1VerdictCache).where(E1VerdictCache.ticker == "TCS"),
            )
        ).scalar_one()
        assert row.case_id == "01HQZSPECIFIC000000000001"


# ---------------------------------------------------------------------------
# Eval framework smoke tests
# ---------------------------------------------------------------------------


class TestEvalHarness:
    def test_structural_harness_all_passed(self) -> None:
        report = run_structural_eval()
        assert report.all_passed, (
            f"Structural harness regressions: {report.failures!r}"
        )
        assert report.total >= 11

    def test_rubric_has_eight_cases(self) -> None:
        assert len(RUBRIC_CASES) == 8
        agents = {c.agent_id for c in RUBRIC_CASES}
        assert agents == {
            "e1_listed_fundamental_equity",
            "m0_portfolio_risk_analytics",
        }
        # Each case must declare exactly four review criteria
        # (chunk 7.4 §2.2: 4 criteria × 5 points × 8 cases = 160).
        for case in RUBRIC_CASES:
            assert len(case.review_criteria) == 4

    def test_rubric_markdown_renders(self) -> None:
        md = render_rubric_markdown()
        assert "# Cluster 7 manual review rubric" in md
        for case in RUBRIC_CASES:
            assert case.case_id in md
            assert case.expected_verdict_summary in md
        # Total scaffold present.
        assert "**Grand total /160**" in md


# ---------------------------------------------------------------------------
# Cache repository idempotency through the seed
# ---------------------------------------------------------------------------


class TestCacheRepositoryWithRealE1:
    """The cache repository's maintenance ops (TTL eviction, earnings
    invalidation) round-trip cleanly when rows are produced through
    the real-mode E1 path against synthetic cases."""

    @pytest_asyncio.fixture(autouse=True)
    async def _setup(self, db, monkeypatch):
        _patch_prompt_loader(monkeypatch)
        self.client = SmartMockLLMClient()
        agents_runtime.set_llm_client(self.client)
        agents_config.set_agent_impl_overrides(
            {"e1_listed_fundamental_equity": "real"},
        )
        yield
        agents_runtime.reset_runtime()
        agents_config.set_agent_impl_overrides(None)

    async def _warm_cache_for(self, db, tickers: tuple[str, ...]) -> None:
        from artha.api_v2.agents.cache.backend import DBCacheBackend

        backend = DBCacheBackend(db)
        for ticker in tickers:
            await agents_runtime.dispatch_real_agent(
                case=_SyntheticCase(ticker=ticker),
                agent_id="e1_listed_fundamental_equity",
                cache=backend,
                db=db,
            )

    @pytest.mark.asyncio
    async def test_evict_expired_idempotent_on_fresh_cache(self, db) -> None:
        await self._warm_cache_for(db, ("RELIANCE", "INFY", "HDFCBANK"))
        # Fresh rows — TTL eviction with default 90 days should drop
        # nothing.
        deleted = await cache_repo.evict_expired(db, ttl_days=90)
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_earnings_invalidation_drops_only_target_ticker(
        self, db,
    ) -> None:
        from artha.api_v2.agents.cache.models import E1VerdictCache

        await self._warm_cache_for(db, ("RELIANCE", "INFY", "HDFCBANK"))
        rows_before = list(
            (await db.execute(select(E1VerdictCache))).scalars(),
        )
        assert len(rows_before) == 3

        # Brand-new earnings event for RELIANCE → drop its row only.
        deleted = await cache_repo.invalidate_for_ticker_earnings(
            db, ticker="RELIANCE", new_earnings_id="E_NEW",
        )
        assert deleted == 1
        survivors_by_ticker = {
            r.ticker: r for r in (
                await db.execute(select(E1VerdictCache))
            ).scalars()
        }
        assert "RELIANCE" not in survivors_by_ticker
        assert "INFY" in survivors_by_ticker
        assert "HDFCBANK" in survivors_by_ticker
