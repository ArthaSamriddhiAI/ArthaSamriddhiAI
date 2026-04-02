"""Pydantic schemas and questionnaire template for investor risk profiling."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ──

class InvestorType(str, Enum):
    INDIVIDUAL = "individual"
    HNI = "hni"
    FAMILY_OFFICE = "family_office"
    NRI = "nri"


class RiskCategory(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATELY_CONSERVATIVE = "moderately_conservative"
    MODERATE = "moderate"
    MODERATELY_AGGRESSIVE = "moderately_aggressive"
    AGGRESSIVE = "aggressive"


class FamilyOfficeType(str, Enum):
    SINGLE_FAMILY = "single_family"
    MULTI_FAMILY = "multi_family"
    INFORMAL_JOINT = "informal_joint"


# ── API Models ──

class CreateInvestorRequest(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    investor_type: InvestorType = InvestorType.INDIVIDUAL
    family_office_id: str | None = None


class InvestorResponse(BaseModel):
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    investor_type: InvestorType
    family_office_id: str | None = None
    risk_profile: RiskProfileResponse | None = None
    created_at: datetime


class CreateFamilyOfficeRequest(BaseModel):
    name: str
    office_type: FamilyOfficeType = FamilyOfficeType.SINGLE_FAMILY
    total_aum_band: str | None = None


class FamilyOfficeResponse(BaseModel):
    id: str
    name: str
    office_type: FamilyOfficeType
    total_aum_band: str | None = None
    complexity_score: int | None = None
    created_at: datetime


class QuestionResponse(BaseModel):
    question_number: int
    selected_option: str  # a, b, c, d


class SubmitQuestionnaireRequest(BaseModel):
    responses: list[QuestionResponse]
    include_family_office: bool = False
    family_office_responses: list[QuestionResponse] = Field(default_factory=list)
    assessed_by: str = "system"
    assessment_context: str = "ad_hoc"  # onboarding, annual_review, ad_hoc, regulatory


class RiskProfileResponse(BaseModel):
    id: str
    investor_id: str
    overall_score: float
    risk_category: RiskCategory
    category_scores: dict[str, float]
    constraints: RiskConstraints
    family_complexity_score: int | None = None
    family_constraints: FamilyConstraints | None = None
    effective_constraints: RiskConstraints
    computed_at: datetime


class RiskConstraints(BaseModel):
    max_volatility: float  # 0-1
    max_drawdown: float  # 0-1
    equity_allocation_min: float  # 0-1
    equity_allocation_max: float  # 0-1
    investment_horizon: str  # short/medium/long
    risk_tolerance_label: str


class FamilyConstraints(BaseModel):
    complexity_score: int  # 1-5
    requires_committee_approval: bool = False
    escalation_threshold_multiplier: float = 1.0  # lower = stricter
    governance_requirements: list[str] = Field(default_factory=list)
    mandate_constraints: list[str] = Field(default_factory=list)


# ── Questionnaire Template ──

class QuestionOption(BaseModel):
    key: str  # a, b, c, d
    text: str
    score: int  # 10, 20, 30, 40


class Question(BaseModel):
    number: int
    text: str
    options: list[QuestionOption]


class QuestionCategory(BaseModel):
    id: str
    name: str
    description: str
    questions: list[Question]
    is_optional: bool = False
    condition: str | None = None  # e.g., "investor_type in ['hni', 'family_office']"


class QuestionnaireTemplate(BaseModel):
    version: str = "1.0"
    categories: list[QuestionCategory]


def get_questionnaire_template() -> QuestionnaireTemplate:
    """Return the full questionnaire structure."""
    return QuestionnaireTemplate(
        version="1.0",
        categories=[
            QuestionCategory(
                id="personal_financial",
                name="Personal & Financial Background",
                description="Understanding your life stage, income stability, and financial obligations",
                questions=[
                    Question(number=1, text="Describe your current stage of life?", options=[
                        QuestionOption(key="a", text="Retired", score=10),
                        QuestionOption(key="b", text="Married with dependent family members", score=20),
                        QuestionOption(key="c", text="Married but no financial burden", score=30),
                        QuestionOption(key="d", text="Single with no financial burden", score=40),
                    ]),
                    Question(number=2, text="How stable is your current income / job or business?", options=[
                        QuestionOption(key="a", text="Very unstable", score=10),
                        QuestionOption(key="b", text="Somewhat unstable", score=20),
                        QuestionOption(key="c", text="Stable", score=30),
                        QuestionOption(key="d", text="Very stable", score=40),
                    ]),
                    Question(number=3, text="How many family members are dependent on you?", options=[
                        QuestionOption(key="a", text="Sole earner for family", score=10),
                        QuestionOption(key="b", text="3 or 4 dependents", score=20),
                        QuestionOption(key="c", text="1 or 2 dependents", score=30),
                        QuestionOption(key="d", text="0 dependents", score=40),
                    ]),
                    Question(number=4, text="Do you consider yourself financially secured?", options=[
                        QuestionOption(key="a", text="Strongly disagree", score=10),
                        QuestionOption(key="b", text="Neither agree nor disagree", score=20),
                        QuestionOption(key="c", text="Agree somewhat", score=30),
                        QuestionOption(key="d", text="Strongly agree", score=40),
                    ]),
                    Question(number=5, text="How well do your family members understand and participate in managing your financial affairs?", options=[
                        QuestionOption(key="a", text="My family has no idea", score=10),
                        QuestionOption(key="b", text="My family has limited information", score=20),
                        QuestionOption(key="c", text="My family has a good enough idea", score=30),
                        QuestionOption(key="d", text="My family has complete understanding", score=40),
                    ]),
                    Question(number=6, text="Do you have any outstanding liabilities or debts?", options=[
                        QuestionOption(key="a", text="Yes, significant liabilities", score=10),
                        QuestionOption(key="b", text="Yes, but on verge of closing", score=20),
                        QuestionOption(key="c", text="Yes, but manageable", score=30),
                        QuestionOption(key="d", text="No, I am debt-free", score=40),
                    ]),
                    Question(number=7, text="What is your monthly EMI as a percentage of income?", options=[
                        QuestionOption(key="a", text="Above 60% of monthly income", score=10),
                        QuestionOption(key="b", text="30-60% of monthly income", score=20),
                        QuestionOption(key="c", text="Up to 30% of monthly income", score=30),
                        QuestionOption(key="d", text="No loans / EMIs", score=40),
                    ]),
                ],
            ),
            QuestionCategory(
                id="financial_health",
                name="Financial Health & Liquidity",
                description="Assessing your cash flow, emergency preparedness, and liquidity needs",
                questions=[
                    Question(number=1, text="What portion of your monthly net income goes towards paying loan installments?", options=[
                        QuestionOption(key="a", text="Above 75%", score=10),
                        QuestionOption(key="b", text="51-75%", score=20),
                        QuestionOption(key="c", text="26-50%", score=30),
                        QuestionOption(key="d", text="0-25%", score=40),
                    ]),
                    Question(number=2, text="What percentage of your monthly income can be invested?", options=[
                        QuestionOption(key="a", text="0-15%", score=10),
                        QuestionOption(key="b", text="16-30%", score=20),
                        QuestionOption(key="c", text="31-45%", score=30),
                        QuestionOption(key="d", text="Above 45%", score=40),
                    ]),
                    Question(number=3, text="How many months of living expenses do you have in an Emergency Fund?", options=[
                        QuestionOption(key="a", text="Less than 3 months", score=10),
                        QuestionOption(key="b", text="3-6 months", score=20),
                        QuestionOption(key="c", text="6-12 months", score=30),
                        QuestionOption(key="d", text="More than 12 months", score=40),
                    ]),
                    Question(number=4, text="How easily do you need to access your investment funds?", options=[
                        QuestionOption(key="a", text="I need immediate access", score=10),
                        QuestionOption(key="b", text="I prefer to lock for a while", score=20),
                        QuestionOption(key="c", text="Flexible, but some liquidity preferred", score=30),
                        QuestionOption(key="d", text="Not required at all", score=40),
                    ]),
                    Question(number=5, text="Do you need regular payouts or withdrawals from your investments?", options=[
                        QuestionOption(key="a", text="Yes, monthly", score=10),
                        QuestionOption(key="b", text="Yes, quarterly", score=20),
                        QuestionOption(key="c", text="Maybe, depends on returns", score=30),
                        QuestionOption(key="d", text="No, let it grow", score=40),
                    ]),
                ],
            ),
            QuestionCategory(
                id="experience_risk_tolerance",
                name="Investment Experience & Risk Tolerance",
                description="Understanding your investment history and comfort with risk",
                questions=[
                    Question(number=1, text="How would you characterize your past and current investments?", options=[
                        QuestionOption(key="a", text="Mostly safe investments like FDs, PF, etc.", score=10),
                        QuestionOption(key="b", text="Somewhat safe investments and some risky", score=20),
                        QuestionOption(key="c", text="Equal combination of safe and risky", score=30),
                        QuestionOption(key="d", text="Mostly risky investments like stocks and equities", score=40),
                    ]),
                    Question(number=2, text="How long have you been investing in Equity Markets / Stocks / Mutual Funds?", options=[
                        QuestionOption(key="a", text="Less than 1 year", score=10),
                        QuestionOption(key="b", text="1-3 years", score=20),
                        QuestionOption(key="c", text="4-6 years", score=30),
                        QuestionOption(key="d", text="More than 7 years", score=40),
                    ]),
                    Question(number=3, text="How well do you understand investing in the markets?", options=[
                        QuestionOption(key="a", text="No knowledge at all", score=10),
                        QuestionOption(key="b", text="Invested a few times but not seasoned", score=20),
                        QuestionOption(key="c", text="Intermittent investing based on fluctuations", score=30),
                        QuestionOption(key="d", text="Experienced investor with research work", score=40),
                    ]),
                    Question(number=4, text="In which category do you hold the most significant portion of your wealth (excluding primary residence)?", options=[
                        QuestionOption(key="a", text="No other savings than real estate", score=10),
                        QuestionOption(key="b", text="Gold / Silver / Commodities", score=20),
                        QuestionOption(key="c", text="Cash / FDs / PPFs / Bonds", score=30),
                        QuestionOption(key="d", text="Equity / MFs / Stocks / PMS / AIF", score=40),
                    ]),
                    Question(number=5, text="How do you usually react to a significant decline (20-40% drop) in your investments?", options=[
                        QuestionOption(key="a", text="I would sell all my investments", score=10),
                        QuestionOption(key="b", text="I would sell some of my investments", score=20),
                        QuestionOption(key="c", text="I would hold and do nothing", score=30),
                        QuestionOption(key="d", text="I would buy more at the lower price", score=40),
                    ]),
                    Question(number=6, text="How comfortable are you with taking risks / losses to achieve better returns?", options=[
                        QuestionOption(key="a", text="Not comfortable at all", score=10),
                        QuestionOption(key="b", text="Slightly comfortable", score=20),
                        QuestionOption(key="c", text="Moderately comfortable", score=30),
                        QuestionOption(key="d", text="Very comfortable", score=40),
                    ]),
                    Question(number=7, text="What level of temporary decrease in portfolio value can you tolerate?", options=[
                        QuestionOption(key="a", text="Up to 10% loss", score=10),
                        QuestionOption(key="b", text="11-20% loss", score=20),
                        QuestionOption(key="c", text="21-30% loss", score=30),
                        QuestionOption(key="d", text="Greater than 40% loss", score=40),
                    ]),
                ],
            ),
            QuestionCategory(
                id="goals_horizon",
                name="Investment Goals & Horizon",
                description="Your return expectations, time horizon, and investment allocation",
                questions=[
                    Question(number=1, text="What is your expected annual return on investments?", options=[
                        QuestionOption(key="a", text="Around 6-8%", score=10),
                        QuestionOption(key="b", text="Around 9-11%", score=20),
                        QuestionOption(key="c", text="Around 12-14%", score=30),
                        QuestionOption(key="d", text="More than 14%", score=40),
                    ]),
                    Question(number=2, text="How long do you plan to keep the investments?", options=[
                        QuestionOption(key="a", text="1-3 years", score=10),
                        QuestionOption(key="b", text="3-10 years", score=20),
                        QuestionOption(key="c", text="10-20 years", score=30),
                        QuestionOption(key="d", text="More than 20 years", score=40),
                    ]),
                    Question(number=3, text="How flexible are you with your investment time horizon?", options=[
                        QuestionOption(key="a", text="Not flexible at all", score=10),
                        QuestionOption(key="b", text="Slightly flexible", score=20),
                        QuestionOption(key="c", text="Somewhat flexible", score=30),
                        QuestionOption(key="d", text="Very flexible", score=40),
                    ]),
                    Question(number=4, text="What percentage of your monthly income do you invest for long-term goals?", options=[
                        QuestionOption(key="a", text="No investment", score=10),
                        QuestionOption(key="b", text="0-30%", score=20),
                        QuestionOption(key="c", text="30-60%", score=30),
                        QuestionOption(key="d", text="More than 60%", score=40),
                    ]),
                ],
            ),
            QuestionCategory(
                id="tax_regulatory",
                name="Taxation & Regulatory (NRI-Specific)",
                description="Tax awareness and regulatory compliance considerations",
                is_optional=True,
                condition="investor_type in ['nri']",
                questions=[
                    Question(number=1, text="Are you familiar with tax implications in India (TDS, DTAA benefits)?", options=[
                        QuestionOption(key="a", text="Not familiar", score=10),
                        QuestionOption(key="b", text="Somewhat familiar", score=20),
                        QuestionOption(key="c", text="Knows but would explore more", score=30),
                        QuestionOption(key="d", text="Knows in and out", score=40),
                    ]),
                    Question(number=2, text="Do you require repatriation of your investment returns?", options=[
                        QuestionOption(key="a", text="Not sure yet", score=10),
                        QuestionOption(key="b", text="No, I would re-invest in India", score=20),
                        QuestionOption(key="c", text="Partial is sufficient", score=30),
                        QuestionOption(key="d", text="Yes, I need in full", score=40),
                    ]),
                    Question(number=3, text="Do you have investments requiring FEMA compliance?", options=[
                        QuestionOption(key="a", text="I need guidance on this", score=10),
                        QuestionOption(key="b", text="I do not have such investments", score=20),
                        QuestionOption(key="c", text="I have but unsure about FEMA", score=30),
                        QuestionOption(key="d", text="I am aware and compliant", score=40),
                    ]),
                ],
            ),
            QuestionCategory(
                id="insurance_protection",
                name="Insurance & Protection Planning",
                description="Evaluating your safety net coverage",
                questions=[
                    Question(number=1, text="How much health insurance cover do you have for your family?", options=[
                        QuestionOption(key="a", text="No health insurance", score=10),
                        QuestionOption(key="b", text="Up to 5 lacs", score=20),
                        QuestionOption(key="c", text="5-15 lacs", score=30),
                        QuestionOption(key="d", text="Above 15 lacs", score=40),
                    ]),
                    Question(number=2, text="How much is your life insurance coverage?", options=[
                        QuestionOption(key="a", text="No life insurance", score=10),
                        QuestionOption(key="b", text="Up to 50 lacs", score=20),
                        QuestionOption(key="c", text="50 lacs to 1 crore", score=30),
                        QuestionOption(key="d", text="Above 1 crore", score=40),
                    ]),
                ],
            ),
            QuestionCategory(
                id="market_outlook",
                name="Market & Economic Outlook",
                description="Your perspective on the economy and inflation",
                questions=[
                    Question(number=1, text="How optimistic are you about the long-term prospects of the economy?", options=[
                        QuestionOption(key="a", text="Negative", score=10),
                        QuestionOption(key="b", text="Keeps an eye", score=20),
                        QuestionOption(key="c", text="Somewhat optimistic", score=30),
                        QuestionOption(key="d", text="Strong believer", score=40),
                    ]),
                    Question(number=2, text="How concerned are you that your investments should exceed the rate of inflation?", options=[
                        QuestionOption(key="a", text="Not concerned", score=10),
                        QuestionOption(key="b", text="Slightly concerned", score=20),
                        QuestionOption(key="c", text="Moderately concerned", score=30),
                        QuestionOption(key="d", text="Highly concerned", score=40),
                    ]),
                ],
            ),
            QuestionCategory(
                id="psychometric",
                name="Psychometric Market Test",
                description="Scenario-based questions to assess your real-world decision-making under market stress",
                questions=[
                    Question(number=1, text="You have Rs 10,00,000 in an index fund. A global crisis causes a 30% drop in one month. What do you do?", options=[
                        QuestionOption(key="a", text="Sell immediately to cut further losses", score=10),
                        QuestionOption(key="b", text="Hold tight and wait for recovery", score=20),
                        QuestionOption(key="c", text="Buy more at lower prices, seeing it as opportunity", score=40),
                        QuestionOption(key="d", text="Switch to bonds or fixed deposits for safety", score=10),
                    ]),
                    Question(number=2, text="You invested in government bonds. Interest rates rise unexpectedly, reducing bond prices by 10%. How do you react?", options=[
                        QuestionOption(key="a", text="Sell and move to safer assets", score=10),
                        QuestionOption(key="b", text="Hold until maturity for fixed returns", score=20),
                        QuestionOption(key="c", text="Buy more bonds at higher yield to average down", score=40),
                        QuestionOption(key="d", text="Move funds to high-dividend stocks", score=30),
                    ]),
                    Question(number=3, text="You bought a premium residential property. Market softens, prices drop 15%. Selling is difficult. What do you do?", options=[
                        QuestionOption(key="a", text="Sell at a loss and invest elsewhere", score=10),
                        QuestionOption(key="b", text="Hold and wait for recovery", score=20),
                        QuestionOption(key="c", text="Rent out the property for cash flow", score=30),
                        QuestionOption(key="d", text="Refinance and wait for better opportunity", score=40),
                    ]),
                    Question(number=4, text="Inflation rises unexpectedly. Your portfolio is equity and bonds. Gold surges 25%. What's your move?", options=[
                        QuestionOption(key="a", text="Shift a portion into gold as a hedge", score=30),
                        QuestionOption(key="b", text="Keep portfolio unchanged, ride it out", score=20),
                        QuestionOption(key="c", text="Sell equities and go heavy on commodities", score=10),
                        QuestionOption(key="d", text="Move into cash to wait for stability", score=10),
                    ]),
                    Question(number=5, text="You invested Rs 5,00,000 in a private equity fund. The company isn't profitable yet. Your reaction?", options=[
                        QuestionOption(key="a", text="Sell off, even at a discount, to recover capital", score=10),
                        QuestionOption(key="b", text="Hold and give the company time to scale", score=30),
                        QuestionOption(key="c", text="Invest more in similar alternative assets", score=40),
                        QuestionOption(key="d", text="Exit and move to traditional stocks and bonds", score=20),
                    ]),
                    Question(number=6, text="Your friend made 40% in stocks while your mutual fund returned 12%. He suggests switching to direct stocks. What do you do?", options=[
                        QuestionOption(key="a", text="Sell mutual funds and invest in stocks", score=10),
                        QuestionOption(key="b", text="Allocate a small portion to direct stocks, keep MFs", score=30),
                        QuestionOption(key="c", text="Stick to mutual funds for diversification", score=20),
                        QuestionOption(key="d", text="Move to index funds, avoiding stock-picking risk", score=20),
                    ]),
                    Question(number=7, text="You invested in an emerging market ETF. Political instability and currency depreciation cause a 25% drop. Your response?", options=[
                        QuestionOption(key="a", text="Exit immediately to avoid further losses", score=10),
                        QuestionOption(key="b", text="Hold, emerging markets tend to recover", score=20),
                        QuestionOption(key="c", text="Invest more to average down the cost", score=40),
                        QuestionOption(key="d", text="Shift funds to developed markets for safety", score=30),
                    ]),
                    Question(number=8, text="A bank offers 7.5% on a 5-year FD. The stock market is volatile but historically returns 12-15%. Where do you invest?", options=[
                        QuestionOption(key="a", text="Put everything in FDs for safety", score=10),
                        QuestionOption(key="b", text="Split between FDs and stocks", score=20),
                        QuestionOption(key="c", text="Invest fully in stocks for long-term gains", score=40),
                        QuestionOption(key="d", text="Move into hybrid/balanced funds", score=30),
                    ]),
                    Question(number=9, text="Your portfolio was 60% equity, 30% bonds, 10% gold. Market changes make it 75% equity, 15% bonds, 10% gold. What do you do?", options=[
                        QuestionOption(key="a", text="Leave it as is - higher equity means better growth", score=30),
                        QuestionOption(key="b", text="Add more to equity since it's performing well", score=40),
                        QuestionOption(key="c", text="Sell some stocks to restore original allocation", score=20),
                        QuestionOption(key="d", text="Increase bonds and gold to reduce volatility", score=10),
                    ]),
                ],
            ),
            QuestionCategory(
                id="family_office",
                name="Family / Family Office Profile",
                description="For HNI (5Cr+) and Family Office clients — assessing governance complexity and multi-stakeholder dynamics",
                is_optional=True,
                condition="investor_type in ['hni', 'family_office']",
                questions=[
                    Question(number=1, text="What type of family investment structure do you have?", options=[
                        QuestionOption(key="a", text="Individual decision-making, no formal structure", score=10),
                        QuestionOption(key="b", text="Informal joint family investing", score=20),
                        QuestionOption(key="c", text="Single-family office with dedicated staff", score=30),
                        QuestionOption(key="d", text="Multi-family office or institutional setup", score=40),
                    ]),
                    Question(number=2, text="How many family members have investment decision authority?", options=[
                        QuestionOption(key="a", text="Single patriarch/matriarch decides", score=10),
                        QuestionOption(key="b", text="2 key decision makers", score=20),
                        QuestionOption(key="c", text="3-5 family members involved", score=30),
                        QuestionOption(key="d", text="Formal investment committee with voting", score=40),
                    ]),
                    Question(number=3, text="What is the status of succession planning for wealth management?", options=[
                        QuestionOption(key="a", text="No succession planning in place", score=10),
                        QuestionOption(key="b", text="Informal discussions, nothing formalized", score=20),
                        QuestionOption(key="c", text="Formalized plan with legal documentation", score=30),
                        QuestionOption(key="d", text="Trust structure with professional trustees", score=40),
                    ]),
                    Question(number=4, text="How aligned are family members on investment mandates across generations?", options=[
                        QuestionOption(key="a", text="All aligned on the same objectives", score=10),
                        QuestionOption(key="b", text="Mostly aligned with minor differences", score=20),
                        QuestionOption(key="c", text="Some divergence in risk appetite", score=30),
                        QuestionOption(key="d", text="Significant divergence across generations", score=40),
                    ]),
                    Question(number=5, text="Does your family have a formal investment committee?", options=[
                        QuestionOption(key="a", text="No formal structure", score=10),
                        QuestionOption(key="b", text="Informal family discussions", score=20),
                        QuestionOption(key="c", text="Quarterly formal committee meetings", score=30),
                        QuestionOption(key="d", text="Monthly committee with documented minutes", score=40),
                    ]),
                    Question(number=6, text="What is the total family AUM (Assets Under Management)?", options=[
                        QuestionOption(key="a", text="Rs 5-10 crore", score=10),
                        QuestionOption(key="b", text="Rs 10-25 crore", score=20),
                        QuestionOption(key="c", text="Rs 25-50 crore", score=30),
                        QuestionOption(key="d", text="Above Rs 50 crore", score=40),
                    ]),
                    Question(number=7, text="How diverse are the family's asset classes?", options=[
                        QuestionOption(key="a", text="Primarily equity and mutual funds", score=10),
                        QuestionOption(key="b", text="Equity, debt, and real estate", score=20),
                        QuestionOption(key="c", text="Multi-asset including alternatives (PMS/AIF)", score=30),
                        QuestionOption(key="d", text="Full spectrum including PE, VC, art, philanthropy", score=40),
                    ]),
                    Question(number=8, text="What is the family's cross-border investment exposure?", options=[
                        QuestionOption(key="a", text="No international investments", score=10),
                        QuestionOption(key="b", text="Some NRI assets or LRS investments", score=20),
                        QuestionOption(key="c", text="Significant international diversification", score=30),
                        QuestionOption(key="d", text="Multi-jurisdiction with offshore structures", score=40),
                    ]),
                    Question(number=9, text="How many advisor/PMS/AIF relationships does the family maintain?", options=[
                        QuestionOption(key="a", text="None or 1", score=10),
                        QuestionOption(key="b", text="2-3 relationships", score=20),
                        QuestionOption(key="c", text="4-5 relationships", score=30),
                        QuestionOption(key="d", text="More than 5 advisory relationships", score=40),
                    ]),
                    Question(number=10, text="What are the family's ethical/ESG investment mandates?", options=[
                        QuestionOption(key="a", text="No specific mandates", score=10),
                        QuestionOption(key="b", text="Soft preferences, not strictly enforced", score=20),
                        QuestionOption(key="c", text="Formal exclusion list for certain sectors", score=30),
                        QuestionOption(key="d", text="ESG-first mandate with measurable targets", score=40),
                    ]),
                    Question(number=11, text="What are the family's liquidity requirements?", options=[
                        QuestionOption(key="a", text="No near-term liquidity needs", score=10),
                        QuestionOption(key="b", text="Some planned liquidity events", score=20),
                        QuestionOption(key="c", text="Regular distributions to family members", score=30),
                        QuestionOption(key="d", text="Complex cash flow needs across entities", score=40),
                    ]),
                    Question(number=12, text="What consolidated reporting does the family need?", options=[
                        QuestionOption(key="a", text="Single consolidated view is sufficient", score=10),
                        QuestionOption(key="b", text="Per-member portfolio breakdowns", score=20),
                        QuestionOption(key="c", text="Per-entity reporting (trust, HUF, etc.)", score=30),
                        QuestionOption(key="d", text="Multi-entity with regulatory reporting", score=40),
                    ]),
                ],
            ),
        ],
    )
