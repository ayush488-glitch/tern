"""Tern CLI entry point.

Composition root. Concrete adapters get wired here once they exist; today we
only have the smoke surface (`tern --version`) and the observability surface
(`tern spans <session>`).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import typer
from rich.console import Console

from tern import __version__
from tern.core.canonical import (
    SCHEMA_VERSION,
    CanonicalMessage,
    Metadata,
    TextBlock,
)
from tern.core.events import LLMResponded, TurnEvent
from tern.core.loop import run_turn
from tern.core.routing import select_adapter
from tern.core.turn import Turn, TurnPurpose
from tern.obs.paths import project_dir, spans_path
from tern.obs.recorder import SpanRecorder
from tern.obs.render import print_forest
from tern.obs.replay import replay_to_recorder
from tern.obs.sink import NDJSONSpanSink

app = typer.Typer(
    name="tern",
    no_args_is_help=True,
    add_completion=False,
    help="Tern — a Python CLI coding agent.",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tern {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Tern — a Python CLI coding agent."""
    return None


@app.command()
def version() -> None:
    """Show version."""
    typer.echo(f"tern {__version__}")


@app.command()
def spans(
    session: str = typer.Argument(..., help="Session id (or partial prefix)."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project directory (default: current)."),
) -> None:
    """Pretty-print the span tree for a recorded session."""
    path = spans_path(session, cwd=cwd)
    if not path.exists():
        # Try prefix match.
        spans_dir = (project_dir(cwd) / "spans")
        candidates = sorted(spans_dir.glob(f"{session}*.ndjson")) if spans_dir.exists() else []
        if not candidates:
            typer.secho(f"no span file at {path}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        path = candidates[0]
    rec = replay_to_recorder(path)
    title = f"spans · {path.stem}  (cost ${rec.total_cost_usd():.4f})"
    print_forest(rec.roots, title=title, console=Console())


_PURPOSE_ALIASES: dict[str, TurnPurpose] = {
    "arch": TurnPurpose.ARCH,
    "code": TurnPurpose.CODE,
    "lint": TurnPurpose.LINT,
    "boilerplate": TurnPurpose.BOILERPLATE,
}


@app.command()
def run(
    prompt: str = typer.Argument(..., help="The user prompt to send."),
    purpose: str = typer.Option(
        "code",
        "--purpose",
        "-p",
        help="Routing purpose: arch, code, lint, boilerplate.",
    ),
    max_tokens: int = typer.Option(1024, "--max-tokens", help="Response cap."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir (default: current)."),
) -> None:
    """One-shot turn: send PROMPT, print the assistant reply.

    Live Bedrock call. Requires `TERN_LIVE=1` to actually hit the network —
    otherwise we refuse and tell you why. Spans flow into .tern/spans/.
    """
    if os.environ.get("TERN_LIVE") != "1":
        typer.secho(
            "tern run is a live Bedrock call. Set TERN_LIVE=1 to confirm.\n"
            "  TERN_LIVE=1 tern run \"say hello\"",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)

    purpose_key = purpose.lower()
    if purpose_key not in _PURPOSE_ALIASES:
        typer.secho(
            f"unknown purpose '{purpose}'. expected one of: "
            f"{', '.join(_PURPOSE_ALIASES)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    turn_purpose = _PURPOSE_ALIASES[purpose_key]
    adapter = select_adapter(turn_purpose)

    session_id = uuid.uuid4().hex[:12]
    turn = Turn(
        id=uuid.uuid4().hex[:12],
        session_id=session_id,
        idx=0,
        purpose=turn_purpose,
        messages=(
            CanonicalMessage(
                role="user",
                content=(TextBlock(text=prompt),),
                metadata=Metadata(
                    schema_version=SCHEMA_VERSION,
                    ts=0.0,
                    provenance="cli",
                ),
            ),
        ),
        max_tokens=max_tokens,
    )

    sink = NDJSONSpanSink(session_id=session_id, cwd=cwd)
    rec = SpanRecorder(sink=sink)
    console = Console()

    async def _go() -> None:
        async for ev in run_turn(turn, adapter):
            rec.consume(ev)
            _print_event_one_liner(ev, console)

    asyncio.run(_go())

    # Print the assistant text last, plain.
    response_msg = adapter.last_response_message  # type: ignore[attr-defined]
    if response_msg is not None:
        for block in response_msg.content:
            if isinstance(block, TextBlock):
                typer.echo(block.text)
    typer.secho(
        f"\nsession {session_id}  ·  cost ${rec.total_cost_usd():.4f}",
        fg=typer.colors.BRIGHT_BLACK,
        err=True,
    )


def _print_event_one_liner(ev: TurnEvent, console: Console) -> None:
    """Stderr breadcrumbs — keeps stdout clean for the assistant text."""
    if isinstance(ev, LLMResponded):
        console.print(
            f"[dim]· {ev.model_id}  in={ev.tokens_in} out={ev.tokens_out} "
            f"${ev.cost_usd:.4f}[/dim]",
            style="dim",
            highlight=False,
            soft_wrap=True,
        )


if __name__ == "__main__":
    app()


@app.command()
def chat(
    mode: str = typer.Option(
        "default",
        "--mode",
        "-m",
        help="Permission mode: default, safe, yolo.",
    ),
    cwd: Path | None = typer.Option(
        None, "--cwd", help="Repo root for tool sandbox (default: current)."
    ),
) -> None:
    """Open an inline REPL chat session with tools wired in.

    Streams Bedrock tokens live; destructive tools prompt inline with a
    unified diff. Ctrl+C cancels the in-flight turn; press it twice to exit.
    Requires `TERN_LIVE=1` to confirm you want a live Bedrock call.
    """
    if os.environ.get("TERN_LIVE") != "1":
        typer.secho(
            "tern chat is a live Bedrock call. Set TERN_LIVE=1 to confirm.\n"
            "  TERN_LIVE=1 tern chat",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)

    if mode not in {"default", "safe", "yolo"}:
        typer.secho(
            f"unknown mode '{mode}'. expected: default, safe, yolo.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    from tern.ui import run_chat

    run_chat(mode=mode, repo_root=cwd)
