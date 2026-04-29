"""Section 9.2 — agent activation envelope.

Per Thesis 4.2 every shared agent reads `run_mode` (case vs construction).
Per Section 9.2 every agent activation comprises three inputs (structured
context, static prompt reference, optional briefing) plus one optional dialog
channel (clarification request / response).

This envelope ships in Pass 6 and is *consumed* in Phase C when E1–E6, S1, IC1,
and A1 are wired. Putting it in canonical/ early lets the Router and downstream
glue reference one stable shape rather than redefining per-agent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.case import CaseObject
from artha.canonical.investor import InvestorContextProfile
from artha.canonical.mandate import MandateObject
from artha.canonical.model_portfolio import ModelPortfolioObject
from artha.common.standards import ClarificationRequest
from artha.common.types import RunMode, VersionPins


class M0Briefing(BaseModel):
    """Section 9.3 — a single natural-language briefing attached to an activation.

    Captured verbatim; no transformation between Briefer output and T1. The
    accompanying `briefer_version` and `trigger_flag` make the briefing
    auditable post-hoc by A1's accountability surface (Section 9.6).
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    token_count: int
    trigger_flag: str  # e.g. "multi_product", "structural_anomaly", "advisor_emphasis"
    briefer_version: str = "0.1.0"


class ClarificationDialog(BaseModel):
    """Section 9.4 — the structured request + response pair, capped at one round trip."""

    model_config = ConfigDict(extra="forbid")

    request: ClarificationRequest
    response_text: str | None = None  # natural-language response from M0; None until answered
    response_token_count: int | None = None
    responding_actor: str | None = None  # m0 | m0_briefer | m0_indian_context | etc.


class AgentActivationEnvelope(BaseModel):
    """Section 9.2 — what every downstream agent reads on activation.

    Three inputs (structured context, prompt reference, optional briefing) plus
    the optional clarification dialog. The structured context references the
    canonical objects already in the case bundle; the agent reads the relevant
    slice for its lane.

    `run_mode` plumbs Thesis 4.2's pipeline mode through to the agent.
    `version_pins` captures every load-bearing version for replay (Section 3.7,
    3.8, 15.11.1).
    """

    model_config = ConfigDict(extra="forbid")

    # Input 1: structured context packet (Section 9.2)
    case: CaseObject
    investor_profile: InvestorContextProfile | None = None
    mandate: MandateObject | None = None
    model_portfolio: ModelPortfolioObject | None = None
    prior_agent_outputs: dict[str, Any] = Field(default_factory=dict)

    # Input 2: static prompt is referenced by version, not embedded
    target_agent: str  # e.g. "e1_financial_risk", "s1_synthesis"
    prompt_version: str = "0.1.0"

    # Input 3: optional M0.Briefer output (Section 9.3)
    briefing: M0Briefing | None = None

    # Dialog channel (Section 9.4)
    clarification: ClarificationDialog | None = None

    # Pipeline mode (Thesis 4.2) — read by every shared agent
    run_mode: RunMode = RunMode.CASE

    # Version pins for T1 replay (Section 3.11 / 15.11.1)
    version_pins: VersionPins = Field(default_factory=VersionPins)
