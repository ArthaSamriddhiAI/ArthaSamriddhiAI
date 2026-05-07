"""Cluster 5 chunk 5.4 — stub dispatch + seed fixture lookup.

The dispatch registry is the single place that maps an ``agent_id`` to
its stub function. The pipeline orchestrator (:mod:`.pipeline`) calls
:func:`dispatch_stub` once per stage and writes the returned payload
through the repository.

Seed-data plumbing: when a case has ``is_seed_data=True``, the
dispatcher looks the case's ``seed_archetype_id`` up in
``data/fixtures/case_seed_data.json``. Cluster 5.6 ships the actual
fixture; chunk 5.4 ships the loader + the lookup interface.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from artha.api_v2.cases import stubs
from artha.api_v2.cases.models import Case
from artha.api_v2.cases.state_machine import ProducedVia
from artha.api_v2.cases.stubs import StubContext

# ---------------------------------------------------------------------------
# Seed fixture
# ---------------------------------------------------------------------------

_DEFAULT_SEED_FIXTURE = (
    Path(__file__).resolve().parents[4] / "data" / "fixtures" / "case_seed_data.json"
)

_SEED_FIXTURE_OVERRIDE: Path | None = None
_seed_cache: dict[str, dict[str, Any]] | None = None


def get_seed_fixture_path() -> Path:
    return _SEED_FIXTURE_OVERRIDE if _SEED_FIXTURE_OVERRIDE is not None else _DEFAULT_SEED_FIXTURE


def set_seed_fixture_path(path: Path | None) -> None:
    """Test-only override of the seed-fixture file location."""
    global _SEED_FIXTURE_OVERRIDE, _seed_cache
    _SEED_FIXTURE_OVERRIDE = path
    _seed_cache = None


def load_seed_fixture() -> dict[str, dict[str, Any]]:
    """Return the parsed seed fixture (cached). Empty dict if missing.

    Shape: ``{archetype_id: {stage_key: payload, ...}, ...}``. Stage
    keys match the seed-payload conventions in :mod:`.stubs` (e.g.
    ``"evidence.e1_listed_fundamental_equity"``, ``"synthesis.case_mode"``).
    """
    global _seed_cache
    if _seed_cache is not None:
        return _seed_cache
    path = get_seed_fixture_path()
    if not path.exists():
        _seed_cache = {}
        return _seed_cache
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        _seed_cache = {}
        return _seed_cache
    _seed_cache = raw
    return _seed_cache


def get_seed_payload_for(case: Case) -> dict[str, Any]:
    """Return the seed payload dict for a case, or ``{}`` if non-seeded."""
    if not case.is_seed_data:
        return {}
    fixture = load_seed_fixture()

    # Cluster 6 stage 3: per-case payloads override per-archetype
    # payloads. Each archetype has 1-2 distinct cases (e.g. Lalitha's
    # PA + DIAG) with materially different synthesis narratives, so the
    # primary lookup key is ``case_id``. Fall back to ``seed_archetype_id``
    # for archetype-shared payloads (cluster 5 model).
    case_payload = fixture.get(case.case_id)
    if isinstance(case_payload, dict) and case_payload:
        return case_payload

    if case.seed_archetype_id:
        archetype = fixture.get(case.seed_archetype_id, {})
        if isinstance(archetype, dict):
            return archetype

    return {}


def produced_via_for(case: Case) -> ProducedVia:
    """Pick the ``produced_via`` value for stub-produced rows."""
    if case.is_seed_data:
        return ProducedVia.LOOKUP_STUB_SEED
    return ProducedVia.LOOKUP_STUB_PLACEHOLDER


# ---------------------------------------------------------------------------
# Stub registry
# ---------------------------------------------------------------------------


StubFn = Callable[[StubContext], dict[str, Any]]


#: Stage-row category used by the pipeline to pick the right repository
#: inserter. Mirrors the FR 20.1 §2 stage-table list.
class StageKind(str):
    PORTFOLIO_RISK = "portfolio_risk"
    EVIDENCE = "evidence"
    SYNTHESIS = "synthesis"
    IC1 = "ic1"
    GOVERNANCE = "governance"
    A1 = "a1"
    BRIEFING = "briefing"
    HEALTH = "health"


@dataclass(frozen=True)
class DispatchEntry:
    """Static metadata about a dispatchable stub.

    ``stage_kind`` tells the pipeline which inserter to call.
    ``stage_arg`` carries any inserter-specific argument (e.g. the
    governance gate identifier).
    """

    agent_id: str
    stage_kind: str
    stub_fn: StubFn
    stage_arg: str | None = None


#: The 16 canonical stub entries, keyed by ``agent_id``. The pipeline
#: uses this both to walk the case mode's stage list and to answer
#: ``"which agent produces this stage row?"``.
#:
#: Cluster 6 reframe (FR 20.3 cluster 6 revision §3): evidence agents
#: renumbered to E1-E7 with corrected per-domain framing. Cluster 5's
#: ``e1_equity_evidence`` etc. family is superseded.
STUB_DISPATCH: dict[str, DispatchEntry] = {
    "m0_portfolio_risk_analytics": DispatchEntry(
        agent_id="m0_portfolio_risk_analytics",
        stage_kind=StageKind.PORTFOLIO_RISK,
        stub_fn=stubs.stub_portfolio_risk_analytics,
    ),
    "e1_listed_fundamental_equity": DispatchEntry(
        agent_id="e1_listed_fundamental_equity",
        stage_kind=StageKind.EVIDENCE,
        stub_fn=stubs.stub_evidence_e1_listed_fundamental_equity,
    ),
    "e2_industry_business": DispatchEntry(
        agent_id="e2_industry_business",
        stage_kind=StageKind.EVIDENCE,
        stub_fn=stubs.stub_evidence_e2_industry_business,
    ),
    "e3_macro_policy_news": DispatchEntry(
        agent_id="e3_macro_policy_news",
        stage_kind=StageKind.EVIDENCE,
        stub_fn=stubs.stub_evidence_e3_macro_policy_news,
    ),
    "e4_behavioural_historical": DispatchEntry(
        agent_id="e4_behavioural_historical",
        stage_kind=StageKind.EVIDENCE,
        stub_fn=stubs.stub_evidence_e4_behavioural_historical,
    ),
    "e5_unlisted_equity": DispatchEntry(
        agent_id="e5_unlisted_equity",
        stage_kind=StageKind.EVIDENCE,
        stub_fn=stubs.stub_evidence_e5_unlisted_equity,
    ),
    "e6_pms_aif_sif": DispatchEntry(
        agent_id="e6_pms_aif_sif",
        stage_kind=StageKind.EVIDENCE,
        stub_fn=stubs.stub_evidence_e6_pms_aif_sif,
    ),
    "e7_mutual_fund": DispatchEntry(
        agent_id="e7_mutual_fund",
        stage_kind=StageKind.EVIDENCE,
        stub_fn=stubs.stub_evidence_e7_mutual_fund,
    ),
    "s1_case_mode": DispatchEntry(
        agent_id="s1_case_mode",
        stage_kind=StageKind.SYNTHESIS,
        stub_fn=stubs.stub_synthesis_case_mode,
        stage_arg="case_mode",
    ),
    "s1_diagnostic_mode": DispatchEntry(
        agent_id="s1_diagnostic_mode",
        stage_kind=StageKind.SYNTHESIS,
        stub_fn=stubs.stub_synthesis_diagnostic_mode,
        stage_arg="diagnostic",
    ),
    "s1_briefing_mode": DispatchEntry(
        agent_id="s1_briefing_mode",
        stage_kind=StageKind.SYNTHESIS,
        stub_fn=stubs.stub_synthesis_briefing_mode,
        stage_arg="briefing",
    ),
    "ic1_chair": DispatchEntry(
        agent_id="ic1_chair",
        stage_kind=StageKind.IC1,
        stub_fn=stubs.stub_ic1_deliberation,
    ),
    "g1_mandate_gate": DispatchEntry(
        agent_id="g1_mandate_gate",
        stage_kind=StageKind.GOVERNANCE,
        stub_fn=stubs.stub_governance_g1_mandate,
        stage_arg="g1_mandate",
    ),
    "g2_sebi_regulatory_gate": DispatchEntry(
        agent_id="g2_sebi_regulatory_gate",
        stage_kind=StageKind.GOVERNANCE,
        stub_fn=stubs.stub_governance_g2_sebi,
        stage_arg="g2_sebi_regulatory",
    ),
    "g3_action_filter_gate": DispatchEntry(
        agent_id="g3_action_filter_gate",
        stage_kind=StageKind.GOVERNANCE,
        stub_fn=stubs.stub_governance_g3_action_filter,
        stage_arg="g3_action_filter",
    ),
    "a1_challenge": DispatchEntry(
        agent_id="a1_challenge",
        stage_kind=StageKind.A1,
        stub_fn=stubs.stub_a1_challenge,
    ),
}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StubResult:
    """Output of :func:`dispatch_stub` — payload + dispatch metadata."""

    agent_id: str
    stage_kind: str
    stage_arg: str | None
    payload: dict[str, Any]
    produced_via: ProducedVia


def dispatch_stub(
    *,
    case: Case,
    agent_id: str,
    upstream: dict[str, Any] | None = None,
) -> StubResult:
    """Run the stub for ``agent_id`` against ``case`` and return its payload.

    Loads the seed-payload bundle from the on-disk fixture if the case
    is seed_data; otherwise the stub returns its placeholder default.
    """
    if agent_id not in STUB_DISPATCH:
        raise KeyError(
            f"Unknown agent_id {agent_id!r} (expected one of "
            f"{sorted(STUB_DISPATCH.keys())}).",
        )
    entry = STUB_DISPATCH[agent_id]
    seed_payload = get_seed_payload_for(case)
    via = produced_via_for(case)
    ctx = StubContext(
        case=case,
        produced_via=via,
        seed_payload=seed_payload,
        upstream=upstream or {},
    )
    payload = entry.stub_fn(ctx)
    return StubResult(
        agent_id=agent_id,
        stage_kind=entry.stage_kind,
        stage_arg=entry.stage_arg,
        payload=payload,
        produced_via=via,
    )


def list_dispatchable_agent_ids() -> list[str]:
    """Return the 16 agent_ids currently dispatched by the stub layer."""
    return sorted(STUB_DISPATCH.keys())


# ---------------------------------------------------------------------------
# Reset helpers (tests + dev hot-reload)
# ---------------------------------------------------------------------------


def reset_seed_cache() -> None:
    """Test helper: drop the cached seed fixture so the next call re-reads."""
    global _seed_cache
    _seed_cache = None


# Honour an env var so prod can disable hot-reloading the seed fixture
# (today the loader is on-demand + cached; this knob is forward-looking).
_HOT_RELOAD_ENV = "ARTHA_SEED_FIXTURE_HOT_RELOAD"


def _hot_reload_enabled() -> bool:
    val = os.environ.get(_HOT_RELOAD_ENV, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


__all__ = [
    "STUB_DISPATCH",
    "DispatchEntry",
    "StageKind",
    "StubResult",
    "dispatch_stub",
    "get_seed_fixture_path",
    "get_seed_payload_for",
    "list_dispatchable_agent_ids",
    "load_seed_fixture",
    "produced_via_for",
    "reset_seed_cache",
    "set_seed_fixture_path",
]
