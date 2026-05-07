#!/usr/bin/env python3
"""Cluster 6 Stage 3: extract case_arch_*_pipeline.md narratives into
case_seed_data.json keyed by case_id.

Reads the per-case curated pipeline markdown from the cluster-6
deliverables and produces structured per-case synthesis payloads + (for
decided proposed_action / scenario cases) decision-artifact rationales.

Schema (consumed by ``cases.dispatch.get_seed_payload_for``):

    {
      "case_arch01_a": {
        "synthesis.case_mode": {
          "output_mode": "case_mode",
          "synthesis_narrative": "...",
          "recommendation": "...",
          ...
        },
        "decision_artifact": {
          "decision": "approved",
          "rationale": "..."
        }
      },
      ...
    }

The synthesis narrative is the highest-visibility artifact in the
case detail UI; decision rationale closes the loop on decided cases.
Other stage outputs (per-agent evidence, governance per-gate, etc.)
are deferred to follow-up work — the parser surface is here ready
for the extension.

Run:
  python3 scripts/build_cluster6_case_seed_data.py \\
    > data/fixtures/case_seed_data.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

CLUSTER6_DIR = Path(
    "/Users/shubhamsahamate/Desktop/IMT-G/"
    "25 - WealthWisers Technologies - Summer Internship/"
    "10 - Product Feature Change Requests/02 to 07 - Consolidated/"
    "03 - Change Implementation - Clusters:Chunks/"
    "Cluster 6 - Specialist Agents Enrichment"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "data" / "fixtures" / "_cluster6_cases.json"


# Maps the markdown synthesis-section heading to the dispatcher key +
# output_mode value.
SYNTHESIS_VARIANTS: dict[str, tuple[str, str]] = {
    "synthesis (s1, case mode)": ("synthesis.case_mode", "case_mode"),
    "synthesis (s1, scenario mode)": ("synthesis.case_mode", "case_mode"),
    "synthesis (s1, diagnostic mode)": ("synthesis.diagnostic", "diagnostic"),
    "synthesis (s1, briefing mode)": ("synthesis.briefing", "briefing"),
    "synthesis": ("synthesis.case_mode", "case_mode"),  # fallback
}


def _read_section(text: str, heading_re: str) -> str:
    """Return the body between a ``## <heading_re>`` line and the next
    ``## `` (or EOF). Empty string if not found.
    """
    pattern = re.compile(
        rf"^## {heading_re}\s*\n(.*?)(?=^## |\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _extract_synthesis(text: str) -> tuple[str, dict[str, Any]] | None:
    """Find the synthesis section + return (dispatch_key, payload)."""
    for heading_lower, (dispatch_key, output_mode) in SYNTHESIS_VARIANTS.items():
        # Match the heading allowing trailing punctuation / parens.
        body = _read_section(
            text, re.escape(heading_lower).replace(r"\ ", r"\s+"),
        )
        if body:
            narrative = _extract_narrative_text(body)
            recommendation = _extract_recommendation(body)
            return dispatch_key, {
                "output_mode": output_mode,
                "synthesis_narrative": narrative,
                "recommendation": recommendation,
                "consensus": {"summary": _extract_consensus(body) or narrative[:160]},
                "agreement_areas": {"areas": []},
                "conflict_areas": {"areas": []},
                "uncertainty_flag": False,
                "amplification": _extract_amplification(body),
                "mode_dominance": _extract_mode_dominance(body),
                "escalation_recommended": False,
                "counterfactual_framing": _extract_counterfactual(body),
                "flags": {},
                "reasoning_summary": (
                    "Cluster 6 enriched synthesis (per case_arch pipeline). "
                    "Source: case_arch markdown."
                ),
            }
    return None


def _extract_narrative_text(body: str) -> str:
    """Pull the most narrative-looking paragraph from the synthesis body.

    Heuristic: the longest paragraph in the section that doesn't start
    with a bold "**Field:**" prefix. Falls back to the first
    "Reasoning summary:" block if present.
    """
    # Prefer an explicit "Reasoning summary" block when authored.
    reasoning_match = re.search(
        r"(?:\*\*)?Reasoning summary(?:\*\*)?[: ]\s*(?:\")?(.*?)(?:\")?(?=\n\n|\Z)",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    if reasoning_match:
        text = reasoning_match.group(1).strip().strip('"').strip()
        if text and len(text) > 60:
            return _normalise_whitespace(text)

    # Otherwise take the longest plain paragraph.
    paragraphs = re.split(r"\n\s*\n", body)
    cleaned = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        # Skip table-shaped paragraphs and bullet-only blocks.
        if p.startswith("|") or all(
            line.strip().startswith(("-", "*", "|", "**"))
            for line in p.splitlines()
        ):
            continue
        cleaned.append(p)
    if not cleaned:
        return ""
    longest = max(cleaned, key=len)
    return _normalise_whitespace(longest)


def _normalise_whitespace(text: str) -> str:
    out = re.sub(r"\s+", " ", text).strip()
    # Strip leading/trailing markdown emphasis markers + stray quotes.
    out = re.sub(r'^[\*\s"]+|[\*\s"]+$', "", out)
    return out


def _extract_consensus(body: str) -> str | None:
    m = re.search(r"\*\*Consensus[:\*]+\s*(.*?)(?:\.|\n)", body, re.IGNORECASE)
    if m:
        return _normalise_whitespace(m.group(1)).rstrip(".")
    return None


def _extract_recommendation(body: str) -> str:
    """Best-effort recommendation enum mapping from synthesis body."""
    text = body.lower()
    if "support_with_conditions" in text or "support with conditions" in text:
        return "support_with_conditions"
    if "no_action_required" in text or "no action required" in text:
        return "no_action_required"
    if "discuss_with_client" in text or "discuss with client" in text:
        return "discuss_with_client"
    if re.search(r"\bproceed\b", text):
        return "proceed"
    return "proceed"


def _extract_mode_dominance(body: str) -> str:
    m = re.search(r"\*\*Mode dominance[:\*]+\s*([^.\n]+)", body, re.IGNORECASE)
    if m:
        text = _normalise_whitespace(m.group(1)).lower()
        if "portfolio_shift" in text:
            return "portfolio_shift"
        if "proposal_evaluation" in text:
            return "proposal_evaluation"
    return "balanced"


def _extract_amplification(body: str) -> dict[str, Any] | None:
    """Detect amplification flag if mentioned in synthesis body."""
    if re.search(
        r"amplification.{0,30}(true|flag|yes|fired)",
        body,
        re.IGNORECASE | re.DOTALL,
    ):
        return {"flag": True}
    return None


def _extract_counterfactual(body: str) -> dict[str, Any] | None:
    m = re.search(
        r"\*\*Counterfactual framing[:\*]+\s*(?:\")?(.*?)(?:\")?(?:\n\*\*|\n\n|\Z)",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        text = _normalise_whitespace(m.group(1)).strip('"').strip()
        if text:
            return {"description": text}
    return None


def _extract_decision_rationale(text: str) -> dict[str, Any] | None:
    """Find the Decision Artifact section + return a structured payload."""
    body = _read_section(text, r"Decision Artifact")
    if not body:
        return None

    decision = "approved"
    decision_match = re.search(
        r"\*\*Decision[:\*]+\s*([a-z_]+)", body, re.IGNORECASE,
    )
    if decision_match:
        decision = decision_match.group(1).lower()

    rationale = ""
    rationale_match = re.search(
        r"\*\*Rationale[^:]*:\*\*\s*(?:\")?(.*?)(?:\")?(?:\n\*\*|\n\n|\Z)",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    if rationale_match:
        rationale = _normalise_whitespace(
            rationale_match.group(1).strip().strip('"'),
        )

    if not rationale:
        return None
    return {"decision": decision, "rationale": rationale}


def _extract_health_report(text: str) -> dict[str, Any] | None:
    body = _read_section(text, r"Health Report.*")
    if not body:
        return None
    overall = "healthy"
    if re.search(r"urgent", body, re.IGNORECASE):
        overall = "urgent"
    elif re.search(r"attention.needed|attention_needed", body, re.IGNORECASE):
        overall = "attention_needed"
    return {
        "overall_health": overall,
        "asset_allocation_status": {
            "summary": _normalise_whitespace(_extract_narrative_text(body)),
        },
        "performance_summary": {},
        "drift_indicators": {},
        "recommendations": {
            "items": _extract_bullet_list(body, max_items=4),
        },
    }


def _extract_briefing_note(text: str) -> dict[str, Any] | None:
    body = _read_section(text, r"Briefing Note.*")
    if not body:
        return None
    return {
        "meeting_context": _extract_narrative_text(body)[:400],
        "recent_activity_summary": "",
        "current_state_summary": "",
        "market_context": "",
        "prep_questions": {
            "questions": _extract_bullet_list(body, max_items=5),
        },
    }


def _extract_bullet_list(body: str, *, max_items: int = 5) -> list[str]:
    items: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")):
            items.append(_normalise_whitespace(line[2:]))
        if len(items) >= max_items:
            break
    return items


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build() -> dict[str, dict[str, Any]]:
    cases_payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    case_rows = {c["case_id"]: c for c in cases_payload["rows"]}

    output: dict[str, dict[str, Any]] = {}
    md_files = sorted(CLUSTER6_DIR.glob("case_arch*_pipeline.md"))
    for md_file in md_files:
        # Extract case_id from filename: ``case_arch01_a_pipeline.md`` →
        # ``case_arch01_a``.
        case_id = md_file.stem.replace("_pipeline", "")
        if case_id not in case_rows:
            print(
                f"WARN: case_arch markdown without a matching cases.json "
                f"row: {case_id}",
                file=sys.stderr,
            )
            continue

        text = md_file.read_text(encoding="utf-8")
        per_case: dict[str, Any] = {}

        # Synthesis (mode-specific).
        synth = _extract_synthesis(text)
        if synth:
            dispatch_key, payload = synth
            per_case[dispatch_key] = payload

        # Decision artifact (decided proposed_action / scenario only).
        decision = _extract_decision_rationale(text)
        case_row = case_rows[case_id]
        if decision is None and case_row.get("_decision_artifact_preview"):
            # Fall back to the cases.json preview when the markdown
            # didn't surface a parseable decision section.
            preview = case_row["_decision_artifact_preview"]
            decision = {
                "decision": preview.get("decision", "approved"),
                "rationale": preview.get("rationale", ""),
            }
        if decision:
            per_case["decision_artifact"] = decision

        # Health report (diagnostic mode).
        if case_row["case_mode"] == "diagnostic":
            health = _extract_health_report(text)
            if health:
                per_case["health_report"] = health

        # Briefing note (briefing mode).
        if case_row["case_mode"] == "briefing":
            briefing = _extract_briefing_note(text)
            if briefing:
                per_case["briefing_note"] = briefing

        if per_case:
            output[case_id] = per_case

    return output


if __name__ == "__main__":
    result = build()
    print(json.dumps(result, indent=2))
    print(
        f"# Extracted {len(result)} case payloads. "
        f"keys: {sorted(result.keys())}",
        file=sys.stderr,
    )
