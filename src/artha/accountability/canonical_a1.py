"""§13.5 — A1 Accountability / Challenge Layer (LLM-backed, advisory).

A1 reads the case bundle (evidence verdicts, S1 synthesis, IC1 deliberation,
governance outputs, briefings, clarifications) and surfaces:

  * `challenge_points` — counter-arguments, stress tests, edge cases.
  * `alternative_proposals` — operationally-feasible alternatives.
  * `stress_test_scenarios` — specific, named, testable stress conditions.
  * `accountability_flags` — flags against briefings / clarifications per §9.6
    (close-paraphrase, verdict-anticipation).

Per §13.5.6 A1 is **advisory only** — outputs surface to the human alongside
synthesis + governance, but never gate. The case proceeds regardless of A1
severity. The deterministic layer enforces:

  * Stress-test specificity — at least one named impact per scenario.
  * Alternative-proposal feasibility — surface `infeasible` flag when no
    L4 instruments cited.
  * Accountability-flag de-duplication.
"""

from __future__ import annotations

import logging
from typing import Any

from artha.canonical.agent_envelope import AgentActivationEnvelope
from artha.canonical.evidence_verdict import StandardEvidenceVerdict
from artha.canonical.governance import (
    A1Challenge,
    AccountabilityFlag,
    AlternativeProposal,
    ChallengePoint,
    G1Evaluation,
    G2Evaluation,
    G3Evaluation,
    StressTestScenario,
    _LlmA1Output,
)
from artha.canonical.synthesis import IC1Deliberation, S1Synthesis
from artha.common.clock import get_clock
from artha.common.errors import ArthaError
from artha.common.hashing import payload_hash
from artha.common.types import (
    InputsUsedManifest,
)
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest

logger = logging.getLogger(__name__)


# Minimum specificity bars enforced deterministically.
MIN_NAMED_IMPACTS_PER_SCENARIO = 1
MIN_L4_INSTRUMENTS_FOR_FEASIBLE = 1


class A1LLMUnavailableError(ArthaError):
    """Raised when A1's LLM provider fails."""


_SYSTEM_PROMPT = """\
You are A1, the Accountability / Challenge Layer for Samriddhi AI (§13.5).

Your job: read the synthesis + governance outputs and surface (a) challenges
to the prevailing recommendation, (b) operationally-feasible alternative
proposals from the L4 manifest, (c) specific stress-test scenarios, and (d)
accountability flags against briefings / clarifications per §9.6.

Strict rules:
- Output JSON with: challenge_points, alternative_proposals,
  stress_test_scenarios, accountability_flags, confidence (0.0-1.0),
  reasoning_trace.
- Stress-test scenarios MUST have specific named conditions and named
  impacts (not vague language like "market downturn"; instead "Nifty -25%
  with debt yields +200bps").
- Alternative proposals MUST cite at least one L4 instrument by id.
- Accountability flags: only flag a briefing for `briefing_close_paraphrase`
  when its text closely mirrors agent-verdict wording. Only flag a
  clarification for `clarification_verdict_anticipation` when the text
  steers toward a predetermined verdict.
- You are advisory only. NEVER produce decision language ("approve",
  "reject"). Surface findings only.
"""


class AccountabilitySurface:
    """§13.5 LLM-backed challenge layer.

    Construction:
      * `provider` — LLM provider for the challenge generation.
      * `prompt_version` / `agent_version` — pinned for replay.
    """

    agent_id = "advisory_challenge"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        prompt_version: str = "0.1.0",
        agent_version: str = "0.1.0",
    ) -> None:
        self._provider = provider
        self._prompt_version = prompt_version
        self._agent_version = agent_version

    # --------------------- Public API --------------------------------

    async def evaluate(
        self,
        envelope: AgentActivationEnvelope,
        *,
        verdicts: list[StandardEvidenceVerdict],
        s1_synthesis: S1Synthesis,
        ic1_deliberation: IC1Deliberation | None = None,
        g1: G1Evaluation | None = None,
        g2: G2Evaluation | None = None,
        g3: G3Evaluation | None = None,
        clarification_event_ids: list[str] | None = None,
        briefing_event_ids: list[str] | None = None,
    ) -> A1Challenge:
        """Run A1 over the full case bundle. Returns an `A1Challenge`."""
        signals_block = self._render_signals(
            verdicts=verdicts,
            s1_synthesis=s1_synthesis,
            ic1_deliberation=ic1_deliberation,
            g1=g1,
            g2=g2,
            g3=g3,
        )
        signals_input_for_hash = self._collect_input_for_hash(
            envelope=envelope,
            verdicts=verdicts,
            s1_synthesis=s1_synthesis,
            ic1_deliberation=ic1_deliberation,
            g1=g1,
            g2=g2,
            g3=g3,
        )

        try:
            llm_output = await self._provider.complete_structured(
                LLMRequest(
                    messages=[
                        LLMMessage(role="system", content=_SYSTEM_PROMPT),
                        LLMMessage(
                            role="user",
                            content=self._render_user_prompt(envelope, signals_block),
                        ),
                    ],
                    temperature=0.0,
                ),
                _LlmA1Output,
            )
        except Exception as exc:
            logger.warning("A1 LLM unavailable: %s", exc)
            raise A1LLMUnavailableError(
                f"a1 LLM provider unavailable: {exc}"
            ) from exc

        # Deterministic post-processing: feasibility + specificity.
        challenge_points = self._dedupe_challenges(llm_output.challenge_points)
        alternatives = [
            self._enforce_feasibility(p) for p in llm_output.alternative_proposals
        ]
        scenarios = [
            self._enforce_specificity(s) for s in llm_output.stress_test_scenarios
        ]
        flags = self._dedupe_flags(llm_output.accountability_flags)

        manifest = self._build_inputs_used_manifest(signals_input_for_hash)

        return A1Challenge(
            case_id=envelope.case.case_id,
            timestamp=get_clock().now(),
            run_mode=envelope.run_mode,
            challenge_points=challenge_points,
            alternative_proposals=alternatives,
            stress_test_scenarios=scenarios,
            accountability_flags=flags,
            confidence=llm_output.confidence,
            reasoning_trace=llm_output.reasoning_trace,
            inputs_used_manifest=manifest,
            input_hash=payload_hash(signals_input_for_hash),
            prompt_version=self._prompt_version,
            agent_version=self._agent_version,
        )

    # --------------------- Helpers ----------------------------------

    def _render_signals(
        self,
        *,
        verdicts: list[StandardEvidenceVerdict],
        s1_synthesis: S1Synthesis,
        ic1_deliberation: IC1Deliberation | None,
        g1: G1Evaluation | None,
        g2: G2Evaluation | None,
        g3: G3Evaluation | None,
    ) -> str:
        lines: list[str] = []
        lines.append(
            f"s1.consensus.risk_level = {s1_synthesis.consensus.risk_level.value} "
            f"@ confidence {s1_synthesis.consensus.confidence:.2f}"
        )
        for c in s1_synthesis.conflict_areas:
            lines.append(
                f"s1.conflict.{c.dimension} severity={c.severity} "
                f"agents={','.join(c.agents_flagging)}"
            )
        lines.append(f"s1.escalation_recommended = {s1_synthesis.escalation_recommended}")
        lines.append(f"s1.uncertainty_flag = {s1_synthesis.uncertainty_flag}")

        for v in verdicts:
            lines.append(
                f"verdict.{v.agent_id}.risk_level = {v.risk_level.value} "
                f"flags={','.join(v.flags) or '<none>'}"
            )

        if ic1_deliberation is not None:
            lines.append(
                f"ic1.recommendation = {ic1_deliberation.recommendation.value}"
            )
            for d in ic1_deliberation.dissent_recorded:
                lines.append(
                    f"ic1.dissent.{d.source_role.value} = {d.dissent_point[:200]}"
                )

        if g1 is not None:
            lines.append(f"g1.aggregated_status = {g1.aggregated_status.value}")
            for r in g1.breach_reasons:
                lines.append(f"g1.breach = {r}")
        if g2 is not None:
            lines.append(f"g2.aggregated_permission = {g2.aggregated_permission.value}")
            for r in g2.blocking_reasons:
                lines.append(f"g2.block = {r}")
        if g3 is not None:
            lines.append(f"g3.permission = {g3.permission.value}")

        return "\n".join(lines)

    def _render_user_prompt(
        self,
        envelope: AgentActivationEnvelope,
        signals_block: str,
    ) -> str:
        return "\n".join(
            [
                f"Case: {envelope.case.case_id}",
                f"Client: {envelope.case.client_id}",
                f"Dominant lens: {envelope.case.dominant_lens.value}",
                f"Run mode: {envelope.run_mode.value}",
                "Signals:",
                signals_block,
                "Produce the structured A1 challenge per the system prompt's schema.",
            ]
        )

    def _enforce_specificity(self, scenario: StressTestScenario) -> StressTestScenario:
        """§13.5.8 Test 2 — stress tests must be specific & testable."""
        if len(scenario.named_impacts) >= MIN_NAMED_IMPACTS_PER_SCENARIO:
            return scenario
        # Append a deterministic placeholder so the test sees the scenario but
        # the operator knows it's unverified.
        return StressTestScenario(
            scenario_name=scenario.scenario_name,
            conditions=list(scenario.conditions),
            named_impacts=list(scenario.named_impacts) + ["impact_unspecified"],
            severity=scenario.severity,
        )

    def _enforce_feasibility(self, proposal: AlternativeProposal) -> AlternativeProposal:
        """§13.5.8 Test 3 — feasibility = at least one L4 instrument cited."""
        if len(proposal.cited_l4_instruments) >= MIN_L4_INSTRUMENTS_FOR_FEASIBLE:
            return proposal
        return AlternativeProposal(
            proposal_summary=proposal.proposal_summary,
            structure_changes=list(proposal.structure_changes),
            rationale=proposal.rationale,
            feasibility_check="infeasible",
            cited_l4_instruments=list(proposal.cited_l4_instruments),
        )

    def _dedupe_challenges(
        self, challenges: list[ChallengePoint]
    ) -> list[ChallengePoint]:
        seen: set[tuple[str, str]] = set()
        out: list[ChallengePoint] = []
        for c in challenges:
            key = (c.challenge_type.value, c.content[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        return out

    def _dedupe_flags(
        self, flags: list[AccountabilityFlag]
    ) -> list[AccountabilityFlag]:
        seen: set[tuple[str, str | None]] = set()
        out: list[AccountabilityFlag] = []
        for f in flags:
            key = (f.flag_type.value, f.flagged_event_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out

    def _collect_input_for_hash(
        self,
        *,
        envelope: AgentActivationEnvelope,
        verdicts: list[StandardEvidenceVerdict],
        s1_synthesis: S1Synthesis,
        ic1_deliberation: IC1Deliberation | None,
        g1: G1Evaluation | None,
        g2: G2Evaluation | None,
        g3: G3Evaluation | None,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "envelope": envelope.model_dump(mode="json"),
            "verdict_input_hashes": sorted(v.input_hash for v in verdicts),
            "s1_input_hash": s1_synthesis.input_hash,
            "ic1_input_hash": ic1_deliberation.input_hash if ic1_deliberation else None,
            "g1_input_hash": g1.input_hash if g1 else None,
            "g2_input_hash": g2.input_hash if g2 else None,
            "g3_input_hash": g3.input_hash if g3 else None,
        }

    def _build_inputs_used_manifest(
        self, signals_input_for_hash: dict[str, Any]
    ) -> InputsUsedManifest:
        inputs_dict: dict[str, dict[str, str]] = {}
        for k, v in signals_input_for_hash.items():
            if k == "envelope":
                inputs_dict["envelope"] = {"hash": payload_hash(v)}
            else:
                inputs_dict[k] = {"shape_hash": payload_hash(v) if v is not None else ""}
        return InputsUsedManifest(inputs=inputs_dict)


__all__ = [
    "MIN_L4_INSTRUMENTS_FOR_FEASIBLE",
    "MIN_NAMED_IMPACTS_PER_SCENARIO",
    "A1LLMUnavailableError",
    "AccountabilitySurface",
]
