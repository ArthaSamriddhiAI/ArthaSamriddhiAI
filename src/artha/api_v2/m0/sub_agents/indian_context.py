"""M0 indian_context — YAML knowledge-store lookup (FR Entry 20.2 §3.3).

Six small YAML files under ``config/indian_context/`` carry the
Indian-specific reference data the evidence + synthesis layers need:

- ``tax_matrix.yaml`` — STCG / LTCG rates by asset class + holding period
  (FR 9.2 §3).
- ``structure_matrix.yaml`` — vehicle structure rules: PMS minimum
  ticket, AIF cat-I/II/III, mutual-fund minimums, demat requirements.
- ``sebi_boundaries.yaml`` — SEBI-prescribed concentration / single-issuer
  / sector caps that the governance gates check against.
- ``gift_city_routing.yaml`` — IFSC GIFT-City routing flags for
  international assets.
- ``demat_mechanics.yaml`` — settlement T+N + demat-tagging rules.
- ``regulatory_changelog.yaml`` — recent SEBI / RBI / FEMA changes the
  evidence agents should be aware of.

Loader caches the parsed dicts process-wide; tests use
:func:`reset_cache` to flush.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_CONTEXT_DIR = (
    Path(__file__).resolve().parents[5] / "config" / "indian_context"
)

_CONTEXT_DIR_OVERRIDE: Path | None = None

KNOWN_KNOWLEDGE_STORES: frozenset[str] = frozenset({
    "tax_matrix",
    "structure_matrix",
    "sebi_boundaries",
    "gift_city_routing",
    "demat_mechanics",
    "regulatory_changelog",
})


def get_context_dir() -> Path:
    """Return the directory currently used by the loader."""
    return _CONTEXT_DIR_OVERRIDE if _CONTEXT_DIR_OVERRIDE is not None else _DEFAULT_CONTEXT_DIR


def set_context_dir(path: Path | None) -> None:
    """Test-only: override the indian_context directory."""
    global _CONTEXT_DIR_OVERRIDE
    _CONTEXT_DIR_OVERRIDE = path
    reset_cache()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IndianContextError(Exception):
    """Base for indian_context loader errors."""


class IndianContextMissingError(IndianContextError):
    """Raised when a knowledge-store name has no on-disk YAML."""


class IndianContextParseError(IndianContextError):
    """Raised on malformed YAML."""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnowledgeStore:
    """Parsed knowledge-store: name + payload + source path."""

    name: str
    payload: dict[str, Any]
    source_path: Path


_cache: dict[str, KnowledgeStore] = {}


def reset_cache() -> None:
    """Drop the cache; tests + dev hot-reload."""
    _cache.clear()


def load_knowledge_store(name: str) -> KnowledgeStore:
    """Load and cache a knowledge store by short name (no extension)."""
    if name not in KNOWN_KNOWLEDGE_STORES:
        raise IndianContextError(
            f"Unknown knowledge store {name!r}; expected one of "
            f"{sorted(KNOWN_KNOWLEDGE_STORES)}.",
        )
    cached = _cache.get(name)
    if cached is not None:
        return cached

    path = get_context_dir() / f"{name}.yaml"
    if not path.exists():
        raise IndianContextMissingError(
            f"Indian-context knowledge store {name!r} not found at {path}.",
        )
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise IndianContextParseError(
            f"Indian-context store {name!r} at {path} has malformed YAML: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise IndianContextParseError(
            f"Indian-context store {name!r} at {path} root is not a mapping.",
        )

    store = KnowledgeStore(name=name, payload=payload, source_path=path)
    _cache[name] = store
    return store


def lookup(name: str, *path_keys: str, default: Any = None) -> Any:
    """Walk ``path_keys`` into a knowledge store; return value or default.

    Convenience: ``lookup("tax_matrix", "equity", "ltcg_rate_pct")`` is
    equivalent to ``load_knowledge_store("tax_matrix").payload["equity"]
    ["ltcg_rate_pct"]`` with KeyError → default.
    """
    store = load_knowledge_store(name)
    cursor: Any = store.payload
    for k in path_keys:
        if not isinstance(cursor, dict) or k not in cursor:
            return default
        cursor = cursor[k]
    return cursor


__all__ = [
    "KNOWN_KNOWLEDGE_STORES",
    "IndianContextError",
    "IndianContextMissingError",
    "IndianContextParseError",
    "KnowledgeStore",
    "get_context_dir",
    "load_knowledge_store",
    "lookup",
    "reset_cache",
    "set_context_dir",
]
