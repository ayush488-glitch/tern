"""read_file native tool — happy path, missing path, sandbox escape, slicing."""

from __future__ import annotations

from pathlib import Path

from tern.tools import ToolContext
from tern.tools.native import ReadFileTool
from tern.tools.native.read_file import ReadFileArgs


def _ctx(repo: Path) -> ToolContext:
    return ToolContext(repo_root=repo, session_id="s", turn_idx=0, mode="default")


async def test_read_file_happy(tmp_path: Path) -> None:
    f = tmp_path / "hello.txt"
    f.write_text("alpha\nbeta\ngamma\n")
    res = await ReadFileTool().invoke(ReadFileArgs(path="hello.txt"), _ctx(tmp_path))
    assert res.ok
    assert res.content == "1|alpha\n2|beta\n3|gamma"
    assert res.metadata["total_lines"] == 3


async def test_read_file_offset_and_limit(tmp_path: Path) -> None:
    f = tmp_path / "many.txt"
    f.write_text("\n".join(str(i) for i in range(1, 11)) + "\n")
    res = await ReadFileTool().invoke(
        ReadFileArgs(path="many.txt", offset=4, limit=2), _ctx(tmp_path)
    )
    assert res.ok
    assert res.content == "4|4\n5|5"


async def test_read_file_missing(tmp_path: Path) -> None:
    res = await ReadFileTool().invoke(
        ReadFileArgs(path="nope.txt"), _ctx(tmp_path)
    )
    assert not res.ok
    assert res.error is not None and "no such file" in res.error


async def test_read_file_sandbox_escape(tmp_path: Path) -> None:
    # tmp_path/repo is the root; ../outside is forbidden
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    res = await ReadFileTool().invoke(
        ReadFileArgs(path="../outside.txt"), _ctx(repo)
    )
    assert not res.ok
    assert res.error is not None and "escapes repo root" in res.error


async def test_read_file_directory_rejected(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    res = await ReadFileTool().invoke(ReadFileArgs(path="sub"), _ctx(tmp_path))
    assert not res.ok
    assert res.error is not None and "directory" in res.error
