"""S15 — memory tool surface."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tern.memory.store import load_memory
from tern.tools.native.memory_tool import MemoryArgs, MemoryTool
from tern.tools.protocol import ToolContext


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TERN_HOME", str(tmp_path))
    yield


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        repo_root=tmp_path, session_id="s", turn_idx=0, mode="default"
    )


def _run(coro):
    return asyncio.run(coro)


def test_add_creates_entry(tmp_path):
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="memory", content="proc note")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert res.ok, res.error
    snap = load_memory("memory")
    assert snap.entries == ("proc note",)


def test_add_to_user_target(tmp_path):
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="user", content="user fact")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert res.ok
    assert load_memory("user").entries == ("user fact",)


def test_replace_swaps_entry(tmp_path):
    tool = MemoryTool()
    _run(tool.invoke(MemoryArgs(action="add", target="memory", content="old AWS region us-east"), _ctx(tmp_path)))
    res = _run(tool.invoke(
        MemoryArgs(
            action="replace", target="memory",
            old_text="us-east", content="new AWS region us-west",
        ),
        _ctx(tmp_path),
    ))
    assert res.ok, res.error
    assert "us-west" in load_memory("memory").entries[0]


def test_remove_drops_entry(tmp_path):
    tool = MemoryTool()
    _run(tool.invoke(MemoryArgs(action="add", target="memory", content="kill me"), _ctx(tmp_path)))
    res = _run(tool.invoke(
        MemoryArgs(action="remove", target="memory", old_text="kill me"),
        _ctx(tmp_path),
    ))
    assert res.ok
    assert load_memory("memory").entries == ()


def test_unknown_target_returns_error(tmp_path):
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="bogus", content="x")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert not res.ok
    assert "unknown target" in res.error.lower()


def test_unknown_action_returns_error(tmp_path):
    tool = MemoryTool()
    args = MemoryArgs(action="merge", target="memory", content="x")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert not res.ok
    assert "unknown action" in res.error.lower()


def test_add_missing_content_returns_error(tmp_path):
    tool = MemoryTool()
    args = MemoryArgs(action="add", target="memory")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert not res.ok
    assert "content" in res.error.lower()


def test_replace_missing_args_returns_error(tmp_path):
    tool = MemoryTool()
    args = MemoryArgs(action="replace", target="memory", content="x")
    res = _run(tool.invoke(args, _ctx(tmp_path)))
    assert not res.ok


def test_over_cap_warning_in_metadata(tmp_path):
    tool = MemoryTool()
    huge = "y" * 3000
    res = _run(tool.invoke(
        MemoryArgs(action="add", target="memory", content=huge),
        _ctx(tmp_path),
    ))
    assert res.ok
    assert res.metadata["over_cap"] is True
    assert "consider" in res.content.lower()
