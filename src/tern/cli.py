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
from tern.obs.store import (
    list_branches,
    list_sessions,
    persist_message,
    read_session_head,
    update_session_head,
    walk_chain,
    write_branch,
)
from tern.skills.catalog import (
    build_system_prompt,
    load_skills,
)
from tern.skills.retrieval import select_active

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

    # ---- D2 / S11: skills runtime --------------------------------------
    skills = load_skills(cwd)
    active = select_active(prompt, skills)
    sys_text = build_system_prompt(skills, active)
    sys_msg = (
        CanonicalMessage(
            role="system",
            content=(TextBlock(text=sys_text),),
            metadata=Metadata(
                schema_version=SCHEMA_VERSION, ts=0.0, provenance="cli"
            ),
        ),
    ) if sys_text else ()

    session_id = uuid.uuid4().hex[:12]
    turn = Turn(
        id=uuid.uuid4().hex[:12],
        session_id=session_id,
        idx=0,
        purpose=turn_purpose,
        messages=(
            *sys_msg,
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

    # ---- D3 / S10: persist user message before sending ------------------
    user_msg = turn.messages[-1]
    _user_obj, parent_sha = persist_message(
        user_msg,
        session_id=session_id,
        turn_idx=0,
        parent=None,
        cwd=cwd,
        routing_purpose=turn_purpose.value,
    )
    update_session_head(session_id, parent_sha, cwd=cwd)

    async def _go() -> None:
        async for ev in run_turn(turn, adapter):
            rec.consume(ev)
            _print_event_one_liner(ev, console)

    asyncio.run(_go())

    # Persist the assistant reply (if any) and advance the session head.
    response_msg = adapter.last_response_message  # type: ignore[attr-defined]
    if response_msg is not None:
        _, head_sha = persist_message(
            response_msg,
            session_id=session_id,
            turn_idx=0,
            parent=parent_sha,
            cwd=cwd,
            routing_purpose=turn_purpose.value,
        )
        update_session_head(session_id, head_sha, cwd=cwd)
        for block in response_msg.content:
            if isinstance(block, TextBlock):
                typer.echo(block.text)

    # D4 / S12: best-effort live HTML notes artifact refresh after the turn.
    try:
        from tern.notes import render_html

        out = render_html(session_id, cwd=cwd)
        typer.secho(f"notes: {out}", fg=typer.colors.BRIGHT_BLACK, err=True)
    except Exception as exc:
        typer.secho(f"notes render skipped: {exc}", fg=typer.colors.YELLOW, err=True)
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


# ---------------------------------------------------------------------------
# S10 / D3 — session graph commands
# ---------------------------------------------------------------------------


def _resolve_session(prefix: str, cwd: Path | None) -> str:
    """Return full session_id from a prefix, or raise typer.Exit. Empty prefix
    picks the most recent session."""
    sessions = list_sessions(cwd)
    if not sessions:
        typer.secho("no sessions in this project", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if not prefix:
        return sessions[0][0]
    matches = [s for s in sessions if s[0].startswith(prefix)]
    if not matches:
        typer.secho(f"no session matching {prefix!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if len(matches) > 1:
        typer.secho(
            f"ambiguous prefix {prefix!r} matches {len(matches)} sessions",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    return matches[0][0]


@app.command(name="log")
def log_cmd(
    session: str = typer.Argument("", help="Session id or prefix (default: most recent)."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir (default: current)."),
) -> None:
    """Show the chain of turn-objects for a session, root → head."""
    sid = _resolve_session(session, cwd)
    head = read_session_head(sid, cwd=cwd)
    if head is None:
        typer.secho(f"session {sid} has no head", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    chain = walk_chain(head, cwd=cwd)
    console = Console()
    console.print(f"[bold]session {sid}[/bold]  head [cyan]{head[:12]}[/cyan]  ({len(chain)} turns)")
    for i, obj in enumerate(chain):
        from tern.obs.store import content_hash as _ch
        sha = _ch(obj)
        cost = f"${obj.cost.usd_total:.4f}" if obj.cost else "-"
        model = obj.model_id or "-"
        preview = ""
        for blk in obj.content:
            if isinstance(blk, TextBlock):
                preview = blk.text.replace("\n", " ")[:60]
                break
        console.print(
            f"  [dim]{i:>2}[/dim] [yellow]{sha[:10]}[/yellow] "
            f"[magenta]{obj.role:<9}[/magenta] {model:<60} {cost:>9}  {preview}"
        )
    branches = list_branches(sid, cwd=cwd)
    if branches:
        console.print("\n[bold]branches[/bold]")
        for name, sha in branches:
            console.print(f"  [green]{name}[/green]  → [yellow]{sha[:12]}[/yellow]")


@app.command()
def sessions(
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir."),
) -> None:
    """List all sessions in this project, newest first."""
    rows = list_sessions(cwd)
    if not rows:
        typer.echo("no sessions")
        return
    console = Console()
    for sid, sha, _ in rows:
        console.print(f"  [cyan]{sid}[/cyan]  head [yellow]{sha[:12]}[/yellow]")


@app.command()
def resume(
    session: str = typer.Argument("", help="Session id/prefix (default: most recent)."),
    prompt: str = typer.Argument(..., help="The next user prompt."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir."),
    max_tokens: int = typer.Option(1024, "--max-tokens"),
) -> None:
    """Resume a session: load chain, append prompt, run one turn, advance head."""
    if os.environ.get("TERN_LIVE") != "1":
        typer.secho("tern resume is a live Bedrock call. Set TERN_LIVE=1.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=2)

    sid = _resolve_session(session, cwd)
    head = read_session_head(sid, cwd=cwd)
    if head is None:
        typer.secho(f"session {sid} has no head", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    chain = walk_chain(head, cwd=cwd)
    from tern.obs.store import chain_to_messages
    history = list(chain_to_messages(chain))

    # Pick purpose from the most recent assistant turn, default CODE.
    last_purpose = next(
        (TurnPurpose(o.routing_purpose) for o in reversed(chain)
         if o.routing_purpose in {p.value for p in TurnPurpose}),
        TurnPurpose.CODE,
    )
    adapter = select_adapter(last_purpose)

    user_msg = CanonicalMessage(
        role="user",
        content=(TextBlock(text=prompt),),
        metadata=Metadata(schema_version=SCHEMA_VERSION, ts=0.0, provenance="cli"),
    )
    history.append(user_msg)
    next_idx = (chain[-1].turn_idx or 0) + 1

    # ---- D2 / S11: skills runtime --------------------------------------
    skills = load_skills(cwd)
    active = select_active(prompt, skills)
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

    _, parent_sha = persist_message(
        user_msg, session_id=sid, turn_idx=next_idx, parent=head,
        cwd=cwd, routing_purpose=last_purpose.value,
    )
    update_session_head(sid, parent_sha, cwd=cwd)

    turn = Turn(
        id=uuid.uuid4().hex[:12],
        session_id=sid,
        idx=next_idx,
        purpose=last_purpose,
        messages=(*sys_prefix, *history),
        max_tokens=max_tokens,
    )
    sink = NDJSONSpanSink(session_id=sid, cwd=cwd)
    rec = SpanRecorder(sink=sink)
    console = Console()

    async def _go() -> None:
        async for ev in run_turn(turn, adapter):
            rec.consume(ev)
            _print_event_one_liner(ev, console)

    asyncio.run(_go())
    response_msg = adapter.last_response_message  # type: ignore[attr-defined]
    if response_msg is not None:
        _, head_sha = persist_message(
            response_msg, session_id=sid, turn_idx=next_idx, parent=parent_sha,
            cwd=cwd, routing_purpose=last_purpose.value,
        )
        update_session_head(sid, head_sha, cwd=cwd)
        for blk in response_msg.content:
            if isinstance(blk, TextBlock):
                typer.echo(blk.text)
    typer.secho(
        f"\nresumed {sid}  ·  cost ${rec.total_cost_usd():.4f}",
        fg=typer.colors.BRIGHT_BLACK, err=True,
    )


@app.command()
def branch(
    name: str = typer.Argument(..., help="Branch name."),
    target: str = typer.Argument("", help="Turn-hash or session prefix to fork from (default: head of most recent session)."),
    session: str = typer.Option("", "--session", help="Session id/prefix to branch under."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir."),
) -> None:
    """Create a named branch pointing at a turn-hash. Forks the conversation
    graph; does NOT modify your workspace."""
    sid = _resolve_session(session, cwd)
    head = read_session_head(sid, cwd=cwd)
    if head is None:
        typer.secho(f"session {sid} has no head", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if not target:
        target_sha = head
    else:
        # Try as full hash, else search the chain for prefix match.
        chain = walk_chain(head, cwd=cwd)
        from tern.obs.store import content_hash as _ch
        candidates = [_ch(o) for o in chain if _ch(o).startswith(target)]
        if not candidates:
            typer.secho(f"no turn matching {target!r} in {sid}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if len(candidates) > 1:
            typer.secho(f"ambiguous prefix {target!r}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        target_sha = candidates[0]
    write_branch(sid, name, target_sha, cwd=cwd)
    typer.secho(f"branch {name} → {target_sha[:12]}", fg=typer.colors.GREEN)


@app.command()
def branches(
    session: str = typer.Argument("", help="Session id/prefix."),
    cwd: Path | None = typer.Option(None, "--cwd"),
) -> None:
    """List branches on a session."""
    sid = _resolve_session(session, cwd)
    rows = list_branches(sid, cwd=cwd)
    if not rows:
        typer.echo(f"no branches on {sid}")
        return
    for n, sha in rows:
        typer.echo(f"  {n}  {sha[:12]}")


@app.command()
def replay(
    session: str = typer.Argument("", help="Session id/prefix (default: most recent)."),
    check: bool = typer.Option(True, "--check/--no-check", help="Assert content hashes are stable."),
    cwd: Path | None = typer.Option(None, "--cwd"),
) -> None:
    """Pure replay: walk the chain, re-hash every object, verify integrity.

    Per ADR-0005: pure replay does not re-fetch from the provider. It re-reads
    every turn-object and asserts hash equality. A mismatch means the store is
    corrupt or someone hand-edited an object file.
    """
    sid = _resolve_session(session, cwd)
    head = read_session_head(sid, cwd=cwd)
    if head is None:
        typer.secho(f"session {sid} has no head", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    chain = walk_chain(head, cwd=cwd)
    from tern.obs.store import content_hash as _ch
    failures: list[tuple[int, str, str]] = []
    for i, obj in enumerate(chain):
        recomputed = _ch(obj)
        # The hash we got from walk is implicit in the parent chain; we
        # recompute and compare against the file path it was stored at by
        # round-tripping. Same content → same hash invariant.
        # (Object name in the store IS recomputed; if files were mutated,
        # the read would already have failed in walk_chain.)
        if i + 1 < len(chain):
            child = chain[i + 1]
            if child.parent != recomputed:
                failures.append((i, recomputed, child.parent or ""))
    console = Console()
    console.print(f"[bold]replay {sid}[/bold]  {len(chain)} turns  head [cyan]{head[:12]}[/cyan]")
    if check and failures:
        for idx, expected, got in failures:
            console.print(f"  [red]✗[/red] turn {idx}: child.parent={got[:12]} expected {expected[:12]}")
        raise typer.Exit(code=1)
    console.print("[green]✓ hash chain consistent[/green]")


# ---------------------------------------------------------------------------
# S11 / D2 — skills CLI
# ---------------------------------------------------------------------------

skills_app = typer.Typer(
    name="skills",
    help="Inspect the skills catalog discovered on disk.",
    no_args_is_help=False,
    invoke_without_command=True,
)
app.add_typer(skills_app, name="skills")


@skills_app.callback()
def _skills_default(
    ctx: typer.Context,
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir."),
) -> None:
    """`tern skills` (no subcommand) lists all discovered skills."""
    if ctx.invoked_subcommand is not None:
        return
    items = load_skills(cwd)
    console = Console()
    if not items:
        console.print("[dim]no skills discovered[/dim]")
        console.print(
            "[dim]drop SKILL.md files into ~/.tern/skills/<name>/ "
            "or .tern/skills/<name>/[/dim]"
        )
        return
    for s in items:
        src = "[cyan]project[/cyan]" if s.source == "project" else "[magenta]user[/magenta]"
        console.print(f"  [yellow]{s.name:<24}[/yellow] {src}  {s.description}")


@skills_app.command("show")
def skills_show(
    name: str = typer.Argument(..., help="Skill name."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir."),
) -> None:
    """Print the full body of one skill."""
    items = load_skills(cwd)
    match = next((s for s in items if s.name == name), None)
    console = Console()
    if match is None:
        typer.secho(f"no skill named {name!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    console.print(f"[bold]{match.name}[/bold]  [dim]({match.source})[/dim]")
    console.print(f"[dim]{match.path}[/dim]")
    console.print(f"\n[italic]{match.description}[/italic]")
    if match.when_to_use:
        console.print(f"[dim]when: {match.when_to_use}[/dim]")
    if match.allowed_tools:
        console.print(f"[dim]tools: {', '.join(match.allowed_tools)}[/dim]")
    console.print()
    console.print(match.body)


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
    resume: str = typer.Option(
        "", "--resume", "-r", help="Session id/prefix to resume (default: fresh)."
    ),
) -> None:
    """Open an inline REPL chat session with tools wired in.

    Streams Bedrock tokens live; destructive tools prompt inline with a
    unified diff panel. Ctrl+C cancels the in-flight turn; press it twice to exit.
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

    resolved_resume: str | None = None
    if resume:
        resolved_resume = _resolve_session(resume, cwd)
    run_chat(mode=mode, repo_root=cwd, resume_session=resolved_resume)


@app.command(name="notes")
def notes_cmd(
    session: str = typer.Argument(
        "", help="Session id or prefix (default: most recent)."
    ),
    cwd: Path | None = typer.Option(
        None, "--cwd", help="Project dir (default: current)."
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="Override output path (default: <project>/notes/<session>.html).",
    ),
    open_after: bool = typer.Option(
        False, "--open", help="Open the rendered file in the OS default browser."
    ),
) -> None:
    """Render the live HTML notes artifact for a session (D4 / S12)."""
    from tern.notes import render_html

    sid = _resolve_session(session, cwd)
    path = render_html(sid, cwd=cwd, out_path=out)
    typer.echo(str(path))
    if open_after:
        import webbrowser

        webbrowser.open(path.as_uri())
