"""M0 router — picks applicable evidence agents per case (FR 20.2 §3.1).

Purely deterministic: given a case mode + intent + dominant lens (and
optionally a manual override list), return the ordered tuple of
evidence agent_ids that should produce verdicts before synthesis. The
result is persisted on the case row as ``applicable_evidence_agents``
(see :class:`artha.api_v2.cases.models.Case`) so replay is reproducible.

The routing table is small enough to live inline; cluster 7+ may swap
this for an LLM-routed variant with the deterministic table as a
fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from artha.api_v2.cases.state_machine import CaseIntent, CaseMode, DominantLens

# ---------------------------------------------------------------------------
# Routing table
# ---------------------------------------------------------------------------

#: Default evidence-agent set per case mode (FR 20.3 cluster 6 revision).
#: Activation rules per principles §3.1:
#:
#: - E1 (listed/fundamental equity) — case involves listed equity
#: - E2 (industry/business) — case involves listed equity with sector tags
#: - E3 (macro/policy/news) — mandatory unconditional activation
#: - E4 (behavioural/historical) — always on case_mode + scenario;
#:   selective on diagnostic
#: - E5 (unlisted equity) — case involves unlisted equity
#: - E6 (PMS/AIF/SIF) — case involves PMS / AIF / SIF
#: - E7 (mutual fund) — case involves MF specifically
#:
#: The router's *default* per mode is the maximal common set; the
#: dispatcher prunes via per-case applicability flags. Briefing skips
#: the heavier evidence layer.
_BY_MODE: dict[CaseMode, tuple[str, ...]] = {
    CaseMode.PROPOSED_ACTION: (
        "e1_listed_fundamental_equity",
        "e2_industry_business",
        "e3_macro_policy_news",
        "e4_behavioural_historical",
        "e5_unlisted_equity",
        "e6_pms_aif_sif",
        "e7_mutual_fund",
    ),
    CaseMode.SCENARIO: (
        "e1_listed_fundamental_equity",
        "e2_industry_business",
        "e3_macro_policy_news",
        "e4_behavioural_historical",
        "e6_pms_aif_sif",
    ),
    CaseMode.DIAGNOSTIC: (
        "e1_listed_fundamental_equity",
        "e2_industry_business",
        "e3_macro_policy_news",
        "e4_behavioural_historical",
    ),
    CaseMode.BRIEFING: (
        "e3_macro_policy_news",
        "e4_behavioural_historical",
    ),
}

#: Intent-specific overlays added on top of the mode default.
_INTENT_ADDS: dict[CaseIntent, tuple[str, ...]] = {
    # Tax-related intents pull in MF analysis (E7) which surfaces
    # category-specific tax treatment.
    CaseIntent.TAX_LOSS_HARVESTING: ("e7_mutual_fund",),
    CaseIntent.LIQUIDITY_MOBILISATION: ("e7_mutual_fund",),
}

#: Lens-specific overlays.
_LENS_ADDS: dict[DominantLens, tuple[str, ...]] = {
    DominantLens.PORTFOLIO_SHIFT: ("e4_behavioural_historical",),
}


@dataclass(frozen=True)
class RouterDecision:
    """Result of :func:`route`: ordered evidence agent_ids + reasoning."""

    applicable_evidence_agents: tuple[str, ...]
    reason: str


def route(
    *,
    case_mode: CaseMode | str,
    case_intent: CaseIntent | str | None = None,
    dominant_lens: DominantLens | str | None = None,
    manual_override: tuple[str, ...] | None = None,
) -> RouterDecision:
    """Compute the evidence agent set for a case.

    A ``manual_override`` (CIO-curated) bypasses the routing table
    entirely; the returned tuple is the override verbatim with reason
    ``"manual_override"``. Otherwise the result is the mode default,
    deduplicated and order-preserved with intent + lens overlays.
    """
    if manual_override is not None:
        return RouterDecision(
            applicable_evidence_agents=tuple(manual_override),
            reason="manual_override",
        )

    mode = CaseMode(case_mode) if isinstance(case_mode, str) else case_mode
    base = list(_BY_MODE[mode])
    reasons: list[str] = [f"mode={mode.value}"]

    if case_intent is not None:
        intent_key = (
            CaseIntent(case_intent) if isinstance(case_intent, str) else case_intent
        )
        for extra in _INTENT_ADDS.get(intent_key, ()):
            if extra not in base:
                base.append(extra)
                reasons.append(f"intent={intent_key.value}")

    if dominant_lens is not None:
        lens_key = (
            DominantLens(dominant_lens)
            if isinstance(dominant_lens, str)
            else dominant_lens
        )
        for extra in _LENS_ADDS.get(lens_key, ()):
            if extra not in base:
                base.append(extra)
                reasons.append(f"lens={lens_key.value}")

    return RouterDecision(
        applicable_evidence_agents=tuple(base),
        reason="+".join(reasons),
    )


__all__ = ["RouterDecision", "route"]
