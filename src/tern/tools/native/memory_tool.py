"""memory — model-callable tool for persistent MEMORY.md / USER.md edits.

Three actions x two targets, mirroring the Hermes contract:
    add | replace | remove   x   memory | user

Writes are atomic (memory/store.py). The tool is non-destructive in the
sandbox sense — it only touches files under ~/.tern/memory/ — but it is
PERSISTENT across sessions, so we mark it `destructive=False` and leave it
unprompted. Misuse is recoverable via `replace`/`remove`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from tern.memory.store import (
    add_entry,
    remove_entry,
    replace_entry,
)
from tern.tools.protocol import (
    ToolAnnotations,
    ToolContext,
    ToolResult,
)


class MemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        ...,
        description="One of: add | replace | remove.",
    )
    target: str = Field(
        ...,
        description="Which file: 'memory' (procedural notes) or 'user' (user profile).",
    )
    content: str | None = Field(
        None,
        description="Required for add/replace. The full new entry text (one cohesive note).",
    )
    old_text: str | None = Field(
        None,
        description="Required for replace/remove. A short unique substring identifying the entry.",
    )


class MemoryTool:
    """Write durable cross-session memory."""

    name = "memory"
    title = "Edit memory"
    description = (
        "Persist a cross-session fact to MEMORY.md (your notes) or USER.md "
        "(who the user is). Use 'add' for a brand-new entry, 'replace' to "
        "update an existing one (old_text identifies it), 'remove' to delete. "
        "Save: user preferences, environment quirks, project conventions, "
        "stable corrections. SKIP: task progress, today's TODO, transient state."
    )
    args_model: type[BaseModel] = MemoryArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=False, read_only=False, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, MemoryArgs)
        if args.target not in ("memory", "user"):
            return ToolResult(
                ok=False, content="", error=f"unknown target: {args.target!r}"
            )
        target: str = args.target
        try:
            if args.action == "add":
                if not args.content:
                    return ToolResult(
                        ok=False, content="", error="add requires `content`"
                    )
                snap = add_entry(target, args.content)  # type: ignore[arg-type]
                msg = f"added entry to {target} ({len(snap.entries)} total)"
            elif args.action == "replace":
                if not args.old_text or not args.content:
                    return ToolResult(
                        ok=False,
                        content="",
                        error="replace requires both `old_text` and `content`",
                    )
                snap = replace_entry(target, args.old_text, args.content)  # type: ignore[arg-type]
                msg = f"replaced entry in {target}"
            elif args.action == "remove":
                if not args.old_text:
                    return ToolResult(
                        ok=False, content="", error="remove requires `old_text`"
                    )
                snap = remove_entry(target, args.old_text)  # type: ignore[arg-type]
                msg = f"removed entry from {target} ({len(snap.entries)} remaining)"
            else:
                return ToolResult(
                    ok=False,
                    content="",
                    error=f"unknown action: {args.action!r}; expected add|replace|remove",
                )
        except (LookupError, ValueError) as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        warning = ""
        if snap.over_cap:
            warning = (
                f"  ⚠ {target} is now {snap.char_count}/{snap.cap} chars — "
                "consider consolidating or removing stale entries."
            )
        return ToolResult(
            ok=True,
            content=msg + warning,
            metadata={
                "target": target,
                "entries": len(snap.entries),
                "char_count": snap.char_count,
                "over_cap": snap.over_cap,
            },
        )


__all__ = ["MemoryArgs", "MemoryTool"]
