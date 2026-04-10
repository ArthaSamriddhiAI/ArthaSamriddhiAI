"""Pydantic models for LLM request/response."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    temperature: float = 0.0
    max_tokens: int = 4096
    model: str | None = None  # Provider-specific override
    provider_hint: str | None = None  # "claude" to route to Anthropic, None = default (Mistral)


class LLMResponse(BaseModel):
    content: str
    model: str
    usage: LLMUsage


class LLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
