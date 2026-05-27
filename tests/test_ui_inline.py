"""Inline REPL helpers: edit_block diff preview."""
from __future__ import annotations

from pathlib import Path

from tern.tools.native.edit_block import EditBlockArgs
from tern.ui.app import _diff_for_edit_block


def test_diff_preview_shows_search_replace(tmp_path: Path) -> None:
    f = tmp_path / "hello.py"
    f.write_text("print('hi')\n")
    args = EditBlockArgs(path="hello.py", search="print('hi')", replace="print('hello')")
    diff = _diff_for_edit_block(args, tmp_path)
    assert diff is not None
    assert "-print('hi')" in diff
    assert "+print('hello')" in diff
    assert "warning" not in diff


def test_diff_preview_warns_when_search_missing(tmp_path: Path) -> None:
    f = tmp_path / "hello.py"
    f.write_text("print('hi')\n")
    args = EditBlockArgs(path="hello.py", search="nope", replace="yep")
    diff = _diff_for_edit_block(args, tmp_path)
    assert diff is not None
    assert "warning: search block not found" in diff
