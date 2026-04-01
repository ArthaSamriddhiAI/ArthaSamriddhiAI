"""Anthropic Claude LLM provider — uses tool_use for structured output."""

from __future__ import annotations

import json
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from artha.common.errors import LLMError
from artha.llm.models import LLMRequest, LLMResponse, LLMUsage

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class AnthropicProvider:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return "anthropic"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        system_msg = ""
        messages = []
        for m in request.messages:
            if m.role == "system":
                system_msg = m.content
            else:
                messages.append({"role": m.role, "content": m.content})

        try:
            response = await self._client.messages.create(
                model=request.model or self._model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=system_msg or anthropic.NOT_GIVEN,
                messages=messages,
            )
        except anthropic.APIError as e:
            raise LLMError("anthropic", str(e)) from e

        content = response.content[0].text if response.content else ""
        return LLMResponse(
            content=content,
            model=response.model,
            usage=LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
        )

    async def complete_structured(
        self, request: LLMRequest, output_type: type[T]
    ) -> T:
        schema = output_type.model_json_schema()
        tool = {
            "name": "structured_output",
            "description": f"Return a structured {output_type.__name__} response.",
            "input_schema": schema,
        }

        system_msg = ""
        messages = []
        for m in request.messages:
            if m.role == "system":
                system_msg = m.content
            else:
                messages.append({"role": m.role, "content": m.content})

        # Append instruction to use the tool
        if messages:
            messages[-1]["content"] += (
                "\n\nYou MUST use the structured_output tool to provide your response."
            )

        try:
            response = await self._client.messages.create(
                model=request.model or self._model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=system_msg or anthropic.NOT_GIVEN,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "tool", "name": "structured_output"},
            )
        except anthropic.APIError as e:
            raise LLMError("anthropic", str(e)) from e

        for block in response.content:
            if block.type == "tool_use" and block.name == "structured_output":
                return output_type.model_validate(block.input)

        raise LLMError("anthropic", "No structured output in response")
