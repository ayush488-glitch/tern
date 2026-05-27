"""glob — find files by glob pattern under repo root.

Pure stdlib (`pathlib.Path.rglob` / `glob.glob`). Skips a small set of obvious
junk dirs (`.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`)
without trying to be a full .gitignore reader — that's a separate dependency
(`pathspec`) and an obvious next step, not S14 scope.

Read-only. Sandboxed.
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

_SKIP_DIRS = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tern",
})

_DEFAULT_LIMIT = 200
_MAX_LIMIT = 2000


class GlobArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(
        ...,
        description=(
            "Glob pattern, e.g. '**/*.py' or 'src/**/test_*.py'. "
            "Always evaluated relative to the search root."
        ),
    )
    path: str = Field(
        ".", description="Search root, repo-relative (default: repo root)."
    )
    limit: int = Field(
        _DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT,
        description="Max paths to return.",
    )


class GlobTool:
    """List files matching a glob pattern. Conforms to Tool Protocol."""

    name = "glob"
    title = "Find files (glob)"
    description = (
        "Find files matching a glob pattern (e.g. '**/*.py'). Skips .git, "
        "node_modules, __pycache__, .venv, dist, build, .tern, and various "
        "tool caches. Returns repo-relative paths sorted by mtime (newest "
        "first). Use grep to search inside the matched files."
    )
    args_model: type[BaseModel] = GlobArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=True, read_only=True, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, GlobArgs)
        try:
            root = ctx.resolve_under_repo(args.path)
        except PermissionError as exc:
            return ToolResult(ok=False, content="", error=str(exc))
        if not root.exists():
            return ToolResult(ok=False, content="", error=f"no such path: {root}")
        if not root.is_dir():
            return ToolResult(ok=False, content="", error=f"not a directory: {root}")

        repo_root = ctx.repo_root.resolve()
        matches: list[Path] = []
        for p in root.glob(args.pattern):
            if not p.is_file():
                continue
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            matches.append(p)

        # newest-first by mtime; stable on ties via path string.
        matches.sort(key=lambda p: (-p.stat().st_mtime, str(p)))
        truncated = len(matches) > args.limit
        matches = matches[: args.limit]

        rels = [str(p.resolve().relative_to(repo_root)) for p in matches]
        body = "\n".join(rels) if rels else "(no matches)"
        return ToolResult(
            ok=True,
            content=body,
            metadata={
                "pattern": args.pattern,
                "root": str(root),
                "count": len(rels),
                "truncated": truncated,
            },
        )


__all__ = ["GlobArgs", "GlobTool", "Tool"]
