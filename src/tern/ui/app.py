"""Inline REPL chat surface (M2).

Replaces the Textual full-screen TUI with a Claude-Code-style inline experience:

  - prompt_toolkit handles input (history, multiline, key bindings)
  - rich.live streams assistant tokens in place
  - tool calls render as collapsed one-liners (`← read_file ok 3,054B`)
  - destructive tools prompt inline with an up-front unified diff
  - Ctrl+C cancels the current turn; second Ctrl+C exits

No screen takeover. Scrollback preserved. Output goes through one `Console`.
"""
from __future__ import annotations

import asyncio
import difflib
import uuid
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from pydantic import BaseModel
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
)
from tern.core.events import (
    ApprovalRequested,
    LLMResponded,
    LLMTextDelta,
    ReflectionTriggered,
    ToolCalled,
    ToolReturned,
    TurnCompleted,
    TurnEvent,
)
from tern.core.loop import run_turn
from tern.core.provider import ProviderAdapter
from tern.core.routing import select_adapter
from tern.core.turn import Turn, TurnPurpose
from tern.obs.paths import spans_path
from tern.obs.recorder import SpanRecorder
from tern.obs.sink import NDJSONSpanSink
from tern.tools import (
    ApprovalDecision,
    PermissionGate,
    Registry,
    Tool,
    ToolContext,
)
from tern.tools.native import EditBlockTool, NotesAppendTool, ReadFileTool, WebFetchTool
from tern.tools.permissions import Prompter

# ---------------------------------------------------------------------------
# inline approval prompter
# ---------------------------------------------------------------------------


def _diff_for_edit_block(args: BaseModel, repo_root: Path) -> str | None:
    """Best-effort unified diff for edit_block. Returns None if not applicable."""
    path = getattr(args, "path", None)
    search = getattr(args, "search", None)
    replace = getattr(args, "replace", None)
    if not (path and search is not None and replace is not None):
        return None
    fpath = (repo_root / path).resolve()
    try:
        original = fpath.read_text()
    except OSError:
        original = ""
    # Render a small "would change" diff against the search/replace pair, even
    # if we can't apply it cleanly here. The model already chose the strings;
    # showing the user (search → replace) is the honest preview.
    diff = difflib.unified_diff(
        search.splitlines(keepends=True),
        replace.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    text = "".join(diff)
    if not text and search != replace:
        text = f"--- a/{path}\n+++ b/{path}\n-{search}\n+{replace}\n"
    # Sanity: confirm the search string appears in the file at all.
    if search and original and search not in original:
        text = (
            f"# warning: search block not found verbatim in {path}\n"
            f"# (will fall back to fuzzy match)\n" + text
        )
    return text or None


def _build_inline_prompter(
    console: Console, repo_root: Path
) -> Prompter:
    """Make an async prompter that renders the diff up-front and reads y/n/d."""

    async def prompter(
        tool: Tool, args: BaseModel, ctx: ToolContext
    ) -> ApprovalDecision:
        # Print the request line.
        console.print()
        console.print(
            Text.assemble(
                ("⚠ ", "yellow"),
                (f"{tool.name}", "bold"),
                (" wants to run: ", "yellow"),
                (str(args), "dim"),
            )
        )
        # Up-front diff for edit_block.
        if tool.name == "edit_block":
            diff = _diff_for_edit_block(args, repo_root)
            if diff:
                console.print(
                    Panel(
                        Syntax(diff, "diff", theme="ansi_dark", word_wrap=True),
                        title="proposed change",
                        border_style="dim",
                    )
                )

        # Inline y/n prompt — uses prompt_toolkit so stdin lives nicely
        # alongside any background output.
        sess: PromptSession[str] = PromptSession()
        loop = asyncio.get_running_loop()
        while True:
            try:
                ans = (
                    await loop.run_in_executor(
                        None,
                        lambda: sess.prompt("approve? [y/N] ").strip().lower(),
                    )
                )
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in {"y", "yes"}:
                return ApprovalDecision.GRANTED
            if ans in {"", "n", "no"}:
                return ApprovalDecision.DENIED
            console.print("[dim]please answer y or n[/dim]")

    return prompter


# ---------------------------------------------------------------------------
# event renderer
# ---------------------------------------------------------------------------


class _StreamRenderer:
    """Owns the Live region for the in-flight assistant message.

    Prints non-streamed events (tool lines, approvals) directly through the
    same console — Live yields cleanly so scrollback stays sane.
    """

    def __init__(self, console: Console) -> None:
        self.console = console
        self._buf: list[str] = []
        self._live: Live | None = None

    def _render(self) -> Markdown:
        return Markdown("".join(self._buf) or "…")

    def _open(self) -> None:
        if self._live is None:
            self._live = Live(
                self._render(),
                console=self.console,
                refresh_per_second=24,
                transient=False,
            )
            self._live.__enter__()

    def _close(self) -> None:
        if self._live is not None:
            self._live.update(self._render(), refresh=True)
            self._live.__exit__(None, None, None)
            self._live = None
            self._buf.clear()

    def feed(self, ev: TurnEvent) -> None:
        if isinstance(ev, LLMTextDelta):
            self._open()
            self._buf.append(ev.text)
            assert self._live is not None
            self._live.update(self._render())
            return

        if isinstance(ev, LLMResponded):
            self._close()
            self.console.print(
                f"[dim]· {ev.model_id}  in={ev.tokens_in} out={ev.tokens_out} "
                f"${ev.cost_usd:.4f}[/dim]"
            )
            return

        # any non-streaming event — close the live block first.
        self._close()

        if isinstance(ev, ToolCalled):
            self.console.print(
                f"[cyan]→[/cyan] {ev.tool_name} [dim]{ev.args_preview}[/dim]"
            )
        elif isinstance(ev, ToolReturned):
            mark = "[green]✓[/green]" if ev.ok else "[red]✗[/red]"
            tail = f"  {ev.bytes_out}B" if ev.ok else f"  {ev.error}"
            self.console.print(f"{mark} {ev.tool_name}[dim]{tail}[/dim]")
        elif isinstance(ev, ApprovalRequested):
            # the prompter renders the actual prompt; this is just a marker
            pass
        elif isinstance(ev, ReflectionTriggered):
            self.console.print(
                f"[yellow]↻[/yellow] reflect: {ev.cause}"
            )
        elif isinstance(ev, TurnCompleted) and ev.reason != "done":
            self.console.print(f"[dim]turn ended: {ev.reason}[/dim]")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


_HELP = """\
[bold]tern chat[/bold] — inline REPL.

  type a prompt and press Enter to send.
  Esc, Enter inserts a newline (multi-line input).
  Ctrl+C cancels the current turn; press it twice to exit.
  /help    show this
  /quit    exit
"""


def run_chat(
    *,
    mode: str = "default",
    repo_root: Path | None = None,
    resume_session: str | None = None,
) -> None:
    """Blocking entry point. Wires registry + gate + adapter, runs the REPL."""
    repo = (repo_root or Path.cwd()).resolve()
    console = Console()
    console.print(_HELP)

    registry = Registry([ReadFileTool(), EditBlockTool(), NotesAppendTool(), WebFetchTool()])
    gate = PermissionGate(prompter=_build_inline_prompter(console, repo))

    # ---- D3 / S10: optionally resume a prior session, else fresh -------
    from tern.obs.store import (
        chain_to_messages,
        persist_message,
        read_session_head,
        update_session_head,
        walk_chain,
    )

    history: list[CanonicalMessage] = []
    parent_sha: str | None = None
    turn_idx = 0
    if resume_session:
        head = read_session_head(resume_session, cwd=repo)
        if head is None:
            console.print(f"[red]no session {resume_session} in this project[/red]")
            return
        session_id = resume_session
        chain = walk_chain(head, cwd=repo)
        history = list(chain_to_messages(chain))
        parent_sha = head
        turn_idx = (chain[-1].turn_idx or 0) + 1
        console.print(f"[dim]resumed {session_id} · {len(chain)} prior turns[/dim]")
    else:
        session_id = uuid.uuid4().hex[:12]

    sink = NDJSONSpanSink(session_id=session_id, cwd=repo)
    rec = SpanRecorder(sink=sink)

    pt_session: PromptSession[str] = PromptSession(history=InMemoryHistory())

    while True:
        try:
            with patch_stdout():
                user_text = pt_session.prompt("» ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]bye.[/dim]")
            break
        if not user_text:
            continue
        if user_text in {"/quit", "/exit"}:
            console.print("[dim]bye.[/dim]")
            break
        if user_text == "/help":
            console.print(_HELP)
            continue

        user_msg = CanonicalMessage(
            role="user",
            content=(TextBlock(text=user_text),),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION, ts=0.0, provenance="cli"
            ),
        )
        history.append(user_msg)
        # Persist user turn-object and advance head before sending.
        _, parent_sha = persist_message(
            user_msg,
            session_id=session_id,
            turn_idx=turn_idx,
            parent=parent_sha,
            cwd=repo,
            routing_purpose=TurnPurpose.CODE.value,
        )
        update_session_head(session_id, parent_sha, cwd=repo)
        adapter = select_adapter(TurnPurpose.CODE)

        # ---- D2 / S11: skills runtime ----------------------------------
        from tern.skills import build_system_prompt, load_skills, select_active

        skills = load_skills(repo)
        active = select_active(user_text, skills)
        sys_text = build_system_prompt(skills, active)
        sys_prefix: tuple[CanonicalMessage, ...] = (
            (
                CanonicalMessage(
                    role="system",
                    content=(TextBlock(text=sys_text),),
                    metadata=Metadata(
                        schema_version=SCHEMA_VERSION, ts=0.0, provenance="cli"
                    ),
                ),
            )
            if sys_text
            else ()
        )
        if active:
            console.print(
                f"[dim]· skills active: {', '.join(s.name for s in active)}[/dim]"
            )

        turn = Turn(
            id=uuid.uuid4().hex[:12],
            session_id=session_id,
            idx=turn_idx,
            purpose=TurnPurpose.CODE,
            messages=(*sys_prefix, *history),
            mode=mode,
            registry=registry,
            gate=gate,
            repo_root=repo,
            max_tokens=2048,
        )
        renderer = _StreamRenderer(console)

        async def _go(
            _turn: Turn = turn,
            _adapter: ProviderAdapter = adapter,
            _r: _StreamRenderer = renderer,
        ) -> None:
            async for ev in run_turn(_turn, _adapter):
                rec.consume(ev)
                _r.feed(ev)

        try:
            asyncio.run(_go())
        except KeyboardInterrupt:
            renderer._close()
            console.print("[yellow]·[/yellow] turn cancelled (Ctrl+C again to exit)")
            try:
                with patch_stdout():
                    pt_session.prompt("» ", default="").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("[dim]bye.[/dim]")
                break

        # Append the final assistant message to history so multi-turn works.
        last = getattr(adapter, "last_response_message", None)
        if last is not None:
            history.append(last)
            _, parent_sha = persist_message(
                last,
                session_id=session_id,
                turn_idx=turn_idx,
                parent=parent_sha,
                cwd=repo,
                routing_purpose=TurnPurpose.CODE.value,
            )
            update_session_head(session_id, parent_sha, cwd=repo)
        turn_idx += 1

        # ---- D4 / S12: refresh the live HTML notes artifact after each turn.
        # Best-effort; a render failure should never break the chat.
        try:
            from tern.notes import render_html

            render_html(session_id, cwd=repo)
        except Exception as exc:
            console.print(f"[dim red]· notes render failed: {exc}[/dim red]")

    console.print(
        f"[dim]session {session_id}  ·  cost ${rec.total_cost_usd():.4f}[/dim]"
    )
    console.print(f"[dim]spans: {spans_path(session_id, cwd=repo)}[/dim]")


__all__ = ["run_chat"]
