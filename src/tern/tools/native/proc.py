"""proc — background process manager (S21 / ADR-0012 §3).

Mirrors Hermes's process() tool. Long-lived servers (dev watchers, daemons)
start in the background; the agent continues to curl/test in the same turn.

Actions:
  start   — launch a command in the background, return session_id
  poll    — return new output lines since last poll
  wait    — block until process exits (or timeout)
  kill    — terminate the process
  log     — return full output (paginated)
  list    — list all live processes for this tern session

Per-session process registry (in-memory dict). ADR-0009 bash deny-list
extends to proc start.

Security: proc start is destructive=True, open_world=True — same as bash.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tern.tools.protocol import (
    ToolAnnotations,
    ToolContext,
    ToolResult,
)

# Reuse bash deny-list patterns.
_DENY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+)?/(\s|$)"),
    re.compile(r"curl\s+.*\|\s*(ba)?sh"),
    re.compile(r":\(\)\s*\{.*\}"),
    re.compile(r"\bdd\b.*of=/dev/(sd|nvme|vd)"),
)

_DEFAULT_TIMEOUT_S = 30.0
_MAX_WAIT_S = 300.0
_MAX_OUTPUT_BYTES = 200_000
_POLL_LINES = 50


def _check_deny(command: str) -> str | None:
    """Return a denial reason or None if the command is allowed."""
    for pat in _DENY_PATTERNS:
        if pat.search(command):
            return f"command blocked by deny-list: {pat.pattern!r}"
    return None


@dataclass
class _ProcEntry:
    session_id: str
    command: str
    proc: asyncio.subprocess.Process
    output_lines: list[str] = field(default_factory=list)
    _poll_cursor: int = field(default=0, init=False)
    started_at: float = field(default_factory=time.time)

    @property
    def pid(self) -> int | None:
        return self.proc.pid

    @property
    def returncode(self) -> int | None:
        return self.proc.returncode

    def is_running(self) -> bool:
        return self.proc.returncode is None


# Module-level per-session registry (keyed by tern session_id then proc_id).
_REGISTRY: dict[str, _ProcEntry] = {}
_COUNTER = 0


def _make_proc_id(session_id: str) -> str:
    global _COUNTER
    _COUNTER += 1
    short = session_id[:8] if session_id else "x"
    return f"proc-{short}-{_COUNTER}"


def _get_proc(proc_id: str) -> _ProcEntry | None:
    return _REGISTRY.get(proc_id)


class ProcArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["start", "poll", "wait", "kill", "log", "list"] = Field(
        ...,
        description=(
            "start: launch command. poll: new output since last poll. "
            "wait: block until done. kill: terminate. log: full output. "
            "list: show all procs."
        ),
    )
    command: str | None = Field(
        None, description="Shell command (required for start)."
    )
    session_id: str | None = Field(
        None,
        description="Process session_id returned by start (required for poll/wait/kill/log).",
    )
    timeout: float = Field(
        _DEFAULT_TIMEOUT_S,
        ge=0.1,
        le=_MAX_WAIT_S,
        description="Timeout seconds for wait action.",
    )
    offset: int = Field(0, ge=0, description="Line offset for log action.")
    limit: int = Field(200, ge=1, le=2000, description="Max lines for log action.")


class ProcTool:
    """Background process manager. Conforms to Tool Protocol."""

    name = "proc"
    title = "Background process"
    description = (
        "Start, poll, wait, kill, or inspect background shell processes. "
        "Use start to launch a long-running server; use poll/wait to check progress. "
        "proc start shares bash's deny-list (no rm -rf /, no curl|sh, etc.)."
    )
    args_model: type[BaseModel] = ProcArgs
    annotations = ToolAnnotations(
        destructive=True, idempotent=False, read_only=False, open_world=True
    )

    async def invoke(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(args, ProcArgs)

        if args.action == "start":
            return await self._start(args, ctx)
        if args.action == "list":
            return self._list(ctx)
        # All other actions require session_id.
        if not args.session_id:
            return ToolResult(
                ok=False,
                content="",
                error=f"action={args.action!r} requires session_id",
            )
        entry = _get_proc(args.session_id)
        if entry is None:
            return ToolResult(
                ok=False,
                content="",
                error=f"no proc with session_id={args.session_id!r}",
            )
        if args.action == "poll":
            return self._poll(entry)
        if args.action == "wait":
            return await self._wait(entry, args.timeout)
        if args.action == "kill":
            return await self._kill(entry)
        if args.action == "log":
            return self._log(entry, args.offset, args.limit)
        return ToolResult(ok=False, content="", error=f"unknown action: {args.action!r}")

    # ── actions ───────────────────────────────────────────────────────────────

    async def _start(self, args: ProcArgs, ctx: ToolContext) -> ToolResult:
        if not args.command:
            return ToolResult(ok=False, content="", error="command is required for start")
        deny = _check_deny(args.command)
        if deny:
            return ToolResult(ok=False, content="", error=deny)

        proc_id = _make_proc_id(ctx.session_id)
        try:
            proc = await asyncio.create_subprocess_shell(
                args.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(ctx.repo_root) if ctx.repo_root else None,
            )
        except OSError as exc:
            return ToolResult(ok=False, content="", error=f"failed to start: {exc}")

        entry = _ProcEntry(session_id=proc_id, command=args.command, proc=proc)
        _REGISTRY[proc_id] = entry

        # Kick off a background reader coroutine to drain stdout.
        _drain_task = asyncio.ensure_future(_drain(entry))
        del _drain_task  # task runs in background; reference kept by event loop

        return ToolResult(
            ok=True,
            content=f"started (pid={proc.pid}, session_id={proc_id!r})",
            metadata={
                "session_id": proc_id,
                "pid": proc.pid,
                "command": args.command,
            },
        )

    def _poll(self, entry: _ProcEntry) -> ToolResult:
        new_lines = entry.output_lines[entry._poll_cursor:]
        entry._poll_cursor = len(entry.output_lines)
        status = "running" if entry.is_running() else f"exited({entry.returncode})"
        return ToolResult(
            ok=True,
            content="\n".join(new_lines) if new_lines else "(no new output)",
            metadata={
                "session_id": entry.session_id,
                "status": status,
                "new_lines": len(new_lines),
            },
        )

    async def _wait(self, entry: _ProcEntry, timeout: float) -> ToolResult:
        try:
            await asyncio.wait_for(entry.proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return ToolResult(
                ok=True,
                content=f"timed out after {timeout}s — process still running",
                metadata={"session_id": entry.session_id, "status": "timeout"},
            )
        rc = entry.returncode
        tail = "\n".join(entry.output_lines[-20:])
        return ToolResult(
            ok=True,
            content=f"exited({rc})\n{tail}",
            metadata={"session_id": entry.session_id, "returncode": rc},
        )

    async def _kill(self, entry: _ProcEntry) -> ToolResult:
        if not entry.is_running():
            return ToolResult(
                ok=True,
                content=f"already exited({entry.returncode})",
                metadata={"session_id": entry.session_id},
            )
        try:
            entry.proc.kill()
            await asyncio.wait_for(entry.proc.wait(), timeout=5.0)
        except (ProcessLookupError, asyncio.TimeoutError):
            pass
        _REGISTRY.pop(entry.session_id, None)
        return ToolResult(
            ok=True,
            content=f"killed pid={entry.pid}",
            metadata={"session_id": entry.session_id},
        )

    def _log(self, entry: _ProcEntry, offset: int, limit: int) -> ToolResult:
        slice_ = entry.output_lines[offset : offset + limit]
        status = "running" if entry.is_running() else f"exited({entry.returncode})"
        return ToolResult(
            ok=True,
            content="\n".join(slice_),
            metadata={
                "session_id": entry.session_id,
                "status": status,
                "total_lines": len(entry.output_lines),
                "returned": len(slice_),
            },
        )

    def _list(self, ctx: ToolContext) -> ToolResult:
        rows = []
        for pid, e in _REGISTRY.items():
            status = "running" if e.is_running() else f"exited({e.returncode})"
            rows.append(f"{pid}  {status}  {e.command[:60]}")
        body = "\n".join(rows) if rows else "(no processes)"
        return ToolResult(ok=True, content=body, metadata={"count": len(_REGISTRY)})


async def _drain(entry: _ProcEntry) -> None:
    """Read stdout from a background process and append to entry.output_lines."""
    assert entry.proc.stdout is not None
    total = 0
    try:
        async for line in entry.proc.stdout:
            decoded = line.decode(errors="replace").rstrip()
            entry.output_lines.append(decoded)
            total += len(line)
            if total > _MAX_OUTPUT_BYTES:
                entry.output_lines.append("[output truncated — 200 KiB cap reached]")
                break
    except Exception:
        pass


__all__ = ["ProcArgs", "ProcTool", "_ProcEntry", "_drain", "_make_proc_id"]
