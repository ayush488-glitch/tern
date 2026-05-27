"""Tests for grep_tool (S14). Forces the Python-re fallback path so tests are
deterministic regardless of whether ripgrep is installed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from tern.tools.native import grep_tool as gmod
from tern.tools.native.grep_tool import GrepArgs, GrepTool
from tern.tools.protocol import ToolContext


@pytest.fixture(autouse=True)
def _force_re_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the Python re backend so test behavior is identical across hosts.
    monkeypatch.setattr(gmod.shutil, "which", lambda _name: None)


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        repo_root=tmp_path, session_id="s", turn_idx=0, mode="default"
    )


def test_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        GrepArgs(pattern="x", oops=1)  # type: ignore[call-arg]


def test_finds_match(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello world\nbye\n")
    (tmp_path / "b.py").write_text("nothing\n")
    tool = GrepTool()
    res = asyncio.run(tool.invoke(GrepArgs(pattern="hello"), _ctx(tmp_path)))
    assert res.ok
    assert "a.py:1:hello world" in res.content
    assert "b.py" not in res.content


def test_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("Hello\n")
    tool = GrepTool()
    res = asyncio.run(tool.invoke(
        GrepArgs(pattern="hello", case_insensitive=True), _ctx(tmp_path)
    ))
    assert res.ok and "a.py:1:Hello" in res.content


def test_file_glob_filter(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("target\n")
    (tmp_path / "a.md").write_text("target\n")
    tool = GrepTool()
    res = asyncio.run(tool.invoke(
        GrepArgs(pattern="target", file_glob="*.md"), _ctx(tmp_path)
    ))
    assert res.ok
    assert "a.md" in res.content
    assert "a.py" not in res.content


def test_skips_junk_dirs(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.py").write_text("findme\n")
    (tmp_path / "good.py").write_text("findme\n")
    tool = GrepTool()
    res = asyncio.run(tool.invoke(GrepArgs(pattern="findme"), _ctx(tmp_path)))
    assert res.ok
    assert "good.py" in res.content
    assert "node_modules" not in res.content


def test_bad_regex(tmp_path: Path) -> None:
    tool = GrepTool()
    res = asyncio.run(tool.invoke(GrepArgs(pattern="("), _ctx(tmp_path)))
    assert not res.ok
    assert "bad regex" in (res.error or "")


def test_truncation(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("\n".join(["match"] * 10) + "\n")
    tool = GrepTool()
    res = asyncio.run(tool.invoke(GrepArgs(pattern="match", limit=3), _ctx(tmp_path)))
    assert res.ok
    assert res.metadata["truncated"] is True
    assert res.metadata["matches"] == 3
