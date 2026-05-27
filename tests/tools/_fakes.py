"""Shared test doubles for M5 tool tests."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from tern.tools import ToolAnnotations, ToolContext, ToolResult


class _NopArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: str = ""


class FakeReadOnlyTool:
    """Conforms to Tool Protocol. Read-only; never blocked."""

    name = "fake_read"
    title = "Fake read-only tool"
    description = "A no-op read tool for tests."
    args_model: type[BaseModel] = _NopArgs
    annotations = ToolAnnotations(destructive=False, read_only=True)

    def __init__(self) -> None:
        self.calls: list[_NopArgs] = []

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, _NopArgs)
        self.calls.append(args)
        return ToolResult(ok=True, content=f"read:{args.payload}")


class FakeDestructiveTool:
    """Conforms to Tool Protocol. Destructive; gated."""

    name = "fake_write"
    title = "Fake destructive tool"
    description = "A no-op write tool for tests."
    args_model: type[BaseModel] = _NopArgs
    annotations = ToolAnnotations(destructive=True, read_only=False)

    def __init__(self) -> None:
        self.calls: list[_NopArgs] = []

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, _NopArgs)
        self.calls.append(args)
        return ToolResult(ok=True, content=f"wrote:{args.payload}")
