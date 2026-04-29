"""§15.9 — governance + accountability schemas.

  * G1 (§13.2 / §15.9.1) — mandate compliance gate.
  * G2 (§13.3 / §15.9.2) — regulatory boundary engine.
  * G3 (§13.4 / §15.9.3) — action permission filter (G1+G2 aggregator).
  * A1 (§13.5 / §15.9.4) — accountability / challenge surface (LLM-backed,
    never gates).

Per §13.2.4 / §13.3.4 / §13.4.4 the gate stack vocabulary is:

  * G1 emits per-constraint statuses then `aggregated_status` ∈ Permission.
  * G2 emits per-rule statuses (PASS / BLOCK / ESCALATE_REQUIREMENT_UNMET)
    then `aggregated_permission` ∈ Permission.
  * G3 aggregates G1+G2 (and S1 escalation_recommended) into a single
    `permission` ∈ Permission and surfaces override paths.

A1's outputs are always advisory; the schema does NOT carry a Permission
field — A1 surfaces challenges to the human alongside the governance chain.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from artha.common.types import (
    ConfidenceField,
    InputsUsedManifest,
    Permission,
    RunMode,
    SourceCitation,
)

# ===========================================================================
# G1 — Mandate Compliance (§15.9.1)
# ===========================================================================


class ConstraintEvaluationStatus(str, Enum):
    """§7.10 — per-constraint outcome inside G1's evaluation."""

    PASS = "pass"
    BREACH = "breach"
    WARN = "warn"  # near-limit; drives ESCALATION_REQUIRED at G1 aggregation


class ConstraintType(str, Enum):
    """§7.3 — the constraint families G1 enforces."""

    ASSET_CLASS_LIMIT = "asset_class_limit"
    VEHICLE_LIMIT = "vehicle_limit"
    SUB_ASSET_CLASS_LIMIT = "sub_asset_class_limit"
    CONCENTRATION_LIMIT = "concentration_limit"
    SECTOR_HARD_BLOCK = "sector_hard_block"
    SECTOR_EXCLUSION = "sector_exclusion"
    LIQUIDITY_FLOOR = "liquidity_floor"
    LIQUIDITY_WINDOW = "liquidity_window"
    FAMILY_OVERRIDE_OUT_OF_BAND = "family_override_out_of_band"


class ConstraintEvaluation(BaseModel):
    """§15.9.1 — one row of G1's per-constraint evaluation list."""

    model_config = ConfigDict(extra="forbid")

    constraint_id: str  # e.g. "asset_class_limit:equity"
    constraint_type: ConstraintType
    status: ConstraintEvaluationStatus
    evaluation_detail: str = ""
    current_value: float | None = None
    proposed_value: float | None = None
    limit_value: float | None = None
    family_member_id: str | None = None  # populated when family override applies
    citation: str | None = None  # mandate version pin


class G1Evaluation(BaseModel):
    """§15.9.1 — mandate compliance gate output."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["mandate_compliance"] = "mandate_compliance"
    case_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE

    aggregated_status: Permission
    per_constraint_evaluations: list[ConstraintEvaluation] = Field(default_factory=list)
    breach_reasons: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)

    mandate_version: int  # the mandate version pinned at decision time
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


# ===========================================================================
# G2 — Regulatory Boundary (§15.9.2)
# ===========================================================================


class RegulatoryRuleStatus(str, Enum):
    """§13.3.4 — per-rule G2 outcome."""

    PASS = "pass"
    BLOCK = "block"
    ESCALATE_REQUIREMENT_UNMET = "escalate_requirement_unmet"


class RegulatoryRuleSeverity(str, Enum):
    """§13.3 — severity for a rule violation."""

    HARD = "hard"
    SOFT = "soft"
    INFO = "info"


class RegulatoryRuleEvaluation(BaseModel):
    """§15.9.2 — one rule's evaluation in G2's output."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str  # e.g. "SEBI_AIF_2012_REGULATION_2"
    rule_version: str
    status: RegulatoryRuleStatus
    severity: RegulatoryRuleSeverity = RegulatoryRuleSeverity.HARD
    citation: SourceCitation | None = None
    evaluation_detail: str = ""
    requirement_unmet: str | None = None  # populated on ESCALATE_REQUIREMENT_UNMET


class G2Evaluation(BaseModel):
    """§15.9.2 — regulatory engine output."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["regulatory_engine"] = "regulatory_engine"
    case_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE

    aggregated_permission: Permission
    per_rule_evaluations: list[RegulatoryRuleEvaluation] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)

    rule_corpus_version: str
    decision_date: datetime  # the date used for time-aware rule evaluation
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


# ===========================================================================
# G3 — Action Permission Filter (§15.9.3)
# ===========================================================================


class OverrideRequirements(BaseModel):
    """§15.9.3 — what the advisor must do to override a BLOCKED outcome."""

    model_config = ConfigDict(extra="forbid")

    override_permitted: bool = False
    requires: list[str] = Field(default_factory=list)
    rationale: str = ""


class G3Evaluation(BaseModel):
    """§15.9.3 — final permission filter output (G1+G2 aggregator).

    `permission` is what consumers (M0.Stitcher, advisor UI) read. `override_requirements`
    is non-null only when `permission` is BLOCKED but firm policy allows an override.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["permission_filter"] = "permission_filter"
    case_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE

    permission: Permission
    blocking_reasons: list[str] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)
    override_requirements: OverrideRequirements | None = None
    conditions_to_attach: list[str] = Field(default_factory=list)

    # Pinning the upstream gate hashes for replay
    g1_input_hash: str
    g2_input_hash: str
    s1_escalation_recommended: bool = False
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    agent_version: str = "0.1.0"


# ===========================================================================
# A1 — Accountability Surface (§15.9.4)
# ===========================================================================


class ChallengeType(str, Enum):
    """§13.5.2 — taxonomy of challenge points A1 surfaces."""

    COUNTER_ARGUMENT = "counter_argument"
    STRESS_TEST = "stress_test"
    EDGE_CASE = "edge_case"


class ChallengeSeverity(str, Enum):
    """§13.5 — severity of a challenge / accountability flag."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ChallengePoint(BaseModel):
    """§15.9.4 — one structured challenge against the synthesis."""

    model_config = ConfigDict(extra="forbid")

    challenge_type: ChallengeType
    content: str
    severity: ChallengeSeverity = ChallengeSeverity.MEDIUM
    cited_agent_ids: list[str] = Field(default_factory=list)


class AlternativeProposal(BaseModel):
    """§15.9.4 — an alternative course of action A1 surfaces."""

    model_config = ConfigDict(extra="forbid")

    proposal_summary: str
    structure_changes: list[str] = Field(default_factory=list)
    rationale: str = ""
    feasibility_check: Literal["feasible", "infeasible", "unverified"] = "feasible"
    cited_l4_instruments: list[str] = Field(default_factory=list)


class StressTestScenario(BaseModel):
    """§15.9.4 — a specific stress test the proposal would face."""

    model_config = ConfigDict(extra="forbid")

    scenario_name: str
    conditions: list[str] = Field(default_factory=list)
    named_impacts: list[str] = Field(default_factory=list)
    severity: ChallengeSeverity = ChallengeSeverity.MEDIUM


class AccountabilityFlagType(str, Enum):
    """§9.6 / §13.5.2 — accountability surface taxonomy."""

    BRIEFING_CLOSE_PARAPHRASE = "briefing_close_paraphrase"
    CLARIFICATION_VERDICT_ANTICIPATION = "clarification_verdict_anticipation"
    OTHER = "other"


class AccountabilityFlag(BaseModel):
    """§15.9.4 — flag raised against a specific T1 event."""

    model_config = ConfigDict(extra="forbid")

    flag_type: AccountabilityFlagType
    flagged_event_id: str | None = None
    severity: ChallengeSeverity = ChallengeSeverity.MEDIUM
    rationale: str


class A1Challenge(BaseModel):
    """§15.9.4 — accountability layer output. Advisory only; never gates."""

    model_config = ConfigDict(extra="forbid")

    agent_id: Literal["advisory_challenge"] = "advisory_challenge"
    case_id: str
    timestamp: datetime
    run_mode: RunMode = RunMode.CASE

    challenge_points: list[ChallengePoint] = Field(default_factory=list)
    alternative_proposals: list[AlternativeProposal] = Field(default_factory=list)
    stress_test_scenarios: list[StressTestScenario] = Field(default_factory=list)
    accountability_flags: list[AccountabilityFlag] = Field(default_factory=list)

    confidence: ConfidenceField = 0.0
    reasoning_trace: str = ""
    inputs_used_manifest: InputsUsedManifest = Field(default_factory=InputsUsedManifest)
    input_hash: str
    prompt_version: str = "0.1.0"
    agent_version: str = "0.1.0"


# ===========================================================================
# Internal LLM-output schema for A1
# ===========================================================================


class _LlmA1Output(BaseModel):
    """Internal A1 LLM output — string-typed for mock provider compatibility."""

    model_config = ConfigDict(extra="forbid")

    challenge_points: list[ChallengePoint] = Field(default_factory=list)
    alternative_proposals: list[AlternativeProposal] = Field(default_factory=list)
    stress_test_scenarios: list[StressTestScenario] = Field(default_factory=list)
    accountability_flags: list[AccountabilityFlag] = Field(default_factory=list)
    confidence: ConfidenceField = 0.5
    reasoning_trace: str = ""


__all__ = [
    "A1Challenge",
    "AccountabilityFlag",
    "AccountabilityFlagType",
    "AlternativeProposal",
    "ChallengePoint",
    "ChallengeSeverity",
    "ChallengeType",
    "ConstraintEvaluation",
    "ConstraintEvaluationStatus",
    "ConstraintType",
    "G1Evaluation",
    "G2Evaluation",
    "G3Evaluation",
    "OverrideRequirements",
    "RegulatoryRuleEvaluation",
    "RegulatoryRuleSeverity",
    "RegulatoryRuleStatus",
    "StressTestScenario",
    "_LlmA1Output",
]
