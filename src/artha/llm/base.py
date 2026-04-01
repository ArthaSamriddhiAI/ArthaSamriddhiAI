"""LLM provider protocol — the contract all providers must implement."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from artha.llm.models import LLMRequest, LLMResponse

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Protocol for LLM providers.

    Two methods:
    - complete(): free-form text response
    - complete_structured(): returns a validated Pydantic model instance
    """

    @property
    def name(self) -> str: ...

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def complete_structured(
        self, request: LLMRequest, output_type: type[T]
    ) -> T: ...
