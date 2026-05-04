"""Cluster 1 chunk 1.2 — skill.md loader test suite.

The two prompt templates are loaded from ``skill.md`` at import time and
cached. These tests verify the parser pulls the right blocks, the
substitutions work, and authoring the file produces both prompts even if
new code blocks are added later.
"""

from __future__ import annotations

import pytest

from artha.api_v2.c0 import prompts


@pytest.fixture(autouse=True)
def reset_cache():
    prompts.reset_skill_cache()
    yield
    prompts.reset_skill_cache()


class TestSkillLoad:
    def test_intent_detection_block_present(self):
        skill = prompts.load_skill()
        assert "intent_detection" in skill
        body = skill["intent_detection"]
        assert "investor_onboarding" in body
        assert "<user_message>" in body

    def test_slot_extraction_block_present(self):
        skill = prompts.load_skill()
        assert "slot_extraction" in skill
        body = skill["slot_extraction"]
        assert "<user_response>" in body
        assert "<current_state_machine_prompt>" in body
        assert "<list_of_fields_with_descriptions>" in body

    def test_skill_version_is_v1_0(self):
        assert prompts.SKILL_VERSION == "v1.0"


class TestRenderers:
    def test_render_intent_substitutes_user_message(self):
        out = prompts.render_intent_prompt(
            user_message="I want to onboard a new client"
        )
        assert "I want to onboard a new client" in out
        assert "<user_message>" not in out

    def test_render_slot_substitutes_all_three_placeholders(self):
        out = prompts.render_slot_prompt(
            user_response="rajesh@example.com and 9876543210",
            current_prompt="What's his email and phone?",
            expected_fields=["email", "phone"],
        )
        assert "rajesh@example.com and 9876543210" in out
        assert "What's his email and phone?" in out
        assert "email" in out and "phone" in out
        for placeholder in (
            "<user_response>",
            "<current_state_machine_prompt>",
            "<list_of_fields_with_descriptions>",
        ):
            assert placeholder not in out

    def test_render_slot_handles_empty_field_list(self):
        out = prompts.render_slot_prompt(
            user_response="hello",
            current_prompt="What now?",
            expected_fields=[],
        )
        assert "<list_of_fields_with_descriptions>" not in out
