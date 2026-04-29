"""Section 15.6.1 + 15.6.2 — M0.Router canonical schemas.

Section 8.3 — the Router is the canonical owner of the 8-type intent taxonomy.
Every channel (C0, form, API, N0 response, system trigger) routes through it.
The Router either confirms a high-confidence pre-tag from the channel or
classifies via LLM when the pre-tag is missing or low-confidence.

The output carries `run_mode` per Thesis 4.2 — every agent activated downstream
reads the pipeline mode (`case` for the case pipeline, `construction` for the
model portfolio construction pipeline) so the same agents serve both pipelines.
Inbound case-pipeline events default to `RunMode.CASE`; the construction
pipeline workflow sets `RunMode.CONSTRUCTION` directly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artha.canonical.case import CaseChannel
from artha.common.types import CaseIntent, ConfidenceField, RunMode


class M0RouterInput(BaseModel):
    """Section 15.6.1 — inbound event passed to M0.Router for classification.

    `pre_tag` and `pre_tag_confidence` are the channel's own classification.
    C0 emits a confidence on the rubric in Section 3.2; forms and APIs emit
    explicit intent tags with high confidence by construction.
    """

    model_config = ConfigDict(extra="forbid")

    channel: CaseChannel
    pre_tag: CaseIntent | None = None
    pre_tag_confidence: ConfidenceField | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class M0RouterOutput(BaseModel):
    """Section 15.6.2 — Router's classification result.

    `intent_type` and `intent_confidence` are the canonical owner's verdict.
    `routing_metadata` carries per-intent-type fields needed by downstream
    consumers (e.g. `client_id` for a case, `alert_id` for a monitoring_response);
    its shape is intentionally permissive in MVP (Pass 6).

    `run_mode` is the pipeline mode flag per Thesis 4.2 — every downstream agent
    reads it from the agent activation envelope. The Router defaults to
    `RunMode.CASE` for inbound case-pipeline events; the construction pipeline
    sets `RunMode.CONSTRUCTION` outside the Router.

    `clarification_required` is True when the Router cannot determine intent
    with sufficient confidence; the channel surfaces a clarification prompt
    to the source (advisor or system) and re-submits.
    """

    model_config = ConfigDict(extra="forbid")

    intent_type: CaseIntent
    intent_confidence: ConfidenceField
    routing_metadata: dict[str, Any] = Field(default_factory=dict)
    run_mode: RunMode = RunMode.CASE
    clarification_required: bool = False
    clarification_payload: dict[str, Any] | None = None


class M0RouterClassification(BaseModel):
    """Internal LLM-output schema used by the Router service.

    Kept small and string-typed (rather than enum-typed) so that LLM providers
    that don't natively understand enum constraints still produce parseable
    JSON. The Router service validates the string against the canonical
    `CaseIntent` enum before producing `M0RouterOutput`.
    """

    model_config = ConfigDict(extra="forbid")

    intent_type_value: str  # validated against CaseIntent in M0Router
    confidence: ConfidenceField
    reasoning: str = ""
