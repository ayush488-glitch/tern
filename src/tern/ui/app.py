"""Tern chat — a Textual TUI for the agent loop.

Replaces the one-shot `tern run` workflow with a persistent chat session.
Wires the M5 tool registry into M1 so read_file + edit_block are callable.
Permission gate prompts route through a modal overlay; user picks y/n with
the keyboard.

Usage:
    TERN_LIVE=1 tern chat
    TERN_LIVE=1 tern chat --mode safe   # destructive tools filtered out
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, RichLog

from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
)
from tern.core.events import (
    ApprovalRequested,
    LLMResponded,
    ToolCalled,
    ToolReturned,
    TurnCompleted,
    TurnEvent,
)
from tern.core.loop import run_turn
from tern.core.routing import select_adapter
from tern.core.turn import Turn, TurnPurpose
from tern.obs.recorder import SpanRecorder
from tern.obs.sink import NDJSONSpanSink
from tern.tools import ApprovalDecision, PermissionGate, Registry
from tern.tools.native import EditBlockTool, ReadFileTool


class PermissionModal(ModalScreen[bool]):  # type: ignore[misc]
    """Yes/no overlay for destructive tool calls."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("y", "approve", "Approve"),
        Binding("n", "deny", "Deny"),
        Binding("escape", "deny", "Deny"),
    ]

    def __init__(self, tool_name: str, args_preview: str) -> None:
        super().__init__()
        self._tool = tool_name
        self._args = args_preview

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"[b]{self._tool}[/b] wants to run."),
            Label(f"[dim]{self._args}[/dim]"),
            Label(""),
            Label("[y] approve   [n] deny"),
            id="permission-modal",
        )

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)


class ChatApp(App[None]):  # type: ignore[misc]
    """Tern chat application."""

    CSS = """
    Screen { background: $surface; }
    #log { height: 1fr; border: round $primary; padding: 0 1; }
    Input { dock: bottom; }
    #permission-modal {
        align: center middle;
        background: $boost;
        padding: 1 2;
        border: thick $warning;
        width: 60;
        height: auto;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        mode: str = "default",
        repo_root: Path | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.repo_root = repo_root or Path.cwd()
        self.session_id = uuid.uuid4().hex[:12]
        self.messages: tuple[CanonicalMessage, ...] = ()
        self.turn_idx = 0
        self.registry = Registry([ReadFileTool(), EditBlockTool()])
        self.gate = PermissionGate(prompter=self._approval_prompt)
        self.sink = NDJSONSpanSink(session_id=self.session_id)
        self.recorder = SpanRecorder(sink=self.sink)
        self.busy = False

    # ---- compose / startup ------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield RichLog(id="log", markup=True, wrap=True, highlight=False)
        yield Input(placeholder="ask tern… ('/exit' to quit)")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"tern · session {self.session_id} · mode={self.mode}"
        log = self.query_one("#log", RichLog)
        log.write(Text("welcome to tern. type a prompt or /exit.", style="dim"))

    # ---- input ------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text in {"/exit", "/quit"}:
            self.exit()
            return
        if self.busy:
            self._log_dim("(busy — wait for the current turn to finish)")
            return
        self._log_user(text)
        self.busy = True
        self.run_worker(self._run_one_turn(text), exclusive=True)

    # ---- turn runner ------------------------------------------------------

    async def _run_one_turn(self, prompt: str) -> None:
        try:
            user_msg = CanonicalMessage(
                role="user",
                content=(TextBlock(text=prompt),),
                metadata=Metadata(
                    schema_version=SCHEMA_VERSION, ts=0.0, provenance="cli"
                ),
            )
            self.messages = (*self.messages, user_msg)
            adapter = select_adapter(TurnPurpose.CODE)
            turn = Turn(
                id=uuid.uuid4().hex[:12],
                session_id=self.session_id,
                idx=self.turn_idx,
                purpose=TurnPurpose.CODE,
                messages=self.messages,
                registry=self.registry,
                gate=self.gate,
                mode=self.mode,
                repo_root=self.repo_root,
                max_tokens=1024,
            )
            assistant_text_seen = False
            async for ev in run_turn(turn, adapter):
                self.recorder.consume(ev)
                self._log_event(ev)
                if isinstance(ev, TurnCompleted):
                    pass
            # Append the rolling assistant + tool messages by re-pulling the
            # final assistant text (cached on the adapter, last call).
            last_msg = getattr(adapter, "last_response_message", None)
            if last_msg is not None:
                self.messages = (*self.messages, last_msg)
                for block in last_msg.content:
                    if isinstance(block, TextBlock):
                        self._log_assistant(block.text)
                        assistant_text_seen = True
            if not assistant_text_seen:
                self._log_dim("(no assistant text this turn)")
            self.turn_idx += 1
        except Exception as exc:
            self._log_dim(f"[red]error: {exc}[/red]")
        finally:
            self.busy = False

    # ---- approval prompter ------------------------------------------------

    async def _approval_prompt(
        self, tool: Any, args: Any, ctx: Any
    ) -> ApprovalDecision:
        decision_future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        def _on_dismiss(value: bool | None) -> None:
            if not decision_future.done():
                decision_future.set_result(bool(value))

        def _push() -> None:
            self.push_screen(
                PermissionModal(tool.name, repr(args)[:80]), _on_dismiss
            )

        self.call_from_thread(_push) if False else _push()  # always on UI thread
        granted = await decision_future
        return ApprovalDecision.GRANTED if granted else ApprovalDecision.DENIED

    # ---- log helpers ------------------------------------------------------

    def _log(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)

    def _log_user(self, text: str) -> None:
        self._log(f"[bold cyan]you[/bold cyan] {text}")

    def _log_assistant(self, text: str) -> None:
        self._log(f"[bold green]tern[/bold green] {text}")

    def _log_dim(self, text: str) -> None:
        self._log(f"[dim]{text}[/dim]")

    def _log_event(self, ev: TurnEvent) -> None:
        if isinstance(ev, LLMResponded):
            self._log_dim(
                f"· llm {ev.model_id} in={ev.tokens_in} out={ev.tokens_out} "
                f"${ev.cost_usd:.4f} ({ev.stop_reason})"
            )
        elif isinstance(ev, ToolCalled):
            self._log_dim(f"· tool {ev.tool_name}({ev.args_preview})")
        elif isinstance(ev, ToolReturned):
            tag = "ok" if ev.ok else f"err: {ev.error}"
            self._log_dim(f"· ← {ev.tool_name} {tag} ({ev.bytes_out}B)")
        elif isinstance(ev, ApprovalRequested):
            self._log_dim(f"· asking permission for {ev.tool_name}…")
        elif isinstance(ev, TurnCompleted):
            self._log_dim(f"· turn done: {ev.reason}")


def run_chat(*, mode: str = "default", repo_root: Path | None = None) -> None:
    """Entry point used by the CLI."""
    ChatApp(mode=mode, repo_root=repo_root).run()
