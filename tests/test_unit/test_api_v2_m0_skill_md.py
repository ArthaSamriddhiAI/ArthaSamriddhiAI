"""Cluster 5 chunk 5.2 — skill.md loader / validator / hot-reload tests.

Pins FR Entry 20.2 §10.3 front-matter contract + the four runtime
guarantees:

1. Front-matter must parse as YAML and contain all 9 required keys.
2. Type coercion + range checks reject malformed values.
3. Cache returns the same SkillMd instance until reset.
4. Hot-reload is gated by ARTHA_SKILL_MD_HOT_RELOAD env var.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from artha.api_v2.m0 import skill_md


@pytest.fixture
def tmp_skill_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the loader at a fresh tmp dir + clear caches."""
    monkeypatch.delenv("ARTHA_SKILL_MD_HOT_RELOAD", raising=False)
    skill_md.set_skill_dir(tmp_path)
    yield tmp_path
    skill_md.set_skill_dir(None)


def _write_skill(
    dir_: Path,
    *,
    agent_id: str,
    front_matter: str | None = None,
    body: str = "Body text.",
) -> Path:
    if front_matter is None:
        front_matter = (
            f"agent_id: {agent_id}\n"
            f"skill_md_version: v0.1\n"
            f"draft_version: 1\n"
            f"authored_in_cluster: 5\n"
            f"finalised_in_cluster: null\n"
            f"llm_model: claude-sonnet-4-5\n"
            f"max_tokens: 1000\n"
            f"temperature: 0.1\n"
            f"output_schema_ref: ../schemas/{agent_id}.json"
        )
    path = dir_ / f"{agent_id}.md"
    path.write_text(f"---\n{front_matter}\n---\n{body}", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_load_minimal_skill(self, tmp_skill_dir: Path) -> None:
        _write_skill(tmp_skill_dir, agent_id="t1_happy")
        skill = skill_md.load_skill("t1_happy")
        assert skill.agent_id == "t1_happy"
        assert skill.skill_md_version == "v0.1"
        # ``draft_version`` is now a string per FR 20.3 §4.1; a numeric
        # int in the YAML coerces to its string form.
        assert skill.draft_version == "1"
        assert skill.authored_in_cluster == 5
        assert skill.finalised_in_cluster is None
        assert skill.llm_model == "claude-sonnet-4-5"
        assert skill.max_tokens == 1000
        assert skill.temperature == pytest.approx(0.1)
        assert skill.output_schema_ref == "../schemas/t1_happy.json"
        assert skill.body == "Body text."

    def test_cache_returns_identical_instance(self, tmp_skill_dir: Path) -> None:
        _write_skill(tmp_skill_dir, agent_id="t2_cache")
        a = skill_md.load_skill("t2_cache")
        b = skill_md.load_skill("t2_cache")
        assert a is b

    def test_finalised_int_accepted(self, tmp_skill_dir: Path) -> None:
        fm = (
            "agent_id: t_final\n"
            "skill_md_version: v0.1\n"
            "draft_version: 1\n"
            "authored_in_cluster: 5\n"
            "finalised_in_cluster: 8\n"
            "llm_model: claude-sonnet-4-5\n"
            "max_tokens: 1000\n"
            "temperature: 0.1\n"
            "output_schema_ref: ../schemas/t_final.json"
        )
        _write_skill(tmp_skill_dir, agent_id="t_final", front_matter=fm)
        skill = skill_md.load_skill("t_final")
        assert skill.finalised_in_cluster == 8


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TestErrors:
    def test_missing_file_raises(self, tmp_skill_dir: Path) -> None:
        with pytest.raises(skill_md.SkillMdMissingError):
            skill_md.load_skill("absent")

    def test_no_front_matter_raises(self, tmp_skill_dir: Path) -> None:
        path = tmp_skill_dir / "noyaml.md"
        path.write_text("Just markdown, no front-matter.", encoding="utf-8")
        with pytest.raises(skill_md.SkillMdParseError):
            skill_md.load_skill("noyaml")

    def test_missing_required_key_raises(self, tmp_skill_dir: Path) -> None:
        # Drop max_tokens.
        fm = (
            "agent_id: t_short\n"
            "skill_md_version: v0.1\n"
            "draft_version: 1\n"
            "authored_in_cluster: 5\n"
            "finalised_in_cluster: null\n"
            "llm_model: claude-sonnet-4-5\n"
            "temperature: 0.1\n"
            "output_schema_ref: ../schemas/t_short.json"
        )
        _write_skill(tmp_skill_dir, agent_id="t_short", front_matter=fm)
        with pytest.raises(skill_md.SkillMdValidationError, match="max_tokens"):
            skill_md.load_skill("t_short")

    def test_invalid_temperature_raises(self, tmp_skill_dir: Path) -> None:
        fm = (
            "agent_id: t_temp\n"
            "skill_md_version: v0.1\n"
            "draft_version: 1\n"
            "authored_in_cluster: 5\n"
            "finalised_in_cluster: null\n"
            "llm_model: claude-sonnet-4-5\n"
            "max_tokens: 1000\n"
            "temperature: 5.0\n"
            "output_schema_ref: ../schemas/t_temp.json"
        )
        _write_skill(tmp_skill_dir, agent_id="t_temp", front_matter=fm)
        with pytest.raises(skill_md.SkillMdValidationError, match="temperature"):
            skill_md.load_skill("t_temp")

    def test_invalid_agent_id_raises(self, tmp_skill_dir: Path) -> None:
        fm = (
            "agent_id: BadAgentId\n"
            "skill_md_version: v0.1\n"
            "draft_version: 1\n"
            "authored_in_cluster: 5\n"
            "finalised_in_cluster: null\n"
            "llm_model: claude-sonnet-4-5\n"
            "max_tokens: 1000\n"
            "temperature: 0.1\n"
            "output_schema_ref: ../schemas/x.json"
        )
        # Filename matches the bad ID so the file lookup succeeds.
        path = tmp_skill_dir / "BadAgentId.md"
        path.write_text(f"---\n{fm}\n---\nBody.", encoding="utf-8")
        with pytest.raises(skill_md.SkillMdValidationError, match="snake_case"):
            skill_md.load_skill("BadAgentId")

    def test_filename_id_mismatch_raises(self, tmp_skill_dir: Path) -> None:
        # Front-matter says agent_id=other but file is filed as t_mismatch.md.
        fm = (
            "agent_id: other\n"
            "skill_md_version: v0.1\n"
            "draft_version: 1\n"
            "authored_in_cluster: 5\n"
            "finalised_in_cluster: null\n"
            "llm_model: claude-sonnet-4-5\n"
            "max_tokens: 1000\n"
            "temperature: 0.1\n"
            "output_schema_ref: ../schemas/x.json"
        )
        path = tmp_skill_dir / "t_mismatch.md"
        path.write_text(f"---\n{fm}\n---\nBody.", encoding="utf-8")
        with pytest.raises(skill_md.SkillMdValidationError, match="filed as"):
            skill_md.load_skill("t_mismatch")

    def test_negative_max_tokens_raises(self, tmp_skill_dir: Path) -> None:
        fm = (
            "agent_id: t_neg\n"
            "skill_md_version: v0.1\n"
            "draft_version: 1\n"
            "authored_in_cluster: 5\n"
            "finalised_in_cluster: null\n"
            "llm_model: claude-sonnet-4-5\n"
            "max_tokens: 0\n"
            "temperature: 0.1\n"
            "output_schema_ref: ../schemas/t_neg.json"
        )
        _write_skill(tmp_skill_dir, agent_id="t_neg", front_matter=fm)
        with pytest.raises(skill_md.SkillMdValidationError, match="max_tokens"):
            skill_md.load_skill("t_neg")

    def test_malformed_yaml_raises(self, tmp_skill_dir: Path) -> None:
        path = tmp_skill_dir / "t_yaml.md"
        path.write_text(
            "---\nbad: : value\n---\nBody.",
            encoding="utf-8",
        )
        with pytest.raises(skill_md.SkillMdParseError):
            skill_md.load_skill("t_yaml")


# ---------------------------------------------------------------------------
# Hot-reload
# ---------------------------------------------------------------------------


class TestHotReload:
    def test_reload_disabled_by_default(
        self,
        tmp_skill_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ARTHA_SKILL_MD_HOT_RELOAD", raising=False)
        _write_skill(tmp_skill_dir, agent_id="t_reload")
        skill_md.load_skill("t_reload")
        with pytest.raises(skill_md.SkillMdError, match="disabled"):
            skill_md.reload_skill("t_reload")

    def test_reload_works_when_enabled(
        self,
        tmp_skill_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARTHA_SKILL_MD_HOT_RELOAD", "1")
        _write_skill(tmp_skill_dir, agent_id="t_reload2")
        skill = skill_md.load_skill("t_reload2")
        assert skill.draft_version == "1"

        # Edit the file: bump draft_version.
        fm = (
            "agent_id: t_reload2\n"
            "skill_md_version: v0.2\n"
            "draft_version: 2\n"
            "authored_in_cluster: 5\n"
            "finalised_in_cluster: null\n"
            "llm_model: claude-sonnet-4-5\n"
            "max_tokens: 1000\n"
            "temperature: 0.1\n"
            "output_schema_ref: ../schemas/t_reload2.json"
        )
        _write_skill(tmp_skill_dir, agent_id="t_reload2", front_matter=fm)

        # Without reload, cache returns the stale row.
        cached = skill_md.load_skill("t_reload2")
        assert cached.draft_version == "1"

        # After reload, the new row appears.
        reloaded = skill_md.reload_skill("t_reload2")
        assert reloaded.draft_version == "2"
        assert reloaded.skill_md_version == "v0.2"

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("", False),
        ],
    )
    def test_hot_reload_env_truthy(
        self,
        monkeypatch: pytest.MonkeyPatch,
        value: str,
        expected: bool,
    ) -> None:
        monkeypatch.setenv("ARTHA_SKILL_MD_HOT_RELOAD", value)
        assert skill_md._hot_reload_enabled() is expected


# ---------------------------------------------------------------------------
# Available agent listing
# ---------------------------------------------------------------------------


class TestListing:
    def test_list_available_agent_ids(self, tmp_skill_dir: Path) -> None:
        _write_skill(tmp_skill_dir, agent_id="aa_first")
        _write_skill(tmp_skill_dir, agent_id="bb_second")
        assert skill_md.list_available_agent_ids() == ["aa_first", "bb_second"]

    def test_list_loaded_agent_ids(self, tmp_skill_dir: Path) -> None:
        _write_skill(tmp_skill_dir, agent_id="cc_one")
        _write_skill(tmp_skill_dir, agent_id="dd_two")
        skill_md.load_skill("dd_two")
        # Only loaded agents in the cache; "cc_one" was never read.
        assert skill_md.list_loaded_agent_ids() == ["dd_two"]


# ---------------------------------------------------------------------------
# Repo skill.md set integration
# ---------------------------------------------------------------------------


class TestRepoSkillMdSet:
    """End-to-end: parse every on-disk skill.md in config/skills/."""

    def test_all_repo_skill_md_files_load(self) -> None:
        skill_md.set_skill_dir(None)  # restore default
        skill_md.reset_cache()
        try:
            agents = skill_md.list_available_agent_ids()
            # Cluster 6 inventory: 21 skill.md files on disk (governance
            # gates G1/G2/G3 are deterministic Python checks without
            # skill.md; m0_briefer / m0_librarian / m0_portfolio_state /
            # m0_portfolio_analytics / ic1_member_quant retired).
            assert len(agents) == 21, f"expected 21 skill.md files, got {len(agents)}: {agents}"
            for agent_id in agents:
                skill = skill_md.load_skill(agent_id)
                assert skill.agent_id == agent_id
                assert skill.authored_in_cluster == 5
                # Cluster 6 enriched files mark draft_version="provisional";
                # cluster 5 placeholders used numeric strings ("1").
                dv = skill.draft_version
                assert dv in {"provisional", "production"} or dv.isdigit()
        finally:
            skill_md.reset_cache()
