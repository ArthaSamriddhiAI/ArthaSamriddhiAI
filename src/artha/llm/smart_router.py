"""Smart LLM Router — Mistral default, Claude for complex tasks.

Routes based on provider_hint in LLMRequest:
- provider_hint="claude" → Anthropic (for synthesis, CPR, ISE)
- provider_hint=None → Mistral (for everything else)

Falls back to Mistral if Claude key is not configured.
Optimizes Claude token usage via context condensation.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from artha.llm.models import LLMMessage, LLMRequest, LLMResponse, LLMUsage

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)


class SmartLLMRouter:
    """Drop-in LLMProvider that routes between Mistral (default) and Claude (complex)."""

    def __init__(self) -> None:
        self._default_provider = None  # Lazy: Mistral
        self._claude_provider = None  # Lazy: Anthropic
        self._claude_available = None  # Unknown until first check

    @property
    def name(self) -> str:
        return "smart_router"

    def _get_default(self):
        """Lazy init for default provider (Mistral)."""
        if self._default_provider is None:
            from artha.llm.registry import get_provider
            self._default_provider = get_provider()  # Uses DEFAULT_LLM_PROVIDER from config
        return self._default_provider

    def _get_claude(self):
        """Lazy init for Claude provider. Returns None if not configured."""
        if self._claude_available is False:
            return None

        if self._claude_provider is None:
            from artha.config import settings
            if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("sk-ant-..."):
                logger.info("Anthropic API key not configured. Claude routing disabled, falling back to default.")
                self._claude_available = False
                return None

            try:
                from artha.llm.providers.anthropic import AnthropicProvider
                self._claude_provider = AnthropicProvider(api_key=settings.anthropic_api_key)
                self._claude_available = True
                logger.info("Claude provider initialized for complex task routing.")
            except Exception as e:
                logger.warning(f"Failed to initialize Claude provider: {e}. Falling back to default.")
                self._claude_available = False
                return None

        return self._claude_provider

    def _select_provider(self, request: LLMRequest):
        """Select provider based on provider_hint."""
        if request.provider_hint == "claude":
            claude = self._get_claude()
            if claude is not None:
                logger.debug("Routing to Claude (provider_hint=claude)")
                return claude
            else:
                logger.debug("Claude requested but unavailable, falling back to default")

        return self._get_default()

    def _optimize_for_claude(self, request: LLMRequest) -> LLMRequest:
        """Optimize request for Claude to minimize token consumption.

        1. Trim system prompt: remove version/metadata lines
        2. Cap max_tokens based on task type
        3. Condense context in user messages
        """
        optimized_messages = []
        for msg in request.messages:
            content = msg.content

            if msg.role == "system":
                # Strip version lines and metadata that don't affect reasoning
                lines = content.split("\n")
                filtered = [
                    line for line in lines
                    if not line.strip().startswith("## Version")
                    and not line.strip().startswith("1.0.0")
                    and not line.strip().startswith("2.0.0")
                ]
                content = "\n".join(filtered)

            elif msg.role == "user":
                # Truncate very long JSON blocks to reduce tokens
                # Keep first 6000 chars of user content if over 8000
                if len(content) > 8000:
                    content = content[:6000] + "\n\n[... context truncated for token efficiency ...]\n"

            optimized_messages.append(LLMMessage(role=msg.role, content=content))

        # Cap max_tokens for Claude
        max_tokens = min(request.max_tokens, 4096)

        return LLMRequest(
            messages=optimized_messages,
            temperature=request.temperature,
            max_tokens=max_tokens,
            model=request.model,
            provider_hint=request.provider_hint,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route and complete a free-form text request."""
        provider = self._select_provider(request)

        if request.provider_hint == "claude" and provider.name == "anthropic":
            request = self._optimize_for_claude(request)
            logger.info(f"Claude call: {len(request.messages)} messages, max_tokens={request.max_tokens}")

        response = await provider.complete(request)

        if provider.name == "anthropic":
            logger.info(
                f"Claude usage: in={response.usage.input_tokens}, out={response.usage.output_tokens}, "
                f"total={response.usage.input_tokens + response.usage.output_tokens}"
            )

        return response

    async def complete_structured(self, request: LLMRequest, output_type: type[T]) -> T:
        """Route and complete a structured output request."""
        provider = self._select_provider(request)

        if request.provider_hint == "claude" and provider.name == "anthropic":
            request = self._optimize_for_claude(request)
            logger.info(f"Claude structured call: {output_type.__name__}, max_tokens={request.max_tokens}")

        result = await provider.complete_structured(request, output_type)

        return result


# Singleton
_smart_router: SmartLLMRouter | None = None


def get_smart_router() -> SmartLLMRouter:
    """Get or create the global SmartLLMRouter instance."""
    global _smart_router
    if _smart_router is None:
        _smart_router = SmartLLMRouter()
    return _smart_router
