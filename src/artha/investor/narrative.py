"""AI narrative generation for investor risk profiles.

The deterministic score is computed first. Then, the LLM generates:
1. A personalized narrative explanation of what the scores mean
2. Flags for inconsistencies or noteworthy patterns in the responses
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest


class ProfileNarrative(BaseModel):
    """AI-generated narrative and flags. Advisory only — never modifies the score."""

    summary: str = ""
    key_drivers: list[str] = Field(default_factory=list)
    inconsistency_flags: list[str] = Field(default_factory=list)
    advisor_notes: list[str] = Field(default_factory=list)
    suitability_observations: str = ""


NARRATIVE_SYSTEM_PROMPT = """You are a risk profiling analyst for a wealth management firm.
Given an investor's deterministic risk profile scores and questionnaire responses,
generate a concise, professional narrative explaining:

1. SUMMARY: A 2-3 sentence overview of the investor's risk profile in plain English.
2. KEY_DRIVERS: 3-5 bullet points on what primarily drives this investor's risk classification.
3. INCONSISTENCY_FLAGS: Any contradictions in the responses (e.g., claims aggressive tolerance
   but has no emergency fund). These are advisory flags for the wealth manager, not score adjustments.
4. ADVISOR_NOTES: 2-3 practical notes for the relationship manager handling this client.
5. SUITABILITY_OBSERVATIONS: 1-2 sentences on what types of products/strategies are suitable.

CRITICAL: You NEVER modify the deterministic score. Your role is explanation, not judgment.
The score is final. You explain what it means and flag what the advisor should know."""


async def generate_narrative(
    llm: LLMProvider,
    investor_name: str,
    investor_type: str,
    overall_score: float,
    risk_category: str,
    category_scores: dict[str, float],
    constraints: dict[str, Any],
    family_complexity: int | None = None,
    responses_summary: list[dict[str, Any]] | None = None,
) -> ProfileNarrative:
    """Generate AI narrative for a risk profile. Advisory only."""
    import json

    context = {
        "investor_name": investor_name,
        "investor_type": investor_type,
        "overall_score": overall_score,
        "risk_category": risk_category,
        "category_scores": category_scores,
        "constraints": constraints,
    }
    if family_complexity:
        context["family_complexity_score"] = family_complexity
    if responses_summary:
        context["responses_summary"] = responses_summary[:20]  # Limit context size

    user_msg = (
        f"Generate a risk profile narrative for this investor.\n\n"
        f"```json\n{json.dumps(context, indent=2, default=str)}\n```"
    )

    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content=NARRATIVE_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_msg),
        ],
        temperature=0.2,  # Slightly creative but consistent
        max_tokens=1024,
    )

    try:
        result = await llm.complete_structured(request, ProfileNarrative)
        return result
    except Exception:
        # Fallback: generate a basic narrative without AI
        return ProfileNarrative(
            summary=f"{investor_name} has been assessed as {risk_category.replace('_', ' ')} "
                    f"with an overall score of {overall_score:.1f}/40.",
            key_drivers=[f"Overall score: {overall_score:.1f}"],
            inconsistency_flags=[],
            advisor_notes=[f"Risk category: {risk_category.replace('_', ' ').title()}"],
            suitability_observations=f"Suitable for {risk_category.replace('_', ' ')} investment strategies.",
        )
