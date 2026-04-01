"""OpenAI LLM provider — uses function_calling for structured output."""

from __future__ import annotations

import json
from typing import TypeVar

import openai
from pydantic import BaseModel

from artha.common.errors import LLMError
from artha.llm.models import LLMRequest, LLMResponse, LLMUsage

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return "openai"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        try:
            response = await self._client.chat.completions.create(
                model=request.model or self._model,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
        except openai.APIError as e:
            raise LLMError("openai", str(e)) from e

        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage=LLMUsage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            ),
        )

    async def complete_structured(
        self, request: LLMRequest, output_type: type[T]
    ) -> T:
        schema = output_type.model_json_schema()
        tool = {
            "type": "function",
            "function": {
                "name": "structured_output",
                "description": f"Return a structured {output_type.__name__} response.",
                "parameters": schema,
            },
        }

        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        try:
            response = await self._client.chat.completions.create(
                model=request.model or self._model,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "structured_output"}},
            )
        except openai.APIError as e:
            raise LLMError("openai", str(e)) from e

        choice = response.choices[0]
        if choice.message.tool_calls:
            args_str = choice.message.tool_calls[0].function.arguments
            return output_type.model_validate_json(args_str)

        raise LLMError("openai", "No structured output in response")
