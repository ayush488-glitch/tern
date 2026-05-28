"""memory — model-callable tool for persistent MEMORY.md / USER.md edits
(global scope) and <repo>/.tern/memory/{ARCH,DECISIONS,FAILURES,REVIEWERS}.md
(repo scope, S17).

Actions x targets:
    scope="global"  (default)  add | replace | remove   x   memory | user
    scope="repo"               add | replace | remove   x   arch | decisions |
                                                            failures | reviewers

Writes are atomic (memory/store.py, memory/repo_store.py). Both scopes are
non-destructive in the sandbox sense but PERSISTENT across sessions.
Repo scope requires the tool to be running inside a detectable repo root
(.git or .tern directory). If no root is found the call returns an error.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tern.memory.repo_store import (
    REPO_TARGETS,
    add_repo_entry,
    remove_repo_entry,
    replace_repo_entry,
)
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

_GLOBAL_TARGETS = ("memory", "user")
_REPO_TARGETS = set(REPO_TARGETS)


class MemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        ...,
        description="One of: add | replace | remove.",
    )
    target: str = Field(
        ...,
        description=(
            "global scope: 'memory' (procedural notes) or 'user' (user profile). "
            "repo scope: 'arch', 'decisions', 'failures', or 'reviewers'."
        ),
    )
    content: str | None = Field(
        None,
        description="Required for add/replace. The full new entry text (one cohesive note).",
    )
    old_text: str | None = Field(
        None,
        description="Required for replace/remove. A short unique substring identifying the entry.",
    )
    scope: str = Field(
        "global",
        description=(
            "Which memory tier to write to: 'global' (default, ~/.tern/memory/) "
            "or 'repo' (<repo_root>/.tern/memory/). "
            "repo requires a .git or .tern directory in the current or parent directories."
        ),
    )


class MemoryTool:
    """Write durable cross-session memory — global or repo-scoped."""

    name = "memory"
    title = "Edit memory"
    description = (
        "Persist a cross-session fact. "
        "scope='global' (default): writes to MEMORY.md (your notes) or USER.md "
        "(who the user is). scope='repo': writes to the current repo's "
        ".tern/memory/{ARCH,DECISIONS,FAILURES,REVIEWERS}.md. "
        "Use 'add' for a brand-new entry, 'replace' to update an existing one "
        "(old_text identifies it), 'remove' to delete. "
        "Save: user preferences, environment quirks, project conventions, "
        "repo architecture notes, failure patterns. "
        "SKIP: task progress, today's TODO, transient state."
    )
    args_model: type[BaseModel] = MemoryArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=False, read_only=False, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, MemoryArgs)

        if args.scope not in ("global", "repo"):
            return ToolResult(
                ok=False, content="", error=f"unknown scope: {args.scope!r}; expected global|repo"
            )

        if args.scope == "repo":
            return await self._invoke_repo(args, ctx)
        return await self._invoke_global(args, ctx)

    async def _invoke_global(self, args: MemoryArgs, ctx: ToolContext) -> ToolResult:
        if args.target not in _GLOBAL_TARGETS:
            return ToolResult(
                ok=False,
                content="",
                error=(
                    f"unknown target for global scope: {args.target!r}; "
                    "expected memory|user"
                ),
            )
        target: str = args.target
        try:
            if args.action == "add":
                if not args.content:
                    return ToolResult(ok=False, content="", error="add requires `content`")
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
                    return ToolResult(ok=False, content="", error="remove requires `old_text`")
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
                "scope": "global",
                "target": target,
                "entries": len(snap.entries),
                "char_count": snap.char_count,
                "over_cap": snap.over_cap,
            },
        )

    async def _invoke_repo(self, args: MemoryArgs, ctx: ToolContext) -> ToolResult:
        if args.target not in _REPO_TARGETS:
            return ToolResult(
                ok=False,
                content="",
                error=(
                    f"unknown target for repo scope: {args.target!r}; "
                    "expected arch|decisions|failures|reviewers"
                ),
            )

        # Repo root detection: prefer ctx.repo_root (already resolved by CLI)
        # then fall back to find_repo_root from cwd.
        repo_root: Path | None = None
        if ctx.repo_root and ctx.repo_root != Path("."):
            # Check whether it actually looks like a repo root
            from tern.memory.repo_store import find_repo_root as _frr
            candidate = ctx.repo_root.resolve()
            if (candidate / ".git").exists() or (candidate / ".tern").exists():
                repo_root = candidate
            else:
                # walk up from repo_root
                repo_root = _frr(candidate)
        if repo_root is None:
            from tern.memory.repo_store import find_repo_root as _frr
            repo_root = _frr(None)

        if repo_root is None:
            return ToolResult(
                ok=False,
                content="",
                error=(
                    "no repo root found (no .git or .tern directory in current "
                    "or parent directories). Use scope='global' for user-wide memory."
                ),
            )

        target = args.target
        try:
            if args.action == "add":
                if not args.content:
                    return ToolResult(ok=False, content="", error="add requires `content`")
                entries = add_repo_entry(target, args.content, repo_root)
                msg = f"added entry to repo/{target} ({len(entries)} total)"
            elif args.action == "replace":
                if not args.old_text or not args.content:
                    return ToolResult(
                        ok=False,
                        content="",
                        error="replace requires both `old_text` and `content`",
                    )
                entries = replace_repo_entry(target, args.old_text, args.content, repo_root)
                msg = f"replaced entry in repo/{target}"
            elif args.action == "remove":
                if not args.old_text:
                    return ToolResult(ok=False, content="", error="remove requires `old_text`")
                entries = remove_repo_entry(target, args.old_text, repo_root)
                msg = f"removed entry from repo/{target} ({len(entries)} remaining)"
            else:
                return ToolResult(
                    ok=False,
                    content="",
                    error=f"unknown action: {args.action!r}; expected add|replace|remove",
                )
        except (LookupError, ValueError) as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        return ToolResult(
            ok=True,
            content=msg,
            metadata={
                "scope": "repo",
                "target": target,
                "repo_root": str(repo_root),
                "entries": len(entries),
            },
        )


__all__ = ["MemoryArgs", "MemoryTool"]
