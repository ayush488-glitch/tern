"""Tests for glob_tool (S14)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from tern.tools.native.glob_tool import GlobArgs, GlobTool
from tern.tools.protocol import ToolContext


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        repo_root=tmp_path, session_id="s", turn_idx=0, mode="default"
    )


def test_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        GlobArgs(pattern="*", oops=1)  # type: ignore[call-arg]


def test_finds_python_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "c.txt").write_text("c")
    tool = GlobTool()
    res = asyncio.run(tool.invoke(GlobArgs(pattern="*.py"), _ctx(tmp_path)))
    assert res.ok
    paths = set(res.content.split("\n"))
    assert "a.py" in paths and "b.py" in paths
    assert "c.txt" not in paths


def test_skips_junk_dirs(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "x.py").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "y.py").write_text("y")
    (tmp_path / "good.py").write_text("z")
    tool = GlobTool()
    res = asyncio.run(tool.invoke(GlobArgs(pattern="**/*.py"), _ctx(tmp_path)))
    assert res.ok
    assert res.content == "good.py"


def test_no_matches(tmp_path: Path) -> None:
    tool = GlobTool()
    res = asyncio.run(tool.invoke(GlobArgs(pattern="*.nope"), _ctx(tmp_path)))
    assert res.ok
    assert "no matches" in res.content


def test_truncation(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")
    tool = GlobTool()
    res = asyncio.run(tool.invoke(GlobArgs(pattern="*.txt", limit=3), _ctx(tmp_path)))
    assert res.ok
    assert res.metadata["count"] == 3
    assert res.metadata["truncated"] is True


def test_outside_repo_refused(tmp_path: Path) -> None:
    tool = GlobTool()
    res = asyncio.run(tool.invoke(GlobArgs(pattern="*", path="/etc"), _ctx(tmp_path)))
    assert not res.ok
