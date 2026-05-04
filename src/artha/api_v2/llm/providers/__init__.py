"""SmartLLMRouter provider adapters — FR Entry 16.0 §3.

The adapter pattern lets the router stay agnostic of any single provider's
HTTP shape. Cluster 1 ships two adapters:

- :mod:`artha.api_v2.llm.providers.mistral` — chat completions endpoint with
  native ``response_format`` support.
- :mod:`artha.api_v2.llm.providers.claude` — Anthropic Messages API; JSON
  mode is prompt-driven (Anthropic doesn't expose a native parameter).

Adding a future provider (FR 16.0 §3.3) is purely additive: implement
:class:`ProviderAdapter`, register it in :data:`PROVIDER_REGISTRY`, surface
it in the settings UI.
"""

from __future__ import annotations

from artha.api_v2.llm.providers.base import (
    LLMCallRequest,
    LLMCallResponse,
    Message,
    ProviderAdapter,
    ProviderAuthError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
)
from artha.api_v2.llm.providers.claude import ClaudeAdapter
from artha.api_v2.llm.providers.mistral import MistralAdapter

# Provider name → adapter class. The router resolves the active provider from
# the DB config and instantiates the right adapter on each call.
PROVIDER_REGISTRY: dict[str, type[ProviderAdapter]] = {
    "mistral": MistralAdapter,
    "claude": ClaudeAdapter,
}

# Public list used by the schemas + settings UI radio group.
SUPPORTED_PROVIDERS: tuple[str, ...] = tuple(PROVIDER_REGISTRY.keys())


__all__ = [
    "LLMCallRequest",
    "LLMCallResponse",
    "Message",
    "PROVIDER_REGISTRY",
    "SUPPORTED_PROVIDERS",
    "ProviderAdapter",
    "ProviderAuthError",
    "ProviderError",
    "ProviderInvalidResponseError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderTransientError",
    "MistralAdapter",
    "ClaudeAdapter",
]
