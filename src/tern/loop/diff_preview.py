"""Unified diff preview helper for write_file and edit_block (S21 / ADR-0012 §5).

In mode != "yolo", a destructive write emits a diff event before applying.
CLI renders the diff; user accepts (Enter) or rejects (Ctrl-C / 'n').

This module is pure computation — no I/O, no asyncio.
The gate/approval flow in loop.py handles the interactive prompt.
"""
from __future__ import annotations

import difflib


def unified_diff(old: str, new: str, path: str, context: int = 3) -> str:
    """Return a unified diff string between *old* and *new* content.

    Returns empty string when old == new (no-op write).
    """
    if old == new:
        return ""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context,
    )
    return "".join(diff)


def line_count(diff: str) -> int:
    """Count added + removed lines in a unified diff string."""
    added = sum(
        1 for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    return added + removed


__all__ = ["line_count", "unified_diff"]
