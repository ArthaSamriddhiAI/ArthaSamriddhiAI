"""Tests for LLM providers."""

from __future__ import annotations

import pytest

from pydantic import BaseModel, Field

from artha.llm.models import LLMMessage, LLMRequest
from artha.llm.providers.mock import MockProvider


class SampleOutput(BaseModel):
    risk_level: str = "medium"
    confidence: float = 0.5
    drivers: list[str] = Field(default_factory=list)


@pytest.mark.asyncio
async def test_mock_complete():
    provider = MockProvider()
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="Hello")]
    )
    response = await provider.complete(request)
    assert response.model == "mock"
    assert response.content.startswith("Mock response")


@pytest.mark.asyncio
async def test_mock_complete_with_registered_response():
    provider = MockProvider()
    provider.set_response("portfolio", "Rebalance recommended")
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="Analyze portfolio")]
    )
    response = await provider.complete(request)
    assert response.content == "Rebalance recommended"


@pytest.mark.asyncio
async def test_mock_structured_output():
    provider = MockProvider()
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="Analyze")]
    )
    output = await provider.complete_structured(request, SampleOutput)
    assert isinstance(output, SampleOutput)
    assert output.risk_level == "medium"


@pytest.mark.asyncio
async def test_mock_structured_with_override():
    provider = MockProvider()
    provider.set_structured_response("risk", {"risk_level": "high", "confidence": 0.9, "drivers": ["vol"]})
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="Assess risk")]
    )
    output = await provider.complete_structured(request, SampleOutput)
    assert output.risk_level == "high"
    assert output.confidence == 0.9
