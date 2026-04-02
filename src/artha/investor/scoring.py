"""Scoring engine — transforms questionnaire responses into a risk profile."""

from __future__ import annotations

from artha.investor.schemas import (
    FamilyConstraints,
    QuestionResponse,
    RiskCategory,
    RiskConstraints,
    get_questionnaire_template,
)

# ── Category weights for overall score ──
CATEGORY_WEIGHTS: dict[str, float] = {
    "personal_financial": 0.10,
    "financial_health": 0.12,
    "experience_risk_tolerance": 0.25,
    "goals_horizon": 0.15,
    "tax_regulatory": 0.03,
    "insurance_protection": 0.05,
    "market_outlook": 0.05,
    "psychometric": 0.25,
}

# ── Risk category thresholds and constraints ──
RISK_BANDS: list[tuple[float, RiskCategory, dict]] = [
    (17, RiskCategory.CONSERVATIVE, {
        "max_volatility": 0.10, "max_drawdown": 0.10,
        "equity_min": 0.0, "equity_max": 0.30, "horizon": "short",
    }),
    (24, RiskCategory.MODERATELY_CONSERVATIVE, {
        "max_volatility": 0.15, "max_drawdown": 0.15,
        "equity_min": 0.20, "equity_max": 0.50, "horizon": "medium",
    }),
    (30, RiskCategory.MODERATE, {
        "max_volatility": 0.20, "max_drawdown": 0.25,
        "equity_min": 0.40, "equity_max": 0.70, "horizon": "medium",
    }),
    (36, RiskCategory.MODERATELY_AGGRESSIVE, {
        "max_volatility": 0.30, "max_drawdown": 0.35,
        "equity_min": 0.60, "equity_max": 0.85, "horizon": "long",
    }),
    (40, RiskCategory.AGGRESSIVE, {
        "max_volatility": 0.40, "max_drawdown": 0.45,
        "equity_min": 0.75, "equity_max": 1.0, "horizon": "long",
    }),
]


def score_option(option: str) -> int:
    """Convert option letter to score."""
    return {"a": 10, "b": 20, "c": 30, "d": 40}.get(option.lower(), 0)


def compute_category_scores(
    responses: list[QuestionResponse],
) -> dict[str, float]:
    """Compute average score per category."""
    template = get_questionnaire_template()
    cat_id_by_qnum: dict[str, list[int]] = {}

    # Map category_id → list of question numbers
    for cat in template.categories:
        if cat.id == "family_office":
            continue  # Scored separately
        cat_id_by_qnum[cat.id] = [q.number for q in cat.questions]

    # Group responses by category
    # Responses are sequential: categories 1-8, questions numbered within each
    category_scores: dict[str, list[int]] = {cid: [] for cid in cat_id_by_qnum}

    # Build a flat list of (category_id, question_number) from the template
    flat_questions: list[tuple[str, int]] = []
    for cat in template.categories:
        if cat.id == "family_office":
            continue
        for q in cat.questions:
            flat_questions.append((cat.id, q.number))

    for i, resp in enumerate(responses):
        if i < len(flat_questions):
            cat_id, _ = flat_questions[i]
            score = score_option(resp.selected_option)
            if score > 0:
                category_scores[cat_id].append(score)

    # Average per category
    result: dict[str, float] = {}
    for cat_id, scores in category_scores.items():
        if scores:
            result[cat_id] = round(sum(scores) / len(scores), 2)
        else:
            result[cat_id] = 0.0
    return result


def compute_overall_score(category_scores: dict[str, float]) -> float:
    """Weighted average across categories."""
    total_weight = 0.0
    weighted_sum = 0.0
    for cat_id, weight in CATEGORY_WEIGHTS.items():
        score = category_scores.get(cat_id, 0.0)
        if score > 0:
            weighted_sum += score * weight
            total_weight += weight
    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 2)


def classify_risk(overall_score: float) -> tuple[RiskCategory, dict]:
    """Map overall score to risk category and constraints."""
    for threshold, category, constraints in RISK_BANDS:
        if overall_score <= threshold:
            return category, constraints
    return RiskCategory.AGGRESSIVE, RISK_BANDS[-1][2]


def build_risk_constraints(category: RiskCategory, band_constraints: dict) -> RiskConstraints:
    """Build a RiskConstraints object from the band lookup."""
    return RiskConstraints(
        max_volatility=band_constraints["max_volatility"],
        max_drawdown=band_constraints["max_drawdown"],
        equity_allocation_min=band_constraints["equity_min"],
        equity_allocation_max=band_constraints["equity_max"],
        investment_horizon=band_constraints["horizon"],
        risk_tolerance_label=category.value.replace("_", " ").title(),
    )


# ── Family Office Scoring ──

def compute_family_complexity(fo_responses: list[QuestionResponse]) -> int:
    """Compute family complexity score (1-5) from FO questionnaire responses."""
    if not fo_responses:
        return 1

    scores = [score_option(r.selected_option) for r in fo_responses]
    avg = sum(scores) / len(scores) if scores else 10

    if avg <= 14:
        return 1  # Simple HNI
    elif avg <= 20:
        return 2  # Moderate HNI
    elif avg <= 28:
        return 3  # Emerging Family Office
    elif avg <= 35:
        return 4  # Structured Family Office
    else:
        return 5  # Complex Family Office


def build_family_constraints(complexity: int) -> FamilyConstraints:
    """Build family governance constraints from complexity score."""
    constraints = FamilyConstraints(
        complexity_score=complexity,
        requires_committee_approval=complexity >= 3,
        escalation_threshold_multiplier=max(0.5, 1.0 - (complexity - 1) * 0.1),
        governance_requirements=[],
        mandate_constraints=[],
    )

    if complexity >= 2:
        constraints.governance_requirements.append("Multi-stakeholder notification on major rebalances")
    if complexity >= 3:
        constraints.governance_requirements.append("Committee approval required for positions > 15% weight")
        constraints.governance_requirements.append("Quarterly portfolio review mandatory")
    if complexity >= 4:
        constraints.governance_requirements.append("Cross-jurisdictional compliance check")
        constraints.governance_requirements.append("Consolidated family reporting")
        constraints.mandate_constraints.append("ESG screening required for new positions")
    if complexity >= 5:
        constraints.governance_requirements.append("Trust deed compliance verification")
        constraints.governance_requirements.append("Succession plan impact assessment")
        constraints.mandate_constraints.append("Alternative investment limit per entity")

    return constraints


def merge_effective_constraints(
    individual: RiskConstraints,
    family: FamilyConstraints | None,
) -> RiskConstraints:
    """Merge individual and family constraints — governance-first (more conservative wins)."""
    if family is None:
        return individual

    # Tighten constraints based on complexity
    multiplier = family.escalation_threshold_multiplier
    return RiskConstraints(
        max_volatility=round(individual.max_volatility * multiplier, 4),
        max_drawdown=round(individual.max_drawdown * multiplier, 4),
        equity_allocation_min=individual.equity_allocation_min,
        equity_allocation_max=round(
            min(individual.equity_allocation_max, individual.equity_allocation_max * multiplier + 0.1), 4
        ),
        investment_horizon=individual.investment_horizon,
        risk_tolerance_label=individual.risk_tolerance_label,
    )
