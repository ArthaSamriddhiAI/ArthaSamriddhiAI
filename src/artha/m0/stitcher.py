"""§8.6 — M0.Stitcher: assemble the human-facing artifact from the case bundle.

The stitcher reads the structured outputs (S1 synthesis, IC1 deliberation,
M0 outputs, evidence verdicts) and produces a `RenderedArtifact` with six
sections (§14): case header, recommendation, supporting evidence, concerns,
decision options, audit-trail link.

Per §8.6.4, composition is faithful — every claim in the natural-language
text must trace to a structured component. Pass 11 ships the deterministic
structured-component arrangement plus an LLM-backed narrative composition;
length-budget enforcement runs deterministically post-LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from artha.canonical.case import CaseObject, DominantLens
from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.synthesis import (
    IC1Deliberation,
    RenderedArtifact,
    RenderingDecision,
    S1Synthesis,
    _LlmStitcherOutput,
)
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.types import (
    InputsUsedManifest,
    MaterialityGateResult,
)
from artha.common.ulid import new_ulid
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


# Length budget for the natural-language artifact. Test §8.6.8 #2 requires
# ≥95% under budget on first composition; over-length triggers a compression
# pass (Pass 11 implements truncation; future passes wire a compression LLM).
DEFAULT_LENGTH_BUDGET_TOKENS: int = 1200


class StitcherLLMUnavailableError(ArthaError):
    """Raised when the stitcher's LLM provider fails (no narrative composed)."""


_SYSTEM_PROMPT = """\
You are M0.Stitcher (§8.6) for Samriddhi AI.

Your job: compose the human-facing artifact for a wealth-management case.
You consume the structured S1 synthesis, IC1 deliberation, and evidence
verdicts already produced; you do NOT add new analysis or invent claims.

Strict rules:
- Output JSON with: natural_language_text (the artifact), section_lengths
  (token counts per section).
- Every claim in natural_language_text must trace to a structured input.
  No new evidence, no invented numbers.
- Lens-aware framing: portfolio-dominant cases lead with portfolio findings;
  proposal-dominant cases lead with the recommendation and counterfactual.
- Six sections in order: case_header, recommendation, supporting_evidence,
  concerns, decision_options, audit_trail.
- Plain formal English. No emojis, no marketing copy.
- Length budget: aim for ≤1200 tokens total.
"""


class M0Stitcher:
    """§8.6 — M0.Stitcher artifact assembly.

    Construction:
      * `provider` — LLM for narrative composition.
      * `length_budget_tokens` — overall token budget (defaults to 1200).
      * `prompt_version` / `stitcher_version` — pinned for replay.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        length_budget_tokens: int = DEFAULT_LENGTH_BUDGET_TOKENS,
        prompt_version: str = "0.1.0",
        stitcher_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._length_budget = length_budget_tokens
        self._prompt_version = prompt_version
        self._stitcher_version = stitcher_version

    # --------------------- Public API --------------------------------

    async def render(
        self,
        case: CaseObject,
        *,
        s1_synthesis: S1Synthesis,
        ic1_deliberation: IC1Deliberation | None = None,
        verdicts: list[StandardEvidenceVerdict] | None = None,
        a1_challenges: list[str] | None = None,
        governance_escalations: list[str] | None = None,
        portfolio_summary: dict[str, Any] | None = None,
        indian_context_summary: dict[str, Any] | None = None,
    ) -> RenderedArtifact:
        """Compose the rendered artifact end-to-end."""
        verdicts = verdicts or []
        a1_challenges = a1_challenges or []
        governance_escalations = governance_escalations or []

        # ----- 1) Build structured components deterministically -----
        structured = self._build_structured_components(
            case=case,
            s1_synthesis=s1_synthesis,
            ic1_deliberation=ic1_deliberation,
            verdicts=verdicts,
            a1_challenges=a1_challenges,
            governance_escalations=governance_escalations,
            portfolio_summary=portfolio_summary,
            indian_context_summary=indian_context_summary,
        )

        # ----- 2) Decide which optional sections to include -----
        rendering_decisions = self._build_rendering_decisions(
            ic1_deliberation=ic1_deliberation,
            a1_challenges=a1_challenges,
            governance_escalations=governance_escalations,
        )

        # ----- 3) Compose narrative via LLM -----
        signals_input_for_hash = self._collect_input_for_hash(
            case, s1_synthesis, ic1_deliberation, verdicts, structured
        )

        try:
            llm_output = await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=_SYSTEM_PROMPT),
                        LLMMessage(
                            role="user",
                            content=self._render_user_prompt(
                                case, s1_synthesis, ic1_deliberation, structured
                            ),
                        ),
                    ],
                    temperature=0.0,
                ),
                _LlmStitcherOutput,
            )
        except Exception as exc:
            logger.warning("M0.Stitcher LLM unavailable: %s", exc)
            raise StitcherLLMUnavailableError(
                f"M0.Stitcher LLM provider unavailable: {exc}"
            ) from exc

        # ----- 4) Length compliance -----
        final_text = llm_output.natural_language_text
        section_lengths = dict(llm_output.section_lengths)

        total_tokens = self._approx_tokens(final_text)
        if total_tokens > self._length_budget:
            # Compression pass: deterministic truncation. Future passes can
            # call the LLM again with a "condense" prompt.
            final_text = self._truncate_to_budget(final_text, self._length_budget)
            rendering_decisions.append(
                RenderingDecision(
                    decision="condensed",
                    section="overall",
                    rationale=(
                        f"First composition was {total_tokens} tokens; "
                        f"exceeded budget {self._length_budget}. Truncated."
                    ),
                )
            )
            total_tokens = self._approx_tokens(final_text)

        section_lengths["__total__"] = total_tokens

        # ----- 5) Assemble RenderedArtifact -----
        manifest = self._build_inputs_used_manifest(signals_input_for_hash)
        ihash = payload_hash(signals_input_for_hash)

        return RenderedArtifact(
            artifact_id=new_ulid(),
            case_id=case.case_id,
            timestamp=self._now(),
            run_mode=s1_synthesis.run_mode,
            natural_language_text=final_text,
            structured_components=structured,
            length_statistics=section_lengths,
            rendering_decisions=rendering_decisions,
            inputs_used_manifest=manifest,
            input_hash=ihash,
            prompt_version=self._prompt_version,
            stitcher_version=self._stitcher_version,
        )

    # --------------------- Helpers ----------------------------------

    def _build_structured_components(
        self,
        *,
        case: CaseObject,
        s1_synthesis: S1Synthesis,
        ic1_deliberation: IC1Deliberation | None,
        verdicts: list[StandardEvidenceVerdict],
        a1_challenges: list[str],
        governance_escalations: list[str],
        portfolio_summary: dict[str, Any] | None,
        indian_context_summary: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        """Deterministic mapping from inputs → structured component sections.

        Replay correctness (§8.6.8 Test 5): structured components let an
        external reviewer reconstruct the case without other T1 events.
        """
        components: dict[str, dict[str, Any]] = {}

        # --- Section 1: case header ---
        components["case_header"] = {
            "case_id": case.case_id,
            "client_id": case.client_id,
            "advisor_id": case.advisor_id,
            "intent": case.intent.value,
            "dominant_lens": case.dominant_lens.value,
            "channel": case.channel.value,
        }

        # --- Section 2: recommendation ---
        recommendation_block: dict[str, Any] = {
            "consensus_risk_level": s1_synthesis.consensus.risk_level.value,
            "consensus_confidence": s1_synthesis.consensus.confidence,
            "escalation_recommended": s1_synthesis.escalation_recommended,
            "escalation_reason": s1_synthesis.escalation_reason,
        }
        if ic1_deliberation is not None:
            recommendation_block["ic1_recommendation"] = ic1_deliberation.recommendation.value
            recommendation_block["ic1_committee_position"] = (
                ic1_deliberation.committee_position.value
            )
            recommendation_block["ic1_conditions"] = list(ic1_deliberation.conditions)
        if s1_synthesis.counterfactual_framing is not None:
            recommendation_block["counterfactual"] = (
                s1_synthesis.counterfactual_framing.model_dump(mode="json")
            )
        components["recommendation"] = recommendation_block

        # --- Section 3: supporting evidence ---
        components["supporting_evidence"] = {
            "agreement_areas": list(s1_synthesis.agreement_areas),
            "verdicts": [
                {
                    "agent_id": v.agent_id,
                    "risk_level": v.risk_level.value,
                    "confidence": v.confidence,
                    "flags": list(v.flags),
                    "drivers": [d.model_dump(mode="json") for d in v.drivers[:5]],
                }
                for v in verdicts
            ],
            "narrative_citations": list(s1_synthesis.citations),
        }

        # --- Section 4: concerns ---
        concerns_block: dict[str, Any] = {
            "conflict_areas": [c.model_dump(mode="json") for c in s1_synthesis.conflict_areas],
            "uncertainty_flag": s1_synthesis.uncertainty_flag,
            "uncertainty_reasons": list(s1_synthesis.uncertainty_reasons),
        }
        if ic1_deliberation is not None and ic1_deliberation.dissent_recorded:
            concerns_block["ic1_dissent"] = [
                d.model_dump(mode="json") for d in ic1_deliberation.dissent_recorded
            ]
        if a1_challenges:
            concerns_block["a1_challenges"] = list(a1_challenges)
        if governance_escalations:
            concerns_block["governance_escalations"] = list(governance_escalations)
        components["concerns"] = concerns_block

        # --- Section 5: decision options ---
        # Per §14, decision options are the explicit choices presented to the
        # advisor with the system recommendation pre-selected.
        decision_block: dict[str, Any] = {
            "system_recommendation": (
                ic1_deliberation.recommendation.value if ic1_deliberation else "deferred"
            ),
            "options": ["proceed", "modify", "do_not_proceed", "defer"],
            "escalation_to_human": (
                ic1_deliberation.escalation_to_human if ic1_deliberation else True
            ),
        }
        components["decision_options"] = decision_block

        # --- Section 6: audit trail ---
        components["audit_trail"] = {
            "s1_input_hash": s1_synthesis.input_hash,
            "ic1_input_hash": (
                ic1_deliberation.input_hash if ic1_deliberation else None
            ),
            "verdict_input_hashes": [v.input_hash for v in verdicts],
            "case_pinned_versions": (
                case.pinned_versions.model_dump(mode="json")
                if case.pinned_versions
                else {}
            ),
        }

        # --- Optional: portfolio + Indian context summaries ---
        if portfolio_summary:
            components["portfolio_summary"] = portfolio_summary
        if indian_context_summary:
            components["indian_context_summary"] = indian_context_summary

        return components

    def _build_rendering_decisions(
        self,
        *,
        ic1_deliberation: IC1Deliberation | None,
        a1_challenges: list[str],
        governance_escalations: list[str],
    ) -> list[RenderingDecision]:
        """Record which optional sections were included / excluded."""
        decisions: list[RenderingDecision] = []

        if ic1_deliberation is None:
            decisions.append(
                RenderingDecision(
                    decision="excluded",
                    section="ic1_deliberation",
                    rationale="IC1 not convened on this case.",
                )
            )
        elif (
            ic1_deliberation.materiality_gate_result.fired
            is MaterialityGateResult.SKIP
        ):
            decisions.append(
                RenderingDecision(
                    decision="condensed",
                    section="ic1_deliberation",
                    rationale="IC1 materiality gate skipped; minutes section abbreviated.",
                )
            )
        else:
            decisions.append(
                RenderingDecision(
                    decision="included",
                    section="ic1_deliberation",
                    rationale="IC1 fired; minutes included verbatim.",
                )
            )

        if a1_challenges:
            decisions.append(
                RenderingDecision(
                    decision="included",
                    section="a1_challenges",
                    rationale=f"{len(a1_challenges)} A1 challenge(s) surfaced.",
                )
            )

        if governance_escalations:
            decisions.append(
                RenderingDecision(
                    decision="included",
                    section="governance_escalations",
                    rationale=f"{len(governance_escalations)} governance escalation(s) surfaced.",
                )
            )

        return decisions

    def _render_user_prompt(
        self,
        case: CaseObject,
        s1_synthesis: S1Synthesis,
        ic1_deliberation: IC1Deliberation | None,
        structured: dict[str, dict[str, Any]],
    ) -> str:
        lines = [
            f"Case: {case.case_id}",
            f"Client: {case.client_id}",
            f"Dominant lens: {case.dominant_lens.value}",
            f"S1 consensus: {s1_synthesis.consensus.risk_level.value} "
            f"@ confidence {s1_synthesis.consensus.confidence:.2f}",
            f"S1 narrative: {s1_synthesis.synthesis_narrative[:600]}",
        ]
        if ic1_deliberation is not None:
            lines.append(
                f"IC1 recommendation: {ic1_deliberation.recommendation.value} "
                f"({ic1_deliberation.committee_position.value})"
            )
            if ic1_deliberation.conditions:
                lines.append(f"IC1 conditions: {ic1_deliberation.conditions}")
        lines.append(f"Structured components keys: {sorted(structured.keys())}")
        lens = case.dominant_lens
        if lens is DominantLens.PORTFOLIO:
            lines.append(
                "Lead with portfolio findings, then proposal-relative framing."
            )
        else:
            lines.append(
                "Lead with the recommendation and counterfactual framing."
            )
        lines.append(
            "Compose the artifact per the system prompt. Respect length budget."
        )
        return "\n".join(lines)

    def _approx_tokens(self, text: str) -> int:
        """Rough token estimate: 1 token ≈ 4 chars (English heuristic)."""
        return max(1, len(text) // 4)

    def _truncate_to_budget(self, text: str, budget_tokens: int) -> str:
        """Deterministic truncation when the LLM overflows the budget."""
        max_chars = budget_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 24].rstrip() + " [truncated for length]"

    def _collect_input_for_hash(
        self,
        case: CaseObject,
        s1_synthesis: S1Synthesis,
        ic1_deliberation: IC1Deliberation | None,
        verdicts: list[StandardEvidenceVerdict],
        structured: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "stitcher": "m0.stitcher",
            "case_id": case.case_id,
            "s1_input_hash": s1_synthesis.input_hash,
            "ic1_input_hash": (
                ic1_deliberation.input_hash if ic1_deliberation else None
            ),
            "verdict_input_hashes": sorted(v.input_hash for v in verdicts),
            "structured_keys": sorted(structured.keys()),
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)

    def _now(self) -> datetime:
        return get_clock().now()


__all__ = [
    "DEFAULT_LENGTH_BUDGET_TOKENS",
    "M0Stitcher",
    "StitcherLLMUnavailableError",
]
