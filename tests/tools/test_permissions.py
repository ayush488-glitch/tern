"""PermissionGate: mode + annotations + prompter wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from tern.tools import (
    ApprovalDecision,
    PermissionGate,
    Tool,
    ToolBlocked,
    ToolContext,
)
from tests.tools._fakes import FakeDestructiveTool, FakeReadOnlyTool, _NopArgs


def _ctx(mode: str, tmp_path: Path) -> ToolContext:
    return ToolContext(repo_root=tmp_path, session_id="s", turn_idx=0, mode=mode)


async def test_safe_blocks_destructive(tmp_path: Path) -> None:
    gate = PermissionGate()
    with pytest.raises(ToolBlocked, match="refused in safe mode"):
        await gate.check(FakeDestructiveTool(), _NopArgs(), _ctx("safe", tmp_path))


async def test_safe_allows_readonly(tmp_path: Path) -> None:
    gate = PermissionGate()
    decision = await gate.check(
        FakeReadOnlyTool(), _NopArgs(), _ctx("safe", tmp_path)
    )
    assert decision == ApprovalDecision.GRANTED


async def test_default_passes_readonly_without_prompt(tmp_path: Path) -> None:
    gate = PermissionGate()  # no prompter
    decision = await gate.check(
        FakeReadOnlyTool(), _NopArgs(), _ctx("default", tmp_path)
    )
    assert decision == ApprovalDecision.GRANTED


async def test_default_destructive_with_no_prompter_blocks(tmp_path: Path) -> None:
    gate = PermissionGate()
    with pytest.raises(ToolBlocked, match="no prompter"):
        await gate.check(
            FakeDestructiveTool(), _NopArgs(), _ctx("default", tmp_path)
        )


async def test_default_destructive_prompter_grants(tmp_path: Path) -> None:
    seen: list[str] = []

    async def grant(tool: Tool, args: BaseModel, ctx: ToolContext) -> ApprovalDecision:
        seen.append(tool.name)
        return ApprovalDecision.GRANTED

    gate = PermissionGate(prompter=grant)
    decision = await gate.check(
        FakeDestructiveTool(), _NopArgs(), _ctx("default", tmp_path)
    )
    assert decision == ApprovalDecision.GRANTED
    assert seen == ["fake_write"]


async def test_default_destructive_prompter_denies(tmp_path: Path) -> None:
    async def deny(tool: Tool, args: BaseModel, ctx: ToolContext) -> ApprovalDecision:
        return ApprovalDecision.DENIED

    gate = PermissionGate(prompter=deny)
    with pytest.raises(ToolBlocked, match="user denied"):
        await gate.check(
            FakeDestructiveTool(), _NopArgs(), _ctx("default", tmp_path)
        )


async def test_yolo_auto_approves_destructive(tmp_path: Path) -> None:
    async def fail(tool: Tool, args: BaseModel, ctx: ToolContext) -> ApprovalDecision:
        raise AssertionError("prompter should never fire in yolo mode")

    gate = PermissionGate(prompter=fail)
    decision = await gate.check(
        FakeDestructiveTool(), _NopArgs(), _ctx("yolo", tmp_path)
    )
    assert decision == ApprovalDecision.GRANTED
