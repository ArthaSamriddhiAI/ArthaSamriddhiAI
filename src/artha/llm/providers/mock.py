"""Deterministic mock LLM provider for testing and demos."""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any, TypeVar

from pydantic import BaseModel

from artha.llm.models import LLMRequest, LLMResponse, LLMUsage

T = TypeVar("T", bound=BaseModel)

# Seed for deterministic but varied mock responses
_RNG = random.Random(42)


class MockProvider:
    """Returns deterministic responses. For structured output, generates valid
    default instances of the requested Pydantic model.

    Enhanced with context-aware responses for analysis and governance agents
    to produce realistic demo data.
    """

    def __init__(self) -> None:
        self._responses: dict[str, str] = {}
        self._structured_overrides: dict[str, dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "mock"

    def set_response(self, prompt_contains: str, response: str) -> None:
        self._responses[prompt_contains] = response

    def set_structured_response(
        self, prompt_contains: str, data: dict[str, Any]
    ) -> None:
        self._structured_overrides[prompt_contains] = data

    async def complete(self, request: LLMRequest) -> LLMResponse:
        prompt_text = " ".join(m.content for m in request.messages)

        # Check for registered responses
        for key, response in self._responses.items():
            if key in prompt_text:
                return LLMResponse(
                    content=response,
                    model="mock",
                    usage=LLMUsage(input_tokens=len(prompt_text), output_tokens=len(response)),
                )

        # Default deterministic response
        h = hashlib.md5(prompt_text.encode()).hexdigest()[:8]
        content = f"Mock response [{h}]"
        return LLMResponse(
            content=content,
            model="mock",
            usage=LLMUsage(input_tokens=len(prompt_text), output_tokens=len(content)),
        )

    async def complete_structured(
        self, request: LLMRequest, output_type: type[T]
    ) -> T:
        prompt_text = " ".join(m.content for m in request.messages)

        # Check for registered structured overrides
        for key, data in self._structured_overrides.items():
            if key in prompt_text:
                return output_type.model_validate(data)

        # Context-aware mock generation for known types
        type_name = output_type.__name__
        aware = _generate_context_aware(type_name, prompt_text)
        if aware is not None:
            return output_type.model_validate(aware)

        # Generate a valid default instance from the schema
        return _build_default(output_type)


def _build_default(model_type: type[T]) -> T:
    """Build a default instance of a Pydantic model using field defaults and type inference."""
    fields = model_type.model_fields
    data: dict[str, Any] = {}

    for name, field_info in fields.items():
        if field_info.default is not None:
            data[name] = field_info.default
        elif field_info.default_factory is not None:
            data[name] = field_info.default_factory()
        else:
            annotation = field_info.annotation
            if annotation is str:
                data[name] = f"mock_{name}"
            elif annotation is int:
                data[name] = 0
            elif annotation is float:
                data[name] = 0.0
            elif annotation is bool:
                data[name] = False
            elif annotation is list or (hasattr(annotation, "__origin__") and getattr(annotation, "__origin__", None) is list):
                data[name] = []
            elif annotation is dict or (hasattr(annotation, "__origin__") and getattr(annotation, "__origin__", None) is dict):
                data[name] = {}
            else:
                data[name] = None

    return model_type.model_validate(data)


# ── Context-aware mock data generators ──


def _extract_symbols(prompt: str) -> list[str]:
    """Extract stock symbols from prompt context."""
    import re
    # Look for common Indian stock tickers in the prompt
    tickers = re.findall(r'\b([A-Z]{2,12}(?:BANK)?)\b', prompt)
    known = {
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC", "BHARTIARTL", "SBIN",
        "HINDUNILVR", "KOTAKBANK", "MARUTI", "WIPRO", "HCLTECH", "TECHM",
        "ICICIBANK", "BAJFINANCE", "ASIANPAINT", "NESTLEIND", "TITAN",
        "DMART", "PIDILITIND", "SUNPHARMA", "LT", "ADANIENT", "POWERGRID",
        "NTPC", "COALINDIA", "ONGC", "TATAPOWER", "ADANIGREEN", "TATAMOTORS",
    }
    found = [t for t in tickers if t in known]
    return found[:5] if found else ["RELIANCE", "TCS", "HDFCBANK"]


def _extract_intent_type(prompt: str) -> str:
    for t in ["rebalance", "risk_review", "trade_proposal", "scheduled_evaluation"]:
        if t in prompt.lower():
            return t
    return "rebalance"


def _hash_seed(prompt: str) -> int:
    return int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16)


def _generate_context_aware(type_name: str, prompt: str) -> dict[str, Any] | None:
    """Generate realistic mock data based on model type and prompt context."""
    seed = _hash_seed(prompt)
    rng = random.Random(seed)

    if type_name == "ClassificationOutput":
        return _mock_classification(prompt, rng)
    elif type_name == "AnalysisEnvelope":
        return _mock_analysis_envelope(prompt, rng)
    elif type_name == "AgentOutput":
        return _mock_agent_output(prompt, rng)
    return None


def _mock_classification(prompt: str, rng: random.Random) -> dict[str, Any]:
    intent = _extract_intent_type(prompt)
    if intent == "trade_proposal":
        agents = ["fundamental", "technical", "sentiment"]
    elif intent == "risk_review":
        agents = ["macro", "technical", "sentiment"]
    elif intent == "scheduled_evaluation":
        agents = ["fundamental", "technical", "sectoral", "macro", "sentiment"]
    else:
        agents = ["fundamental", "technical", "sectoral", "macro", "sentiment"]

    is_unlisted = "unlisted" in prompt.lower() or "pre_ipo" in prompt.lower()
    is_pms = "pms" in prompt.lower() or "aif" in prompt.lower()

    return {
        "selected_agents": agents,
        "reasoning": f"Intent type '{intent}' requires {', '.join(agents)} analysis."
            + (" Unlisted equity detected." if is_unlisted else "")
            + (" PMS/AIF detected." if is_pms else ""),
        "is_unlisted_equity": is_unlisted,
        "is_pms_aif": is_pms,
    }


_ANALYSIS_AGENT_PROFILES = {
    "analysis_fundamental": {
        "name": "Fundamental Analysis",
        "drivers_pool": [
            "P/E ratio at 22x, in line with sector average",
            "Revenue growth of 15% YoY for last 3 quarters",
            "Debt-to-equity ratio of 0.3x — strong balance sheet",
            "ROE trending up from 14% to 18% over 2 years",
            "Free cash flow covers 2.5x dividend payout",
            "Promoter holding stable at 55% with zero pledging",
            "Operating margin expansion from 18% to 22%",
            "Order book at Rs 45,000 Cr — 2.8x TTM revenue",
            "Working capital cycle improved by 12 days",
            "EPS growth of 20% CAGR over 5 years",
        ],
        "flags_pool": [
            "Quarterly results due in 2 weeks — earnings risk",
            "Peer company valuations have compressed 15% this quarter",
            "Capex cycle may pressure near-term cash flows",
            "Related party transactions need monitoring",
        ],
        "risk_weights": {"low": 0.3, "medium": 0.5, "high": 0.15, "critical": 0.05},
    },
    "analysis_technical": {
        "name": "Technical Analysis",
        "drivers_pool": [
            "Price above 200 DMA — long-term uptrend intact",
            "RSI at 62 — healthy momentum, not overbought",
            "MACD histogram positive and expanding",
            "Volume breakout confirmed on 3 consecutive sessions",
            "Support at Rs 2,450 tested and held twice",
            "Bollinger Band width narrowing — squeeze setup",
            "50 DMA golden cross with 200 DMA last month",
            "ADX at 28 — moderate trend strength",
            "Price consolidating near resistance at Rs 2,800",
            "Bearish divergence on RSI — momentum fading",
        ],
        "flags_pool": [
            "Approaching major resistance — breakout not confirmed",
            "Declining volume on up-moves suggests weakening buying interest",
            "Weekly RSI overbought at 74 — short-term pullback likely",
        ],
        "risk_weights": {"low": 0.25, "medium": 0.45, "high": 0.25, "critical": 0.05},
    },
    "analysis_sectoral": {
        "name": "Sectoral Analysis",
        "drivers_pool": [
            "Banking sector benefiting from credit growth at 16% YoY",
            "IT sector facing headwinds from global spending cuts",
            "Pharma sector tailwind from US FDA approvals pipeline",
            "Auto sector supported by festive demand and rural recovery",
            "FMCG showing volume recovery after 2 quarters of decline",
            "Infrastructure sector boosted by Rs 11.1L Cr govt capex budget",
            "Metal sector under pressure from China demand slowdown",
            "Defence sector with strong order inflows — Rs 2L Cr pipeline",
            "Nifty IT underperforming Nifty 50 by 8% this quarter",
            "Bank Nifty outperforming broad market by 5%",
        ],
        "flags_pool": [
            "Portfolio overweight IT at 28% vs benchmark 15%",
            "Sector concentration risk: top 2 sectors = 55% of portfolio",
            "FII selling in financials for 3rd consecutive month",
        ],
        "risk_weights": {"low": 0.2, "medium": 0.5, "high": 0.25, "critical": 0.05},
    },
    "analysis_macro": {
        "name": "Macro Analysis",
        "drivers_pool": [
            "RBI repo rate steady at 6.0% — rate cut cycle expected Q3",
            "CPI inflation at 4.8% — within RBI comfort zone",
            "INR/USD at 84.5 — stable with RBI intervention",
            "FII flows positive for 2nd month at Rs 8,500 Cr",
            "India GDP growth at 6.8% — resilient domestic demand",
            "US Fed rate cuts expected — positive for EM flows",
            "GST collections at Rs 1.87L Cr — economic momentum strong",
            "Crude oil at $78/bbl — manageable for current account",
            "10Y G-Sec yield at 7.05% — flattening yield curve",
            "PMI manufacturing at 58.3 — expansion territory",
        ],
        "flags_pool": [
            "Geopolitical tensions could trigger risk-off in EM markets",
            "Monsoon forecast below normal — FMCG and auto demand risk",
            "Global recession probability at 25% — monitor leading indicators",
        ],
        "risk_weights": {"low": 0.35, "medium": 0.45, "high": 0.15, "critical": 0.05},
    },
    "analysis_sentiment": {
        "name": "Sentiment Analysis",
        "drivers_pool": [
            "Positive analyst upgrades for HDFC Bank post merger integration",
            "Institutional accumulation seen in Reliance — bulk deal activity",
            "Market breadth positive — 70% stocks above 50 DMA",
            "FII/DII flow divergence narrowing — bullish signal",
            "Nifty VIX at 13.5 — low volatility supports risk-on positioning",
            "Earnings surprise ratio at 1.8x — more beats than misses",
            "Insider buying signal in IT names post correction",
            "Put-call ratio at 1.2 — moderately bullish sentiment",
            "Mutual fund SIP flows at all-time high of Rs 21,000 Cr/month",
            "Corporate buyback announcements up 40% YoY",
        ],
        "flags_pool": [
            "Extreme bullishness in small-cap segment — contrarian caution",
            "IPO pipeline heavy this quarter — supply pressure on secondary market",
            "Retail participation at all-time high — potential froth indicator",
        ],
        "risk_weights": {"low": 0.3, "medium": 0.45, "high": 0.2, "critical": 0.05},
    },
    "analysis_unlisted_equity": {
        "name": "Unlisted Equity Specialist",
        "drivers_pool": [
            "Last funding round at Rs 450 Cr valuation — 8x revenue multiple",
            "IPO filing expected within 12-18 months",
            "Revenue growing at 40% CAGR — path to profitability visible",
            "Grey market premium at 25% — positive sentiment",
        ],
        "flags_pool": [
            "LIQUIDITY RISK: No exchange-traded market — exit timeline uncertain",
            "Information asymmetry: limited public disclosure available",
            "Lock-in period of 3+ years — investor suitability concern",
        ],
        "risk_weights": {"low": 0.05, "medium": 0.3, "high": 0.5, "critical": 0.15},
    },
    "analysis_pms_aif": {
        "name": "PMS/AIF Specialist",
        "drivers_pool": [
            "Fund manager 15-year track record with 18% CAGR net of fees",
            "AUM at Rs 8,000 Cr — optimal size for mid-cap strategy",
            "Sharpe ratio of 1.4 over 5 years — strong risk-adjusted returns",
            "Total expense ratio of 2.5% including performance fee",
        ],
        "flags_pool": [
            "FEE DRAG: 2.5% TER reduces net returns significantly over long term",
            "Lock-in period of 3 years — liquidity constraint",
            "Key person risk: strategy relies heavily on lead fund manager",
        ],
        "risk_weights": {"low": 0.1, "medium": 0.4, "high": 0.4, "critical": 0.1},
    },
}

# Profiles for governance agents
_GOVERNANCE_AGENT_PROFILES = {
    "allocation": {
        "name": "Allocation Reasoning",
        "drivers_pool": [
            "Top holding at 18% — within 20% single position limit",
            "Sector diversification adequate with 6 sectors represented",
            "Cash allocation at 5% — appropriate for current regime",
            "Mid-cap allocation at 22% — balanced growth exposure",
            "Defensive allocation at 30% — provides downside cushion",
            "Portfolio beta at 0.95 — near-market exposure",
            "Rebalancing needed: IT drifted to 28% from target 20%",
            "New position entry at 5% weight — appropriate sizing",
        ],
        "flags_pool": [
            "Portfolio concentrated in top 3 holdings (45%)",
            "No exposure to pharma/healthcare — diversification gap",
            "Rebalancing will trigger capital gains tax event",
        ],
        "actions_pool": [
            {"symbol": "RELIANCE", "action": "hold", "target_weight": 0.12, "rationale": "Core holding, weight appropriate"},
            {"symbol": "TCS", "action": "reduce", "target_weight": 0.08, "rationale": "IT overweight — reduce to target allocation"},
            {"symbol": "HDFCBANK", "action": "increase", "target_weight": 0.15, "rationale": "Banking sector tailwind, underweight vs target"},
            {"symbol": "SUNPHARMA", "action": "buy", "target_weight": 0.05, "rationale": "Diversification into pharma sector"},
        ],
    },
    "risk_interpretation": {
        "name": "Risk Interpretation",
        "drivers_pool": [
            "Portfolio VaR (95%) at 2.8% daily — within tolerance",
            "Maximum drawdown scenario: -18% in market stress test",
            "Correlation matrix shows 0.7 avg between top holdings",
            "Tail risk concentration in IT sector during global slowdown",
            "Volatility estimate at 16% annualized — moderate regime",
            "Liquidity risk low — all positions in Nifty 500 constituents",
        ],
        "flags_pool": [
            "Risk score above investor max_volatility threshold for 2 positions",
            "Concentration risk: correlated positions amplify drawdown",
            "Regime shift probability elevated — increase monitoring frequency",
        ],
    },
    "review": {
        "name": "Review & Explanation",
        "drivers_pool": [
            "Allocation and Risk agents agree on moderate risk assessment",
            "Analysis layer confidence at 0.72 supports the proposed actions",
            "Fundamental and technical signals aligned for banking overweight",
            "Macro environment supportive of current positioning",
            "Sentiment indicators confirm institutional buying pattern",
        ],
        "flags_pool": [
            "Minor disagreement: Technical agent flags overbought RSI while Fundamental sees value",
            "Sectoral analysis flags concentration risk not fully addressed by Allocation agent",
        ],
    },
}


def _pick_risk(rng: random.Random, weights: dict[str, float]) -> str:
    levels = list(weights.keys())
    w = list(weights.values())
    return rng.choices(levels, weights=w, k=1)[0]


def _mock_agent_output(prompt: str, rng: random.Random) -> dict[str, Any]:
    """Generate a realistic AgentOutput based on agent type detected in prompt."""
    symbols = _extract_symbols(prompt)

    # Detect which agent this is for
    agent_id = ""
    agent_name = ""
    profile = None

    for aid, prof in {**_ANALYSIS_AGENT_PROFILES, **_GOVERNANCE_AGENT_PROFILES}.items():
        if prof["name"].lower() in prompt.lower() or aid in prompt.lower():
            agent_id = aid
            agent_name = prof["name"]
            profile = prof
            break

    if profile is None:
        # Fallback for unknown agents
        return {
            "agent_id": "unknown",
            "agent_name": "Unknown Agent",
            "risk_level": "medium",
            "confidence": 0.5,
            "drivers": ["Insufficient context for analysis"],
            "proposed_actions": [],
            "reasoning_summary": "Mock agent could not determine context.",
            "flags": [],
        }

    risk_weights = profile.get("risk_weights", {"low": 0.25, "medium": 0.5, "high": 0.2, "critical": 0.05})
    risk_level = _pick_risk(rng, risk_weights)
    confidence = round(rng.uniform(0.55, 0.92), 2)

    # Pick drivers and flags
    n_drivers = rng.randint(3, min(5, len(profile["drivers_pool"])))
    drivers = rng.sample(profile["drivers_pool"], n_drivers)

    n_flags = rng.randint(0, min(2, len(profile.get("flags_pool", []))))
    flags = rng.sample(profile.get("flags_pool", []), n_flags) if n_flags > 0 else []

    # Actions — only some agents propose actions
    actions = []
    if "actions_pool" in profile:
        n_actions = rng.randint(1, min(3, len(profile["actions_pool"])))
        actions = rng.sample(profile["actions_pool"], n_actions)
    elif symbols and agent_id.startswith("analysis_"):
        # Analysis agents sometimes propose actions
        action_types = ["buy", "sell", "hold", "reduce", "increase"]
        for sym in symbols[:rng.randint(1, 2)]:
            actions.append({
                "symbol": sym,
                "action": rng.choice(action_types),
                "target_weight": round(rng.uniform(0.03, 0.15), 3),
                "rationale": f"Based on {agent_name.lower()} assessment of {sym}",
            })

    # Build reasoning summary
    risk_desc = {"low": "favorable", "medium": "moderate", "high": "elevated", "critical": "critical"}
    reasoning = (
        f"{agent_name} assessment indicates {risk_desc[risk_level]} risk with "
        f"{confidence*100:.0f}% confidence. "
        f"Key factors: {'; '.join(drivers[:2])}. "
        + (f"Flags raised: {'; '.join(flags[:1])}." if flags else "No critical flags.")
    )

    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "risk_level": risk_level,
        "confidence": confidence,
        "drivers": drivers,
        "proposed_actions": actions,
        "reasoning_summary": reasoning,
        "flags": flags,
    }


def _mock_analysis_envelope(prompt: str, rng: random.Random) -> dict[str, Any]:
    """Generate a realistic AnalysisEnvelope for synthesis."""
    symbols = _extract_symbols(prompt)
    intent = _extract_intent_type(prompt)

    risk_level = rng.choice(["low", "medium", "medium", "high"])
    confidence = round(rng.uniform(0.60, 0.88), 2)

    key_drivers = rng.sample([
        "Strong fundamental underpinning — earnings growth across top holdings",
        "Technical momentum supportive — majority of holdings above key moving averages",
        "Macro environment benign — rate cut cycle expected to begin Q3 2026",
        "Sectoral rotation favoring financials and infrastructure plays",
        "Sentiment positive — institutional accumulation and healthy breadth",
        "Valuation comfort — portfolio P/E at discount to Nifty 50",
        "Risk metrics within investor tolerance — VaR and drawdown acceptable",
        "Credit growth at multi-year high — positive for banking heavy portfolios",
    ], k=rng.randint(3, 5))

    conflicts = []
    if rng.random() > 0.4:
        conflicts = rng.sample([
            "Technical agent flags overbought conditions while Fundamental sees continued value",
            "Macro agent cautious on global slowdown vs Sentiment agent seeing domestic resilience",
            "Sectoral analysis warns of IT overweight while Fundamental rates IT holdings as undervalued",
            "Sentiment flags retail froth while Technical shows healthy accumulation pattern",
        ], k=rng.randint(1, 2))

    flags = []
    if rng.random() > 0.3:
        flags = rng.sample([
            "Quarterly earnings season approaching — elevated event risk for 2 weeks",
            "Monsoon forecast below normal — monitor FMCG and auto exposure",
            "FII flow reversal risk if US yields spike above 4.5%",
            "Portfolio sector concentration above 35% in financials",
        ], k=rng.randint(1, 2))

    action_types = ["hold", "increase", "reduce", "buy"]
    actions = []
    for sym in symbols[:rng.randint(2, min(4, len(symbols)))]:
        actions.append({
            "symbol": sym,
            "action": rng.choice(action_types),
            "target_weight": round(rng.uniform(0.05, 0.15), 3),
            "rationale": f"Consensus view across analysis agents for {sym}",
        })

    risk_desc = {"low": "favorable", "medium": "moderate", "high": "elevated"}
    synthesis = (
        f"Multi-lens analysis of {len(symbols)} securities for {intent} intent indicates "
        f"{risk_desc.get(risk_level, 'moderate')} risk environment with {confidence*100:.0f}% overall confidence. "
        f"{key_drivers[0]}. {key_drivers[1]}. "
        + (f"Notable conflict: {conflicts[0]}. " if conflicts else "")
        + f"Overall, the portfolio is {'well-positioned' if risk_level in ('low', 'medium') else 'requiring attention'} "
        f"for the current market regime."
    )

    return {
        "synthesis_summary": synthesis,
        "overall_confidence": confidence,
        "overall_risk_level": risk_level,
        "key_drivers": key_drivers,
        "conflicts": conflicts,
        "flags": flags,
        "recommended_actions": actions,
        "classification_reasoning": f"Intent '{intent}' with {len(symbols)} symbols analyzed across multiple lenses.",
    }
