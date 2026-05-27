"""notes_append — model-callable tool to append a note row.

Notes are read-only from the repo's perspective (write goes to ~/.tern), so
the gate classifies this non-destructive — no approval prompt in default
mode. The tool stamps the row with the current session_id + turn_idx pulled
from ToolContext, so the artifact can interleave note rows next to the turn
they came from.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from tern.notes.store import append_note
from tern.tools.protocol import (
    ToolAnnotations,
    ToolContext,
    ToolResult,
)


class NotesAppendArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="One line of free-form note.")
    tags: list[str] = Field(default_factory=list, description="Optional tag list.")


class NotesAppendTool:
    """Append one note. Conforms to Tool Protocol."""

    name = "notes_append"
    title = "Append note"
    description = (
        "Append a free-form note to the live HTML artifact for this session. "
        "Use sparingly: a note is something a future reader (or you on replay) "
        "will want highlighted. Examples: a non-obvious decision, a pitfall hit, "
        "a TODO worth surfacing."
    )
    args_model: type[BaseModel] = NotesAppendArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=False, read_only=False, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, NotesAppendArgs)
        note = append_note(
            ctx.session_id,
            args.text.strip(),
            turn_idx=ctx.turn_idx,
            tags=tuple(args.tags),
            cwd=ctx.repo_root,
        )
        return ToolResult(
            ok=True,
            content=f"noted (turn {note.turn_idx}): {note.text}",
            metadata={"turn_idx": note.turn_idx, "tags": list(note.tags)},
        )


__all__ = ["NotesAppendArgs", "NotesAppendTool"]
