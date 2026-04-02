"""Investor risk profile business logic."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artha.investor.models import (
    FamilyOfficeResponseRow,
    FamilyOfficeRow,
    InvestorRiskProfileRow,
    InvestorRow,
    QuestionnaireResponseRow,
)
from artha.investor.schemas import (
    CreateFamilyOfficeRequest,
    CreateInvestorRequest,
    FamilyConstraints,
    FamilyOfficeResponse,
    InvestorResponse,
    QuestionResponse,
    RiskConstraints,
    RiskProfileResponse,
    SubmitQuestionnaireRequest,
    get_questionnaire_template,
)
from artha.investor.scoring import (
    build_family_constraints,
    build_risk_constraints,
    classify_risk,
    compute_category_scores,
    compute_family_complexity,
    compute_overall_score,
    merge_effective_constraints,
    score_option,
)


class InvestorService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Investor CRUD ──

    async def create_investor(self, req: CreateInvestorRequest) -> InvestorResponse:
        now = datetime.now(UTC)
        row = InvestorRow(
            id=str(uuid.uuid4()),
            name=req.name,
            email=req.email,
            phone=req.phone,
            investor_type=req.investor_type.value,
            family_office_id=req.family_office_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return InvestorResponse(
            id=row.id, name=row.name, email=row.email, phone=row.phone,
            investor_type=req.investor_type, family_office_id=row.family_office_id,
            created_at=row.created_at,
        )

    async def get_investor(self, investor_id: str) -> InvestorResponse | None:
        stmt = select(InvestorRow).where(InvestorRow.id == investor_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        profile = await self.get_profile(investor_id)
        from artha.investor.schemas import InvestorType
        return InvestorResponse(
            id=row.id, name=row.name, email=row.email, phone=row.phone,
            investor_type=InvestorType(row.investor_type),
            family_office_id=row.family_office_id,
            risk_profile=profile, created_at=row.created_at,
        )

    async def list_investors(self, limit: int = 50) -> list[InvestorResponse]:
        stmt = select(InvestorRow).order_by(InvestorRow.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        investors = []
        for row in result.scalars():
            from artha.investor.schemas import InvestorType
            investors.append(InvestorResponse(
                id=row.id, name=row.name, email=row.email, phone=row.phone,
                investor_type=InvestorType(row.investor_type),
                family_office_id=row.family_office_id, created_at=row.created_at,
            ))
        return investors

    # ── Family Office ──

    async def create_family_office(self, req: CreateFamilyOfficeRequest) -> FamilyOfficeResponse:
        now = datetime.now(UTC)
        row = FamilyOfficeRow(
            id=str(uuid.uuid4()),
            name=req.name,
            office_type=req.office_type.value,
            total_aum_band=req.total_aum_band,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return FamilyOfficeResponse(
            id=row.id, name=row.name, office_type=req.office_type,
            total_aum_band=row.total_aum_band, created_at=row.created_at,
        )

    # ── Questionnaire ──

    async def submit_questionnaire(
        self, investor_id: str, req: SubmitQuestionnaireRequest
    ) -> RiskProfileResponse:
        now = datetime.now(UTC)
        template = get_questionnaire_template()

        # Build flat question list (excluding family_office)
        flat_questions = []
        for cat in template.categories:
            if cat.id == "family_office":
                continue
            for q in cat.questions:
                flat_questions.append((cat.id, cat.name, q))

        # Save individual responses
        for i, resp in enumerate(req.responses):
            if i >= len(flat_questions):
                break
            cat_id, cat_name, q = flat_questions[i]
            self._session.add(QuestionnaireResponseRow(
                id=str(uuid.uuid4()),
                investor_id=investor_id,
                category=cat_id,
                question_number=q.number,
                question_text=q.text,
                selected_option=resp.selected_option,
                score=score_option(resp.selected_option),
                created_at=now,
            ))

        # Save family office responses if applicable
        investor_row = (await self._session.execute(
            select(InvestorRow).where(InvestorRow.id == investor_id)
        )).scalar_one_or_none()

        fo_responses = req.family_office_responses
        family_complexity = None
        family_constraints = None

        if req.include_family_office and fo_responses and investor_row and investor_row.family_office_id:
            fo_cat = next((c for c in template.categories if c.id == "family_office"), None)
            if fo_cat:
                for i, resp in enumerate(fo_responses):
                    if i >= len(fo_cat.questions):
                        break
                    q = fo_cat.questions[i]
                    self._session.add(FamilyOfficeResponseRow(
                        id=str(uuid.uuid4()),
                        family_office_id=investor_row.family_office_id,
                        category="family_office",
                        question_number=q.number,
                        question_text=q.text,
                        selected_option=resp.selected_option,
                        score=score_option(resp.selected_option),
                        created_at=now,
                    ))
            family_complexity = compute_family_complexity(fo_responses)
            family_constraints = build_family_constraints(family_complexity)

        # Compute scores
        category_scores = compute_category_scores(req.responses)
        overall_score = compute_overall_score(category_scores)
        risk_category, band_constraints = classify_risk(overall_score)
        individual_constraints = build_risk_constraints(risk_category, band_constraints)
        effective_constraints = merge_effective_constraints(individual_constraints, family_constraints)

        # Save profile
        profile_id = str(uuid.uuid4())
        profile_row = InvestorRiskProfileRow(
            id=profile_id,
            investor_id=investor_id,
            overall_score=overall_score,
            risk_category=risk_category.value,
            category_scores_json=json.dumps(category_scores),
            constraints_json=json.dumps(individual_constraints.model_dump()),
            family_complexity_score=family_complexity,
            family_constraints_json=json.dumps(family_constraints.model_dump()) if family_constraints else None,
            effective_constraints_json=json.dumps(effective_constraints.model_dump()),
            questionnaire_version="1.0",
            computed_at=now,
            valid_until=now + timedelta(days=365),
        )
        self._session.add(profile_row)
        await self._session.flush()

        return RiskProfileResponse(
            id=profile_id,
            investor_id=investor_id,
            overall_score=overall_score,
            risk_category=risk_category,
            category_scores=category_scores,
            constraints=individual_constraints,
            family_complexity_score=family_complexity,
            family_constraints=family_constraints,
            effective_constraints=effective_constraints,
            computed_at=now,
        )

    async def get_profile(self, investor_id: str) -> RiskProfileResponse | None:
        stmt = (
            select(InvestorRiskProfileRow)
            .where(InvestorRiskProfileRow.investor_id == investor_id)
            .order_by(InvestorRiskProfileRow.computed_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        category_scores = json.loads(row.category_scores_json)
        constraints = RiskConstraints.model_validate(json.loads(row.constraints_json))
        effective = RiskConstraints.model_validate(json.loads(row.effective_constraints_json))
        family_constraints = (
            FamilyConstraints.model_validate(json.loads(row.family_constraints_json))
            if row.family_constraints_json else None
        )

        from artha.investor.schemas import RiskCategory
        return RiskProfileResponse(
            id=row.id,
            investor_id=row.investor_id,
            overall_score=row.overall_score,
            risk_category=RiskCategory(row.risk_category),
            category_scores=category_scores,
            constraints=constraints,
            family_complexity_score=row.family_complexity_score,
            family_constraints=family_constraints,
            effective_constraints=effective,
            computed_at=row.computed_at,
        )
