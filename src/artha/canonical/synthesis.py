"""§15.8 — synthesis-layer schemas: S1, IC1.

S1 (§12.2 + §15.8.1) is the master synthesis agent: it consumes E1–E6
verdicts and produces a unified `S1Synthesis` object. IC1 (§12.3 + §15.8.2)
is the investment-committee agent: it runs a deterministic materiality gate
then four LLM-backed sub-roles (chair, devil's advocate, risk assessor,
minutes recorder) to produce an `IC1Deliberation`.

Both schemas inherit the standard replay discipline (input_hash + manifest)
so T1 replay reproduces the exact decision artifact.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.case import DominantLens
from artha.common.types import (
    ConfidenceField,
    Driver,
    InputsUsedManifest,
    MaterialityGateResult,
    Recommendation,
    RiskLevel,
    RunMode,
)

# ===========================================================================
# S1 — Master Synthesis (§15.8.1)
# ===========================================================================


class ConsensusBlock(BaseModel):
    """The headline risk/confidence pair S1 emits across the layer."""

    model_config = ConfigDict(extra="forbid")

    risk_level: RiskLevel
    confidence: ConfidenceField


class ConflictArea(BaseModel):
    """A structured conflict between two or more evidence agents (§12.2.2).

    `dimension` names the disagreement domain (e.g. "concentration"); the
    array of `agents_flagging` lists the conflicting agent_ids and what each
    said.
    """

    model_config = ConfigDict(extra="forbid")

    dimension: str
    agents_flagging: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"]
    description: str = ""


class AmplificationAssessment(BaseModel):
    """§3.5 / §12.2.2 — when multiple agents collectively raise the risk level.

    `present` is True when at least one driver from each of two-or-more agents
    points the same direction with severity ≥ MEDIUM.
    """

    model_config = ConfigDict(extra="forbid")

    present: bool = False
    drivers: list[Driver] = Field(default_factory=list)
    rationale: str = ""


class CounterfactualFraming(BaseModel):
    """§4.3 — every case is framed against the model-portfolio default.

    `model_default_recommendation` is what the bucket's model portfolio would
    suggest at the same horizon. `proposal_relative_to_default` describes
    how the proposal compares — improves / matches / degrades / orthogonal.
    """

    model_config = ConfigDict(extra="forbid")

    model_default_recommendation: str
    proposal_relative_to_default: Literal[
        "improves", "matches", "degrades", "orthogonal", "not_applicable"
    ] = "not_applicable"
    bucket: str | None = None  # the bucket whose model is the reference


class S1Synthesis(BaseModel):
    """§15.8.1 — master synthesis output from S1.

    S1 never decides; it surfaces consensus, agreements, conflicts, and an
    escalation recommendation. The recommendation enum lives on IC1, not S1.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity / replay
    agent_id: Literal["s1_synthesis"] = "s1_synthesis"
    case_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE

    # Consensus + supporting structure
    consensus: ConsensusBlock
    agreement_areas: list[str] = Field(default_factory=list)
    conflict_areas: list[ConflictArea] = Field(default_factory=list)

    # Uncertainty
    uncertainty_flag: bool = False
    uncertainty_reasons: list[str] = Field(default_factory=list)

    # Amplification + framing
    amplification: AmplificationAssessment | None = None
    mode_dominance: DominantLens
    counterfactual_framing: CounterfactualFraming | None = None

    # Escalation
    escalation_recommended: bool = False
    escalation_reason: str | None = None

    # Narrative + audit
    synthesis_narrative: str = ""
    reasoning_trace: str = ""

    # Replay
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    prompt_version: str = "0.1.0"
    agent_version: str = "0.1.0"

    # Citations: which agent_ids the narrative cites (§12.2.8 Test 6 — at least 3)
    citations: list[str] = Field(default_factory=list)


# ===========================================================================
# IC1 — Investment Committee (§15.8.2)
# ===========================================================================


class MaterialityGateBlock(BaseModel):
    """§12.3.2 — the deterministic gate's verdict.

    `signals` enumerates which materiality conditions tripped (ticket size,
    product complexity, S1 amplification flag, advisor request, firm policy).
    """

    model_config = ConfigDict(extra="forbid")

    fired: MaterialityGateResult  # CONVENE / SKIP
    signals: list[str] = Field(default_factory=list)
    rationale: str = ""


class CommitteePosition(str, Enum):
    """§15.8.2 — committee posture after deliberation."""

    CONSENSUS = "consensus"
    SPLIT = "split"


class IC1SubRole(str, Enum):
    """§12.3.4 — the four sub-roles inside the IC1 deliberation."""

    CHAIR = "chair"
    DEVILS_ADVOCATE = "devils_advocate"
    RISK_ASSESSOR = "risk_assessor"
    MINUTES_RECORDER = "minutes_recorder"


class SubRoleContribution(BaseModel):
    """§12.3.4 — one sub-role's contribution captured verbatim for replay."""

    model_config = ConfigDict(extra="forbid")

    sub_role: IC1SubRole
    contribution: str
    citations: list[str] = Field(default_factory=list)


class DissentPoint(BaseModel):
    """§15.8.2 — a recorded dissent point inside the deliberation."""

    model_config = ConfigDict(extra="forbid")

    dissent_point: str
    source_role: IC1SubRole
    reasoning: str = ""


class IC1Deliberation(BaseModel):
    """§15.8.2 — IC1 deliberation output.

    `recommendation` is one of `Recommendation` (proceed / modify /
    do_not_proceed / defer). `escalation_to_human` is always True per §12.3.6
    — IC1 never produces an autonomous decision. M0.Stitcher consumes this
    along with G1/G2/G3 outputs to compose the final artifact.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity / replay
    agent_id: Literal["ic1_deliberation"] = "ic1_deliberation"
    case_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE

    # Gate
    materiality_gate_result: MaterialityGateBlock

    # Posture + recommendation
    committee_position: CommitteePosition = CommitteePosition.CONSENSUS
    recommendation: Recommendation
    dissent_recorded: list[DissentPoint] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)  # populated when MODIFY

    # Minutes: per-sub-role contributions
    minutes: list[SubRoleContribution] = Field(default_factory=list)

    # Escalation
    escalation_to_human: bool = True

    # Narrative + audit
    reasoning_trace: str = ""

    # Replay
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    prompt_version: str = "0.1.0"
    agent_version: str = "0.1.0"


# ===========================================================================
# M0.Stitcher — RenderedArtifact (§15.6.5)
# ===========================================================================


class RenderingDecision(BaseModel):
    """§8.6 — one decision the stitcher made about what to include / condense."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["included", "excluded", "condensed"]
    section: str
    rationale: str = ""


class RenderedArtifact(BaseModel):
    """§15.6.5 — the human-facing artifact M0.Stitcher composes.

    The artifact has six sections per §14: case header, recommendation,
    supporting evidence, concerns, decision options, audit trail link. The
    stitcher composes natural-language text but every claim must trace to
    structured_components (test §8.6.8 #1 — faithful composition).
    """

    model_config = ConfigDict(extra="forbid")

    # Identity / replay
    artifact_id: str
    case_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE

    # Composed text
    natural_language_text: str

    # Structured components — keyed by §14 section
    structured_components: dict[str, dict] = Field(default_factory=dict)

    # Length stats per section + total tokens
    length_statistics: dict[str, int] = Field(default_factory=dict)

    # Rendering decisions (which optional content was included)
    rendering_decisions: list[RenderingDecision] = Field(default_factory=list)

    # Replay
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    prompt_version: str = "0.1.0"
    stitcher_version: str = "0.1.0"


# ===========================================================================
# Internal LLM-output shapes
# ===========================================================================


class _LlmS1Output(BaseModel):
    """Internal LLM-output shape for S1 — string-typed for mock provider compatibility."""

    model_config = ConfigDict(extra="forbid")

    risk_level_value: str
    confidence: ConfidenceField
    agreement_areas: list[str] = Field(default_factory=list)
    conflict_areas: list[ConflictArea] = Field(default_factory=list)
    uncertainty_flag: bool = False
    uncertainty_reasons: list[str] = Field(default_factory=list)
    amplification: AmplificationAssessment | None = None
    counterfactual_framing: CounterfactualFraming | None = None
    escalation_recommended: bool = False
    escalation_reason: str | None = None
    synthesis_narrative: str = ""
    reasoning_trace: str = ""
    citations: list[str] = Field(default_factory=list)


class _LlmIC1SubRoleOutput(BaseModel):
    """One sub-role's LLM output during IC1 deliberation."""

    model_config = ConfigDict(extra="forbid")

    contribution: str
    citations: list[str] = Field(default_factory=list)
    dissent_point: str | None = None
    proposed_recommendation: str | None = None  # Recommendation enum value
    proposed_conditions: list[str] = Field(default_factory=list)


class _LlmStitcherOutput(BaseModel):
    """Internal LLM-output shape for M0.Stitcher narrative composition."""

    model_config = ConfigDict(extra="forbid")

    natural_language_text: str
    section_lengths: dict[str, int] = Field(default_factory=dict)


__all__ = [
    "AmplificationAssessment",
    "CommitteePosition",
    "ConflictArea",
    "ConsensusBlock",
    "CounterfactualFraming",
    "DissentPoint",
    "IC1Deliberation",
    "IC1SubRole",
    "MaterialityGateBlock",
    "RenderedArtifact",
    "RenderingDecision",
    "S1Synthesis",
    "SubRoleContribution",
    "_LlmIC1SubRoleOutput",
    "_LlmS1Output",
    "_LlmStitcherOutput",
]
