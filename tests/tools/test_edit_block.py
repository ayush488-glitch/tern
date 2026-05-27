"""edit_block — exact match, whitespace-tolerant, ambiguity, sandbox, errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from tern.tools import ToolContext
from tern.tools.native import EditBlockTool
from tern.tools.native.edit_block import (
    EditBlockArgs,
    EditBlockError,
    apply_edit_block,
)


def _ctx(repo: Path) -> ToolContext:
    return ToolContext(repo_root=repo, session_id="s", turn_idx=0, mode="default")


# ---- pure helper tests ----------------------------------------------------


def test_apply_exact_single_match() -> None:
    out = apply_edit_block("a\nb\nc\n", "b\n", "B\n")
    assert out == "a\nB\nc\n"


def test_apply_ambiguous_exact_match_raises() -> None:
    with pytest.raises(EditBlockError, match="appears 2 times"):
        apply_edit_block("x\nx\n", "x\n", "y\n")


def test_apply_not_found_raises() -> None:
    with pytest.raises(EditBlockError, match="not found"):
        apply_edit_block("a\nb\n", "missing\n", "z\n")


def test_apply_empty_search_raises() -> None:
    with pytest.raises(EditBlockError, match="empty"):
        apply_edit_block("anything\n", "", "z\n")


def test_apply_whitespace_tolerant() -> None:
    """Model omits the leading 4-space indent; we still find the match."""
    whole = "def f():\n    return 1\n"
    search = "return 1\n"  # missing 4-space indent
    replace = "return 42\n"
    out = apply_edit_block(whole, search, replace)
    assert out == "def f():\n    return 42\n"


def test_apply_whitespace_ambiguous_raises() -> None:
    # Two separate indented occurrences. The model strips the indent when
    # quoting; exact match misses (interleaved blank lines), whitespace match
    # finds both.
    whole = "    a\n    b\n\n    a\n    b\n"
    with pytest.raises(EditBlockError, match="whitespace-matches"):
        apply_edit_block(whole, "a\nb\n", "X\n")


# ---- end-to-end through the Tool ------------------------------------------


async def test_edit_block_writes_file(tmp_path: Path) -> None:
    f = tmp_path / "foo.py"
    f.write_text("def f():\n    return 1\n")
    res = await EditBlockTool().invoke(
        EditBlockArgs(path="foo.py", search="return 1", replace="return 2"),
        _ctx(tmp_path),
    )
    assert res.ok
    assert f.read_text() == "def f():\n    return 2\n"


async def test_edit_block_missing_file(tmp_path: Path) -> None:
    res = await EditBlockTool().invoke(
        EditBlockArgs(path="nope.py", search="x", replace="y"), _ctx(tmp_path)
    )
    assert not res.ok
    assert res.error is not None and "does not exist" in res.error


async def test_edit_block_sandbox_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("hi\n")
    res = await EditBlockTool().invoke(
        EditBlockArgs(path="../outside.py", search="hi", replace="bye"),
        _ctx(repo),
    )
    assert not res.ok
    assert res.error is not None and "escapes repo root" in res.error


async def test_edit_block_search_not_found_propagates(tmp_path: Path) -> None:
    f = tmp_path / "g.py"
    f.write_text("alpha\n")
    res = await EditBlockTool().invoke(
        EditBlockArgs(path="g.py", search="beta", replace="z"), _ctx(tmp_path)
    )
    assert not res.ok
    assert res.error is not None and "not found" in res.error
    # file must be unchanged on failure
    assert f.read_text() == "alpha\n"
