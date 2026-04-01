"""Deterministic mock LLM provider for testing."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel

from artha.llm.models import LLMRequest, LLMResponse, LLMUsage

T = TypeVar("T", bound=BaseModel)


class MockProvider:
    """Returns deterministic responses. For structured output, generates valid
    default instances of the requested Pydantic model."""

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
