"""Section 15.6.7 — M0.Briefer canonical input/output schemas.

The Briefer is invoked by M0 with a target_agent + case bundle + a trigger flag
indicating which condition prompted the briefing. The output is either a 100-300
token natural-language briefing or a null with a skip_reason.

Per Section 8.8.2 the discipline is strict — no conclusions, no risk-level
assertions, no verdict-anticipation. M0.Briefer's prompt enforces these; the
service runs lint over the LLM output before returning.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BriefingTrigger(str, Enum):
    """Section 8.8.2 — the trigger conditions that prompt a briefing.

    Most cases run with no briefing (no trigger fires). When at least one trigger
    fires, M0 invokes the Briefer; the Briefer may still return null if it
    cannot articulate non-redundant context.
    """

    MULTI_PRODUCT = "multi_product"
    AMBIGUOUS_INPUT = "ambiguous_input"
    CROSS_WORKFLOW = "cross_workflow"
    STRUCTURAL_ANOMALY = "structural_anomaly"
    MANDATE_MODEL_CONFLICT = "mandate_model_conflict"
    OUT_OF_BUCKET = "out_of_bucket"
    ADVISOR_EMPHASIS = "advisor_emphasis"
    M0_JUDGEMENT = "m0_judgement"


class M0BrieferInput(BaseModel):
    """Section 15.6.7 input.

    `case_bundle` is a permissive dict of the canonical case context (case_object,
    investor_profile, mandate, model_portfolio, prior outputs). The Briefer
    reads what it needs to surface non-redundant context.
    """

    model_config = ConfigDict(extra="forbid")

    target_agent: str  # e.g. "e1_financial_risk", "e6_aif_cat_2"
    case_bundle: dict = Field(default_factory=dict)
    trigger_flag: BriefingTrigger
    additional_emphasis: str = ""  # advisor-emphasis text if relevant


class M0BrieferMetadata(BaseModel):
    """Per-briefing metadata captured in T1 alongside `briefing_text` (Section 8.8.6)."""

    model_config = ConfigDict(extra="forbid")

    token_count: int
    generation_timestamp: datetime
    briefer_version: str = "0.1.0"
    trigger_flag: BriefingTrigger
    target_agent: str
    lint_violations: list[str] = Field(default_factory=list)


class M0BrieferOutput(BaseModel):
    """Section 15.6.7 output.

    `briefing_text=None` ⇒ no briefing was emitted; consumers attach nothing
    to the agent activation envelope.
    """

    model_config = ConfigDict(extra="forbid")

    briefing_text: str | None = None
    briefing_metadata: M0BrieferMetadata | None = None
    skip_reason: str | None = None  # populated when briefing_text is None
