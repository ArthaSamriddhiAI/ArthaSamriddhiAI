"""Help chat endpoint — answers platform questions only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from artha.common.db.session import get_session
from artha.llm.base import LLMProvider
from artha.llm.models import LLMMessage, LLMRequest
from artha.llm.registry import get_provider

router = APIRouter(prefix="/help", tags=["help"])

HELP_SYSTEM_PROMPT = """You are the Samriddhi AI Help Assistant. You help advisors navigate and understand the platform.

You CAN answer questions about:
- How to use the platform (navigation, workflows, screens)
- What each module does (Evidence, Governance, Audit Trail, Portfolio, Investors, Markets)
- How to interpret outputs (what governance BLOCK means, how to read agent confidence scores)
- How to complete tasks (create an intent, freeze a portfolio, read the audit trail, add holdings)
- What the EGA (Evidence-Governance-Accountability) architecture means
- Portfolio lifecycle (DRAFT vs LIVE states, freezing, unfreezing)

You CANNOT and MUST NOT:
- Create intents, trigger agent analysis, or make investment decisions
- Interpret specific portfolio data or suggest trades
- Give investment advice or recommend specific actions
- Override governance rules or system constraints

If asked to do any of the above, politely redirect the advisor to the appropriate module and explain why you cannot act on their behalf.

Current context: The advisor is viewing the '{screen}' screen.

Keep responses concise (2-4 sentences). Be specific and actionable."""


class ChatRequest(BaseModel):
    message: str
    screen: str = "dashboard"
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    response: str
    model: str = ""


@router.post("/chat", response_model=ChatResponse)
async def help_chat(req: ChatRequest):
    llm = get_provider()

    system = HELP_SYSTEM_PROMPT.replace("{screen}", req.screen)

    messages = [LLMMessage(role="system", content=system)]

    # Add conversation history (last few turns)
    for msg in req.history[-8:]:
        if msg.get("role") in ("user", "assistant"):
            messages.append(LLMMessage(role=msg["role"], content=msg["content"]))

    # Add current message
    messages.append(LLMMessage(role="user", content=req.message))

    try:
        response = await llm.complete(LLMRequest(
            messages=messages,
            temperature=0.3,
            max_tokens=300,
        ))
        # Strip em dashes from response (T-6 requirement)
        text = response.content.replace(" -- ", ", ").replace("--", ", ").replace(" - ", ", ")
        return ChatResponse(response=text, model=response.model or llm.name)
    except Exception as e:
        return ChatResponse(response=f"I'm having trouble connecting right now. Please try again. (Error: {str(e)[:50]})")
