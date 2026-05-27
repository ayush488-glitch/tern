"""Tests for write_file (S14)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from tern.tools.native.write_file import WriteFileArgs, WriteFileTool
from tern.tools.protocol import ToolContext


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        repo_root=tmp_path, session_id="s", turn_idx=0, mode="default"
    )


def test_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        WriteFileArgs(path="x", content="y", oops=1)  # type: ignore[call-arg]


def test_creates_new_file_with_parents(tmp_path: Path) -> None:
    tool = WriteFileTool()
    args = WriteFileArgs(path="a/b/c.py", content="print('hi')\n")
    res = asyncio.run(tool.invoke(args, _ctx(tmp_path)))
    assert res.ok, res.error
    p = tmp_path / "a" / "b" / "c.py"
    assert p.read_text() == "print('hi')\n"
    assert res.metadata["created"] is True


def test_refuses_overwrite_without_flag(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("old")
    tool = WriteFileTool()
    res = asyncio.run(tool.invoke(WriteFileArgs(path="x.txt", content="new"), _ctx(tmp_path)))
    assert not res.ok
    assert "exists" in (res.error or "")
    assert p.read_text() == "old"


def test_overwrite_when_flag_true(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("old")
    tool = WriteFileTool()
    res = asyncio.run(tool.invoke(
        WriteFileArgs(path="x.txt", content="new", overwrite=True), _ctx(tmp_path)
    ))
    assert res.ok
    assert p.read_text() == "new"
    assert res.metadata["created"] is False


def test_refuses_outside_repo(tmp_path: Path) -> None:
    tool = WriteFileTool()
    res = asyncio.run(tool.invoke(
        WriteFileArgs(path="/etc/passwd_doppel", content="x"), _ctx(tmp_path)
    ))
    assert not res.ok


def test_refuses_directory(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    tool = WriteFileTool()
    res = asyncio.run(tool.invoke(
        WriteFileArgs(path="d", content="x", overwrite=True), _ctx(tmp_path)
    ))
    assert not res.ok
    assert "directory" in (res.error or "")


def test_size_cap(tmp_path: Path) -> None:
    tool = WriteFileTool()
    big = "a" * (1_000_001)
    res = asyncio.run(tool.invoke(WriteFileArgs(path="big.txt", content=big), _ctx(tmp_path)))
    assert not res.ok
    assert "exceeds" in (res.error or "")


def test_annotations_destructive() -> None:
    t = WriteFileTool()
    assert t.annotations.destructive is True
    assert t.annotations.read_only is False
    assert t.annotations.open_world is False
