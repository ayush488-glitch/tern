"""read_file — read a text file, return numbered lines.

Mirrors the Hermes read_file shape (LINE|content). offset is 1-indexed,
limit caps the slice. Read-only; no permission prompt. Refuses paths outside
repo_root via ToolContext.resolve_under_repo() (ADR-0003 §sandbox-boundaries).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tern.loop.read_cache import get_session_cache
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

        # ---- S21 read cache: skip disk read if content unchanged --------------
        # Only cache whole-file reads (offset=1, limit=_MAX_LINES) — partial
        # reads are cheap and usually unique, caching them adds complexity.
        is_full_read = args.offset == 1 and args.limit == _MAX_LINES
        if is_full_read:
            cache = get_session_cache()
            entry = cache.get(path)
            if entry is not None:
                # Slice the cached numbered-lines body to honour offset/limit.
                return ToolResult(
                    ok=True,
                    content=entry.content,
                    metadata={
                        "path": str(path),
                        "total_lines": entry.total_lines,
                        "returned": entry.total_lines,
                        "cached": True,
                        "sha256": entry.sha256,
                        "first_read_turn": entry.turn_idx,
                    },
                )

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

        # Store full-file read in cache for future hits.
        if is_full_read:
            sha = get_session_cache().put(
                path, body, ctx.turn_idx, len(lines)
            )
            metadata: dict[str, object] = {
                "path": str(path),
                "total_lines": len(lines),
                "returned": len(slice_),
                "cached": False,
                "sha256": sha,
            }
        else:
            metadata = {
                "path": str(path),
                "total_lines": len(lines),
                "returned": len(slice_),
            }

        return ToolResult(ok=True, content=body, metadata=metadata)


__all__ = ["Path", "ReadFileArgs", "ReadFileTool", "Tool"]
