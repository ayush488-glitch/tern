"""Tests for the S11 / D2 skills runtime."""
from __future__ import annotations

from pathlib import Path

import pytest

from tern.skills.catalog import (
    _parse_frontmatter,
    build_system_prompt,
    catalog_digest,
    load_skills,
    render_active_block,
)
from tern.skills.retrieval import select_active


def _write_skill(
    root: Path,
    name: str,
    description: str = "do a thing",
    when_to_use: str = "",
    body: str = "step 1\nstep 2\n",
    allowed_tools: list[str] | None = None,
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = [f"name: {name}", f"description: {description}"]
    if when_to_use:
        fm.append(f"when_to_use: {when_to_use}")
    if allowed_tools:
        fm.append(f"allowed_tools: [{', '.join(allowed_tools)}]")
    text = "---\n" + "\n".join(fm) + "\n---\n\n" + body
    path = skill_dir / "SKILL.md"
    path.write_text(text, "utf-8")
    return path


# ---- frontmatter parsing -------------------------------------------------


def test_frontmatter_parses_simple_kv() -> None:
    fm, body = _parse_frontmatter("---\nname: foo\ndescription: bar\n---\n\nbody.\n")
    assert fm == {"name": "foo", "description": "bar"}
    assert body.strip() == "body."


def test_frontmatter_parses_quoted_and_list() -> None:
    text = '---\nname: "x"\nallowed_tools: [a, "b", c]\n---\nbody'
    fm, _ = _parse_frontmatter(text)
    assert fm["name"] == "x"
    assert fm["allowed_tools"] == ["a", "b", "c"]


def test_frontmatter_missing_returns_full_body() -> None:
    fm, body = _parse_frontmatter("# just markdown\nno fence")
    assert fm == {}
    assert body.startswith("# just markdown")


# ---- discovery -----------------------------------------------------------


def test_load_skills_user_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    user = tmp_path / "skills"
    _write_skill(user, "alpha", description="alpha skill")
    _write_skill(user, "beta", description="beta skill")
    skills = load_skills(cwd=tmp_path / "proj")
    assert [s.name for s in skills] == ["alpha", "beta"]
    assert all(s.source == "user" for s in skills)


def test_load_skills_project_overrides_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path / "home"))
    user = tmp_path / "home" / "skills"
    proj_root = tmp_path / "proj"
    proj = proj_root / ".tern" / "skills"
    _write_skill(user, "code-review", description="user version")
    _write_skill(proj, "code-review", description="project override")
    skills = load_skills(cwd=proj_root)
    assert len(skills) == 1
    assert skills[0].source == "project"
    assert skills[0].description == "project override"


def test_load_skills_disabled_via_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    monkeypatch.setenv("TERN_DISABLE_SKILLS", "1")
    _write_skill(tmp_path / "skills", "alpha")
    assert load_skills(cwd=tmp_path / "proj") == ()


def test_load_skills_skips_dirs_without_skill_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    (tmp_path / "skills" / "empty").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "real")
    skills = load_skills(cwd=tmp_path / "proj")
    assert [s.name for s in skills] == ["real"]


def test_load_skills_no_dir_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path / "nope"))
    assert load_skills(cwd=tmp_path / "alsonope") == ()


# ---- digest / active rendering ------------------------------------------


def test_catalog_digest_one_line_per_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    _write_skill(
        tmp_path / "skills",
        "code-review",
        description="checklist for PRs",
        when_to_use="reviewing diffs",
    )
    skills = load_skills(cwd=tmp_path / "proj")
    digest = catalog_digest(skills)
    assert "AVAILABLE SKILLS" in digest
    assert "- code-review: checklist for PRs" in digest
    assert "[when: reviewing diffs]" in digest


def test_render_active_block_includes_full_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    _write_skill(
        tmp_path / "skills",
        "deploy",
        description="ship it",
        body="1. run tests\n2. push",
    )
    skills = load_skills(cwd=tmp_path / "proj")
    block = render_active_block(skills)
    assert "ACTIVE SKILLS" in block
    assert "1. run tests" in block
    assert "### SKILL: deploy" in block


def test_build_system_prompt_empty_when_no_skills() -> None:
    assert build_system_prompt((), ()) == ""


def test_build_system_prompt_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    _write_skill(tmp_path / "skills", "alpha", body="alpha-body")
    skills = load_skills(cwd=tmp_path / "proj")
    text = build_system_prompt(skills, skills, base="You are Tern.")
    assert text.startswith("You are Tern.")
    assert "AVAILABLE SKILLS" in text
    assert "ACTIVE SKILLS" in text
    assert "alpha-body" in text


# ---- retrieval -----------------------------------------------------------


def test_select_active_explicit_mention_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    _write_skill(tmp_path / "skills", "code-review", description="review code")
    _write_skill(tmp_path / "skills", "deploy", description="ship things")
    skills = load_skills(cwd=tmp_path / "proj")
    active = select_active("please use the code-review skill on this PR", skills)
    assert [s.name for s in active] == ["code-review"]


def test_select_active_keyword_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    _write_skill(
        tmp_path / "skills",
        "deploy",
        description="ship to production railway",
        when_to_use="when deploying applications",
    )
    skills = load_skills(cwd=tmp_path / "proj")
    active = select_active("help me deploy this railway application", skills)
    assert [s.name for s in active] == ["deploy"]


def test_select_active_below_threshold_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    _write_skill(
        tmp_path / "skills", "deploy", description="zzz", body="qqq"
    )
    skills = load_skills(cwd=tmp_path / "proj")
    # Prompt shares no tokens with skill — must not activate.
    active = select_active("write a haiku about cats", skills)
    assert active == ()


def test_select_active_caps_at_max(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    for n in ("alpha", "beta", "gamma", "delta", "epsilon"):
        _write_skill(
            tmp_path / "skills", n,
            description=f"thing {n} deploy production railway",
            body="deploy production railway",
        )
    skills = load_skills(cwd=tmp_path / "proj")
    active = select_active("deploy production railway thing", skills)
    assert len(active) == 3


def test_select_active_no_skills_returns_empty() -> None:
    assert select_active("anything", ()) == ()
