"""edit_block — aider-style search/replace block editor.

Lifted from `.scratch/grounding/refs/aider/aider/coders/editblock_coder.py`
(perfect_or_whitespace + replace_part_with_missing_leading_whitespace) and
ported to a clean, type-checked function. Intentionally narrow: no `...`
elision, no fuzzy edit-distance fallback. Those exist in aider for a reason
(GPT-3-era wobble) but Claude 4 with structured tool calls rarely needs them.

Two strategies in order:
  1. exact match — `search` appears verbatim, exactly once.
  2. whitespace-tolerant — outdent both blocks by the common min indent,
     then exact match again; preserve the original indent on replacement.

Ambiguity (more than one match in either strategy) is a hard error so the
model can re-issue with more context. That's a feature, not a bug.

Destructive. Permission-gated.
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


class EditBlockArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Repo-relative or absolute path.")
    search: str = Field(
        ...,
        description=(
            "Exact text to find. Must match exactly once. Include enough surrounding "
            "context (a few lines) to make the match unambiguous."
        ),
    )
    replace: str = Field(..., description="Replacement text.")


class EditBlockTool:
    """Single search/replace edit. Conforms to Tool Protocol."""

    name = "edit_block"
    title = "Edit block"
    description = (
        "Edit a text file by replacing one exact-match block with new text. "
        "The `search` block must appear exactly once. Include 2-3 lines of "
        "surrounding context for ambiguous code. The file must already exist."
    )
    args_model: type[BaseModel] = EditBlockArgs
    annotations = ToolAnnotations(
        destructive=True, idempotent=False, read_only=False, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, EditBlockArgs)
        try:
            path = ctx.resolve_under_repo(args.path)
        except PermissionError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        if not path.exists():
            return ToolResult(
                ok=False, content="", error=f"file does not exist: {path}"
            )
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(
                ok=False, content="", error=f"binary or non-utf8 file: {path}"
            )

        try:
            new_content = apply_edit_block(original, args.search, args.replace)
        except EditBlockError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        path.write_text(new_content, encoding="utf-8")
        return ToolResult(
            ok=True,
            content=f"edited {path}",
            metadata={
                "path": str(path),
                "bytes_before": len(original),
                "bytes_after": len(new_content),
            },
        )


# ---------------------------------------------------------------------------
# Pure helpers (testable without disk)
# ---------------------------------------------------------------------------


class EditBlockError(Exception):
    """Raised when the edit can't apply unambiguously."""


def apply_edit_block(whole: str, search: str, replace: str) -> str:
    """Apply a single search/replace edit. Pure; raises on ambiguity.

    Tries exact match first, then whitespace-tolerant. Both must match
    exactly once. Multiple matches OR zero matches both raise EditBlockError
    so the model gets a clean failure to react to.
    """
    if not search:
        raise EditBlockError("empty search block")

    # 1. exact match — most common path with structured tool calls.
    count = whole.count(search)
    if count == 1:
        return whole.replace(search, replace, 1)
    if count > 1:
        raise EditBlockError(
            f"search block appears {count} times; add surrounding context"
        )

    # 2. whitespace-tolerant — outdent by common min, match, restore indent.
    result = _replace_with_missing_leading_whitespace(whole, search, replace)
    if result is not None:
        return result

    raise EditBlockError("search block not found in file")


def _replace_with_missing_leading_whitespace(
    whole: str, search: str, replace: str
) -> str | None:
    """Aider's `replace_part_with_missing_leading_whitespace`, ported.

    Outdent both blocks by the common minimum indent, then look for an exact
    line-by-line match in `whole`, ignoring leading whitespace. If found,
    re-apply the original whole-side indent to the replacement.
    """
    whole_lines = whole.splitlines(keepends=True)
    search_lines = search.splitlines(keepends=True)
    replace_lines = replace.splitlines(keepends=True)

    if not search_lines:
        return None

    # Common min indent across non-blank lines in both halves.
    indents = [
        len(line) - len(line.lstrip())
        for line in (*search_lines, *replace_lines)
        if line.strip()
    ]
    if indents and min(indents) > 0:
        n = min(indents)
        search_lines = [
            (line[n:] if line.strip() else line) for line in search_lines
        ]
        replace_lines = [
            (line[n:] if line.strip() else line) for line in replace_lines
        ]

    n_search = len(search_lines)
    matches: list[int] = []
    add_indent = ""
    for i in range(len(whole_lines) - n_search + 1):
        candidate_indent = _match_but_for_leading_whitespace(
            whole_lines[i : i + n_search], search_lines
        )
        if candidate_indent is not None:
            matches.append(i)
            add_indent = candidate_indent

    if len(matches) == 0:
        return None
    if len(matches) > 1:
        raise EditBlockError(
            f"search block whitespace-matches {len(matches)} locations; "
            "add surrounding context"
        )

    i = matches[0]
    new_replace = [
        (add_indent + line if line.strip() else line) for line in replace_lines
    ]
    return "".join(whole_lines[:i] + new_replace + whole_lines[i + n_search :])


def _match_but_for_leading_whitespace(
    whole_chunk: list[str], search_chunk: list[str]
) -> str | None:
    """If the two chunks agree once leading whitespace is stripped, return the
    common added indent (so the caller can re-apply it to the replacement).

    Returns None if they don't match.
    """
    if len(whole_chunk) != len(search_chunk):
        return None
    if any(w.lstrip() != s.lstrip() for w, s in zip(whole_chunk, search_chunk)):
        return None
    indents = {
        w[: len(w) - len(w.lstrip())]
        for w, s in zip(whole_chunk, search_chunk)
        if s.strip()
    }
    # All non-blank source lines must have been re-indented by the SAME prefix.
    if len(indents) != 1:
        return None
    return next(iter(indents))


__all__ = [
    "EditBlockArgs",
    "EditBlockError",
    "EditBlockTool",
    "Path",
    "Tool",
    "apply_edit_block",
]
