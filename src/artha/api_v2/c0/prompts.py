"""Loader + renderer for C0 prompt templates.

The two cluster 1 templates live in :file:`skill.md` (per Principles §3.4
skill.md mechanism). This module pulls each fenced block by tag, caches
the result for the process lifetime, and exposes simple ``render_*``
helpers for the two call sites that the C0 service uses.

The cache is process-wide: the application reads ``skill.md`` once at
import time. Editing the file requires a backend restart to take effect.
That trade-off matches FR Entry 14.0 §2.3 ("modifying skill.md and
restarting the application picks up the new prompts").
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

#: The one-and-only skill version string emitted in T1 telemetry. Bump
#: when ``skill.md`` is modified so audit replay can correlate behaviour
#: to prompt version.
SKILL_VERSION = "v1.0"

_SKILL_FILE = Path(__file__).parent / "skill.md"

# Pulls ``\`\`\`<tag>\n...\`\`\``` blocks. The tag is the first capture
# group; the body is the second. Greedy-stop on the closing fence.
_BLOCK_RE = re.compile(r"```([a-z_]+)\n(.*?)\n```", re.DOTALL)


class PromptLoadError(RuntimeError):
    """Raised when ``skill.md`` is missing or a required prompt isn't there."""


@lru_cache(maxsize=1)
def load_skill() -> dict[str, str]:
    """Parse ``skill.md`` once and return ``{prompt_tag: template_body}``.

    Memoised: the cache is cleared by :func:`reset_skill_cache` for tests.
    """
    if not _SKILL_FILE.exists():
        raise PromptLoadError(f"C0 skill file missing: {_SKILL_FILE}")
    text = _SKILL_FILE.read_text(encoding="utf-8")
    blocks: dict[str, str] = {}
    for match in _BLOCK_RE.finditer(text):
        tag, body = match.group(1), match.group(2)
        blocks[tag] = body.strip()
    if "intent_detection" not in blocks:
        raise PromptLoadError("intent_detection block missing from skill.md")
    if "slot_extraction" not in blocks:
        raise PromptLoadError("slot_extraction block missing from skill.md")
    return blocks


def reset_skill_cache() -> None:
    """Test-only helper: drop the memoised skill.md parse."""
    load_skill.cache_clear()


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_intent_prompt(*, user_message: str) -> str:
    """Substitute the user message into the intent-detection template."""
    template = load_skill()["intent_detection"]
    return template.replace("<user_message>", user_message)


def render_slot_prompt(
    *,
    user_response: str,
    current_prompt: str,
    expected_fields: list[str],
) -> str:
    """Substitute the runtime context into the slot-extraction template.

    ``expected_fields`` is the list of field names the state machine is
    asking for in the current turn — passed verbatim into the template's
    ``<list_of_fields_with_descriptions>`` slot. The descriptions live in
    the template body (so authoring stays in skill.md, not Python).
    """
    template = load_skill()["slot_extraction"]
    fields_str = ", ".join(expected_fields)
    return (
        template.replace("<user_response>", user_response)
        .replace("<current_state_machine_prompt>", current_prompt)
        .replace("<list_of_fields_with_descriptions>", fields_str)
    )
