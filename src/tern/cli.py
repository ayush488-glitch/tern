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
from tern.core.events import (
    LLMResponded,
    LLMTextDelta,
    OutcomeSpan,
    RecallQueried,
    RoutingClassified,
    TurnEvent,
)
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

# "auto" is a special sentinel, not a TurnPurpose — the router resolves it.
_VALID_PURPOSES = {*_PURPOSE_ALIASES, "auto"}


@app.command()
def run(
    prompt: str = typer.Argument(..., help="The user prompt to send."),
    purpose: str = typer.Option(
        "auto",
        "--purpose",
        "-p",
        help="Routing purpose: auto (default), arch, code, lint, boilerplate.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model id for this turn (e.g. gpt-5-mini, "
             "us.amazon.nova-lite-v1:0). Wins over --purpose and config.",
    ),
    max_tokens: int = typer.Option(1024, "--max-tokens", help="Response cap."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir (default: current)."),
    print_mode: bool = typer.Option(
        False,
        "--print",
        help="Plain-text output: stream assistant text to stdout, suppress span/cost UI.",
    ),
) -> None:
    """One-shot turn: send PROMPT, print the assistant reply.

    Live Bedrock call. Requires `TERN_LIVE=1` to actually hit the network —
    otherwise we refuse and tell you why. Spans flow into .tern/spans/.

    With --print: raw assistant text only (no Rich), suitable for piping.
    """
    if os.environ.get("TERN_LIVE") != "1":
        typer.secho(
            "tern run is a live Bedrock call. Set TERN_LIVE=1 to confirm.\n"
            "  TERN_LIVE=1 tern run \"say hello\"",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=2)

    from tern.tools import PermissionGate, Registry
    from tern.tools.mcp import MCPManager, load_mcp_config
    from tern.tools.native import (
        BashTool,
        BrowserClickTool,
        BrowserNavigateTool,
        BrowserSnapshotTool,
        BrowserTypeTool,
        BrowserVisionTool,
        EditBlockTool,
        GlobTool,
        GrepTool,
        MemoryTool,
        NotesAppendTool,
        ReadFileTool,
        SkillManageTool,
        WebFetchTool,
        WebSearchTool,
        WriteFileTool,
    )
    from tern.tools.native.proc import ProcTool
    from tern.tools.native.screenshot import ScreenshotTool

    purpose_key = purpose.lower()
    if purpose_key not in _VALID_PURPOSES:
        typer.secho(
            f"unknown purpose '{purpose}'. expected one of: "
            f"{', '.join(sorted(_VALID_PURPOSES))}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    # ---- D1 cost router (S18): resolve purpose + model --------------------
    from tern.core.config import get_config
    from tern.core.routing import adapter_for_model
    from tern.router import route as auto_route

    routing_method = "default"
    if model:
        # Explicit --model wins over everything
        try:
            adapter = adapter_for_model(model)
        except ValueError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        turn_purpose = TurnPurpose.CODE
    elif purpose_key == "auto":
        # Router: regex-first, Nova Micro fallback
        config_model = get_config("default_model")
        if config_model:
            # User pinned a model globally; still classify for span metadata
            turn_purpose, _chosen_mid, routing_method = auto_route(prompt, mode="auto")
            try:
                adapter = adapter_for_model(config_model)
            except ValueError as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from exc
        else:
            turn_purpose, chosen_model_id, routing_method = auto_route(prompt, mode="auto")
            adapter = adapter_for_model(chosen_model_id)
    else:
        # Explicit --purpose flag
        turn_purpose = _PURPOSE_ALIASES[purpose_key]
        config_model = get_config("default_model")
        chosen_model_id = config_model or ""
        if chosen_model_id:
            try:
                adapter = adapter_for_model(chosen_model_id)
            except ValueError as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from exc
        else:
            adapter = select_adapter(turn_purpose)

    # ---- KNN recall (S18): fetch similar past turns -----------------------
    repo = (cwd or Path.cwd()).resolve()
    recall_hits: list[object] = []
    try:
        from tern.memory.repo_store import find_repo_root
        from tern.recall import RecallStore
        from tern.recall.embed import embed

        recall_root = find_repo_root(repo)
        if recall_root is not None:
            store = RecallStore(recall_root)
            if store.size > 0:
                qvec = embed(prompt)
                recall_hits = store.query(qvec)  # type: ignore[assignment]
    except Exception:
        pass  # recall failure must never kill a turn

    # ---- S20: load SO hits from previous turn (if any) -------------------
    _so_banner_text: str = ""
    try:
        from tern.lookup.inject import build_so_banner
        from tern.lookup.store import load_and_clear_so_hits

        _prev_so_hits = load_and_clear_so_hits()
        _so_banner_text = build_so_banner(_prev_so_hits)
    except Exception:
        pass  # SO banner failure must never kill a turn

    # ---- D2 / S11: skills runtime --------------------------------------
    skills = load_skills(cwd)
    active = select_active(prompt, skills)
    sys_text = build_system_prompt(skills, active, cwd=cwd or Path.cwd(), recall_hits=recall_hits or None)
    if _so_banner_text:
        sys_text = f"{sys_text}\n\n{_so_banner_text}"
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
    registry = Registry(
        [
            ReadFileTool(),
            WriteFileTool(),
            EditBlockTool(),
            GlobTool(),
            GrepTool(),
            BashTool(),
            NotesAppendTool(),
            WebFetchTool(),
            MemoryTool(),
            SkillManageTool(),
            ProcTool(),
            ScreenshotTool(),
            WebSearchTool(),
            BrowserNavigateTool(),
            BrowserSnapshotTool(),
            BrowserClickTool(),
            BrowserTypeTool(),
            BrowserVisionTool(),
        ]
    )
    gate = PermissionGate()  # default deny on destructive in default mode

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
        registry=registry,
        gate=gate,
        repo_root=repo,
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

    # S19 outcome accumulators — populated inside _go() by inspecting ToolReturned events.
    _s19_tool_names: set[str] = set()
    _s19_tool_outputs: list[str] = []
    _s19_error_count: int = 0

    async def _go() -> None:
        nonlocal _s19_tool_names, _s19_tool_outputs, _s19_error_count
        # ---- D6 / S13: MCP servers (loaded if .tern/mcp.json or ~/.tern/mcp.json exists)
        mcp_servers = load_mcp_config(cwd)
        async with MCPManager.connect(mcp_servers) as mcp_mgr:
            for t in mcp_mgr.tools:
                registry.register(t)
            if mcp_mgr.tools:
                typer.secho(
                    f"mcp: {len(mcp_mgr.tools)} tool(s) bridged",
                    fg=typer.colors.BRIGHT_BLACK,
                    err=True,
                )
            async for ev in run_turn(turn, adapter):
                rec.consume(ev)
                if print_mode:
                    # --print: stream raw text to stdout, suppress all UI chrome
                    if isinstance(ev, LLMTextDelta):
                        typer.echo(ev.text, nl=False)
                else:
                    _print_event_one_liner(ev, console)
                # Accumulate tool signal for S19 outcome span
                if ev.__class__.__name__ == "ToolCalled":
                    _s19_tool_names.add(getattr(ev, "tool_name", ""))
                elif ev.__class__.__name__ == "ToolReturned":
                    if not getattr(ev, "ok", True):
                        _s19_error_count += 1
                    err_str = getattr(ev, "error", None)
                    if err_str:
                        _s19_tool_outputs.append(str(err_str))

    asyncio.run(_go())
    if print_mode:
        typer.echo("")  # trailing newline after streamed text

    # ---- S18: emit routing + recall span metadata -----------------------
    # Fire RoutingClassified so the span tree records which method + model chose.
    _routing_ev = RoutingClassified(
        parent_id=turn.id,
        prompt_preview=prompt[:120],
        purpose=turn_purpose.value,
        method=routing_method,
        model_id=getattr(adapter, "model_id", ""),
    )
    rec.consume(_routing_ev)
    # Fire RecallQueried so latency + hit-rate is observable in span trees.
    _recall_size = 0
    try:
        from tern.memory.repo_store import find_repo_root
        from tern.recall import RecallStore as _RS
        _rr = find_repo_root(repo)
        if _rr is not None:
            _recall_size = _RS(_rr).size
    except Exception:
        pass
    _recall_ev = RecallQueried(
        parent_id=turn.id,
        prompt_preview=prompt[:120],
        n_candidates=_recall_size,
        n_hits=len(recall_hits),
    )
    rec.consume(_recall_ev)

    # ---- S19: emit OutcomeSpan + log_outcome ----------------------------
    # _tool_outputs, _tool_names, _error_count are collected inside _go().
    _tests_passed: bool | None = None
    _commit_landed: bool | None = None
    try:
        from tern.memory.curate import detect_commit_landed, detect_tests_passed
        _tests_passed = detect_tests_passed(_s19_tool_outputs)
        _commit_landed = detect_commit_landed(_s19_tool_outputs)
    except Exception:
        pass

    _outcome_ev = OutcomeSpan(
        parent_id=turn.id,
        purpose=turn_purpose.value,
        model_id=getattr(adapter, "model_id", ""),
        tool_names=tuple(sorted(_s19_tool_names)),
        error_count=_s19_error_count,
        prompt_preview=prompt[:120],
        tests_passed=_tests_passed,
        commit_landed=_commit_landed,
        user_correction=False,  # retroactively updated by the next turn
    )
    rec.consume(_outcome_ev)

    try:
        from tern.memory.curate import OutcomeRecord, log_outcome
        log_outcome(OutcomeRecord(
            session_id=session_id,
            ts=_outcome_ev.ts / 1e9,
            purpose=_outcome_ev.purpose,
            model_id=_outcome_ev.model_id,
            tool_names=_outcome_ev.tool_names,
            error_count=_outcome_ev.error_count,
            prompt_preview=_outcome_ev.prompt_preview,
            tests_passed=_outcome_ev.tests_passed,
            commit_landed=_outcome_ev.commit_landed,
            user_correction=_outcome_ev.user_correction,
        ))
    except Exception:
        pass

    # ---- S20: StackOverflow lookup on error spans -----------------------
    # When the turn had tool errors, search SO and persist hits for the next turn.
    if _s19_error_count >= 1:
        try:
            from tern.core.events import SOLookupCompleted
            from tern.lookup import search
            from tern.lookup.inject import build_so_banner
            from tern.lookup.search import extract_error_query
            from tern.lookup.store import save_so_hits

            _so_query = extract_error_query(_s19_tool_outputs)
            if _so_query:
                _so_hits = search(_so_query, n=3, _retry=1)
                _so_banner = build_so_banner(_so_hits)
                save_so_hits(_so_hits)
                _so_ev = SOLookupCompleted(
                    parent_id=turn.id,
                    query=_so_query[:120],
                    n_hits=len(_so_hits),
                    error_in_turn=_so_query[:120],
                )
                rec.consume(_so_ev)
                if _so_hits:
                    typer.secho(
                        f"so: {len(_so_hits)} hit(s) for '{_so_query[:60]}…' — injected next turn",
                        fg=typer.colors.BRIGHT_CYAN,
                        err=True,
                    )
        except Exception:
            pass  # SO lookup failure must never kill or slow down a turn

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
    sys_text = build_system_prompt(skills, active, cwd=cwd or Path.cwd())
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


# ===========================================================================
# S16: model breadth — config + models commands
# ===========================================================================


config_app = typer.Typer(help="Manage tern config (default model, etc.).")
app.add_typer(config_app, name="config")


@config_app.command("set")
def config_set(key: str = typer.Argument(..., help="Config key (e.g. default_model, OPENAI_API_KEY)."),
               value: str = typer.Argument(..., help="Value to store.")) -> None:
    """Set a config value. Secret keys (e.g. OPENAI_API_KEY) go to ~/.tern/secrets.json (chmod 600).
    Non-secret keys (e.g. default_model) go to ~/.tern/config.json."""
    from tern.core.config import set_config, valid_keys
    from tern.core.secrets import set_secret

    # Heuristic: anything ending in _KEY / _TOKEN / _SECRET is treated as a secret.
    if key.endswith(("_KEY", "_TOKEN", "_SECRET")):
        set_secret(key, value)
        typer.secho(f"saved {key} -> ~/.tern/secrets.json", fg=typer.colors.GREEN)
        return
    if key not in valid_keys():
        typer.secho(
            f"unknown config key '{key}'. valid: {', '.join(valid_keys())} "
            f"(or any *_KEY / *_TOKEN / *_SECRET).",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2)
    set_config(key, value)
    typer.secho(f"set {key} = {value}", fg=typer.colors.GREEN)


@config_app.command("get")
def config_get(key: str = typer.Argument(..., help="Config key.")) -> None:
    from tern.core.config import get_config
    val = get_config(key)
    if val is None:
        typer.secho(f"{key} is not set", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)
    typer.echo(val)


@config_app.command("show")
def config_show() -> None:
    """Show current non-secret config + names of stored secrets."""
    from tern.core.config import list_config
    from tern.core.secrets import list_secret_names

    cfg = list_config()
    if cfg:
        typer.secho("config:", bold=True)
        for k, v in sorted(cfg.items()):
            typer.echo(f"  {k} = {v}")
    else:
        typer.secho("config: (empty)", fg=typer.colors.BRIGHT_BLACK)

    secrets = list_secret_names()
    if secrets:
        typer.secho("\nsecrets (names only):", bold=True)
        for name in secrets:
            typer.echo(f"  {name}")


@app.command("models")
def models_cmd() -> None:
    """List supported model ids with $/1M pricing."""
    from tern.core.pricing import known_models, pricing_for
    typer.secho(f"{'model_id':<55}  {'$/1M in':>8}  {'$/1M out':>9}", bold=True)
    typer.echo("-" * 78)
    for mid in known_models():
        p = pricing_for(mid)
        typer.echo(f"{mid:<55}  {p.usd_in_per_m:>8.3f}  {p.usd_out_per_m:>9.3f}")


# ===========================================================================
# S18: recall CLI — human inspection of the per-repo KNN index
# ===========================================================================

recall_app = typer.Typer(
    name="recall",
    help="Query and inspect the per-repo KNN recall index (S18).",
    no_args_is_help=False,
    invoke_without_command=True,
)
app.add_typer(recall_app, name="recall")


@recall_app.callback()
def _recall_default(
    ctx: typer.Context,
    query: str = typer.Argument("", help="Prompt text to query similar past turns."),
    top_k: int = typer.Option(3, "--top-k", "-k", help="Max hits to return."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir (default: current)."),
) -> None:
    """`tern recall [QUERY]` — embed query and show top-k similar past turns.

    With no QUERY, shows index stats only.
    """
    if ctx.invoked_subcommand is not None:
        return

    from tern.memory.repo_store import find_repo_root
    from tern.recall import RecallStore
    from tern.recall.embed import embed

    repo = (cwd or Path.cwd()).resolve()
    recall_root = find_repo_root(repo)
    if recall_root is None:
        typer.secho("no .git / .tern found walking up from cwd — not inside a repo", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)

    store = RecallStore(recall_root)
    console = Console()

    if not query:
        console.print(f"recall index: [cyan]{recall_root / '.tern' / 'recall'}[/cyan]")
        console.print(f"indexed turns: [yellow]{store.size}[/yellow]")
        return

    if store.size == 0:
        typer.secho("recall index is empty — run some turns first", fg=typer.colors.YELLOW)
        raise typer.Exit()

    qvec = embed(query)
    hits = store.query(qvec, top_k=top_k)
    if not hits:
        typer.echo("no recall hits (index empty or all zero-vectors)")
        return

    console.print(f"[bold]top {len(hits)} recall hits for:[/bold] {query[:80]}")
    console.print()
    for i, hit in enumerate(hits, 1):
        sim = f"{hit.similarity * 100:.0f}%"
        console.print(f"  [yellow]{i}[/yellow]  [cyan]{hit.purpose:<12}[/cyan]  sim=[green]{sim}[/green]")
        console.print(f"     prompt: {hit.prompt_preview}")
        console.print(f"     reply:  {hit.reply_preview}")
        console.print()


@recall_app.command("add")
def recall_add(
    prompt: str = typer.Argument(..., help="Prompt text to embed and store."),
    reply: str = typer.Argument(..., help="Reply text to store alongside."),
    purpose: str = typer.Option("code", "--purpose", "-p", help="TurnPurpose label."),
    sha: str = typer.Option("", "--sha", help="Turn SHA (default: auto-generated)."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir."),
) -> None:
    """Manually add a (prompt, reply) pair to the recall index. Useful for seeding."""
    import uuid

    from tern.memory.repo_store import find_repo_root
    from tern.recall import RecallStore
    from tern.recall.embed import embed

    repo = (cwd or Path.cwd()).resolve()
    recall_root = find_repo_root(repo)
    if recall_root is None:
        typer.secho("no .git / .tern found — not inside a repo", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    store = RecallStore(recall_root)
    vec = embed(prompt)
    sha_val = sha or uuid.uuid4().hex[:12]
    store.add(sha=sha_val, prompt=prompt, reply=reply, purpose=purpose, vector=vec)
    typer.secho(f"added turn {sha_val} to recall index (size now {store.size})", fg=typer.colors.GREEN)


# ─── tern curate (S19) ───────────────────────────────────────────────────────

curate_app = typer.Typer(name="curate", help="Review and apply curation proposals.", no_args_is_help=False)
app.add_typer(curate_app)


@curate_app.callback(invoke_without_command=True)
def curate_cmd(
    ctx: typer.Context,
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir (default: current)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-accept all proposals (non-interactive)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show proposals without applying any."),
) -> None:
    """Interactive PR-style review of curation proposals.

    Reads from curation_queue.jsonl + outcomes_log.jsonl, distills proposals,
    presents each one for accept (y) / skip (n) / quit (q).
    Accepted proposals are applied atomically to the relevant .tern/memory/*.md file.
    """
    if ctx.invoked_subcommand is not None:
        return

    from tern.memory.curate import (
        apply_proposal,
        clear_proposals,
        distill_proposals,
    )
    from tern.memory.repo_store import find_repo_root

    repo = (cwd or Path.cwd()).resolve()
    repo_root = find_repo_root(repo)
    if repo_root is None:
        typer.secho("no .git / .tern found — not inside a repo", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # Clear stale proposals then regenerate fresh.
    clear_proposals(repo_root)
    proposals = distill_proposals(repo_root)

    if not proposals:
        typer.secho("no curation proposals — nothing to review", fg=typer.colors.BRIGHT_BLACK)
        return

    typer.secho(
        f"\n{'─'*60}\n  {len(proposals)} curation proposal(s) for {repo_root}\n{'─'*60}",
        fg=typer.colors.CYAN,
    )

    applied = 0
    skipped = 0

    for i, prop in enumerate(proposals, 1):
        typer.secho(
            f"\n[{i}/{len(proposals)}] {prop.target.upper()}  action={prop.action}",
            fg=typer.colors.YELLOW,
            bold=True,
        )
        typer.echo(f"  reason : {prop.reason}")
        typer.echo(f"  content: {prop.content[:200]}")
        if prop.action == "replace":
            typer.echo(f"  replaces: {prop.old_text[:120]}")

        if dry_run:
            typer.secho("  [dry-run — skipping]", fg=typer.colors.BRIGHT_BLACK)
            skipped += 1
            continue

        if yes:
            answer = "y"
        else:
            answer = typer.prompt(
                "  Accept? [y=yes / n=skip / q=quit]",
                default="n",
            ).strip().lower()

        if answer == "q":
            typer.secho("aborted", fg=typer.colors.RED)
            break
        elif answer == "y":
            try:
                apply_proposal(repo_root, prop)
                typer.secho(f"  applied → {prop.target}", fg=typer.colors.GREEN)
                applied += 1
            except Exception as exc:
                typer.secho(f"  error applying: {exc}", fg=typer.colors.RED, err=True)
                skipped += 1
        else:
            typer.secho("  skipped", fg=typer.colors.BRIGHT_BLACK)
            skipped += 1

    typer.secho(
        f"\ndone  applied={applied}  skipped={skipped}",
        fg=typer.colors.CYAN,
    )


@curate_app.command("status")
def curate_status(
    cwd: Path | None = typer.Option(None, "--cwd", help="Project dir (default: current)."),
) -> None:
    """Show pending curation proposals without applying them."""
    from tern.memory.curate import distill_proposals, read_outcomes, read_queue
    from tern.memory.repo_store import find_repo_root

    repo = (cwd or Path.cwd()).resolve()
    repo_root = find_repo_root(repo)

    queue_count = len(read_queue())
    outcome_count = len(read_outcomes())
    typer.echo(f"queue nudges  : {queue_count}")
    typer.echo(f"outcome spans : {outcome_count}")

    if repo_root is None:
        typer.secho("not inside a repo — proposal distillation skipped", fg=typer.colors.YELLOW)
        return

    proposals = distill_proposals(repo_root)
    typer.echo(f"proposals     : {len(proposals)}")
    for p in proposals:
        typer.echo(f"  [{p.target}] {p.action}: {p.content[:80]}")


