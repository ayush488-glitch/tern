"""write_file — create a new file or overwrite an existing one.

Closes the demo gap exposed in S13: edit_block can only modify existing files,
so the model couldn't create a new file or scaffold a folder. write_file is
the explicit creation primitive.

Destructive (overwrites). Sandboxed (parents must resolve under repo_root).
Refuses to overwrite an existing file unless `overwrite=True` is passed —
keeps "create new" and "blow away existing" as distinct intents the gate can
weigh independently.

S21: diff preview. When a file exists and overwrite=True, the tool embeds a
unified diff in ToolResult.metadata["pending_diff"] before writing. loop.py
picks this up and emits DiffPreviewEvent; in default mode it prompts the user.
In yolo mode the diff is still computed and logged but no prompt is shown.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tern.loop.diff_preview import line_count, unified_diff
from tern.tools.protocol import (
    Tool,
    ToolAnnotations,
    ToolContext,
    ToolResult,
)

_MAX_BYTES = 1_000_000  # 1 MiB; bigger writes should chunk via edit_block

# In default mode, show diff when changed_lines > this threshold.
_DIFF_THRESHOLD_LINES = 30


class WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Repo-relative or absolute path.")
    content: str = Field(..., description="Full file contents to write (UTF-8).")
    overwrite: bool = Field(
        False,
        description=(
            "If False (default) and the file already exists, the call fails. "
            "Set True only when the user/model explicitly intends to replace "
            "the file."
        ),
    )


class WriteFileTool:
    """Create or overwrite a file. Conforms to Tool Protocol."""

    name = "write_file"
    title = "Write file"
    description = (
        "Create a new file (or overwrite an existing one with overwrite=True). "
        "Parent directories are created automatically. Use edit_block for "
        "targeted changes inside an existing file; use this for new files or "
        "full rewrites. Max 1 MiB."
    )
    args_model: type[BaseModel] = WriteFileArgs
    annotations = ToolAnnotations(
        destructive=True, idempotent=False, read_only=False, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, WriteFileArgs)
        try:
            path = ctx.resolve_under_repo(args.path)
        except PermissionError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        encoded = args.content.encode("utf-8")
        if len(encoded) > _MAX_BYTES:
            return ToolResult(
                ok=False,
                content="",
                error=f"content {len(encoded)} bytes exceeds {_MAX_BYTES} cap",
            )

        existed = path.exists()
        if existed and path.is_dir():
            return ToolResult(
                ok=False, content="", error=f"is a directory: {path}"
            )
        if existed and not args.overwrite:
            return ToolResult(
                ok=False,
                content="",
                error=(
                    f"file exists: {path} (pass overwrite=True to replace, "
                    "or use edit_block for targeted edits)"
                ),
            )

        # ---- S21 diff preview (overwrite only) ------------------------------
        pending_diff: str | None = None
        diff_lines = 0
        if existed and args.overwrite:
            try:
                old_content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                old_content = ""
            pending_diff = unified_diff(old_content, args.content, str(path))
            diff_lines = line_count(pending_diff) if pending_diff else 0

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.content, encoding="utf-8")

        meta: dict[str, object] = {
            "path": str(path),
            "bytes": len(encoded),
            "created": not existed,
        }
        if pending_diff is not None:
            meta["pending_diff"] = pending_diff
            meta["diff_lines"] = diff_lines

        return ToolResult(
            ok=True,
            content=f"{'overwrote' if existed else 'wrote'} {path} ({len(encoded)} bytes)",
            metadata=meta,
        )


__all__ = ["Path", "Tool", "WriteFileArgs", "WriteFileTool"]
