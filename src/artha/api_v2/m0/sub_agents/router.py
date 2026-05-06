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

#: Default evidence-agent set per case mode. The order here is the
#: order returned to the synthesizer. Diagnostic + briefing modes
#: skip the alternatives + tax slices because they don't run the
#: full materiality pipeline (FR 20.1 §6).
_BY_MODE: dict[CaseMode, tuple[str, ...]] = {
    CaseMode.PROPOSED_ACTION: (
        "e1_equity_evidence",
        "e1_debt_evidence",
        "e1_alternatives_evidence",
        "e1_macro_evidence",
        "e1_sentiment_evidence",
        "e1_behavioural_evidence",
        "e1_tax_evidence",
    ),
    CaseMode.SCENARIO: (
        "e1_equity_evidence",
        "e1_debt_evidence",
        "e1_alternatives_evidence",
        "e1_macro_evidence",
        "e1_sentiment_evidence",
    ),
    CaseMode.DIAGNOSTIC: (
        "e1_equity_evidence",
        "e1_debt_evidence",
        "e1_macro_evidence",
        "e1_behavioural_evidence",
    ),
    CaseMode.BRIEFING: (
        "e1_equity_evidence",
        "e1_debt_evidence",
        "e1_macro_evidence",
    ),
}

#: Intent-specific overlays added on top of the mode default.
_INTENT_ADDS: dict[CaseIntent, tuple[str, ...]] = {
    CaseIntent.TAX_LOSS_HARVESTING: ("e1_tax_evidence",),
    CaseIntent.LIQUIDITY_MOBILISATION: ("e1_tax_evidence",),
}

#: Lens-specific overlays.
_LENS_ADDS: dict[DominantLens, tuple[str, ...]] = {
    DominantLens.PORTFOLIO_SHIFT: ("e1_behavioural_evidence",),
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
