"""skill_manage — model-callable tool to author SKILL.md files.

Mirrors the Hermes `skill_manage` surface so the model already knows how to
drive it:
    create | patch | edit | delete | write_file | remove_file

User-scope skills live at `~/.tern/skills/<name>/`; project-scope at
`<repo>/.tern/skills/<name>/` (project wins on collision — see ADR-0006).
Default scope is `user` because skills are reusable across repos.

The tool is non-destructive at the sandbox level — it only writes inside the
two skill roots — so we leave it unprompted. Misuse is recoverable via the
same tool surface.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tern.obs.paths import tern_home
from tern.tools.protocol import (
    ToolAnnotations,
    ToolContext,
    ToolResult,
)

Action = Literal[
    "create", "patch", "edit", "delete", "write_file", "remove_file"
]
Scope = Literal["user", "project"]

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ALLOWED_FILE_PREFIXES = ("references/", "templates/", "scripts/", "assets/")


def _user_skills_dir() -> Path:
    d = tern_home() / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _project_skills_dir(repo: Path) -> Path:
    d = repo / ".tern" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _root_for(scope: Scope, repo: Path) -> Path:
    if scope == "project":
        return _project_skills_dir(repo)
    return _user_skills_dir()


def _validate_name(name: str) -> str | None:
    if not _NAME_RE.match(name):
        return f"invalid skill name: {name!r} (lowercase, [a-z0-9_-], max 64 chars)"
    return None


def _validate_file_path(file_path: str) -> str | None:
    if not file_path or file_path.startswith("/") or ".." in Path(file_path).parts:
        return f"file_path must be a relative path under the skill dir: {file_path!r}"
    if not file_path.startswith(_ALLOWED_FILE_PREFIXES):
        return (
            f"file_path must live under one of {list(_ALLOWED_FILE_PREFIXES)}, "
            f"got {file_path!r}"
        )
    return None


class SkillManageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        ...,
        description=(
            "One of: create | patch | edit | delete | write_file | remove_file."
        ),
    )
    name: str = Field(
        ...,
        description="Skill name (lowercase, hyphens/underscores, max 64 chars).",
    )
    scope: str = Field(
        "user",
        description="'user' (default; ~/.tern/skills) or 'project' (.tern/skills).",
    )
    content: str | None = Field(
        None,
        description=(
            "For create/edit: full SKILL.md content (YAML frontmatter + body)."
        ),
    )
    old_string: str | None = Field(
        None, description="For patch: exact text to find."
    )
    new_string: str | None = Field(
        None,
        description="For patch: replacement text. Empty string deletes the matched text.",
    )
    replace_all: bool = Field(
        False, description="For patch: replace all occurrences (default: false)."
    )
    file_path: str | None = Field(
        None,
        description=(
            "For write_file/remove_file: relative path under the skill dir, "
            "must start with references/, templates/, scripts/, or assets/. "
            "For patch: optional, defaults to SKILL.md."
        ),
    )
    file_content: str | None = Field(
        None, description="For write_file: full content of the supporting file."
    )


class SkillManageTool:
    """Author and edit SKILL.md files."""

    name = "skill_manage"
    title = "Manage skills"
    description = (
        "Create / edit / delete a skill, or manage its supporting files. "
        "Scope is 'user' (cross-repo, default) or 'project' (this repo only). "
        "Actions: create (new SKILL.md), patch (find/replace inside a file), "
        "edit (full SKILL.md rewrite), delete (remove the whole skill dir), "
        "write_file/remove_file (supporting files under references/, templates/, "
        "scripts/, assets/)."
    )
    args_model: type[BaseModel] = SkillManageArgs
    annotations = ToolAnnotations(
        destructive=False, idempotent=False, read_only=False, open_world=False
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, SkillManageArgs)

        err = _validate_name(args.name)
        if err:
            return ToolResult(ok=False, content="", error=err)
        if args.scope not in ("user", "project"):
            return ToolResult(
                ok=False, content="", error=f"unknown scope: {args.scope!r}"
            )
        scope: Scope = args.scope  # type: ignore[assignment]
        root = _root_for(scope, ctx.repo_root)
        skill_dir = root / args.name
        skill_md = skill_dir / "SKILL.md"

        action = args.action
        try:
            if action == "create":
                if not args.content:
                    return ToolResult(
                        ok=False, content="", error="create requires `content`"
                    )
                if skill_md.exists():
                    return ToolResult(
                        ok=False,
                        content="",
                        error=f"skill already exists at {skill_md}; use 'edit' or 'patch'",
                    )
                skill_dir.mkdir(parents=True, exist_ok=True)
                skill_md.write_text(args.content, encoding="utf-8")
                return ToolResult(
                    ok=True,
                    content=f"created {scope}-scope skill {args.name!r} at {skill_md}",
                    metadata={"path": str(skill_md), "scope": scope},
                )

            if action == "edit":
                if not args.content:
                    return ToolResult(
                        ok=False, content="", error="edit requires `content`"
                    )
                if not skill_md.exists():
                    return ToolResult(
                        ok=False, content="", error=f"no skill at {skill_md}"
                    )
                skill_md.write_text(args.content, encoding="utf-8")
                return ToolResult(
                    ok=True,
                    content=f"rewrote {args.name!r} SKILL.md ({len(args.content)} chars)",
                    metadata={"path": str(skill_md)},
                )

            if action == "delete":
                if not skill_dir.exists():
                    return ToolResult(
                        ok=False, content="", error=f"no skill at {skill_dir}"
                    )
                # depth-first remove, no symlink follow
                count = 0
                for p in sorted(
                    skill_dir.rglob("*"), key=lambda x: len(x.parts), reverse=True
                ):
                    if p.is_file() or p.is_symlink():
                        p.unlink()
                        count += 1
                    elif p.is_dir():
                        p.rmdir()
                skill_dir.rmdir()
                return ToolResult(
                    ok=True,
                    content=f"deleted skill {args.name!r} ({count} files removed)",
                    metadata={"removed_files": count},
                )

            if action == "patch":
                if args.old_string is None or args.new_string is None:
                    return ToolResult(
                        ok=False,
                        content="",
                        error="patch requires `old_string` and `new_string`",
                    )
                target_path = (
                    skill_dir / args.file_path if args.file_path else skill_md
                )
                if args.file_path is not None:
                    err = _validate_file_path(args.file_path)
                    if err:
                        return ToolResult(ok=False, content="", error=err)
                if not target_path.exists():
                    return ToolResult(
                        ok=False, content="", error=f"no such file: {target_path}"
                    )
                old = target_path.read_text("utf-8")
                count = old.count(args.old_string)
                if count == 0:
                    return ToolResult(
                        ok=False,
                        content="",
                        error=f"old_string not found in {target_path}",
                    )
                if count > 1 and not args.replace_all:
                    return ToolResult(
                        ok=False,
                        content="",
                        error=(
                            f"old_string matches {count} times; "
                            "set replace_all=true or extend the match"
                        ),
                    )
                new = old.replace(args.old_string, args.new_string)
                target_path.write_text(new, encoding="utf-8")
                return ToolResult(
                    ok=True,
                    content=f"patched {target_path} ({count} occurrence(s))",
                    metadata={"path": str(target_path), "occurrences": count},
                )

            if action == "write_file":
                if not args.file_path:
                    return ToolResult(
                        ok=False, content="", error="write_file requires `file_path`"
                    )
                if args.file_content is None:
                    return ToolResult(
                        ok=False,
                        content="",
                        error="write_file requires `file_content`",
                    )
                err = _validate_file_path(args.file_path)
                if err:
                    return ToolResult(ok=False, content="", error=err)
                if not skill_dir.exists():
                    return ToolResult(
                        ok=False,
                        content="",
                        error=f"no skill at {skill_dir}; create it first",
                    )
                target_path = skill_dir / args.file_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(args.file_content, encoding="utf-8")
                return ToolResult(
                    ok=True,
                    content=f"wrote {target_path} ({len(args.file_content)} chars)",
                    metadata={"path": str(target_path)},
                )

            if action == "remove_file":
                if not args.file_path:
                    return ToolResult(
                        ok=False,
                        content="",
                        error="remove_file requires `file_path`",
                    )
                err = _validate_file_path(args.file_path)
                if err:
                    return ToolResult(ok=False, content="", error=err)
                target_path = skill_dir / args.file_path
                if not target_path.exists():
                    return ToolResult(
                        ok=False, content="", error=f"no such file: {target_path}"
                    )
                target_path.unlink()
                return ToolResult(
                    ok=True,
                    content=f"removed {target_path}",
                    metadata={"path": str(target_path)},
                )

            return ToolResult(
                ok=False, content="", error=f"unknown action: {action!r}"
            )
        except OSError as exc:
            return ToolResult(ok=False, content="", error=f"io error: {exc}")


__all__ = ["SkillManageArgs", "SkillManageTool"]
