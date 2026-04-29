"""Deprecation framework for the legacy → canonical migration (§16 deployment plan).

Pass 20 marks pre-consolidation modules as deprecated without removing them.
Production deployments stay green; new code paths bind to the canonical
schemas; legacy entry points emit a structured `DeprecationWarning` on use
so callers see exactly which symbol to migrate to and when removal is
scheduled.

Design:

  * `@deprecated(canonical_replacement=..., removed_in_pass=..., reason=...)`
    decorator wraps a callable (function, method, or class) and emits a
    warning on the first call within the process. The warning text follows
    a single template so log scrapers can pattern-match.
  * `mark_module_deprecated(__name__, ...)` emits a warning on import.
    Useful for whole-module deprecations (e.g. `artha.decision`).
  * `DEPRECATION_MANIFEST` is the single source of truth — every legacy
    symbol that's been marked carries an entry. Tests assert the manifest
    matches reality so we don't silently drift.

Removal cadence (§15.13.7): legacy symbols stay through one minor release
after deprecation, then are removed in the next major bump. The
`removed_in_pass` field tells callers exactly when to migrate by.
"""

from __future__ import annotations

import functools
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class DeprecationManifestEntry:
    """One entry in the deprecation manifest.

    `module_path` is the dotted import path of the deprecated symbol.
    `canonical_replacement` is the dotted path callers should migrate to;
    use the empty string when no direct replacement exists (e.g. a whole
    module being retired).
    `removed_in_pass` is the pass number at which removal lands.
    """

    module_path: str
    canonical_replacement: str
    removed_in_pass: int
    reason: str = ""
    kind: str = "callable"  # "callable" | "module" | "class"


# Process-wide registry. New entries are appended via `mark_*` calls below.
DEPRECATION_MANIFEST: list[DeprecationManifestEntry] = []

# Track first-use to avoid spamming logs when deprecated callables are
# invoked in a hot loop.
_WARNED_ONCE: set[str] = set()


def _format_warning(entry: DeprecationManifestEntry) -> str:
    parts = [
        f"{entry.module_path} is deprecated",
        f"removed in Pass {entry.removed_in_pass}",
    ]
    if entry.canonical_replacement:
        parts.append(f"use {entry.canonical_replacement} instead")
    if entry.reason:
        parts.append(entry.reason)
    return ". ".join(parts) + "."


def _record_and_warn(entry: DeprecationManifestEntry, *, stacklevel: int = 3) -> None:
    """Append to manifest (once) + emit a `DeprecationWarning` (once per process)."""
    if entry not in DEPRECATION_MANIFEST:
        DEPRECATION_MANIFEST.append(entry)
    if entry.module_path in _WARNED_ONCE:
        return
    _WARNED_ONCE.add(entry.module_path)
    warnings.warn(_format_warning(entry), DeprecationWarning, stacklevel=stacklevel)


def deprecated(
    *,
    canonical_replacement: str = "",
    removed_in_pass: int,
    reason: str = "",
    kind: str = "callable",
) -> Callable[[F], F]:
    """Decorator for deprecated callables / classes.

    Emits a `DeprecationWarning` on first invocation, and registers the
    symbol in `DEPRECATION_MANIFEST`. The decorator preserves the wrapped
    callable's signature (for both functions and class constructors) so
    static type-checkers + introspection still work.

    Example:

        @deprecated(
            canonical_replacement="artha.canonical.investor.InvestorContextProfile",
            removed_in_pass=21,
            reason="legacy 5-tier RiskCategory taxonomy",
        )
        def get_legacy_profile(): ...
    """

    def _wrap(target: F) -> F:
        module_path = f"{target.__module__}.{target.__qualname__}"
        entry = DeprecationManifestEntry(
            module_path=module_path,
            canonical_replacement=canonical_replacement,
            removed_in_pass=removed_in_pass,
            reason=reason,
            kind=kind,
        )

        if isinstance(target, type):
            # Wrap a class: warn on instantiation, preserve everything else.
            original_init = target.__init__

            @functools.wraps(original_init)
            def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
                _record_and_warn(entry)
                original_init(self, *args, **kwargs)

            target.__init__ = new_init  # type: ignore[method-assign]
            # Also register in the manifest right away so static introspection
            # surfaces the deprecation without requiring instantiation.
            if entry not in DEPRECATION_MANIFEST:
                DEPRECATION_MANIFEST.append(entry)
            return target  # type: ignore[return-value]

        @functools.wraps(target)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _record_and_warn(entry)
            return target(*args, **kwargs)

        # Pre-register so listings work pre-call too.
        if entry not in DEPRECATION_MANIFEST:
            DEPRECATION_MANIFEST.append(entry)
        return wrapper  # type: ignore[return-value]

    return _wrap


def mark_module_deprecated(
    module_path: str,
    *,
    canonical_replacement: str = "",
    removed_in_pass: int,
    reason: str = "",
) -> None:
    """Emit a module-level `DeprecationWarning` (called from a module's
    `__init__.py` or top of a `.py` file).

    Use this for whole-package deprecations where every symbol below is
    being retired together (e.g. `artha.decision`).
    """
    entry = DeprecationManifestEntry(
        module_path=module_path,
        canonical_replacement=canonical_replacement,
        removed_in_pass=removed_in_pass,
        reason=reason,
        kind="module",
    )
    _record_and_warn(entry, stacklevel=4)


def manifest() -> list[DeprecationManifestEntry]:
    """Return a copy of the current deprecation manifest."""
    return list(DEPRECATION_MANIFEST)


def reset_manifest_for_tests() -> None:
    """Test-only: wipe the warned-once set + manifest so tests can re-trigger.

    Tests that assert deprecation behaviour should call this in setUp /
    fixtures so warnings fire fresh per test. Production code never calls
    this.
    """
    DEPRECATION_MANIFEST.clear()
    _WARNED_ONCE.clear()


__all__ = [
    "DEPRECATION_MANIFEST",
    "DeprecationManifestEntry",
    "deprecated",
    "manifest",
    "mark_module_deprecated",
    "reset_manifest_for_tests",
]
