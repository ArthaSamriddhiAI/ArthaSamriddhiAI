"""Provider registry — factory for LLM providers."""

from __future__ import annotations

from artha.config import LLMProviderName, settings
from artha.llm.base import LLMProvider

_providers: dict[str, LLMProvider] = {}


def register_provider(name: str, provider: LLMProvider) -> None:
    _providers[name] = provider


def get_provider(name: str | None = None) -> LLMProvider:
    provider_name = name or settings.default_llm_provider.value
    if provider_name in _providers:
        return _providers[provider_name]

    # Lazy initialization
    if provider_name == LLMProviderName.ANTHROPIC.value:
        from artha.llm.providers.anthropic import AnthropicProvider
        provider = AnthropicProvider(api_key=settings.anthropic_api_key)
    elif provider_name == LLMProviderName.OPENAI.value:
        from artha.llm.providers.openai import OpenAIProvider
        provider = OpenAIProvider(api_key=settings.openai_api_key)
    elif provider_name == LLMProviderName.MISTRAL.value:
        from artha.llm.providers.mistral import MistralProvider
        provider = MistralProvider(api_key=settings.mistral_api_key)
    elif provider_name == LLMProviderName.MOCK.value:
        from artha.llm.providers.mock import MockProvider
        provider = MockProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")

    _providers[provider_name] = provider
    return provider


def get_smart_router() -> LLMProvider:
    """Get the SmartLLMRouter — Mistral default, Claude for complex tasks.

    Returns a drop-in LLMProvider that routes based on provider_hint in LLMRequest.
    Use this instead of get_provider() when you want intelligent routing.
    """
    from artha.llm.smart_router import get_smart_router as _get
    return _get()
