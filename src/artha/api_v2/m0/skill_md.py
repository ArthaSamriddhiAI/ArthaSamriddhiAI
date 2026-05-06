"""skill.md loader + validator + hot-reloader (FR Entry 20.2 §10.3).

A *skill.md* file is the authoring surface for an agent's prompt and
invocation parameters. Each file is markdown with a YAML front-matter
header bracketed by ``---`` lines. The body below the front-matter is
the prompt template (or, for deterministic sub-agents, free-form notes).

Front-matter keys (FR 20.2 §10.3.1):

- ``agent_id`` — string, primary key, snake_case.
- ``skill_md_version`` — semver-ish string used in T1 telemetry.
- ``draft_version`` — int, increments on every edit.
- ``authored_in_cluster`` — int, cluster number that first authored.
- ``finalised_in_cluster`` — int | null, cluster that froze the wording.
- ``llm_model`` — string, e.g. ``claude-sonnet-4-5``,
  ``mistral-medium-3``, or ``deterministic`` for sub-agents that
  don't call an LLM.
- ``max_tokens`` — int.
- ``temperature`` — float in [0.0, 2.0].
- ``output_schema_ref`` — relative path under
  :data:`SKILL_DIR`, e.g. ``../schemas/m0_router_output.json``. The
  string is stored verbatim — resolution is deferred to chunk 5.4
  when the stub layer needs it.

Loader caches parsed files keyed by ``agent_id``. Calling
:func:`reload_skill` clears one entry and emits the
:data:`SKILL_MD_HOT_RELOADED` T1 event (gated by the ``ARTHA_SKILL_MD_HOT_RELOAD``
env var so production locks the cache).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Repo-relative directory that holds every skill.md file. Resolved to
#: an absolute :class:`Path` lazily so tests can monkeypatch
#: :data:`_SKILL_DIR_OVERRIDE` without recomputing imports.
_DEFAULT_SKILL_DIR = (
    Path(__file__).resolve().parents[4] / "config" / "skills"
)

_SKILL_DIR_OVERRIDE: Path | None = None


def get_skill_dir() -> Path:
    """Return the directory currently used by the loader.

    Tests override via :func:`set_skill_dir`. Default points to
    ``<repo_root>/config/skills/``.
    """
    return _SKILL_DIR_OVERRIDE if _SKILL_DIR_OVERRIDE is not None else _DEFAULT_SKILL_DIR


def set_skill_dir(path: Path | None) -> None:
    """Test-only: override the skill.md root directory."""
    global _SKILL_DIR_OVERRIDE
    _SKILL_DIR_OVERRIDE = path
    reset_cache()


#: Required front-matter keys per FR 20.2 §10.3.1.
_REQUIRED_KEYS: frozenset[str] = frozenset({
    "agent_id",
    "skill_md_version",
    "draft_version",
    "authored_in_cluster",
    "finalised_in_cluster",
    "llm_model",
    "max_tokens",
    "temperature",
    "output_schema_ref",
})

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)", re.DOTALL)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SkillMdError(Exception):
    """Base error for skill.md parsing / validation failures."""


class SkillMdMissingError(SkillMdError):
    """Raised when an agent_id has no on-disk skill.md."""


class SkillMdParseError(SkillMdError):
    """Raised when YAML front-matter is malformed or missing."""


class SkillMdValidationError(SkillMdError):
    """Raised when front-matter is parseable but missing required keys
    or has out-of-range values."""


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillMd:
    """Parsed skill.md file: front-matter + body."""

    agent_id: str
    skill_md_version: str
    draft_version: int
    authored_in_cluster: int
    finalised_in_cluster: int | None
    llm_model: str
    max_tokens: int
    temperature: float
    output_schema_ref: str
    body: str
    source_path: Path
    front_matter_raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cache + parser
# ---------------------------------------------------------------------------

_cache: dict[str, SkillMd] = {}


def reset_cache() -> None:
    """Drop the entire skill.md parse cache. Used by tests + hot-reload."""
    _cache.clear()


def _parse_text(text: str, *, source_path: Path) -> SkillMd:
    """Parse a single skill.md file's text into a :class:`SkillMd`.

    Raises :class:`SkillMdParseError` for malformed front-matter or
    :class:`SkillMdValidationError` for missing / invalid fields.
    """
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        raise SkillMdParseError(
            f"skill.md at {source_path} is missing the YAML front-matter "
            f"block (expected leading '---\\n...\\n---').",
        )
    raw_yaml, body = match.group(1), match.group(2)
    try:
        fm = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError as exc:
        raise SkillMdParseError(
            f"skill.md at {source_path} has malformed YAML front-matter: {exc}",
        ) from exc
    if not isinstance(fm, dict):
        raise SkillMdParseError(
            f"skill.md at {source_path} front-matter is not a mapping.",
        )

    missing = _REQUIRED_KEYS - set(fm)
    if missing:
        raise SkillMdValidationError(
            f"skill.md at {source_path} missing required keys: "
            f"{sorted(missing)}",
        )

    # Type coercion + range checks.
    try:
        agent_id = str(fm["agent_id"])
        skill_md_version = str(fm["skill_md_version"])
        draft_version = int(fm["draft_version"])
        authored_in_cluster = int(fm["authored_in_cluster"])
        finalised_raw = fm["finalised_in_cluster"]
        finalised_in_cluster = (
            None if finalised_raw is None else int(finalised_raw)
        )
        llm_model = str(fm["llm_model"])
        max_tokens = int(fm["max_tokens"])
        temperature = float(fm["temperature"])
        output_schema_ref = str(fm["output_schema_ref"])
    except (TypeError, ValueError) as exc:
        raise SkillMdValidationError(
            f"skill.md at {source_path} has a non-coercible field: {exc}",
        ) from exc

    if not agent_id or not re.fullmatch(r"[a-z][a-z0-9_]*", agent_id):
        raise SkillMdValidationError(
            f"skill.md at {source_path} has invalid agent_id "
            f"{agent_id!r} (must be snake_case starting with a letter).",
        )
    if max_tokens <= 0:
        raise SkillMdValidationError(
            f"skill.md at {source_path} has non-positive max_tokens "
            f"({max_tokens}).",
        )
    if not (0.0 <= temperature <= 2.0):
        raise SkillMdValidationError(
            f"skill.md at {source_path} has out-of-range temperature "
            f"({temperature}); expected 0.0..2.0.",
        )
    if draft_version < 0:
        raise SkillMdValidationError(
            f"skill.md at {source_path} has negative draft_version "
            f"({draft_version}).",
        )

    return SkillMd(
        agent_id=agent_id,
        skill_md_version=skill_md_version,
        draft_version=draft_version,
        authored_in_cluster=authored_in_cluster,
        finalised_in_cluster=finalised_in_cluster,
        llm_model=llm_model,
        max_tokens=max_tokens,
        temperature=temperature,
        output_schema_ref=output_schema_ref,
        body=body.strip(),
        source_path=source_path,
        front_matter_raw=fm,
    )


def _resolve_path(agent_id: str) -> Path:
    """Return the on-disk path for ``agent_id``: ``<dir>/<agent_id>.md``."""
    return get_skill_dir() / f"{agent_id}.md"


def load_skill(agent_id: str) -> SkillMd:
    """Read + parse the skill.md for ``agent_id`` (cached).

    Raises :class:`SkillMdMissingError` if the file doesn't exist;
    :class:`SkillMdParseError` / :class:`SkillMdValidationError` per
    :func:`_parse_text`.
    """
    cached = _cache.get(agent_id)
    if cached is not None:
        return cached

    path = _resolve_path(agent_id)
    if not path.exists():
        raise SkillMdMissingError(
            f"skill.md for agent_id={agent_id!r} not found at {path}.",
        )
    text = path.read_text(encoding="utf-8")
    skill = _parse_text(text, source_path=path)

    if skill.agent_id != agent_id:
        raise SkillMdValidationError(
            f"skill.md at {path} has front-matter agent_id="
            f"{skill.agent_id!r} but is filed as {agent_id!r}.",
        )

    _cache[agent_id] = skill
    return skill


def reload_skill(agent_id: str) -> SkillMd:
    """Drop the cache entry for ``agent_id`` and reload from disk.

    Hot-reload is gated by the ``ARTHA_SKILL_MD_HOT_RELOAD`` env var;
    when unset (production default) calling :func:`reload_skill` raises
    :class:`SkillMdError` to prevent accidental config drift after
    deploy.
    """
    if not _hot_reload_enabled():
        raise SkillMdError(
            "skill.md hot-reload is disabled. Set "
            "ARTHA_SKILL_MD_HOT_RELOAD=1 in dev to enable.",
        )
    _cache.pop(agent_id, None)
    return load_skill(agent_id)


def list_loaded_agent_ids() -> list[str]:
    """Return a sorted list of agent_ids currently in the cache."""
    return sorted(_cache.keys())


def list_available_agent_ids() -> list[str]:
    """Return every agent_id discoverable on disk (one .md per agent)."""
    skill_dir = get_skill_dir()
    if not skill_dir.exists():
        return []
    return sorted(p.stem for p in skill_dir.glob("*.md") if p.is_file())


def _hot_reload_enabled() -> bool:
    """True when ``ARTHA_SKILL_MD_HOT_RELOAD`` is set to a truthy value."""
    val = os.environ.get("ARTHA_SKILL_MD_HOT_RELOAD", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


__all__ = [
    "SkillMd",
    "SkillMdError",
    "SkillMdMissingError",
    "SkillMdParseError",
    "SkillMdValidationError",
    "get_skill_dir",
    "list_available_agent_ids",
    "list_loaded_agent_ids",
    "load_skill",
    "reload_skill",
    "reset_cache",
    "set_skill_dir",
]
