"""Prompt template loader (cluster 7 chunk 7.1 §4).

Wraps :func:`artha.api_v2.m0.skill_md.load_skill` with the cluster-7
prompt-rendering surface: extracts the skill.md body as the system
prompt, supports placeholder substitution for the small set of
per-call inputs E1 + M0.PortfolioRiskAnalytics declare, and exposes a
``prompt_version`` string the cache layer (chunk 7.2) keys off.

Placeholder set (chunk 7.1 §4.3):

| Placeholder         | Source                                       |
|---------------------|----------------------------------------------|
| {ticker}            | agent_inputs.payload["ticker"]               |
| {snapshot_excerpt}  | shim-built compact snapshot view             |
| {mandate_excerpt}   | shim-built compact mandate view              |
| {macro_context}     | dispatched E3 verdict (when available)       |

Placeholders not found in inputs raise :class:`MissingPlaceholderError`
*before* the LLM call so missing-input issues surface at the shim
boundary rather than as bad LLM output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from artha.api_v2.m0.skill_md import SkillMd, load_skill


class MissingPlaceholderError(RuntimeError):
    """Raised when the rendered prompt would still contain a
    ``{placeholder}`` because the caller didn't supply a substitution."""


@dataclass(frozen=True)
class PromptTemplate:
    """Parsed skill.md ready for per-call rendering."""

    agent_id: str
    skill_md_version: str
    system_body: str
    llm_model: str
    max_tokens: int
    temperature: float
    output_schema_ref: str

    @property
    def prompt_version(self) -> str:
        """Stable identifier for cache invalidation (chunk 7.1 §4.4)."""
        return f"{self.agent_id}@{self.skill_md_version}"


@dataclass(frozen=True)
class PromptPayload:
    """One LLM call's prompt: system body + the user message."""

    system: str
    user: str
    llm_model: str
    max_tokens: int
    temperature: float


_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


def load_prompt_template(agent_id: str) -> PromptTemplate:
    """Load + cache the cluster-6 enriched skill.md as a
    :class:`PromptTemplate`.

    Memoised via the underlying :func:`load_skill` cache.
    """
    skill: SkillMd = load_skill(agent_id)
    return PromptTemplate(
        agent_id=skill.agent_id,
        skill_md_version=skill.skill_md_version,
        system_body=skill.body,
        llm_model=skill.llm_model,
        max_tokens=skill.max_tokens,
        temperature=skill.temperature,
        output_schema_ref=skill.output_schema_ref,
    )


def render_user_prompt(
    template: str,
    *,
    placeholders: dict[str, Any],
) -> str:
    """Substitute ``{placeholder}`` tokens in ``template`` from
    ``placeholders``. Raises :class:`MissingPlaceholderError` when any
    declared placeholder isn't supplied.
    """
    rendered = template
    declared = set(_PLACEHOLDER_RE.findall(template))
    missing = sorted(declared - set(placeholders.keys()))
    if missing:
        raise MissingPlaceholderError(
            f"Prompt template missing placeholders: {missing}",
        )
    for key, value in placeholders.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


__all__ = [
    "MissingPlaceholderError",
    "PromptPayload",
    "PromptTemplate",
    "load_prompt_template",
    "render_user_prompt",
]
