"""bash — run a shell command in the repo sandbox.

The most powerful tool we ship and the one that earns the gate's keep.
Three lines of defense:
  1. registry filter: bash is destructive=True, open_world=True. In safe mode
     it never reaches the model's tool list.
  2. deny-list: a small set of obvious foot-guns ('rm -rf /', 'curl ... | sh',
     fork bombs, dd to /dev) raise ToolBlocked-style errors before subprocess.
  3. permission gate: in default mode the user is prompted per-call (unless
     prompter is a yes-man, which is the user's choice).

Everything runs through `bash -lc` with cwd pinned to repo_root, a hard
timeout, and an output byte cap. Stdout/stderr come back interleaved so the
model sees what a human would see in a terminal.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil

from pydantic import BaseModel, ConfigDict, Field

from tern.tools.protocol import (
    Tool,
    ToolAnnotations,
    ToolContext,
    ToolResult,
)

_DEFAULT_TIMEOUT_S = 60.0
_MAX_TIMEOUT_S = 600.0
_MAX_OUTPUT_BYTES = 200_000  # 200 KiB; bigger output truncated with marker

# Patterns we refuse outright. Cheap regex pre-screen, not a sandbox — a
# determined model can still cause damage; this catches accidents.
_DENY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+)?/(\s|$)"),    # rm -rf /
    re.compile(r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+)?(--no-preserve-root)"),
    re.compile(r"\bdd\s+.*\bof=/dev/(sd|nvme|disk|hd)"),
    re.compile(r"\bmkfs\."),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:&\s*\}"),                   # fork bomb
    re.compile(r"\bcurl\b[^|;]*\|\s*(bash|sh|zsh|python|perl)"),    # curl|sh
    re.compile(r"\bwget\b[^|;]*\|\s*(bash|sh|zsh|python|perl)"),    # wget|sh
    re.compile(r"\bchmod\s+-R\s+777\s+/"),
    re.compile(r"\bchown\s+-R\s+.*\s+/(\s|$)"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"\bsudo\s+rm\s+(-[a-zA-Z]*[rRf])"),
)


class BashArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(
        ...,
        description=(
            "Shell command to run. Executed via 'bash -lc' with cwd pinned "
            "to the repo root. Stdout and stderr are returned interleaved."
        ),
    )
    timeout: float = Field(
        _DEFAULT_TIMEOUT_S,
        gt=0.0,
        le=_MAX_TIMEOUT_S,
        description="Hard timeout in seconds (max 600).",
    )
    workdir: str | None = Field(
        None,
        description=(
            "Optional repo-relative cwd override. Must resolve under the repo "
            "root; absolute paths outside are refused."
        ),
    )


class BashTool:
    """Run a bash command. Destructive, open-world, gated."""

    name = "bash"
    title = "Run shell command"
    description = (
        "Run a bash command in the repo sandbox. Use for builds, tests, git, "
        "package managers, file moves/deletes — anything edit_block and "
        "write_file can't express directly. Hard 600s timeout, 200 KiB "
        "output cap (truncated with a marker if exceeded). Refuses obvious "
        "foot-guns (rm -rf /, curl|sh, fork bombs)."
    )
    args_model: type[BaseModel] = BashArgs
    annotations = ToolAnnotations(
        destructive=True, idempotent=False, read_only=False, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, BashArgs)

        for pat in _DENY_PATTERNS:
            if pat.search(args.command):
                return ToolResult(
                    ok=False,
                    content="",
                    error=f"refused: command matches deny pattern {pat.pattern!r}",
                )

        cwd = ctx.repo_root.resolve()
        if args.workdir is not None:
            try:
                cwd = ctx.resolve_under_repo(args.workdir)
            except PermissionError as exc:
                return ToolResult(ok=False, content="", error=str(exc))
            if not cwd.is_dir():
                return ToolResult(
                    ok=False, content="", error=f"workdir not a directory: {cwd}"
                )

        bash = shutil.which("bash")
        if bash is None:
            return ToolResult(
                ok=False, content="", error="bash not found on PATH"
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                bash, "-lc", args.command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            return ToolResult(ok=False, content="", error=f"spawn failed: {exc}")

        async def _read_capped() -> tuple[bytes, bool]:
            """Read until EOF or cap+1 bytes (so we can detect truncation)."""
            assert proc.stdout is not None
            buf = bytearray()
            cap = _MAX_OUTPUT_BYTES
            while len(buf) <= cap:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    return (bytes(buf), False)
                buf.extend(chunk)
            return (bytes(buf), True)

        try:
            stdout_bytes, hit_cap = await asyncio.wait_for(
                _read_capped(), timeout=args.timeout
            )
            if hit_cap:
                proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=args.timeout)
        except (TimeoutError, asyncio.TimeoutError):
            proc.kill()
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            return ToolResult(
                ok=False,
                content="",
                error=f"timed out after {args.timeout}s",
                metadata={"timed_out": True, "cwd": str(cwd)},
            )

        truncated = hit_cap or len(stdout_bytes) > _MAX_OUTPUT_BYTES
        if truncated:
            stdout_bytes = stdout_bytes[:_MAX_OUTPUT_BYTES]
        try:
            output = stdout_bytes.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover — decode with errors=replace can't raise
            output = stdout_bytes.decode("latin-1", errors="replace")
        if truncated:
            output += (
                f"\n[... output truncated at {_MAX_OUTPUT_BYTES} bytes ...]"
            )

        rc = proc.returncode if proc.returncode is not None else -1
        return ToolResult(
            ok=rc == 0,
            content=output,
            error=None if rc == 0 else f"exit {rc}",
            metadata={
                "exit_code": rc,
                "cwd": str(cwd),
                "truncated": truncated,
                "bytes": len(stdout_bytes),
            },
        )


__all__ = ["BashArgs", "BashTool", "Tool"]
