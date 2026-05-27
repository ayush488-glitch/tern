"""read_file — read a text file, return numbered lines.

Mirrors the Hermes read_file shape (LINE|content). offset is 1-indexed,
limit caps the slice. Read-only; no permission prompt. Refuses paths outside
repo_root via ToolContext.resolve_under_repo() (ADR-0003 §sandbox-boundaries).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tern.tools.protocol import (
    Tool,
    ToolAnnotations,
    ToolContext,
    ToolResult,
)

_MAX_LINES = 2000


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Repo-relative or absolute path.")
    offset: int = Field(1, ge=1, description="1-indexed first line.")
    limit: int = Field(500, ge=1, le=_MAX_LINES, description="Max lines to return.")


class ReadFileTool:
    """Read a slice of a text file. Conforms to Tool Protocol."""

    name = "read_file"
    title = "Read file"
    description = (
        "Read a text file and return numbered lines. Format: 'LINE|CONTENT'. "
        "Use offset and limit to page large files."
    )
    args_model: type[BaseModel] = ReadFileArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=True, read_only=True, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, ReadFileArgs)
        try:
            path = ctx.resolve_under_repo(args.path)
        except PermissionError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        if not path.exists():
            return ToolResult(ok=False, content="", error=f"no such file: {path}")
        if path.is_dir():
            return ToolResult(ok=False, content="", error=f"is a directory: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(
                ok=False, content="", error=f"binary or non-utf8 file: {path}"
            )

        lines = text.splitlines()
        start = args.offset - 1
        end = start + args.limit
        slice_ = lines[start:end]
        body = "\n".join(f"{start + i + 1}|{line}" for i, line in enumerate(slice_))
        return ToolResult(
            ok=True,
            content=body,
            metadata={
                "path": str(path),
                "total_lines": len(lines),
                "returned": len(slice_),
            },
        )


__all__ = ["ReadFileArgs", "ReadFileTool", "Path", "Tool"]
