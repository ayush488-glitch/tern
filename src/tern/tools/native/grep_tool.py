"""grep — search file contents by regex.

Uses `rg` (ripgrep) if available on PATH; falls back to a Python `re` walker.
Both paths return the same line-oriented shape: `path:line:content`.

Read-only. Sandboxed (search root must be under repo root).
"""

from __future__ import annotations

import re
import shutil
import subprocess
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
_MAX_FILE_BYTES = 1_000_000  # skip files bigger than 1 MiB in fallback walker


class GrepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(..., description="Regex pattern to search for.")
    path: str = Field(".", description="Search root, repo-relative.")
    file_glob: str | None = Field(
        None,
        description="Optional glob to restrict files (e.g. '*.py', '*.md').",
    )
    case_insensitive: bool = Field(False, description="Match case-insensitively.")
    limit: int = Field(
        _DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max matching lines."
    )


class GrepTool:
    """Regex search over files. Conforms to Tool Protocol."""

    name = "grep"
    title = "Search file contents (grep)"
    description = (
        "Regex search across files. Returns 'path:line:content' lines. Uses "
        "ripgrep if available (faster), falls back to Python re. Filter by "
        "file_glob ('*.py', '*.md'). Use glob to find files by name; use "
        "this to search inside them."
    )
    args_model: type[BaseModel] = GrepArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=True, read_only=True, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, GrepArgs)
        try:
            root = ctx.resolve_under_repo(args.path)
        except PermissionError as exc:
            return ToolResult(ok=False, content="", error=str(exc))
        if not root.exists():
            return ToolResult(ok=False, content="", error=f"no such path: {root}")

        repo_root = ctx.repo_root.resolve()
        rg = shutil.which("rg")
        if rg is not None:
            lines, truncated = _rg_search(rg, root, args)
        else:
            try:
                lines, truncated = _re_search(root, args)
            except re.error as exc:
                return ToolResult(
                    ok=False, content="", error=f"bad regex: {exc}"
                )

        # rebase paths to repo-relative
        rebased: list[str] = []
        for ln in lines:
            try:
                head, rest = ln.split(":", 1)
                p = Path(head).resolve()
                rebased.append(f"{p.relative_to(repo_root)}:{rest}")
            except (ValueError, OSError):
                rebased.append(ln)

        body = "\n".join(rebased) if rebased else "(no matches)"
        return ToolResult(
            ok=True,
            content=body,
            metadata={
                "pattern": args.pattern,
                "engine": "rg" if rg else "re",
                "matches": len(rebased),
                "truncated": truncated,
            },
        )


def _rg_search(rg: str, root: Path, args: GrepArgs) -> tuple[list[str], bool]:
    """Shell out to ripgrep; return (lines, truncated)."""
    cmd = [rg, "--no-heading", "--line-number", "--color=never"]
    if args.case_insensitive:
        cmd.append("-i")
    if args.file_glob:
        cmd.extend(["-g", args.file_glob])
    for skip in _SKIP_DIRS:
        cmd.extend(["-g", f"!{skip}"])
    # cap matches to (limit + 1) so we can detect truncation
    cmd.extend(["-m", str(args.limit + 1), "--", args.pattern, str(root)])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired:
        return ([], True)
    out = proc.stdout.splitlines()
    truncated = len(out) > args.limit
    return (out[: args.limit], truncated)


def _re_search(root: Path, args: GrepArgs) -> tuple[list[str], bool]:
    """Pure-Python fallback when rg is not on PATH."""
    flags = re.IGNORECASE if args.case_insensitive else 0
    pat = re.compile(args.pattern, flags)
    out: list[str] = []
    truncated = False
    glob_pat = args.file_glob or "*"
    iter_paths = root.rglob(glob_pat) if root.is_dir() else iter([root])
    for p in iter_paths:
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        try:
            if p.stat().st_size > _MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if pat.search(line):
                out.append(f"{p}:{i}:{line}")
                if len(out) > args.limit:
                    truncated = True
                    return (out[: args.limit], truncated)
    return (out, truncated)


__all__ = ["GrepArgs", "GrepTool", "Tool"]
