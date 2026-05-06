"""M0 stitcher — renders markdown templates (FR Entry 20.2 §3.4).

Three templates ship in cluster 5.2 under ``config/stitcher/``:

- ``case_detail.md`` — the per-case detail page body that the case
  detail UI shows (chunk 5.5).
- ``health_report.md`` — the diagnostic-mode health report body.
- ``briefing_note.md`` — the briefing-mode meeting prep body.

The renderer is intentionally minimal: ``{{ key }}`` substitution +
optional ``{% for x in xs %}...{% endfor %}`` loop syntax. Anything more
sophisticated (Jinja2, sandboxing) lives in a later cluster. We do
**not** evaluate expressions — values are looked up by exact key name
in the supplied context dict; missing keys render as
``[unknown:key]`` so an output bug surfaces in review rather than
silently rendering an empty string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_STITCHER_DIR = (
    Path(__file__).resolve().parents[5] / "config" / "stitcher"
)

_STITCHER_DIR_OVERRIDE: Path | None = None

KNOWN_TEMPLATES: frozenset[str] = frozenset({
    "case_detail",
    "health_report",
    "briefing_note",
})


def get_stitcher_dir() -> Path:
    """Return the directory currently used by the loader."""
    return _STITCHER_DIR_OVERRIDE if _STITCHER_DIR_OVERRIDE is not None else _DEFAULT_STITCHER_DIR


def set_stitcher_dir(path: Path | None) -> None:
    """Test-only: override the stitcher template directory."""
    global _STITCHER_DIR_OVERRIDE
    _STITCHER_DIR_OVERRIDE = path
    reset_cache()


# Patterns
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")
_FOR_RE = re.compile(
    r"\{%\s*for\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+in\s+"
    r"([a-zA-Z_][a-zA-Z0-9_.]*)\s*%\}(.*?)\{%\s*endfor\s*%\}",
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StitcherError(Exception):
    """Base for stitcher errors."""


class StitcherTemplateMissingError(StitcherError):
    """Raised when a template name has no on-disk file."""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    name: str
    body: str
    source_path: Path


_cache: dict[str, Template] = {}


def reset_cache() -> None:
    """Drop the cache; used by tests + dev hot-reload."""
    _cache.clear()


def load_template(name: str) -> Template:
    """Read a template by short name (no extension), cached."""
    if name not in KNOWN_TEMPLATES:
        raise StitcherError(
            f"Unknown stitcher template {name!r}; expected one of "
            f"{sorted(KNOWN_TEMPLATES)}.",
        )
    cached = _cache.get(name)
    if cached is not None:
        return cached

    path = get_stitcher_dir() / f"{name}.md"
    if not path.exists():
        raise StitcherTemplateMissingError(
            f"Stitcher template {name!r} not found at {path}.",
        )
    body = path.read_text(encoding="utf-8")
    tpl = Template(name=name, body=body, source_path=path)
    _cache[name] = tpl
    return tpl


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def _resolve(context: dict[str, Any], key: str) -> Any:
    """Look up ``key`` in ``context`` with dot-traversal (a.b.c)."""
    cursor: Any = context
    for part in key.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    return cursor


def _render_vars(text: str, context: dict[str, Any]) -> str:
    """Substitute every ``{{ key }}`` with its context value."""

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        val = _resolve(context, key)
        if val is None:
            return f"[unknown:{key}]"
        return str(val)

    return _VAR_RE.sub(repl, text)


def _render_loops(text: str, context: dict[str, Any]) -> str:
    """Expand every ``{% for x in xs %}...{% endfor %}`` block.

    Re-runs until no loop syntax remains so nested iterables work the
    natural way.
    """
    out = text
    while True:
        match = _FOR_RE.search(out)
        if match is None:
            return out
        var_name, list_key, body = match.group(1), match.group(2), match.group(3)
        items = _resolve(context, list_key)
        if items is None or not hasattr(items, "__iter__"):
            replacement = f"[unknown:{list_key}]"
        else:
            pieces: list[str] = []
            for item in items:
                local_ctx = {**context, var_name: item}
                # Render vars (and any nested loops) inside body for this item.
                rendered = _render_vars(body, local_ctx)
                rendered = _render_loops(rendered, local_ctx)
                pieces.append(rendered)
            replacement = "".join(pieces)
        out = out[: match.start()] + replacement + out[match.end():]


def render(name: str, context: dict[str, Any]) -> str:
    """Render template ``name`` against ``context``.

    Loops are expanded first so loop bodies that contain ``{{ var }}``
    references see the per-iteration context.
    """
    tpl = load_template(name)
    expanded = _render_loops(tpl.body, context)
    return _render_vars(expanded, context)


__all__ = [
    "KNOWN_TEMPLATES",
    "StitcherError",
    "StitcherTemplateMissingError",
    "Template",
    "get_stitcher_dir",
    "load_template",
    "render",
    "reset_cache",
    "set_stitcher_dir",
]
