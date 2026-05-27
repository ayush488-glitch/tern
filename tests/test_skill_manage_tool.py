"""S15 — skill_manage tool surface."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tern.tools.native.skill_manage import SkillManageArgs, SkillManageTool
from tern.tools.protocol import ToolContext


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path / "tern_home"))
    yield


def _ctx(repo: Path) -> ToolContext:
    return ToolContext(repo_root=repo, session_id="s", turn_idx=0, mode="default")


def _run(coro):
    return asyncio.run(coro)


SAMPLE = """---
name: greet
description: Say hi
---
# Greet
Just say hi.
"""


def test_create_user_scope(tmp_path):
    tool = SkillManageTool()
    res = _run(tool.invoke(
        SkillManageArgs(action="create", name="greet", scope="user", content=SAMPLE),
        _ctx(tmp_path),
    ))
    assert res.ok, res.error
    p = Path(res.metadata["path"])
    assert p.exists()
    assert "greet" in str(p)


def test_create_project_scope_writes_under_repo(tmp_path):
    tool = SkillManageTool()
    res = _run(tool.invoke(
        SkillManageArgs(action="create", name="proj-only", scope="project", content=SAMPLE),
        _ctx(tmp_path),
    ))
    assert res.ok
    assert ".tern/skills/proj-only" in res.metadata["path"]


def test_create_rejects_duplicate(tmp_path):
    tool = SkillManageTool()
    _run(tool.invoke(SkillManageArgs(action="create", name="g", content=SAMPLE), _ctx(tmp_path)))
    res = _run(tool.invoke(SkillManageArgs(action="create", name="g", content=SAMPLE), _ctx(tmp_path)))
    assert not res.ok
    assert "already exists" in res.error


def test_invalid_name_rejected(tmp_path):
    tool = SkillManageTool()
    res = _run(tool.invoke(
        SkillManageArgs(action="create", name="BAD NAME!", content=SAMPLE),
        _ctx(tmp_path),
    ))
    assert not res.ok
    assert "invalid skill name" in res.error


def test_patch_replaces_unique_string(tmp_path):
    tool = SkillManageTool()
    _run(tool.invoke(SkillManageArgs(action="create", name="g", content=SAMPLE), _ctx(tmp_path)))
    res = _run(tool.invoke(
        SkillManageArgs(
            action="patch", name="g",
            old_string="Just say hi.", new_string="Say hi politely.",
        ),
        _ctx(tmp_path),
    ))
    assert res.ok, res.error
    assert "1 occurrence" in res.content


def test_patch_ambiguous_without_replace_all_rejected(tmp_path):
    tool = SkillManageTool()
    body = SAMPLE + "\nhi\nhi\n"
    _run(tool.invoke(SkillManageArgs(action="create", name="g", content=body), _ctx(tmp_path)))
    res = _run(tool.invoke(
        SkillManageArgs(action="patch", name="g", old_string="hi", new_string="hello"),
        _ctx(tmp_path),
    ))
    assert not res.ok
    assert "matches" in res.error


def test_edit_rewrites(tmp_path):
    tool = SkillManageTool()
    _run(tool.invoke(SkillManageArgs(action="create", name="g", content=SAMPLE), _ctx(tmp_path)))
    new_body = SAMPLE.replace("Just say hi.", "Wave instead.")
    res = _run(tool.invoke(
        SkillManageArgs(action="edit", name="g", content=new_body),
        _ctx(tmp_path),
    ))
    assert res.ok
    assert "Wave" in Path(res.metadata["path"]).read_text("utf-8")


def test_delete_removes_dir(tmp_path):
    tool = SkillManageTool()
    _run(tool.invoke(SkillManageArgs(action="create", name="g", content=SAMPLE), _ctx(tmp_path)))
    res = _run(tool.invoke(SkillManageArgs(action="delete", name="g"), _ctx(tmp_path)))
    assert res.ok
    # second delete should fail
    res2 = _run(tool.invoke(SkillManageArgs(action="delete", name="g"), _ctx(tmp_path)))
    assert not res2.ok


def test_write_file_under_references(tmp_path):
    tool = SkillManageTool()
    _run(tool.invoke(SkillManageArgs(action="create", name="g", content=SAMPLE), _ctx(tmp_path)))
    res = _run(tool.invoke(
        SkillManageArgs(
            action="write_file", name="g",
            file_path="references/api.md", file_content="# API",
        ),
        _ctx(tmp_path),
    ))
    assert res.ok, res.error
    assert Path(res.metadata["path"]).read_text("utf-8") == "# API"


def test_write_file_outside_allowed_prefix_rejected(tmp_path):
    tool = SkillManageTool()
    _run(tool.invoke(SkillManageArgs(action="create", name="g", content=SAMPLE), _ctx(tmp_path)))
    res = _run(tool.invoke(
        SkillManageArgs(
            action="write_file", name="g",
            file_path="evil/x.sh", file_content="rm -rf /",
        ),
        _ctx(tmp_path),
    ))
    assert not res.ok
    assert "must live under" in res.error


def test_remove_file(tmp_path):
    tool = SkillManageTool()
    _run(tool.invoke(SkillManageArgs(action="create", name="g", content=SAMPLE), _ctx(tmp_path)))
    _run(tool.invoke(
        SkillManageArgs(
            action="write_file", name="g",
            file_path="scripts/run.sh", file_content="#!/bin/sh\necho hi",
        ),
        _ctx(tmp_path),
    ))
    res = _run(tool.invoke(
        SkillManageArgs(action="remove_file", name="g", file_path="scripts/run.sh"),
        _ctx(tmp_path),
    ))
    assert res.ok


def test_unknown_scope_rejected(tmp_path):
    tool = SkillManageTool()
    res = _run(tool.invoke(
        SkillManageArgs(action="create", name="g", scope="moon", content=SAMPLE),
        _ctx(tmp_path),
    ))
    assert not res.ok
    assert "scope" in res.error.lower()
