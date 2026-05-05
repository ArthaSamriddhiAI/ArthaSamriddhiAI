"""Process-wide adapter registry (FR Entry 10.1 §3.1).

Adapters register at application startup. The registry exposes:

- :func:`register_adapter` — explicit registration call.
- :func:`get_adapter` — lookup by source_identifier (raises if missing).
- :func:`list_adapters` — iterate over all registered adapters.
- :func:`reset_registry` — test-only helper to drop registered adapters
  between cases.

Cluster 3's chunk 3.2 registers the :class:`JSONFixtureAdapter` once at
application startup; cluster 17 will register live adapters alongside.
"""

from __future__ import annotations

from artha.api_v2.d0.adapter_base import D0Adapter


class AdapterNotRegisteredError(KeyError):
    """Raised when ``get_adapter`` is called for an unknown source id."""


_registry: dict[str, D0Adapter] = {}


def register_adapter(adapter: D0Adapter) -> None:
    """Register an adapter under its ``source_identifier``.

    Re-registering the same source_identifier replaces the previous entry
    (this is intentional so tests can swap in stub adapters without
    leaking state across cases).
    """
    _registry[adapter.source_identifier] = adapter


def get_adapter(source_identifier: str) -> D0Adapter:
    """Return the adapter registered under ``source_identifier``.

    Raises :class:`AdapterNotRegisteredError` when no adapter is registered.
    """
    try:
        return _registry[source_identifier]
    except KeyError as exc:
        raise AdapterNotRegisteredError(
            f"No adapter registered for source_identifier={source_identifier!r}. "
            f"Registered: {sorted(_registry.keys())}"
        ) from exc


def list_adapters() -> list[D0Adapter]:
    """Return all registered adapters, sorted by source_identifier."""
    return [
        _registry[key]
        for key in sorted(_registry.keys())
    ]


def reset_registry() -> None:
    """Test-only helper: drop all registered adapters."""
    _registry.clear()
